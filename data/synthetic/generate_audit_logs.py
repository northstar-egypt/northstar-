"""
Synthetic AuditLog data generator for NorthStar.
Generates fake append-only audit records matching the AuditLog table schema in
docs/schema.md. Feeds the security workstream (accountability) and the
integrity board (surfacing suspicious activity).

Depends on: users.json, players.json, performance_entries.json (must be generated first).
"""
import json
import uuid
import random
from datetime import datetime, timedelta, timezone
from faker import Faker

fake = Faker()

# (action, entity_type) pairs. entity_type=None means the action has no single row target.
ACTIONS = [
    ("login.success", None),
    ("login.failed", None),
    ("search.run", None),
    ("player.create", "Player"),
    ("player.update", "Player"),
    ("player.view", "Player"),
    ("measurement.create", "Measurement"),
    ("performance_entry.create", "PerformanceEntry"),
    ("consent.update", "Consent"),
    ("user.role_change", "User"),
]


def entity_id_for(entity_type, players, performance_entries, users):
    if entity_type == "Player" and players:
        return random.choice(players)["id"]
    if entity_type == "PerformanceEntry" and performance_entries:
        return random.choice(performance_entries)["id"]
    if entity_type == "User" and users:
        return random.choice(users)["id"]
    if entity_type in ("Measurement", "Consent"):
        # Standalone tables not always loaded by this generator; still needs an id.
        return str(uuid.uuid4())
    return None


def generate_log_entry(users, players, performance_entries):
    action, entity_type = random.choice(ACTIONS)
    is_system_action = action == "login.failed" and random.random() > 0.5

    actor_user_id = None if is_system_action else (random.choice(users)["id"] if users else None)
    entity_id = entity_id_for(entity_type, players, performance_entries, users)

    metadata = None
    if action == "player.update":
        metadata = {"changed_fields": random.sample(["tier", "position", "status"], k=1)}
    elif action == "user.role_change":
        metadata = {"from_role": "scout", "to_role": "coach"}
    elif action == "login.failed":
        metadata = {"reason": random.choice(["bad_password", "unknown_email", "account_locked"])}

    created_at = datetime.now(timezone.utc) - timedelta(
        days=random.randint(0, 120),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )

    return {
        "id": str(uuid.uuid4()),
        "actor_user_id": actor_user_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "metadata": metadata,
        "ip_address": fake.ipv4(),
        "created_at": created_at.isoformat(),
    }


def generate_audit_logs(users, players, performance_entries, count=60):
    rows = [generate_log_entry(users, players, performance_entries) for _ in range(count)]
    rows.sort(key=lambda r: r["created_at"])
    return rows


if __name__ == "__main__":
    with open("data/synthetic/users.json", encoding="utf-8") as f:
        users = json.load(f)
    with open("data/synthetic/players.json", encoding="utf-8") as f:
        players = json.load(f)
    with open("data/synthetic/performance_entries.json", encoding="utf-8") as f:
        performance_entries = json.load(f)

    logs = generate_audit_logs(users, players, performance_entries, 60)
    with open("data/synthetic/audit_logs.json", "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(logs)} synthetic audit log entries -> data/synthetic/audit_logs.json")
