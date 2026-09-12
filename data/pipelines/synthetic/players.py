"""Player identity and demographics.

Three of the review points are really one point: the player's age must be the
thing the rest of the row is derived from. Tier, minor status, consent, growth
curves and performance rates all hang off it. The previous pass sampled them
independently, which is how four youth-tier players ended up being adults and one
of them 32.

`PlayerProfile` pairs the ORM `Player` with the generation parameters that
produced it. Those parameters are not columns: they are the hidden state the
measurement and performance generators need in order to stay consistent with the
identity, and the state the ground-truth writer needs in order to describe a
planted case honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import growth
from .config import GeneratorConfig
from .orm import Player, enums
from .reference import DIASPORA_COUNTRIES, EGYPT, FOOTBALL_POSITIONS, TABLE_TENNIS_STYLES
from .rng import Rng

MINOR_AGE = 18


@dataclass
class PlayerProfile:
    """A player plus the hidden parameters that generated them."""

    player: Player

    # Age the body was generated from. Equal to the age implied by
    # `player.date_of_birth` for everyone except planted age-fraud cases, where
    # the recorded date of birth is younger than the true one.
    true_date_of_birth: date

    sex: str
    adult_height_cm: float
    build_offset: float
    talent_offset: float

    # Positive for a late maturer. Shifts the whole growth curve later; see
    # growth.height_fraction.
    maturity_offset_years: float = 0.0

    # Per-90 performance rates, drawn once so a player's match returns are
    # recognisably theirs across the season rather than resampled every row.
    ability: float = 1.0

    position: str | None = None
    is_planted_late_bloomer: bool = False
    is_planted_age_fraud: bool = False
    is_planted_metric_fraud: bool = False
    duplicate_cluster_id: str | None = None
    notes: dict = field(default_factory=dict)

    @property
    def id(self):
        return self.player.id

    def recorded_age(self, on: date) -> float:
        return growth.age_in_years(self.player.date_of_birth, on)

    def true_age(self, on: date) -> float:
        return growth.age_in_years(self.true_date_of_birth, on)

    def effective_ability(self, on: date) -> float:
        """Ability as it shows up in results, given who the player competes against.

        Youth football is played in age groups, so a player's returns depend not
        only on how good they are but on how developed they are relative to the
        age group they were entered in. For everyone honest, true age and
        recorded age are the same and this is exactly `ability`.

        For a planted age-fraud case the recorded age is younger, so the player
        is competing below their development level and their numbers rise. That
        makes "performance outlier for stated age" a property the data actually
        has, rather than a label asserting a signal nobody planted. The exponent
        turns the small ratio between two points on the maturity curve into the
        kind of dominance that is visible in a season's returns.
        """
        recorded = max(self.recorded_age(on), 6.0)
        true = max(self.true_age(on), 6.0)
        ratio = growth.height_fraction(true, self.sex) / growth.height_fraction(
            recorded, self.sex
        )
        return self.ability * (ratio**8)


def _draw_date_of_birth(rng: Rng, reference: date, min_age: int, max_age: int) -> date:
    days = rng.randint(int(min_age * 365.2425), int(max_age * 365.2425))
    return reference - timedelta(days=days)


def _pick_position(rng: Rng, sport: str) -> str:
    if sport == enums.Sport.TABLE_TENNIS.value:
        return rng.choice(TABLE_TENNIS_STYLES)
    names = [p for p, _ in FOOTBALL_POSITIONS]
    weights = [w for _, w in FOOTBALL_POSITIONS]
    return rng.choices(names, weights=weights, k=1)[0]


def derive_tier(age: float, based_abroad: bool) -> str:
    """Tier is a pathway, and the pathway is a function of age and where they play.

    - under 18 and playing in Egypt -> youth, the deep implementation
    - playing abroad and Egypt-eligible -> diaspora, at any age
    - 18 or over and playing in Egypt -> pro

    Deriving it means a youth-tier player can never be 32.
    """
    if based_abroad:
        return enums.FootballTier.DIASPORA.value
    if age < MINOR_AGE:
        return enums.FootballTier.YOUTH.value
    return enums.FootballTier.PRO.value


def generate_players(rng: Rng, config: GeneratorConfig) -> list[PlayerProfile]:
    pop = config.population
    reference = pop.reference_date

    n_minors = round(pop.n_players * pop.minor_fraction)
    n_adults = pop.n_players - n_minors
    n_diaspora = round(n_adults * pop.diaspora_fraction_of_adults)
    # Minors abroad exist too, and they are a real part of the diaspora pipeline.
    n_diaspora_minors = max(1, round(n_minors * 0.10))

    profiles: list[PlayerProfile] = []

    plan: list[tuple[bool, bool]] = []  # (is_minor, based_abroad)
    plan += [(True, True)] * n_diaspora_minors
    plan += [(True, False)] * (n_minors - n_diaspora_minors)
    plan += [(False, True)] * n_diaspora
    plan += [(False, False)] * (n_adults - n_diaspora)
    plan = rng.shuffled(plan)

    for is_minor_target, based_abroad in plan:
        if is_minor_target:
            dob = _draw_date_of_birth(rng, reference, pop.min_age, MINOR_AGE - 1)
        else:
            dob = _draw_date_of_birth(rng, reference, MINOR_AGE, pop.max_age)

        age = growth.age_in_years(dob, reference)
        sex = "female" if rng.chance(pop.female_fraction) else "male"
        sport = (
            enums.Sport.TABLE_TENNIS.value
            if rng.chance(pop.table_tennis_fraction)
            else enums.Sport.FOOTBALL.value
        )

        if based_abroad:
            # An eligible diaspora player is a dual national. A non-eligible one
            # is on the watchlist but has not committed, which is exactly the
            # distinction is_egypt_eligible exists to record. Hardcoding it True
            # collapsed the two.
            eligible = rng.chance(0.75)
            host = rng.choice(DIASPORA_COUNTRIES)
            nationality = [EGYPT, host] if eligible else [host]
        else:
            eligible = True
            nationality = [EGYPT]

        full_name = rng.faker.eg_full_name(sex)

        external_ids = {}
        if rng.chance(0.55):
            external_ids["footystats"] = f"FS{rng.randint(100000, 999999)}"
        if rng.chance(0.3):
            external_ids["federation_ref"] = f"EFA-{rng.randint(10000, 99999)}"

        player = Player(
            id=rng.uuid(),
            full_name=full_name,
            known_as=full_name.split()[0] if rng.chance(0.35) else None,
            date_of_birth=dob,
            sex=sex,
            nationality=nationality,
            is_egypt_eligible=eligible,
            primary_sport=sport,
            tier=derive_tier(age, based_abroad),
            position=_pick_position(rng, sport),
            is_minor=age < MINOR_AGE,
            external_ids=external_ids,
            status=enums.PlayerStatus.ACTIVE.value,
            merged_into=None,
        )

        profiles.append(
            PlayerProfile(
                player=player,
                true_date_of_birth=dob,
                sex=sex,
                adult_height_cm=growth.draw_adult_height(rng, sex),
                build_offset=rng.gauss(0.0, 1.15),
                talent_offset=rng.gauss(0.0, 0.055),
                ability=max(0.25, rng.gauss(1.0, 0.28)),
                position=player.position,
                notes={"based_abroad": based_abroad},
            )
        )

    return profiles
