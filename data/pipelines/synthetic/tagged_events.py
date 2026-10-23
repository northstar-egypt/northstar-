"""Synthetic tagged match events, so the shot map and the tagging screen have something to show.

Real tags come from coaches watching match video (apps/web/app/(app)/matches/tag, decision
0005). The seeded database has match records but no video, so this module makes the events a
coach would have tagged from a footballer's last few matches, and writes them as if they had.

It works from the match records already in the database, not from the generator:

- **Existing databases get events too.** The seed container only loads the generator's data
  into an empty database (docker/seed.py), so events added to the generator would never reach a
  database that already has players. This runs every boot and adds events once.
- **The generator and its export are untouched**, so nothing the ML evaluations read changes and
  no published number in ml/README.md can move.

Each event is drawn on its own random stream seeded by the match record's id, so a database
always gets the same events. **A match's events add up exactly to its logged totals** (shots,
shots on target, goals, passes, completed passes, key passes, assists, tackles), by the sport
module's `counts`. The one exception: a record with more assists than key passes cannot be
matched, because every assist is also a key pass, so its key passes come out higher. Records
that fail their sport module (the planted impossible rows) are skipped, and so is a second
match record on a date a player already has one for.

Where on the pitch is drawn from the kind of event and the player's position group: shots from
inside the attacking third, goals closer and more central; passes and tackles in the zones the
player's role covers. These are plausible, not measured.

    python -m data.pipelines.synthetic.tagged_events --database-url postgresql+psycopg://...
"""

from __future__ import annotations

import argparse
import random

from . import orm  # noqa: F401  (puts apps/api on the path)

MATCHES_PER_PLAYER = 3
SOURCE = "coach_tagged"

POSITION_GROUPS = {
    "GK": "goalkeeper",
    "CB": "defender", "LB": "defender", "RB": "defender",
    "CDM": "midfielder", "CM": "midfielder", "CAM": "midfielder",
    "LW": "forward", "RW": "forward", "ST": "forward",
}
# How far up the pitch (x, 0 = own goal line) each group plays its passes and makes its tackles.
PASS_ZONE = {"goalkeeper": (2, 30), "defender": (8, 60), "midfielder": (25, 80), "forward": (45, 92)}
TACKLE_ZONE = {"goalkeeper": (3, 20), "defender": (8, 45), "midfielder": (25, 70), "forward": (45, 85)}
# Shots by outcome: (x range, spread of y around the centre line).
SHOT_ZONE = {
    "goal": ((83, 97), 10),
    "on_target": ((75, 96), 13),
    "off_target": ((68, 95), 18),
    "blocked": ((72, 92), 15),
}


def _clamp(value: float, low: float = 1, high: float = 99) -> float:
    return round(min(high, max(low, value)), 1)


def outcomes(metrics: dict, rng: random.Random) -> list[tuple[str, str]]:
    """(event type, outcome) pairs that add up to the record's totals."""
    get = lambda key: max(0, int(metrics.get(key) or 0))  # noqa: E731
    goals, on_target, shots = get("goals"), get("shots_on_target"), get("shots")
    assists, key_passes = get("assists"), get("key_passes")
    attempted, completed, tackles = get("passes_attempted"), get("passes_completed"), get("tackles")

    pairs = [("shot", "goal")] * goals
    pairs += [("shot", "on_target")] * max(0, on_target - goals)
    for _ in range(max(0, shots - max(on_target, goals))):
        pairs.append(("shot", "off_target" if rng.random() < 0.7 else "blocked"))

    plain_key = max(0, key_passes - assists)
    pairs += [("pass", "assist")] * assists
    pairs += [("pass", "key_pass")] * plain_key
    pairs += [("pass", "complete")] * max(0, completed - assists - plain_key)
    pairs += [("pass", "incomplete")] * max(0, attempted - max(completed, assists + plain_key))

    pairs += [("tackle", "won")] * tackles
    # Lost tackles are not a logged total; a coach would still tag some.
    pairs += [("tackle", "lost")] * round(tackles * rng.uniform(0.3, 0.8))
    return pairs


def events_for(entry_id: str, metrics: dict, position: str | None) -> list[dict]:
    """The events a coach would have tagged from one match record, with places and video times."""
    minutes = int(metrics.get("minutes_played") or 0)
    if minutes <= 0:
        return []
    rng = random.Random(f"tagged-events:{entry_id}")
    group = POSITION_GROUPS.get(position or "", "midfielder")
    events = []
    for event_type, outcome in outcomes(metrics, rng):
        if event_type == "shot":
            (x_low, x_high), spread = SHOT_ZONE[outcome]
            x, y = rng.uniform(x_low, x_high), rng.gauss(50, spread)
        elif event_type == "pass" and outcome in ("key_pass", "assist"):
            x, y = rng.uniform(60, 92), rng.uniform(10, 90)
        elif event_type == "pass":
            x, y = rng.uniform(*PASS_ZONE[group]), rng.uniform(5, 95)
        else:
            x, y = rng.uniform(*TACKLE_ZONE[group]), rng.uniform(5, 95)
        events.append({
            "event_type": event_type,
            "outcome": outcome,
            "x": _clamp(x),
            "y": _clamp(y),
            "video_seconds": round(rng.uniform(0, minutes * 60), 1),
        })
    events.sort(key=lambda e: e["video_seconds"])
    return events


def seed(database_url: str, matches_per_player: int = MATCHES_PER_PLAYER) -> int:
    """Add synthetic events once. Returns how many were written (0 when already present)."""
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    from app import sports
    from app.models.match_event import MatchEvent
    from app.models.organization import Organization
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player

    engine = create_engine(database_url, future=True)
    with Session(engine) as db:
        # Seeded events have no tagger; a coach's own tags always do. So a hand-tagged
        # database still gets the seeded ones, once.
        already = db.execute(
            select(func.count()).select_from(MatchEvent)
            .where(MatchEvent.tagged_by.is_(None)).where(MatchEvent.source == SOURCE)
        ).scalar_one()
        if already:
            return 0

        clubs = dict(db.execute(select(Organization.id, Organization.name)).all())
        rows = db.execute(
            select(PerformanceEntry, Player.position)
            .join(Player, Player.id == PerformanceEntry.player_id)
            .where(PerformanceEntry.schema_ref == "football.match.v1")
            .where(Player.status != "merged")
            .order_by(PerformanceEntry.player_id, PerformanceEntry.period_start.desc())
        ).all()

        modules = sports.registry()
        taken: dict = {}
        dates: set = set()
        written = 0
        for entry, position in rows:
            if taken.get(entry.player_id, 0) >= matches_per_player:
                continue
            if sports.validate(entry.metrics, entry.schema_ref, modules):
                continue
            # A few players have two match records on one date. Tagged totals are set beside
            # the logged ones by date, so only one of them is tagged.
            if (entry.player_id, entry.period_start) in dates:
                continue
            dates.add((entry.player_id, entry.period_start))
            taken[entry.player_id] = taken.get(entry.player_id, 0) + 1
            label = f"vs {clubs[entry.opponent_org_id]}" if entry.opponent_org_id in clubs else None
            for event in events_for(str(entry.id), entry.metrics, position):
                db.add(MatchEvent(
                    player_id=entry.player_id,
                    organization_id=entry.organization_id,
                    sport="football",
                    match_date=entry.period_start,
                    match_label=label,
                    source=SOURCE,
                    tagged_by=None,
                    **event,
                ))
                written += 1
        db.commit()
        return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--matches-per-player", type=int, default=MATCHES_PER_PLAYER)
    args = parser.parse_args()
    written = seed(args.database_url, args.matches_per_player)
    print(
        f"tagged events: wrote {written}" if written
        else "tagged events: already present, nothing written"
    )


if __name__ == "__main__":
    main()
