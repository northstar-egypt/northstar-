"""
Synthetic PlayerOrganization data generator for NorthStar.
Generates fake player-to-organization affiliation history matching the
PlayerOrganization table schema in docs/schema.md.

This is the many-to-many link: which club/academy a player belonged to and when.
Enforces the no-overlapping-active-affiliation constraint per (player, role).

Depends on: players.json, organizations.json (must be generated first).
"""
import json
import uuid
import random
from datetime import date, timedelta

ROLES = ["player", "youth_prospect", "trialist"]
ROLE_WEIGHTS = [0.6, 0.3, 0.1]


def random_affiliation_role(player):
    if player["is_minor"]:
        return random.choices(
            ["youth_prospect", "trialist", "player"], weights=[0.5, 0.3, 0.2], k=1
        )[0]
    return random.choices(ROLES, weights=ROLE_WEIGHTS, k=1)[0]


def generate_affiliations_for_player(player, orgs):
    rows = []
    num_affiliations = random.randint(1, 3)
    cursor = date.today() - timedelta(days=random.randint(400, 1500))

    for i in range(num_affiliations):
        org = random.choice(orgs)
        role = random_affiliation_role(player)
        start_date = cursor
        is_current = i == num_affiliations - 1

        if is_current:
            end_date = None
        else:
            duration = timedelta(days=random.randint(90, 500))
            end_date = start_date + duration
            cursor = end_date + timedelta(days=random.randint(1, 30))

        rows.append({
            "id": str(uuid.uuid4()),
            "player_id": player["id"],
            "organization_id": org["id"],
            "role": role,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat() if end_date else None,
            "shirt_number": random.randint(1, 99) if role == "player" and random.random() > 0.2 else None,
        })
    return rows


def generate_player_organizations(players, orgs):
    rows = []
    for player in players:
        rows.extend(generate_affiliations_for_player(player, orgs))
    return rows


if __name__ == "__main__":
    with open("data/synthetic/players.json", encoding="utf-8") as f:
        players = json.load(f)
    with open("data/synthetic/organizations.json", encoding="utf-8") as f:
        orgs = json.load(f)

    affiliations = generate_player_organizations(players, orgs)
    with open("data/synthetic/player_organizations.json", "w", encoding="utf-8") as f:
        json.dump(affiliations, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(affiliations)} synthetic player-organization affiliations -> data/synthetic/player_organizations.json")
