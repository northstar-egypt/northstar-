"""Player-organization affiliation history.

`docs/schema.md` wants "no two overlapping active affiliations of the same role
for one player at one org", and `PlayerOrganization` leaves that as a TODO
because it needs a btree_gist exclusion constraint. Until the constraint exists,
the generator is the only thing enforcing it, so it enforces it structurally: a
player's affiliations are built as a chronological chain where each spell starts
after the previous one ended. Overlap is not filtered out afterwards, it is never
constructed.

Diaspora players are affiliated abroad, youth players to academies and Egyptian
clubs. That is what makes the tier mean something downstream.
"""

from __future__ import annotations

from datetime import timedelta

from .config import GeneratorConfig
from .orm import Organization, PlayerOrganization, enums
from .organizations import clubs_for
from .players import MINOR_AGE, PlayerProfile
from .reference import EGYPT
from .rng import Rng


def _role_for(profile: PlayerProfile, age_at_start: float, rng: Rng) -> str:
    if age_at_start < 16:
        return (
            enums.PlayerOrganizationRole.TRIALIST.value
            if rng.chance(0.15)
            else enums.PlayerOrganizationRole.YOUTH_PROSPECT.value
        )
    if age_at_start < MINOR_AGE:
        return (
            enums.PlayerOrganizationRole.YOUTH_PROSPECT.value
            if rng.chance(0.6)
            else enums.PlayerOrganizationRole.PLAYER.value
        )
    return (
        enums.PlayerOrganizationRole.TRIALIST.value
        if rng.chance(0.08)
        else enums.PlayerOrganizationRole.PLAYER.value
    )


def generate_affiliations(
    rng: Rng,
    config: GeneratorConfig,
    profiles: list[PlayerProfile],
    orgs: list[Organization],
) -> tuple[list[PlayerOrganization], dict]:
    """Return the affiliation rows and a map of player id -> current org id."""
    reference = config.population.reference_date
    rows: list[PlayerOrganization] = []
    current: dict = {}

    for profile in profiles:
        abroad = bool(profile.notes.get("based_abroad"))
        pool = clubs_for(
            orgs, profile.player.primary_sport, egypt_only=(False if abroad else True)
        )
        if not pool:
            pool = clubs_for(orgs, profile.player.primary_sport)
        if not pool:
            continue

        age_now = profile.recorded_age(reference)
        # Careers start somewhere between age 9 and now, and nobody has more
        # spells than years of career.
        career_years = max(1.0, min(age_now - 9.0, 12.0))
        n_spells = min(rng.randint(1, 3), max(1, int(career_years // 2) + 1))

        # Walk forward from the career start, leaving a gap between spells so two
        # affiliations can never overlap.
        cursor = reference - timedelta(days=int(career_years * 365.2425))
        used_orgs: set = set()

        for spell in range(n_spells):
            candidates = [o for o in pool if o.id not in used_orgs] or pool
            org = rng.choice(candidates)
            used_orgs.add(org.id)

            start = cursor + timedelta(days=rng.randint(0, 120))
            if start >= reference:
                break

            is_last = spell == n_spells - 1
            if is_last and rng.chance(0.8):
                end = None  # still there
            else:
                span = rng.randint(210, 900)
                end = min(start + timedelta(days=span), reference - timedelta(days=1))
                if end <= start:
                    end = None

            age_at_start = profile.recorded_age(start)
            rows.append(
                PlayerOrganization(
                    id=rng.uuid(),
                    player_id=profile.id,
                    organization_id=org.id,
                    role=_role_for(profile, age_at_start, rng),
                    start_date=start,
                    end_date=end,
                    shirt_number=rng.randint(1, 45) if rng.chance(0.75) else None,
                )
            )

            if end is None:
                current[profile.id] = org.id
                break
            # The next spell starts strictly after this one ended.
            cursor = end + timedelta(days=rng.randint(1, 90))
            if cursor >= reference:
                break

        current.setdefault(profile.id, rows[-1].organization_id if rows else None)

    return rows, current


def find_overlaps(rows: list[PlayerOrganization]) -> list[tuple]:
    """Return any pair of same-player, same-org, same-role spells that overlap.

    Used by the tests. Kept here rather than in the test file because it is the
    executable statement of the constraint docs/schema.md describes in prose.
    """
    by_key: dict = {}
    for row in rows:
        by_key.setdefault((row.player_id, row.organization_id, row.role), []).append(row)

    overlaps = []
    for key, spells in by_key.items():
        spells = sorted(spells, key=lambda r: r.start_date)
        for a, b in zip(spells, spells[1:]):
            a_end = a.end_date
            if a_end is None or a_end >= b.start_date:
                overlaps.append((key, a, b))
    return overlaps
