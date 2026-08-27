"""Organizations: federations, clubs, academies and national teams."""

from __future__ import annotations

from .config import GeneratorConfig
from .orm import Organization, enums
from .reference import (
    ACADEMY_NAME_PARTS_AR,
    CLUB_NAME_PARTS_AR,
    DIASPORA_COUNTRIES,
    EGYPT,
    FEDERATION_NAMES,
    FOREIGN_CLUB_NAMES,
    NATIONAL_TEAM_SUFFIXES,
)
from .rng import Rng


def generate_organizations(rng: Rng, config: GeneratorConfig) -> list[Organization]:
    """Build the org hierarchy.

    Federations sit at the top and parent the national teams and the domestic
    clubs of their sport, which exercises `parent_org_id` and gives the
    federation oversight screens something to drill down through.
    """
    cfg = config.organizations
    orgs: list[Organization] = []

    federations: dict[str, Organization] = {}
    for name, sport in FEDERATION_NAMES[: cfg.n_federations]:
        fed = Organization(
            id=rng.uuid(),
            name=name,
            type=enums.OrganizationType.FEDERATION.value,
            sport=sport,
            country=EGYPT,
            parent_org_id=None,
            external_ids={},
        )
        federations[sport] = fed
        orgs.append(fed)

    def parent_for(sport: str, country: str):
        # Only Egyptian organizations sit under an Egyptian federation.
        if country != EGYPT:
            return None
        fed = federations.get(sport)
        return fed.id if fed else None

    club_names = rng.shuffled(CLUB_NAME_PARTS_AR)
    foreign_names = rng.shuffled(FOREIGN_CLUB_NAMES)
    n_foreign = round(cfg.n_clubs * cfg.foreign_fraction)
    for i in range(cfg.n_clubs):
        foreign = i < n_foreign
        country = rng.choice(DIASPORA_COUNTRIES) if foreign else EGYPT
        name = foreign_names[i % len(foreign_names)] if foreign else club_names[i % len(club_names)]
        sport = enums.Sport.FOOTBALL.value
        orgs.append(
            Organization(
                id=rng.uuid(),
                name=name,
                type=enums.OrganizationType.CLUB.value,
                sport=sport,
                country=country,
                parent_org_id=parent_for(sport, country),
                external_ids={"source": "synthetic"},
            )
        )

    academy_names = rng.shuffled(ACADEMY_NAME_PARTS_AR)
    for i in range(cfg.n_academies):
        sport = (
            enums.Sport.TABLE_TENNIS.value
            if rng.chance(config.population.table_tennis_fraction)
            else enums.Sport.FOOTBALL.value
        )
        orgs.append(
            Organization(
                id=rng.uuid(),
                name=academy_names[i % len(academy_names)],
                type=enums.OrganizationType.ACADEMY.value,
                sport=sport,
                country=EGYPT,
                parent_org_id=parent_for(sport, EGYPT),
                external_ids={"source": "synthetic"},
            )
        )

    for i in range(cfg.n_national_teams):
        suffix = NATIONAL_TEAM_SUFFIXES[i % len(NATIONAL_TEAM_SUFFIXES)]
        sport = enums.Sport.FOOTBALL.value
        orgs.append(
            Organization(
                id=rng.uuid(),
                name=f"منتخب مصر {suffix}",
                type=enums.OrganizationType.NATIONAL_TEAM.value,
                sport=sport,
                country=EGYPT,
                parent_org_id=parent_for(sport, EGYPT),
                external_ids={},
            )
        )

    return orgs


def clubs_for(orgs: list[Organization], sport: str, *, egypt_only: bool | None = None):
    out = []
    for org in orgs:
        if org.type not in (
            enums.OrganizationType.CLUB.value,
            enums.OrganizationType.ACADEMY.value,
        ):
            continue
        if org.sport not in (sport, None):
            continue
        if egypt_only is True and org.country != EGYPT:
            continue
        if egypt_only is False and org.country == EGYPT:
            continue
        out.append(org)
    return out
