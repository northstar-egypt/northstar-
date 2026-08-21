"""
Synthetic User data generator for NorthStar.
Generates fake platform accounts matching the User table schema in docs/schema.md.

Depends on: players.json, organizations.json (must be generated first).
"""
import json
import uuid
import random
from datetime import datetime, timedelta, timezone
from faker import Faker

fake = Faker()

ROLES = ["coach", "scout", "federation", "player", "admin"]
ROLE_WEIGHTS = [0.30, 0.20, 0.10, 0.35, 0.05]

FAKE_HASH_PREFIX = "argon2$fakehash$"


def random_timestamp(days_back=180):
    delta = timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    return (datetime.now(timezone.utc) - delta).isoformat()


def generate_user(orgs, players, used_player_ids):
    role = random.choices(ROLES, weights=ROLE_WEIGHTS, k=1)[0]

    organization_id = random.choice(orgs)["id"] if orgs and random.random() > 0.1 else None

    linked_player_id = None
    if role == "player" and players:
        available = [p["id"] for p in players if p["id"] not in used_player_ids]
        if available:
            linked_player_id = random.choice(available)
            used_player_ids.add(linked_player_id)

    is_active = random.random() > 0.08

    return {
        "id": str(uuid.uuid4()),
        "email": fake.unique.email(),
        "password_hash": FAKE_HASH_PREFIX + uuid.uuid4().hex,
        "full_name": fake.name(),
        "role": role,
        "organization_id": organization_id,
        "linked_player_id": linked_player_id,
        "is_active": is_active,
        "last_login_at": random_timestamp() if is_active and random.random() > 0.15 else None,
    }


def generate_users(orgs, players, count=15):
    used_player_ids = set()
    return [generate_user(orgs, players, used_player_ids) for _ in range(count)]


if __name__ == "__main__":
    with open("data/synthetic/organizations.json", encoding="utf-8") as f:
        orgs = json.load(f)
    with open("data/synthetic/players.json", encoding="utf-8") as f:
        players = json.load(f)

    users = generate_users(orgs, players, 15)
    with open("data/synthetic/users.json", "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(users)} synthetic users -> data/synthetic/users.json")
