"""
Synthetic PerformanceEntry data generator for NorthStar.
Generates fake sport-specific performance records matching the PerformanceEntry
table schema in docs/schema.md. This is where the per-sport JSON metrics blob lives.

Depends on: players.json, organizations.json (must be generated first).
"""
import json
import uuid
import random
from datetime import date, timedelta

PERIOD_TYPES = ["match", "session", "tournament", "season_aggregate"]
SOURCES = ["api", "scrape", "coach_logged", "self_submitted", "import"]
SOURCE_WEIGHTS = [0.2, 0.15, 0.35, 0.2, 0.1]


def football_metrics():
    minutes = random.choice([0, 30, 45, 60, 70, 90])
    return {
        "minutes": minutes,
        "goals": random.choices([0, 1, 2, 3], weights=[0.6, 0.25, 0.1, 0.05])[0],
        "assists": random.choices([0, 1, 2], weights=[0.7, 0.25, 0.05])[0],
        "xg": round(random.uniform(0, 1.2), 2),
        "shots": random.randint(0, 6),
        "passes_completed": random.randint(5, 60),
        "distance_km": round(minutes / 90 * random.uniform(8.5, 11.5), 1),
    }


def table_tennis_metrics():
    played = random.randint(1, 6)
    won = random.randint(0, played)
    return {
        "matches_played": played,
        "matches_won": won,
        "sets_won": random.randint(won, won * 3 + 1),
        "sets_lost": random.randint(0, (played - won) * 3 + 1),
        "avg_rally_length": round(random.uniform(2.5, 6.0), 1),
        "service_points_won_pct": round(random.uniform(0.4, 0.7), 2),
    }


def generate_entry(player, orgs):
    sport = player["primary_sport"]
    period_type = random.choice(PERIOD_TYPES)
    period_start = date.today() - timedelta(days=random.randint(1, 500))
    period_end = (
        None if period_type == "match"
        else period_start + timedelta(days=random.randint(1, 90))
    )

    organization_id = random.choice(orgs)["id"] if orgs and random.random() > 0.15 else None
    opponent_org_id = None
    if period_type == "match" and orgs and random.random() > 0.2:
        candidates = [o["id"] for o in orgs if o["id"] != organization_id]
        opponent_org_id = random.choice(candidates) if candidates else None

    metrics = football_metrics() if sport == "football" else table_tennis_metrics()
    source = random.choices(SOURCES, weights=SOURCE_WEIGHTS, k=1)[0]

    return {
        "id": str(uuid.uuid4()),
        "player_id": player["id"],
        "sport": sport,
        "period_type": period_type,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat() if period_end else None,
        "organization_id": organization_id,
        "opponent_org_id": opponent_org_id,
        "metrics": metrics,
        "schema_ref": f"{sport}@1",
        "source": source,
        "is_validated": random.random() > 0.05,
    }


def generate_performance_entries(players, orgs, entries_per_player_range=(2, 5)):
    rows = []
    for player in players:
        num_entries = random.randint(*entries_per_player_range)
        rows.extend(generate_entry(player, orgs) for _ in range(num_entries))
    return rows


if __name__ == "__main__":
    with open("data/synthetic/players.json", encoding="utf-8") as f:
        players = json.load(f)
    with open("data/synthetic/organizations.json", encoding="utf-8") as f:
        orgs = json.load(f)

    entries = generate_performance_entries(players, orgs)
    with open("data/synthetic/performance_entries.json", "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(entries)} synthetic performance entries -> data/synthetic/performance_entries.json")
