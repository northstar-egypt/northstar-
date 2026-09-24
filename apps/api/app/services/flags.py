"""Reading and deciding flags.

A flag is a claim a detector made about a player. `app/models/flag.py` explains the two-table
shape and the `dedupe_key`; this module is what the API does with them.

Three things worth knowing before changing anything here.

**A flag is a claim, not a verdict.** That sentence is on the player profile screen and it
governs this file. Every flag carries the reason it fired, in language a coach can read, and
the integrity board puts the evidence above the decision buttons so a reviewer can disagree
with the model rather than rubber-stamp it.

**A decision without a reason is refused.** Not bureaucracy: each decision plus its reason is
a labelled example, and labelled examples are what the detectors' precision and recall are
computed from. A dismissal with no reason teaches nothing.

**Deciding writes two rows and never overwrites one.** The status on `flag` changes, and a
`flag_event` records who, what and why. The event log is the history the integrity board shows
and the training signal the ML track reads later.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.audit_log import AuditLog
from app.models.enums import FlagAction, FlagStatus, FlagType, PlayerStatus
from app.models.flag import Flag, FlagEvent
from app.models.measurement import Measurement
from app.models.player import Player

# Flag types the integrity board reviews. `late_bloomer` and `breakout` are not integrity
# concerns; they surface on the player profile and would only add noise to a review queue.
INTEGRITY_TYPES = (FlagType.FRAUD.value, FlagType.DUPLICATE.value, FlagType.ANOMALY.value)

# Human-readable labels for the chips on the profile and squad screens.
FLAG_LABELS = {
    FlagType.LATE_BLOOMER.value: "late bloomer",
    FlagType.FRAUD.value: "possible fraud",
    FlagType.DUPLICATE.value: "possible duplicate",
    FlagType.ANOMALY.value: "anomaly",
    FlagType.BREAKOUT.value: "breakout",
    FlagType.CONSENT.value: "consent",
}

# Statuses that still count as live. A dismissed flag stays in the table as the record of a
# decision, and as the thing that stops a rerun raising it again.
LIVE_STATUSES = (FlagStatus.OPEN.value, FlagStatus.NEEDS_INFO.value)


def make_dedupe_key(
    player_id: uuid.UUID | str, flag_type: str, fingerprint: str = ""
) -> str:
    """Stable identity for "this case".

    Deliberately coarse. It covers the player, the type and a fingerprint of what the evidence
    was *about*, and it excludes the confidence and the exact numbers, so ordinary drift
    between runs does not manufacture a new case out of an old one someone already dismissed.

    It does include the fingerprint, so a materially different observation, a different
    duplicate partner or a different set of offending rows, raises a genuinely new flag. That
    is the compromise the team chose: a dismissal sticks, but it cannot hide something new.
    """
    raw = f"{player_id}|{flag_type}|{fingerprint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Reads used by the player profile and squad screens
# ---------------------------------------------------------------------------


def _summary(flag: Flag) -> dict:
    return {
        "type": flag.type,
        "label": FLAG_LABELS.get(flag.type, flag.type.replace("_", " ")),
        "confidence": flag.confidence,
    }


def flags_for_player(db: Session, player_id: uuid.UUID) -> list[dict]:
    """Live flags against one player, newest first."""
    rows = db.execute(
        select(Flag)
        .where(Flag.player_id == player_id)
        .where(Flag.status.in_(LIVE_STATUSES))
        .order_by(Flag.raised_at.desc())
    ).scalars()
    return [_summary(flag) for flag in rows]


def flags_for_players(
    db: Session, player_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict]]:
    """The same, batched for the squad table.

    Batched because one query per row is what makes a dashboard slow the moment an academy
    has a hundred players.
    """
    out: dict[uuid.UUID, list[dict]] = {player_id: [] for player_id in player_ids}
    if not player_ids:
        return out
    rows = db.execute(
        select(Flag)
        .where(Flag.player_id.in_(player_ids))
        .where(Flag.status.in_(LIVE_STATUSES))
        .order_by(Flag.player_id, Flag.raised_at.desc())
    ).scalars()
    for flag in rows:
        out.setdefault(flag.player_id, []).append(_summary(flag))
    return out


def flag_reason(db: Session, player_id: uuid.UUID) -> str | None:
    """The sentence shown under the flag banner on the player profile.

    The highest-confidence live flag's reason. One sentence rather than all of them, because
    the banner is a summary and the full list is on the integrity board.
    """
    flag = db.execute(
        select(Flag)
        .where(Flag.player_id == player_id)
        .where(Flag.status.in_(LIVE_STATUSES))
        # Nulls last: a rule-based detector with no calibrated confidence should not outrank a
        # model that actually has one.
        .order_by(Flag.confidence.desc().nullslast(), Flag.raised_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return flag.reason if flag else None


def open_flag_count(db: Session, organization_id: uuid.UUID | None = None) -> int:
    """Live integrity flags, optionally scoped to one organization."""
    stmt = (
        select(func.count())
        .select_from(Flag)
        .where(Flag.status.in_(LIVE_STATUSES))
        .where(Flag.type.in_(INTEGRITY_TYPES))
    )
    if organization_id is not None:
        from app.models.player_organization import PlayerOrganization

        stmt = stmt.where(
            Flag.player_id.in_(
                select(PlayerOrganization.player_id)
                .where(PlayerOrganization.organization_id == organization_id)
                .where(PlayerOrganization.end_date.is_(None))
            )
        )
    return db.execute(stmt).scalar_one()


# ---------------------------------------------------------------------------
# The integrity board
# ---------------------------------------------------------------------------


def _relative(when: datetime | None) -> str:
    """"2 days ago", as the wireframe's history table shows it."""
    if when is None:
        return ""
    now = datetime.now(timezone.utc)
    moment = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    days = (now - moment).days
    if days <= 0:
        hours = int((now - moment).total_seconds() // 3600)
        return "just now" if hours < 1 else f"{hours} hours ago"
    return "1 day ago" if days == 1 else f"{days} days ago"


def _duplicate_records(db: Session, flag: Flag) -> dict | None:
    """The field-by-field diff that is the whole decision for a duplicate.

    The wireframe is explicit that this needs to show which record has more history, because
    that determines which one survives the merge.
    """
    if flag.type != FlagType.DUPLICATE.value or flag.related_player_id is None:
        return None

    a = flag.player
    b = db.get(Player, flag.related_player_id)
    if b is None:
        return None

    def measurement_count(player_id: uuid.UUID) -> int:
        return db.execute(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.player_id == player_id)
        ).scalar_one()

    count_a, count_b = measurement_count(a.id), measurement_count(b.id)

    def row(label: str, left, right) -> dict:
        left_text = "" if left is None else str(left)
        right_text = "" if right is None else str(right)
        return {
            "field": label,
            "a": left_text,
            "b": right_text,
            "differs": left_text != right_text,
        }

    return {
        "label": a.full_name,
        "playerId": str(a.id),
        "createdAt": a.created_at.date().isoformat() if a.created_at else "",
        "measurementCount": count_a,
        "source": "coach logged",
        "fields": [
            row("Full name", a.full_name, b.full_name),
            row("Date of birth", a.date_of_birth, b.date_of_birth),
            row("Sex", a.sex, b.sex),
            row("Position", a.position, b.position),
            row("Nationality", ", ".join(a.nationality), ", ".join(b.nationality)),
            row(
                "Created",
                a.created_at.date().isoformat() if a.created_at else None,
                b.created_at.date().isoformat() if b.created_at else None,
            ),
            row("Measurements", count_a, count_b),
            row("Status", a.status, b.status),
        ],
    }


def list_integrity_flags(
    db: Session,
    *,
    status: str | None = FlagStatus.OPEN.value,
    limit: int = 100,
) -> list[dict]:
    """The integrity board's queue: fraud, duplicate and anomaly in one list.

    Three flag types, one queue. They are different models with different evidence, but they
    are the same job for the person reviewing: look, decide, move on.
    """
    from app.services.views import current_organization

    stmt = (
        select(Flag)
        .options(selectinload(Flag.events), selectinload(Flag.player))
        .where(Flag.type.in_(INTEGRITY_TYPES))
        .order_by(Flag.raised_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Flag.status == status)

    today = date.today()
    out: list[dict] = []
    for flag in db.execute(stmt).scalars().unique():
        organization = current_organization(db, flag.player_id)
        raised_on = flag.raised_at.date() if flag.raised_at else today
        out.append(
            {
                "id": str(flag.id),
                "type": flag.type,
                "status": flag.status,
                "playerName": flag.player.full_name,
                "organizationName": organization.name if organization else None,
                "raisedAt": raised_on.isoformat(),
                "ageDays": (today - raised_on).days,
                # The frontend types confidence as a number. A rule-based detector has no
                # calibrated probability, and 0.0 is the honest stand-in for "no score" here
                # rather than a made-up one.
                "confidence": flag.confidence if flag.confidence is not None else 0.0,
                "reason": flag.reason,
                "evidence": list(flag.evidence.get("points", [])),
                "records": _duplicate_records(db, flag),
                "history": [
                    {
                        "at": _relative(event.created_at),
                        "who": event.actor.full_name if event.actor else "system",
                        "what": _event_text(event),
                    }
                    for event in flag.events
                ],
            }
        )
    return out


def _event_text(event: FlagEvent) -> str:
    base = {
        FlagAction.RAISED.value: "flag raised",
        FlagAction.CONFIRMED.value: "confirmed",
        FlagAction.DISMISSED.value: "dismissed",
        FlagAction.NEEDS_INFO.value: "more information requested",
        FlagAction.REOPENED.value: "reopened",
        FlagAction.COMMENTED.value: "commented",
    }.get(event.action, event.action)
    return f"{base}, {event.reason}" if event.reason else base


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------

DECISION_ACTIONS = {
    FlagStatus.CONFIRMED.value: FlagAction.CONFIRMED.value,
    FlagStatus.DISMISSED.value: FlagAction.DISMISSED.value,
    FlagStatus.NEEDS_INFO.value: FlagAction.NEEDS_INFO.value,
}


def decide(
    db: Session,
    *,
    flag: Flag,
    decision: str,
    reason: str,
    actor_user_id: uuid.UUID | None,
) -> Flag:
    """Record a reviewer's decision.

    Writes the new status, an event carrying who and why, and an audit row. The reason is
    required by the caller before this is reached; see the router.
    """
    flag.status = decision
    db.add(
        FlagEvent(
            flag_id=flag.id,
            actor_user_id=actor_user_id,
            action=DECISION_ACTIONS[decision],
            reason=reason,
        )
    )
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=f"flag.{decision}",
            entity_type="flag",
            entity_id=flag.id,
            event_metadata={"reason": reason, "flag_type": flag.type},
        )
    )
    db.flush()
    return flag


# ---------------------------------------------------------------------------
# Writing, used by the detector run
# ---------------------------------------------------------------------------


def upsert(
    db: Session,
    *,
    player_id: uuid.UUID,
    flag_type: str,
    reason: str,
    evidence: dict,
    detector_name: str,
    detector_version: str,
    fingerprint: str = "",
    confidence: float | None = None,
    related_player_id: uuid.UUID | None = None,
) -> tuple[Flag, bool]:
    """Raise a flag, or recognise one already raised. Returns (flag, created).

    A case that already exists is left alone whatever its status. That is the whole point of
    `dedupe_key`: a reviewer who dismissed a false positive last night is not handed it again
    this morning, and a case still open does not accumulate duplicate rows.

    The reason and the evidence of an existing open flag are refreshed, because the detector
    may now phrase the same claim with better numbers, but the status and the history are
    untouched.
    """
    key = make_dedupe_key(player_id, flag_type, fingerprint)
    existing = db.execute(select(Flag).where(Flag.dedupe_key == key)).scalar_one_or_none()

    if existing is not None:
        if existing.status == FlagStatus.OPEN.value:
            existing.reason = reason
            existing.evidence = evidence
            existing.detector_version = detector_version
        return existing, False

    flag = Flag(
        player_id=player_id,
        type=flag_type,
        status=FlagStatus.OPEN.value,
        confidence=confidence,
        reason=reason,
        evidence=evidence,
        detector_name=detector_name,
        detector_version=detector_version,
        dedupe_key=key,
        related_player_id=related_player_id,
    )
    db.add(flag)
    db.flush()
    db.add(
        FlagEvent(
            flag_id=flag.id,
            actor_user_id=None,
            action=FlagAction.RAISED.value,
            reason=(
                f"{detector_name} {detector_version}"
                + (f", confidence {confidence:.2f}" if confidence is not None else "")
            ),
        )
    )
    db.flush()
    return flag, True


def purge_merged_player_flags(db: Session) -> int:
    """Drop live flags against records that have since been merged away.

    A merged record is no longer a player; leaving open flags on it puts cases in the queue
    that cannot be actioned.
    """
    merged = select(Player.id).where(Player.status == PlayerStatus.MERGED)
    flags = list(
        db.execute(
            select(Flag).where(Flag.player_id.in_(merged)).where(Flag.status.in_(LIVE_STATUSES))
        ).scalars()
    )
    for flag in flags:
        flag.status = FlagStatus.DISMISSED.value
        db.add(
            FlagEvent(
                flag_id=flag.id,
                actor_user_id=None,
                action=FlagAction.DISMISSED.value,
                reason="player record was merged into another",
            )
        )
    db.flush()
    return len(flags)
