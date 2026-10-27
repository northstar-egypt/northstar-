"""Match events: tagging them from video, and reading them back.

A coach watches a recording of a match on the tagging screen, pauses, clicks where on the
pitch something happened and picks what it was. Each click is one `MatchEvent`. The rules:

- **Who may tag.** Whoever may log for the player (`access.permissions(...)["can_log"]`): the
  coaches of the player's own club, and admins. A tag is removed by the same people.
- **What may be tagged.** Only the event types and outcomes the player's sport module lists
  (`events` in packages/shared/sports/<sport>.json). A sport with none cannot be tagged yet.
- **Who may read.** Whoever may open the player (`access.may_view`), as for the match records
  on the profile. Events are records of what happened, not analytics, like those rows.

Tagged events are set beside the totals the coach logged for the same player and date
(`match_tags`), because two records of one match that disagree are worth seeing: either the
tagging missed something, or the logged totals are wrong.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sports
from app.models.audit_log import AuditLog
from app.models.enums import PerformanceSource
from app.models.match_event import MatchEvent
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.services.access import Caller, may_view, permissions

MAX_LABEL = 80


class TagRejected(ValueError):
    """An event that cannot be saved, with every reason, worded for the screen."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _club(db: Session, caller: Caller, player: Player) -> uuid.UUID | None:
    """The club a tag belongs to: the coach's own, or for an admin the player's current one."""
    if caller.organization_id is not None:
        return caller.organization_id
    return db.execute(
        select(PlayerOrganization.organization_id)
        .where(PlayerOrganization.player_id == player.id)
        .where(PlayerOrganization.end_date.is_(None))
        .limit(1)
    ).scalar_one_or_none()


def check(player: Player, payload: dict, today: date) -> list[str]:
    """Everything wrong with a tag, before anything is written."""
    problems = []
    module = sports.registry().get(player.primary_sport)
    kind = (module.events if module else {}).get(payload["event_type"])
    if module is None or not module.events:
        problems.append(f"{player.primary_sport.replace('_', ' ')} has no taggable match events yet.")
    elif kind is None:
        problems.append(
            f"\"{payload['event_type']}\" is not an event type for {module.label.lower()}; "
            f"choose one of {', '.join(module.events)}."
        )
    elif payload["outcome"] not in kind.outcomes:
        problems.append(
            f"\"{payload['outcome']}\" is not an outcome of a {kind.label.lower()}; choose one of "
            f"{', '.join(kind.outcomes)}."
        )
    if payload["match_date"] > today:
        problems.append("The match date is in the future.")
    if player.date_of_birth and payload["match_date"] < player.date_of_birth:
        problems.append("The match date is before the player was born.")
    x, y = payload.get("x"), payload.get("y")
    if (x is None) != (y is None):
        problems.append("A place on the pitch needs both coordinates, or neither.")
    for value in (x, y):
        if value is not None and not 0 <= value <= 100:
            problems.append("Pitch coordinates run from 0 to 100.")
            break
    if (payload.get("video_seconds") or 0) < 0:
        problems.append("The video time cannot be negative.")
    if len(payload.get("match_label") or "") > MAX_LABEL:
        problems.append(f"The match label is longer than {MAX_LABEL} characters.")
    if kind is not None and payload["outcome"] in kind.outcomes:
        problems += check_details(kind, payload["outcome"], payload.get("details") or {})
    return problems


def check_details(kind, outcome: str, details: dict) -> list[str]:
    """Everything wrong with a tag's details, against its sport module (decision 0007)."""
    problems = []
    for key, value in details.items():
        detail = kind.details.get(key)
        if detail is None:
            problems.append(
                f"A {kind.label.lower()} has no detail \"{key}\""
                + (f"; it has {', '.join(kind.details)}." if kind.details else ".")
            )
        elif value not in detail.values:
            problems.append(
                f"\"{value}\" is not a {detail.label.lower()}; choose one of {', '.join(detail.values)}."
            )
        elif detail.outcomes and outcome not in detail.outcomes:
            problems.append(
                f"{detail.label} is only recorded for "
                f"{' or '.join(kind.outcomes[o].label.lower() for o in detail.outcomes)}."
            )
    return problems


def tag(db: Session, caller: Caller, player: Player, payload: dict, today: date | None = None) -> MatchEvent:
    """Save one tagged event. Raises TagRejected, having written nothing, if it should not save."""
    problems = check(player, payload, today or date.today())
    if problems:
        raise TagRejected(problems)
    label = (payload.get("match_label") or "").strip() or None
    event = MatchEvent(
        player_id=player.id,
        organization_id=_club(db, caller, player),
        sport=player.primary_sport,
        match_date=payload["match_date"],
        match_label=label,
        event_type=payload["event_type"],
        outcome=payload["outcome"],
        x=payload.get("x"),
        y=payload.get("y"),
        video_seconds=payload.get("video_seconds"),
        details=payload.get("details") or None,
        source=PerformanceSource.COACH_TAGGED.value,
        tagged_by=caller.user_id,
    )
    db.add(event)
    db.flush()
    db.add(
        AuditLog(
            actor_user_id=caller.user_id,
            action="match_event.create",
            entity_type="player",
            entity_id=player.id,
            event_metadata={"match_event_id": str(event.id), "match_date": event.match_date.isoformat(),
                            "event_type": event.event_type, "outcome": event.outcome},
        )
    )
    return event


def set_details(db: Session, caller: Caller, event: MatchEvent, details: dict) -> MatchEvent:
    """Replace a tag's details: the tagging screen saves a tag at its outcome and the coach adds
    the details after. Raises TagRejected, having changed nothing, if they do not fit."""
    module = sports.registry().get(event.sport)
    kind = module.events.get(event.event_type) if module else None
    if kind is None:
        raise TagRejected([f"{event.event_type} is no longer an event type of {event.sport}."])
    problems = check_details(kind, event.outcome, details)
    if problems:
        raise TagRejected(problems)
    event.details = dict(details) or None
    db.add(
        AuditLog(
            actor_user_id=caller.user_id,
            action="match_event.details",
            entity_type="player",
            entity_id=event.player_id,
            event_metadata={"match_event_id": str(event.id), "details": event.details},
        )
    )
    return event


def may_change(db: Session, caller: Caller, event: MatchEvent) -> bool:
    player = db.get(Player, event.player_id)
    return (
        player is not None
        and may_view(db, caller, player)[0]
        and permissions(db, caller, player)["can_log"]
    )


def remove(db: Session, caller: Caller, event: MatchEvent) -> None:
    """Undo a tag. The audit log keeps what it was."""
    db.add(
        AuditLog(
            actor_user_id=caller.user_id,
            action="match_event.delete",
            entity_type="player",
            entity_id=event.player_id,
            event_metadata={"match_event_id": str(event.id), "match_date": event.match_date.isoformat(),
                            "event_type": event.event_type, "outcome": event.outcome},
        )
    )
    db.delete(event)


def tallies(events: list[MatchEvent]) -> dict[str, int]:
    """Match totals the events add up to, by the sport module's `counts`."""
    out: Counter[str] = Counter()
    for event in events:
        module = sports.registry().get(event.sport)
        kind = module.events.get(event.event_type) if module else None
        outcome = kind.outcomes.get(event.outcome) if kind else None
        for total in outcome.counts if outcome else []:
            out[total] += 1
    return dict(out)


def event_out(event: MatchEvent, name: str | None = None) -> dict:
    return {
        "id": event.id,
        "player_id": event.player_id,
        "player_name": name,
        "match_date": event.match_date,
        "match_label": event.match_label,
        "event_type": event.event_type,
        "outcome": event.outcome,
        "x": event.x,
        "y": event.y,
        "video_seconds": event.video_seconds,
        "details": event.details or {},
    }


def match_tags(db: Session, caller: Caller, match_date: date, match_label: str | None) -> dict:
    """One match's tags for the caller's club, with each player's tallies beside their logged
    totals for that date."""
    stmt = (
        select(MatchEvent)
        .where(MatchEvent.organization_id == caller.organization_id)
        .where(MatchEvent.match_date == match_date)
        .order_by(MatchEvent.video_seconds.nulls_last(), MatchEvent.created_at)
    )
    label = (match_label or "").strip() or None
    stmt = stmt.where(
        MatchEvent.match_label == label if label else MatchEvent.match_label.is_(None)
    )
    events = list(db.execute(stmt).scalars())
    names = {
        p.id: p for p in db.execute(
            select(Player).where(Player.id.in_({e.player_id for e in events}))
        ).scalars()
    } if events else {}
    # A player who left the club since stays in the list only for someone who may still open them.
    events = [e for e in events if e.player_id in names and may_view(db, caller, names[e.player_id])[0]]

    players = []
    for pid in dict.fromkeys(e.player_id for e in events):
        mine = [e for e in events if e.player_id == pid]
        logged = db.execute(
            select(PerformanceEntry.metrics)
            .where(PerformanceEntry.player_id == pid)
            .where(PerformanceEntry.period_start == match_date)
            .where(PerformanceEntry.period_type == "match")
            .limit(1)
        ).scalar_one_or_none()
        tally = tallies(mine)
        players.append({
            "player_id": pid,
            "player_name": names[pid].full_name,
            "tagged": tally,
            # Only the totals the tags can count, so the two columns line up.
            "logged": {k: logged.get(k) for k in tally} if logged else None,
        })
    return {
        "match_date": match_date,
        "match_label": label,
        "events": [event_out(e, names[e.player_id].full_name) for e in events],
        "players": players,
    }


def player_events(db: Session, player: Player, event_type: str | None = None) -> dict:
    """A player's tagged events, newest match first, for the profile's maps."""
    stmt = select(MatchEvent).where(MatchEvent.player_id == player.id)
    if event_type:
        stmt = stmt.where(MatchEvent.event_type == event_type)
    events = list(
        db.execute(stmt.order_by(MatchEvent.match_date.desc(), MatchEvent.video_seconds)).scalars()
    )
    by_outcome = Counter(f"{e.event_type}.{e.outcome}" for e in events)
    matches = len({(e.match_date, e.match_label) for e in events})
    return {
        "events": [event_out(e) for e in events],
        "matches": matches,
        "counts": dict(by_outcome),
        "note": (
            f"Tagged by coaches from match video, {matches} "
            f"{'match' if matches == 1 else 'matches'}. A tag is a person's reading of the "
            "video, so expect some to be missed or misplaced."
        ) if events else "No events tagged for this player yet.",
    }
