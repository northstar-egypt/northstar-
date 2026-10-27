"""Similar players on the profile, from the graded method in ml/similarity.py.

This file does not contain a model. It runs `ml/similarity.py`, which
`python -m ml.run_similarity_eval` grades against what the generator hides (ml/README.md,
"Player similarity"), on the rows in this database.

Who is in it
------------
- **Analytics consent.** Only players whose analytics consent is in effect have a profile at
  all, and only they make up the reference each statistic is standardised against: comparing
  a child with others is analytics on their data, whoever is asking.
- **Who may see whom.** A similar player is listed only if the caller may see them
  (`access.may_view`), so a scout never learns from this list that a withheld minor exists.

Caching
-------
Profiles are rebuilt when the performance rows, the players or the consents change, checked
with three cheap queries per request, as the rating does.
TODO: at national scale this belongs in a batch job, not a request.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ConsentPurpose, PlayerStatus
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import cohort
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services.access import (
    Caller,
    consent_signature,
    consent_subquery,
    has_consent,
    may_view,
)

from ml import similarity  # noqa: E402
from ml.detectors.features import FeatureSet  # noqa: E402

K = 5

LABELS = {
    "shots": "shots per 90",
    "shots_on_target": "shots on target per 90",
    "goals": "goals per 90",
    "assists": "assists per 90",
    "key_passes": "key passes per 90",
    "tackles": "tackles per 90",
    "passes_attempted": "passes per 90",
    "distance_km": "distance per 90",
    "pass_completion": "pass completion",
    "service_winners": "service winners per set",
    "unforced_errors": "unforced errors per set",
    "point_share": "share of points won",
    "set_share": "share of sets won",
}


@dataclass
class _Cache:
    signature: tuple = ()
    profiles: dict[str, similarity.Profile] = field(default_factory=dict)


_cache = _Cache()
_lock = threading.Lock()


def _signature(db: Session) -> tuple:
    rows = tuple(db.execute(select(func.count(), func.max(PerformanceEntry.updated_at))).one())
    people = tuple(db.execute(select(func.count(), func.max(Player.updated_at))).one())
    return (rows, people, consent_signature(db, ConsentPurpose.ANALYTICS.value), date.today())


def _build(db: Session) -> dict[str, similarity.Profile]:
    consented = select(consent_subquery(ConsentPurpose.ANALYTICS.value).subquery().c.player_id)
    players = db.execute(
        select(Player).where(Player.status != PlayerStatus.MERGED).where(Player.id.in_(consented))
    ).scalars().all()
    ids = [p.id for p in players]
    entries = db.execute(
        select(PerformanceEntry).where(PerformanceEntry.player_id.in_(ids))
    ).scalars().all() if ids else []
    raw = {
        "players": [
            {
                "id": str(p.id),
                "sex": p.sex,
                "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
                "primary_sport": p.primary_sport,
                "position": p.position,
                "status": p.status,
            }
            for p in players
        ],
        "performance_entries": [
            {
                "id": str(e.id),
                "player_id": str(e.player_id),
                "sport": e.sport,
                "period_type": e.period_type,
                "period_start": e.period_start.isoformat() if e.period_start else None,
                "schema_ref": e.schema_ref,
                "metrics": e.metrics,
                "opponent_player_id": str(e.opponent_player_id) if e.opponent_player_id else None,
                "is_validated": e.is_validated,
                "source": e.source,
            }
            for e in entries
        ],
    }
    return similarity.profiles(FeatureSet("database", raw=raw))


def _profiles(db: Session) -> dict[str, similarity.Profile]:
    signature = _signature(db)
    with _lock:
        if _cache.signature != signature:
            _cache.profiles = _build(db)
            _cache.signature = signature
        return _cache.profiles


def reset_cache() -> None:
    with _lock:
        _cache.signature = ()
        _cache.profiles = {}


def similar_players(db: Session, caller: Caller, player: Player) -> dict:
    """The block for GET /players/{id}/similar: a list, and a note that says what it is."""
    every = _profiles(db)
    pid = str(player.id)
    if pid not in every:
        if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
            note = "Analytics consent is not in effect for this player, so they are not compared."
        else:
            note = (
                "Not enough on record to compare yet: similarity needs 450 minutes of football "
                "or 20 sets of table tennis."
            )
        return {"items": [], "note": note}

    me = every[pid]
    ranked = similarity.nearest(pid, every, k=len(every))
    items = []
    if ranked:
        candidates = {
            str(p.id): p
            for p in db.execute(
                select(Player).where(Player.id.in_([q for q, _ in ranked]))
            ).scalars()
        }
        today = date.today()
        for other_id, gap in ranked:
            other = candidates.get(other_id)
            if other is None or not may_view(db, caller, other)[0]:
                continue
            items.append(
                {
                    "player_id": other.id,
                    "full_name": other.full_name,
                    "position": other.position,
                    "age_label": cohort.age_label(other.date_of_birth, today),
                    "distance": round(gap, 2),
                    "alike": [
                        LABELS.get(k, k) for k in similarity.closest_statistics(me, every[other_id])
                    ],
                }
            )
            if len(items) == K:
                break
    sport = "per 90 minutes" if me.sport == "football" else "per set"
    return {
        "items": items,
        "note": (
            f"Compared on their match record only ({sport}), with players of the same sport and "
            "gender, at any age. It finds players who play a similar role well, and players of "
            "a similar level only in part."
        ),
    }
