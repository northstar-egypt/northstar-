"""Synthetic tagged match events, so the shot map, the points breakdown and the tagging screen
have something to show.

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

Football: where on the pitch is drawn from the kind of event and the player's position group:
shots from inside the attacking third, goals closer and more central; passes and tackles in the
zones the player's role covers. Table tennis: one event per point, won or lost and how, placed
where the deciding ball landed on the table (`TABLE_ZONE`). These are plausible, not measured.

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


def table_tennis_points(metrics: dict, rng: random.Random) -> list[tuple[str, str]]:
    """(event type, outcome) pairs, one per point, that add up to the record's totals."""
    get = lambda key: max(0, int(metrics.get(key) or 0))  # noqa: E731
    won, lost = get("points_won"), get("points_lost")
    service, unforced = min(get("service_winners"), won), min(get("unforced_errors"), lost)
    pairs = [("point_won", "service_winner")] * service
    for _ in range(won - service):
        pairs.append(("point_won", "winner" if rng.random() < 0.6 else "opponent_error"))
    pairs += [("point_lost", "unforced_error")] * unforced
    for _ in range(lost - unforced):
        pairs.append(("point_lost", "opponent_winner" if rng.random() < 0.6 else "forced_error"))
    return pairs


# Where the deciding ball landed on the table (x from the player's own end, 0, to the
# opponent's, 100): a winner on the opponent's half, an error at the net or long, the
# opponent's winner on the player's own half.
TABLE_ZONE = {
    "winner": (55, 97), "service_winner": (60, 97), "opponent_error": (3, 48),
    "unforced_error": (46, 99), "forced_error": (46, 99), "opponent_winner": (3, 45),
}


def table_tennis_events_for(entry_id: str, metrics: dict, position: str | None = None) -> list[dict]:
    """The points a coach would have tagged from one table tennis match record."""
    sets = int(metrics.get("sets_won") or 0) + int(metrics.get("sets_lost") or 0)
    if sets <= 0:
        return []
    rng = random.Random(f"tagged-events:{entry_id}")
    pairs = table_tennis_points(metrics, rng)
    rng.shuffle(pairs)
    # About eight minutes a set; points spread through the match in order.
    seconds = sorted(rng.uniform(0, sets * 480) for _ in pairs)
    events = []
    for (event_type, outcome), at in zip(pairs, seconds):
        low, high = TABLE_ZONE[outcome]
        events.append({
            "event_type": event_type,
            "outcome": outcome,
            "x": _clamp(rng.uniform(low, high)),
            "y": _clamp(rng.uniform(5, 95)),
            "video_seconds": round(at, 1),
        })
    return events


SPORTS = {"football": "football.match.v1", "table_tennis": "table_tennis.match.v1"}

# The details a coach adds after the outcome (decision 0007), drawn per tag. Plausible, not
# measured, and the finishing screen says its rates come from these. A coach does not always
# add them, so some tags have none.
DETAIL_SHARE = {"football": 0.8, "table_tennis": 0.85}
SITUATION = {  # by shot outcome: one on one, open play, set piece, penalty
    "goal": (0.22, 0.55, 0.15, 0.08),
    "on_target": (0.12, 0.68, 0.17, 0.03),
    "off_target": (0.07, 0.73, 0.18, 0.02),
    "blocked": (0.04, 0.78, 0.18, 0.0),
}
SITUATIONS = ("one_on_one", "open_play", "set_piece", "penalty")
PLACEMENTS = ("top_left", "top_middle", "top_right", "bottom_left", "bottom_middle", "bottom_right")
# Goals go in more often low and wide; saves come more often from shots at the middle.
PLACEMENT = {
    "goal": (0.15, 0.10, 0.15, 0.22, 0.16, 0.22),
    "on_target": (0.12, 0.25, 0.12, 0.13, 0.25, 0.13),
}
STROKE = {  # by point outcome: serve, forehand, backhand
    "service_winner": (1.0, 0.0, 0.0),
    "winner": (0.0, 0.6, 0.4),
    "opponent_error": (0.1, 0.55, 0.35),
    "unforced_error": (0.05, 0.45, 0.5),
    "forced_error": (0.0, 0.5, 0.5),
    "opponent_winner": (0.0, 0.5, 0.5),
}


def details_for(event_type: str, outcome: str, rng: random.Random) -> dict | None:
    """What a coach might have added to one tag, or None when they added nothing."""
    pick = lambda options, weights: rng.choices(options, weights)[0]  # noqa: E731
    if event_type == "shot":
        if rng.random() > DETAIL_SHARE["football"]:
            return None
        situation = pick(SITUATIONS, SITUATION[outcome])
        if situation == "penalty":
            technique = pick(("placed", "power"), (0.7, 0.3))
        elif situation == "set_piece":
            technique = pick(("header", "power", "placed", "volley"), (0.45, 0.25, 0.2, 0.1))
        elif situation == "one_on_one":
            technique = pick(("placed", "power", "chip"), (0.6, 0.25, 0.15))
        else:
            technique = pick(("placed", "power", "header", "volley", "chip"), (0.4, 0.35, 0.12, 0.1, 0.03))
        out = {"situation": situation, "technique": technique}
        if outcome in PLACEMENT:
            out["placement"] = pick(PLACEMENTS, PLACEMENT[outcome])
        if situation == "one_on_one":
            out["keeper_distance"] = pick(("under_3", "from_3_to_6", "over_6"), (0.3, 0.45, 0.25))
        return out
    if event_type in ("point_won", "point_lost") and outcome in STROKE:
        if rng.random() > DETAIL_SHARE["table_tennis"]:
            return None
        return {"stroke": pick(("serve", "forehand", "backhand"), STROKE[outcome])}
    return None


def add_details(db) -> int:
    """Add details to generated tags that have none: tags made before details existed, and new
    ones. Each tag's are drawn on a stream seeded by its id, so a database always gets the same.
    A tag drawn to have none is marked {} so it is not drawn again. Coaches' own tags are never
    touched."""
    from sqlalchemy import select

    from app.models.match_event import MatchEvent

    rows = db.execute(
        select(MatchEvent)
        .where(MatchEvent.tagged_by.is_(None))
        .where(MatchEvent.source == SOURCE)
        .where(MatchEvent.details.is_(None))
    ).scalars()
    written = 0
    for event in rows:
        drawn = details_for(event.event_type, event.outcome, random.Random(f"tag-details:{event.id}"))
        event.details = drawn or {}
        written += bool(drawn)
    return written


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
        clubs = dict(db.execute(select(Organization.id, Organization.name)).all())
        modules = sports.registry()
        written = 0
        for sport, schema_ref in SPORTS.items():
            # Seeded events have no tagger; a coach's own tags always do. So a hand-tagged
            # database still gets the seeded ones, once per sport: a database seeded before a
            # sport had event types gets that sport's on the next boot.
            already = db.execute(
                select(func.count()).select_from(MatchEvent)
                .where(MatchEvent.tagged_by.is_(None)).where(MatchEvent.source == SOURCE)
                .where(MatchEvent.sport == sport)
            ).scalar_one()
            if already:
                continue
            rows = db.execute(
                select(PerformanceEntry, Player.position)
                .join(Player, Player.id == PerformanceEntry.player_id)
                .where(PerformanceEntry.schema_ref == schema_ref)
                .where(Player.status != "merged")
                .order_by(PerformanceEntry.player_id, PerformanceEntry.period_start.desc())
            ).all()
            written += _seed_rows(db, sport, rows, clubs, modules, matches_per_player)
        db.flush()
        detailed = add_details(db)
        db.commit()
        if detailed:
            print(f"tagged events: added details to {detailed}")
        return written


def _seed_rows(db, sport: str, rows, clubs: dict, modules: dict, matches_per_player: int) -> int:
    from app import sports
    from app.models.match_event import MatchEvent

    make = {"football": events_for, "table_tennis": table_tennis_events_for}[sport]
    taken: dict = {}
    dates: set = set()
    written = 0
    for entry, position in rows:
        if taken.get(entry.player_id, 0) >= matches_per_player:
            continue
        if sports.validate(entry.metrics, entry.schema_ref, modules):
            continue
        # A few players have two match records on one date. Tagged totals are set beside the
        # logged ones by date, so only one of them is tagged.
        if (entry.player_id, entry.period_start) in dates:
            continue
        dates.add((entry.player_id, entry.period_start))
        taken[entry.player_id] = taken.get(entry.player_id, 0) + 1
        # A club opponent is named; a table tennis opponent is a person, possibly another club's
        # child, so the label never names them.
        label = f"vs {clubs[entry.opponent_org_id]}" if entry.opponent_org_id in clubs else None
        for event in make(str(entry.id), entry.metrics, position):
            db.add(MatchEvent(
                player_id=entry.player_id,
                organization_id=entry.organization_id,
                sport=sport,
                match_date=entry.period_start,
                match_label=label,
                source=SOURCE,
                tagged_by=None,
                **event,
            ))
            written += 1
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
