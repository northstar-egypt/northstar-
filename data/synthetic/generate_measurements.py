"""
Synthetic Measurement data generator for NorthStar.
Generates fake time-series biometric/physical-test readings matching the
Measurement table schema in docs/schema.md.

Long-format: one row per player per metric per date. This is what growth-curve
and maturity-model work (ML track) reads.

Depends on: players.json, users.json (must be generated first).
"""
import json
import uuid
import random
from datetime import date, timedelta
from faker import Faker

fake = Faker()

# metric -> (unit, base value range, per-reading drift range)
METRICS = {
    "height_cm": ("cm", (140, 195), (0, 1.5)),
    "weight_kg": ("kg", (40, 95), (-1.0, 1.5)),
    "sprint_10m_s": ("s", (1.6, 2.3), (-0.05, 0.05)),
}

SOURCES = ["coach_logged", "self_submitted", "import", "api"]
SOURCE_WEIGHTS = [0.5, 0.2, 0.2, 0.1]


def random_series_dates(num_points, span_days=540):
    """Ascending, roughly evenly spaced dates over the trailing span."""
    today = date.today()
    start = today - timedelta(days=span_days)
    offsets = sorted(random.sample(range(span_days), num_points))
    return [start + timedelta(days=o) for o in offsets]


def generate_measurements_for_player(player, users):
    rows = []
    coach_or_admin_users = [
        u["id"] for u in users if u["role"] in ("coach", "admin") and u["is_active"]
    ]

    for metric, (unit, value_range, drift_range) in METRICS.items():
        num_points = random.randint(3, 6)
        dates = random_series_dates(num_points)
        value = round(random.uniform(*value_range), 1)

        for measured_at in dates:
            value = round(value + random.uniform(*drift_range), 1)
            source = random.choices(SOURCES, weights=SOURCE_WEIGHTS, k=1)[0]
            recorded_by = (
                random.choice(coach_or_admin_users)
                if source == "coach_logged" and coach_or_admin_users
                else None
            )

            rows.append({
                "id": str(uuid.uuid4()),
                "player_id": player["id"],
                "measured_at": measured_at.isoformat(),
                "metric": metric,
                "value": value,
                "unit": unit,
                "source": source,
                "recorded_by": recorded_by,
                "confidence": "measured" if source != "import" else random.choice(["measured", "estimated"]),
            })
    return rows


def generate_measurements(players, users):
    rows = []
    for player in players:
        rows.extend(generate_measurements_for_player(player, users))
    return rows


if __name__ == "__main__":
    with open("data/synthetic/players.json", encoding="utf-8") as f:
        players = json.load(f)
    with open("data/synthetic/users.json", encoding="utf-8") as f:
        users = json.load(f)

    measurements = generate_measurements(players, users)
    with open("data/synthetic/measurements.json", "w", encoding="utf-8") as f:
        json.dump(measurements, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(measurements)} synthetic measurements -> data/synthetic/measurements.json")
