"""
Synthetic Organization data generator for NorthStar.
Generates fake clubs, academies, national teams, and federations
matching the Organization table schema in docs/schema.md.
"""
import json
import uuid
import random
from faker import Faker

fake = Faker()

ORG_TYPES = ["club", "academy", "national_team", "federation"]
SPORTS = ["football", "table_tennis", None]  # None = multi-sport body
COUNTRIES = ["EG", "SD", "LY", "SA", "MA", "TN"]

def generate_organization(parent_pool=None):
    org_type = random.choice(ORG_TYPES)
    parent_id = None
    if parent_pool and org_type == "academy" and random.random() > 0.4:
        parent_id = random.choice(parent_pool)

    name_map = {
        "club": f"{fake.city()} SC",
        "academy": f"{fake.city()} Youth Academy",
        "national_team": f"{fake.country()} National Team",
        "federation": f"{fake.country()} Sports Federation",
    }

    return {
        "id": str(uuid.uuid4()),
        "name": name_map[org_type],
        "type": org_type,
        "sport": random.choice(SPORTS) if org_type != "federation" else None,
        "country": random.choice(COUNTRIES),
        "parent_org_id": parent_id,
        "external_ids": {"footystats": random.randint(100, 999)},
    }

def generate_organizations(count=10):
    orgs = []
    clubs_and_teams = []
    for _ in range(count):
        org = generate_organization(parent_pool=clubs_and_teams)
        if org["type"] in ("club", "national_team"):
            clubs_and_teams.append(org["id"])
        orgs.append(org)
    return orgs

if __name__ == "__main__":
    orgs = generate_organizations(10)
    with open("data/synthetic/organizations.json", "w", encoding="utf-8") as f:
        json.dump(orgs, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(orgs)} synthetic organizations -> data/synthetic/organizations.json")
