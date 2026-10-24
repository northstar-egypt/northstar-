"""The governorate of each synthetic Egyptian club and academy (Organization.region).

Two rules, and no random draw, so the generator's random stream and every number the ML
evaluations read stay exactly as they were:

1. **The name says where.** Several club and academy names belong to a place: Al Masry is
   Port Said, Ismaily is Ismailia, "Aswan Academy" is in Aswan. `HOME` lists those.
2. **Otherwise, a fixed draw from the name.** The name is hashed, and the hash picks a
   governorate with probability in proportion to its population (app/regions.py). The same
   name always gets the same governorate. With some 30 organizations most small governorates
   get none, which is the realistic picture the coverage panel is there to show.

National teams, federations and clubs abroad have no governorate.

`backfill` fills the column in a database seeded before it existed; the seed container runs
it on every boot through `backfill_regions` (docker/seed.py, step 5), and it only touches rows
that have no region yet.
"""

from __future__ import annotations

import hashlib

from . import orm  # noqa: F401  (puts apps/api on the path)

from app.regions import GOVERNORATES  # noqa: E402

# Names whose governorate is part of what they mean.
HOME = {
    "الأهلي": "EG-C",
    "الزمالك": "EG-GZ",
    "بيراميدز": "EG-C",
    "المصري": "EG-PTS",
    "الإسماعيلي": "EG-IS",
    "سموحة": "EG-ALX",
    "إنبي": "EG-C",
    "المقاولون العرب": "EG-C",
    "طلائع الجيش": "EG-C",
    "سيراميكا": "EG-C",
    "البنك الأهلي": "EG-C",
    "فاركو": "EG-ALX",
    "غزل المحلة": "EG-GH",
    "الاتحاد السكندري": "EG-ALX",
    "بلدية المحلة": "EG-GH",
    "الجونة": "EG-BA",
    "أكاديمية وادي دجلة": "EG-C",
    "أكاديمية الجزيرة": "EG-C",
    "أكاديمية طيبة": "EG-LX",
    "أكاديمية الأقصر": "EG-LX",
    "أكاديمية بورسعيد": "EG-PTS",
    "أكاديمية أسوان": "EG-ASN",
}
WITH_A_GOVERNORATE = ("club", "academy")


def region_for(name: str, org_type: str, country: str) -> str | None:
    """The governorate code for a synthetic organization, or None when it has none."""
    if country != "EG" or org_type not in WITH_A_GOVERNORATE:
        return None
    if name in HOME:
        return HOME[name]
    # A fixed point in [0, total population), from the name alone.
    codes = sorted(GOVERNORATES)
    total = sum(GOVERNORATES[c].population for c in codes)
    point = int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16) % total
    for code in codes:
        point -= GOVERNORATES[code].population
        if point < 0:
            return code
    return codes[-1]


def backfill(database_url: str) -> int:
    """Set the governorate of every synthetic Egyptian club and academy that has none."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models.organization import Organization

    engine = create_engine(database_url, future=True)
    with Session(engine) as db:
        updated = 0
        for org in db.execute(select(Organization).where(Organization.region.is_(None))).scalars():
            # Only the generator's own rows: a real organization's region is the federation's call.
            if (org.external_ids or {}).get("source") != "synthetic":
                continue
            code = region_for(org.name, org.type, org.country)
            if code:
                org.region = code
                updated += 1
        db.commit()
        return updated
