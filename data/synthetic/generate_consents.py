"""
Synthetic Consent data generator for NorthStar.
Generates fake consent/privacy records matching the Consent table schema in
docs/schema.md. First-class because much of the youth data is about minors --
guardian_name is populated whenever the player is a minor.

Depends on: players.json (must be generated first).
"""
import json
import uuid
import random
from datetime import date, timedelta
from faker import Faker

fake = Faker()

PURPOSES = ["data_storage", "analytics", "scouting_visibility"]


def generate_consent_for_player(player):
    rows = []
    is_minor = player["is_minor"]
    # Not every player has a record for every purpose (some are TODO'd as pending).
    purposes = random.sample(PURPOSES, k=random.randint(1, len(PURPOSES)))

    for purpose in purposes:
        granted = random.random() > 0.1
        valid_from = date.today() - timedelta(days=random.randint(30, 700))
        # Open-ended consent is the common case; some expire.
        valid_until = (
            None if random.random() > 0.25
            else valid_from + timedelta(days=random.randint(180, 1000))
        )

        guardian_name = fake.name() if is_minor else None
        granted_by = guardian_name if is_minor else player["full_name"]

        rows.append({
            "id": str(uuid.uuid4()),
            "player_id": player["id"],
            "purpose": purpose,
            "granted": granted,
            "granted_by": granted_by,
            "guardian_name": guardian_name,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat() if valid_until else None,
            "document_ref": f"consent-docs/{uuid.uuid4().hex[:8]}.pdf" if random.random() > 0.4 else None,
        })
    return rows


def generate_consents(players):
    rows = []
    for player in players:
        rows.extend(generate_consent_for_player(player))
    return rows


if __name__ == "__main__":
    with open("data/synthetic/players.json", encoding="utf-8") as f:
        players = json.load(f)

    consents = generate_consents(players)
    with open("data/synthetic/consents.json", "w", encoding="utf-8") as f:
        json.dump(consents, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(consents)} synthetic consent records -> data/synthetic/consents.json")
