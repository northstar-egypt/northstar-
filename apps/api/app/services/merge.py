"""Merging two records of the same player, and undoing it.

A reviewer who confirms a duplicate on the integrity board is saying "these are one boy". The
merge makes the database agree: one record keeps everything, the other is marked
`status = merged` with `merged_into` pointing at the one kept. Every list, search and cohort
already leaves merged records out, and the table tennis rating already follows `merged_into`,
so the merge only has to move rows and set the pointer. Design and the choices behind it:
docs/decisions/0006-merging-duplicates.md.

What moves to the record kept
-----------------------------
- Measurements, unless the record kept already has the same metric on the same day. Then
  its own reading wins and the other stays behind on the merged record. Nothing is averaged.
- Performance records, unless the record kept already has the same one (same sport, period,
  opponent and figures: one match entered under both records). A match between the two
  records themselves stays where it is: moved, it would be a match against himself.
- Other players' match records that name the merged record as their opponent now name the
  record kept, so a table tennis match still points at a real opponent.
- Tagged match events.
- Academy and club links, so neither coach silently loses the player. A link to an
  organization the record kept is already at stays behind.
- A player account linked to the merged record.

What does not move
------------------
Consent forms. A guardian signed for the registration in front of them; the record kept is
governed by its own forms. And the merged record itself: it stays, with whatever was left
behind, as the history of what was entered.

Undo
----
The audit row of a merge lists every row it moved, so undo moves exactly those back, clears
the pointer, and reopens the flag. A merge of two different children can be put right without
a database fix. Undo needs a reason, like every decision.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.enums import FlagAction, FlagStatus, FlagType, PlayerStatus
from app.models.flag import Flag, FlagEvent
from app.models.match_event import MatchEvent
from app.models.measurement import Measurement
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.models.user import User
from app.services import flags as flag_service

MERGE_ACTION = "player.merge"
UNDO_ACTION = "player.unmerge"


class MergeError(ValueError):
    """A merge or undo that cannot be done, with a reason a reviewer can read. Always raised
    before anything is written."""


def _ids(rows) -> list[str]:
    return [str(row) for row in rows]


def merge(
    db: Session,
    *,
    flag: Flag,
    keep_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    reason: str,
) -> Player:
    """Merge the two records of a duplicate flag. Returns the record kept.

    `keep_id` is the record to keep; None keeps the one with more measurements (the older
    record on a tie). Confirms the flag, in the same transaction, which the caller commits.
    """
    if flag.type != FlagType.DUPLICATE.value or flag.related_player_id is None:
        raise MergeError("Only a duplicate case names two records to merge.")
    pair = {flag.player_id, flag.related_player_id}
    if keep_id is not None and keep_id not in pair:
        raise MergeError("The record to keep must be one of the two in this case.")

    a, b = (db.get(Player, pid) for pid in (flag.player_id, flag.related_player_id))
    if a is None or b is None:
        raise MergeError("One of the two records no longer exists.")
    for player in (a, b):
        if player.status == PlayerStatus.MERGED.value:
            raise MergeError(f"{player.full_name} has already been merged into another record.")
    if a.primary_sport != b.primary_sport or a.sex != b.sex:
        raise MergeError("Records of different sports or genders are not the same player.")

    if keep_id is None:
        keep = max((a, b), key=lambda p: (_measurement_count(db, p.id), -p.created_at.timestamp()))
    else:
        keep = a if a.id == keep_id else b
    gone = b if keep is a else a

    moved = {
        "measurement": _move_measurements(db, gone.id, keep.id),
        "performance_entry": _move_performance(db, gone.id, keep.id),
        "opponent_of": _repoint_opponents(db, gone.id, keep.id),
        "match_event": _move_all(db, MatchEvent, gone.id, keep.id),
        "player_organization": _move_affiliations(db, gone.id, keep.id),
        "user": _move_linked_accounts(db, gone.id, keep.id),
    }

    gone.status = PlayerStatus.MERGED.value
    gone.merged_into = keep.id
    db.flush()

    flag_service.decide(
        db, flag=flag, decision=FlagStatus.CONFIRMED.value, reason=reason,
        actor_user_id=actor_user_id,
    )
    # Cases still open against the merged record cannot be acted on any more.
    closed = _close_live_flags(db, gone.id)

    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=MERGE_ACTION,
            entity_type="player",
            entity_id=gone.id,
            event_metadata={
                "kept": str(keep.id),
                "merged": str(gone.id),
                "flag": str(flag.id),
                "reason": reason,
                "moved": moved,
                "closed_flags": closed,
            },
        )
    )
    db.flush()
    db.expire_all()  # the bulk updates above bypassed the session's copies
    reset_caches()
    return keep


def unmerge(
    db: Session, *, merged_id: uuid.UUID, actor_user_id: uuid.UUID | None, reason: str
) -> Player:
    """Undo the merge of `merged_id`: move back exactly what the merge moved. Returns the
    record restored. The caller commits."""
    player = db.get(Player, merged_id)
    if player is None or player.status != PlayerStatus.MERGED.value:
        raise MergeError("That record is not merged.")
    record = latest_merge(db, merged_id)
    if record is None:
        raise MergeError(
            "This record was merged before merges were recorded, so there is no list of what "
            "to move back."
        )
    meta = record.event_metadata
    keep_id = uuid.UUID(meta["kept"])
    moved = meta["moved"]

    def back(model, column, ids):
        if ids:
            db.execute(
                update(model)
                .where(model.id.in_([uuid.UUID(i) for i in ids]))
                .values({column: merged_id})
                .execution_options(synchronize_session=False)
            )

    back(Measurement, "player_id", moved["measurement"])
    back(PerformanceEntry, "player_id", moved["performance_entry"])
    back(PerformanceEntry, "opponent_player_id", moved["opponent_of"])
    back(MatchEvent, "player_id", moved["match_event"])
    back(PlayerOrganization, "player_id", moved["player_organization"])
    back(User, "linked_player_id", moved["user"])

    player.status = PlayerStatus.ACTIVE.value
    player.merged_into = None

    # The flag that led to the merge, and the cases the merge closed, are open again.
    reopen = [meta["flag"], *meta.get("closed_flags", [])]
    for flag in db.execute(
        select(Flag).where(Flag.id.in_([uuid.UUID(i) for i in reopen]))
    ).scalars():
        flag.status = FlagStatus.OPEN.value
        db.add(FlagEvent(flag_id=flag.id, actor_user_id=actor_user_id,
                         action=FlagAction.REOPENED.value, reason=f"merge undone: {reason}"))

    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=UNDO_ACTION,
            entity_type="player",
            entity_id=merged_id,
            event_metadata={"kept": str(keep_id), "merged": str(merged_id), "reason": reason,
                            "merge_audit": str(record.id)},
        )
    )
    db.flush()
    db.expire_all()  # the bulk updates above bypassed the session's copies
    reset_caches()
    return player


def latest_merge(db: Session, merged_id: uuid.UUID) -> AuditLog | None:
    """The audit row of the merge currently in effect for this record, if one was recorded."""
    return db.execute(
        select(AuditLog)
        .where(AuditLog.action == MERGE_ACTION)
        .where(AuditLog.entity_id == merged_id)
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def merged_into(db: Session, keep_id: uuid.UUID) -> list[dict]:
    """The records merged into this one, for its profile: who, when, by whom, and whether
    the merge can be undone (generated data was merged before merges were recorded)."""
    rows = []
    for player in db.execute(
        select(Player).where(Player.merged_into == keep_id).order_by(Player.full_name)
    ).scalars():
        record = latest_merge(db, player.id)
        rows.append(
            {
                "id": str(player.id),
                "full_name": player.full_name,
                "merged_on": record.created_at.date().isoformat() if record else None,
                "merged_by": record.actor.full_name if record and record.actor else None,
                "undoable": record is not None,
            }
        )
    return rows


def reset_caches() -> None:
    """Everything that counts players: a merge takes one away and moves its rows.

    The forecast model is left alone. It is fitted on the whole population, which one moved
    reading does not change, and refitting it takes seconds.
    """
    from app.services import cohort, concept_filter, rating, similar

    for service in (cohort, concept_filter, rating, similar):
        service.reset_cache()


# ---------------------------------------------------------------------------
# Moving rows. Each returns the ids it moved, for undo.
# ---------------------------------------------------------------------------


def _measurement_count(db: Session, player_id: uuid.UUID) -> int:
    return len(db.execute(select(Measurement.id).where(Measurement.player_id == player_id)).all())


def _move_measurements(db: Session, gone: uuid.UUID, keep: uuid.UUID) -> list[str]:
    taken = set(
        db.execute(
            select(Measurement.metric, Measurement.measured_at).where(Measurement.player_id == keep)
        ).all()
    )
    ids = [
        row.id
        for row in db.execute(select(Measurement).where(Measurement.player_id == gone)).scalars()
        if (row.metric, row.measured_at) not in taken
    ]
    _set(db, Measurement, "player_id", ids, keep)
    return _ids(ids)


def _performance_key(row: PerformanceEntry, opponent) -> tuple:
    return (row.sport, row.period_type, row.period_start, row.period_end, opponent,
            json.dumps(row.metrics, sort_keys=True, default=str))


def _move_performance(db: Session, gone: uuid.UUID, keep: uuid.UUID) -> list[str]:
    taken = {
        _performance_key(row, row.opponent_player_id)
        for row in db.execute(
            select(PerformanceEntry).where(PerformanceEntry.player_id == keep)
        ).scalars()
    }
    ids = [
        row.id
        for row in db.execute(
            select(PerformanceEntry).where(PerformanceEntry.player_id == gone)
        ).scalars()
        if row.opponent_player_id != keep
        and _performance_key(row, row.opponent_player_id) not in taken
    ]
    _set(db, PerformanceEntry, "player_id", ids, keep)
    return _ids(ids)


def _repoint_opponents(db: Session, gone: uuid.UUID, keep: uuid.UUID) -> list[str]:
    ids = list(
        db.execute(
            select(PerformanceEntry.id)
            .where(PerformanceEntry.opponent_player_id == gone)
            .where(PerformanceEntry.player_id != keep)
        ).scalars()
    )
    _set(db, PerformanceEntry, "opponent_player_id", ids, keep)
    return _ids(ids)


def _move_all(db: Session, model, gone: uuid.UUID, keep: uuid.UUID) -> list[str]:
    ids = list(db.execute(select(model.id).where(model.player_id == gone)).scalars())
    _set(db, model, "player_id", ids, keep)
    return _ids(ids)


def _move_affiliations(db: Session, gone: uuid.UUID, keep: uuid.UUID) -> list[str]:
    already = set(
        db.execute(
            select(PlayerOrganization.organization_id).where(PlayerOrganization.player_id == keep)
        ).scalars()
    )
    ids = [
        row.id
        for row in db.execute(
            select(PlayerOrganization).where(PlayerOrganization.player_id == gone)
        ).scalars()
        if row.organization_id not in already
    ]
    _set(db, PlayerOrganization, "player_id", ids, keep)
    return _ids(ids)


def _move_linked_accounts(db: Session, gone: uuid.UUID, keep: uuid.UUID) -> list[str]:
    ids = list(db.execute(select(User.id).where(User.linked_player_id == gone)).scalars())
    _set(db, User, "linked_player_id", ids, keep)
    return _ids(ids)


def _set(db: Session, model, column: str, ids: list, value: uuid.UUID) -> None:
    if ids:
        db.execute(
            update(model)
            .where(model.id.in_(ids))
            .values({column: value})
            .execution_options(synchronize_session=False)
        )


def _close_live_flags(db: Session, player_id: uuid.UUID) -> list[str]:
    """Close the merged record's open cases, as `flags.purge_merged_player_flags` does for
    the detector run, and return their ids so undo can reopen them. That includes duplicate
    cases that name it as the second record."""
    closed = []
    for flag in db.execute(
        select(Flag)
        .where(flag_service.about([player_id]))
        .where(Flag.status.in_(flag_service.LIVE_STATUSES))
    ).scalars():
        flag.status = FlagStatus.DISMISSED.value
        db.add(FlagEvent(flag_id=flag.id, actor_user_id=None, action=FlagAction.DISMISSED.value,
                         reason="player record was merged into another"))
        closed.append(str(flag.id))
    db.flush()
    return closed
