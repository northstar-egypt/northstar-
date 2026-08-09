"""
Synthetic Player data generator for NorthStar.
Generates fake players matching the Player table schema in docs/schema.md.
"""
import json
import uuid
import random
from datetime import date, timedelta
from faker import Faker

fake = Faker()

SPORTS = ["football", "table_tennis"]
TIERS = ["pro", "youth", "diaspora"]
SEXES = ["male", "female"]

def random_date_of_birth(min_age=14, max_age=35):
    today = date.today()
    days_old = random.randint(min_age * 365, max_age * 365)
    return today - timedelta(days=days_old)

def generate_player():
    dob = random_date_of_birth()
    age = (date.today() - dob).days // 365
    sport = random.choice(SPORTS)

    return {
        "id": str(uuid.uuid4()),
        "full_name": fake.name(),
        "known_as": fake.first_name(),
        "date_of_birth": dob.isoformat(),
        "sex": random.choice(SEXES),
        "nationality": ["EG"] if random.random() > 0.2 else ["EG", fake.country_code()],
        "is_egypt_eligible": True,
        "primary_sport": sport,
        "tier": random.choice(TIERS) if sport == "football" else None,
        "position": random.choice(["GK", "DF", "MF", "ST"]) if sport == "football" else None,
        "is_minor": age < 18,
        "external_ids": {"footystats": random.randint(1000, 9999)},
        "status": "active",
        "merged_into": None,
    }

def generate_players(count=20):
    return [generate_player() for _ in range(count)]

if __name__ == "__main__":
    players = generate_players(20)
    with open("data/synthetic/players.json", "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(players)} synthetic players -> data/synthetic/players.json")
