"""The scout's home: what is new for them, not an empty search box.

Three things, each from something already built and evaluated:

- **My shortlist**: the players this user saved, with their own notes (models/shortlist_entry.py).
- **Breakouts this season**: the breakout detector (ml/pro/breakout.py, scored in ml/README.md,
  "Pro tier") run on the latest league season, through the profile's own service
  (services/pro.py), so the list and the profile always agree.
- **Late bloomers**: the late-bloomer flags the detectors raised (ml/write_flags.py) that are
  still open or confirmed: the youth side of a scout's job.

Every player on it is read through `access.may_view`, and analytics consent gates the breakout
list as it gates the profile's league card. A saved player who can no longer be seen is counted
as withheld, never shown.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ConsentPurpose, FlagStatus, FlagType
from app.models.flag import Flag
from app.models.player import Player
from app.models.shortlist_entry import ShortlistEntry
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services import pro
from app.services.access import Caller, consent_subquery, may_view
from app.services.cohort import age_label
from app.services.views import organization_names

from ml.pro import breakout  # noqa: E402

NOTE_MAX = 1000
BREAKOUTS_SHOWN = 8
LATE_BLOOMERS_SHOWN = 6


class NotVisible(Exception):
    """The player does not exist or the caller may not see them."""


def _visible(db: Session, caller: Caller, player_id: uuid.UUID) -> Player:
    player = db.get(Player, player_id)
    if player is None or player.merged_into is not None or not may_view(db, caller, player)[0]:
        raise NotVisible
    return player


def _card(player: Player, clubs: dict, today: date) -> dict:
    return {
        "playerId": str(player.id), "fullName": player.full_name, "position": player.position,
        "tier": player.tier, "ageLabel": age_label(player.date_of_birth, today),
        "club": clubs.get(player.id), "isMinor": player.is_minor,
    }


def shortlist_ids(db: Session, caller: Caller) -> list[str]:
    rows = db.execute(select(ShortlistEntry.player_id).where(ShortlistEntry.user_id == caller.user_id)).scalars()
    return [str(r) for r in rows]


def save(db: Session, caller: Caller, player_id: uuid.UUID, note: str) -> ShortlistEntry:
    """Add the player to the caller's shortlist, or change the note. Raises NotVisible."""
    _visible(db, caller, player_id)
    note = note.strip()[:NOTE_MAX]
    entry = db.execute(select(ShortlistEntry).where(
        ShortlistEntry.user_id == caller.user_id, ShortlistEntry.player_id == player_id)).scalar_one_or_none()
    if entry is None:
        entry = ShortlistEntry(user_id=caller.user_id, player_id=player_id, note=note)
        db.add(entry)
    else:
        entry.note = note
    db.flush()
    return entry


def remove(db: Session, caller: Caller, player_id: uuid.UUID) -> bool:
    entry = db.execute(select(ShortlistEntry).where(
        ShortlistEntry.user_id == caller.user_id, ShortlistEntry.player_id == player_id)).scalar_one_or_none()
    if entry is None:
        return False
    db.delete(entry)
    db.flush()
    return True


def _shortlist(db: Session, caller: Caller, today: date) -> tuple[list[dict], int]:
    rows = db.execute(
        select(ShortlistEntry, Player).join(Player, Player.id == ShortlistEntry.player_id)
        .where(ShortlistEntry.user_id == caller.user_id).order_by(ShortlistEntry.updated_at.desc())
    ).all()
    shown = [(e, p) for e, p in rows if p.merged_into is None and may_view(db, caller, p)[0]]
    clubs = organization_names(db, [p.id for _, p in shown])
    return (
        [_card(p, clubs, today) | {"note": e.note, "savedAt": e.created_at.date().isoformat()} for e, p in shown],
        len(rows) - len(shown),
    )


def _breakouts(db: Session, caller: Caller, today: date) -> tuple[list[dict], str | None]:
    consented = {str(pid) for pid in db.execute(consent_subquery(ConsentPurpose.ANALYTICS.value)).scalars()}
    rows = [r for r in pro._rows(db) if r.player_id in consented]
    if not rows:
        return [], None
    first_year = min(r.end.year for r in rows)
    latest = max(r.end for r in rows)
    flagged = [a for a in breakout.detect(rows, first_year) if a.flagged]
    latest_label = next(r.season for r in rows if r.end == latest)
    flagged = sorted((a for a in flagged if a.season == latest_label), key=lambda a: -(a.score or 0))
    players = {str(p.id): p for p in db.execute(
        select(Player).where(Player.id.in_([uuid.UUID(a.player_id) for a in flagged]))).scalars()} if flagged else {}
    visible = [(a, players[a.player_id]) for a in flagged
               if a.player_id in players and may_view(db, caller, players[a.player_id])[0]][:BREAKOUTS_SHOWN]
    clubs = organization_names(db, [p.id for _, p in visible])
    return [_card(p, clubs, today) | {"season": a.season, "reason": a.reason,
                                      "minutesBefore": a.minutes_before, "minutesAfter": a.minutes_after}
            for a, p in visible], latest_label


def _late_bloomers(db: Session, caller: Caller, today: date) -> list[dict]:
    rows = db.execute(
        select(Flag, Player).join(Player, Player.id == Flag.player_id)
        .where(Flag.type == FlagType.LATE_BLOOMER.value)
        .where(Flag.status.in_([FlagStatus.OPEN.value, FlagStatus.CONFIRMED.value]))
        .order_by(Flag.raised_at.desc())
    ).all()
    seen, shown = set(), []
    for flag, player in rows:
        if player.id in seen or player.merged_into is not None or not may_view(db, caller, player)[0]:
            continue
        seen.add(player.id)
        shown.append((flag, player))
        if len(shown) == LATE_BLOOMERS_SHOWN:
            break
    clubs = organization_names(db, [p.id for _, p in shown])
    return [_card(p, clubs, today) | {"reason": f.reason, "status": f.status} for f, p in shown]


def home(db: Session, caller: Caller, today: date | None = None) -> dict:
    today = today or date.today()
    shortlist, withheld = _shortlist(db, caller, today)
    breakouts, season = _breakouts(db, caller, today)
    return {
        "firstName": (caller.full_name or "").split(" ")[0] or None,
        "shortlist": shortlist,
        "withheld": withheld,
        "breakouts": breakouts,
        "breakoutSeason": season,
        "lateBloomers": _late_bloomers(db, caller, today),
    }
