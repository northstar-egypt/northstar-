"""Tunable knobs for the synthetic generator.

Everything that decides "how much" or "how likely" lives here rather than being
scattered as literals through the generators, so a reviewer can see the shape of
the dataset in one screen and the ML track can regenerate a bigger or smaller one
without editing generator code.

The defaults are chosen to make the dataset useful as an *evaluation set*, not
just as filler: the population is weighted toward minors (that is the tier we
implement deepest, and it is the only tier that exercises guardian consent), and
a known number of late bloomers, age-fraud cases and duplicate identities are
planted so the detectors have something to be scored against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# The committed default. Any run with the same seed produces byte-identical
# output, which is what makes it safe to gitignore the data itself.
DEFAULT_SEED = 20260827

# docs/schema.md stores nationality as ISO country codes. The repo is currently
# inconsistent: the API/pipeline side uses alpha-2, apps/web uses alpha-3. There
# is a board item to settle it. Keeping the choice in one named constant means
# the flip is a one-line change here rather than a hunt through the generators.
COUNTRY_CODE_STANDARD = "alpha-2"


@dataclass(frozen=True)
class PopulationConfig:
    """How many rows, and who they are."""

    n_players: int = 200

    # Fraction of the population under 18 on the reference date. The youth tier
    # is the deep implementation and guardian consent only fires for minors, so
    # a minor-heavy population exercises far more of the system than a realistic
    # age pyramid would.
    minor_fraction: float = 0.62

    # Of the adults, the share that sit in the diaspora tier (playing abroad,
    # Egypt-eligible through nationality rather than residence).
    diaspora_fraction_of_adults: float = 0.22

    # Age bounds, in years, on the reference date.
    min_age: int = 9
    max_age: int = 34

    female_fraction: float = 0.34

    table_tennis_fraction: float = 0.18

    # Everything is generated relative to this date so runs are reproducible
    # regardless of when they happen.
    reference_date: date = date(2026, 6, 30)


@dataclass(frozen=True)
class OrganizationConfig:
    n_clubs: int = 14
    n_academies: int = 10
    n_national_teams: int = 4
    # Federations sit at the top of the org hierarchy and parent the rest.
    n_federations: int = 2
    # Share of orgs based outside Egypt, so diaspora players have somewhere to be.
    foreign_fraction: float = 0.25


@dataclass(frozen=True)
class MeasurementConfig:
    """Biometric time-series shape."""

    # Length of each player's measurement history, in months.
    min_history_months: int = 14
    max_history_months: int = 40

    # Gap between consecutive measurement dates, in days. Deliberately irregular:
    # the growth model is a function of age at the measurement date, so an
    # eight-month gap produces roughly eight months of growth and a three-week
    # gap produces roughly three weeks of it.
    min_gap_days: int = 21
    max_gap_days: int = 150

    # Measurement noise (cm / kg / seconds), applied on top of the curve.
    height_noise_cm: float = 0.55
    weight_noise_kg: float = 1.1
    sprint_noise_s: float = 0.045

    # Share of measurements that are self-reported rather than coach-logged.
    self_submitted_fraction: float = 0.16
    estimated_confidence_fraction: float = 0.12


@dataclass(frozen=True)
class PerformanceConfig:
    min_entries: int = 8
    max_entries: int = 34

    # Share of appearances where the player was an unused substitute: zero
    # minutes, and therefore zero of everything else.
    unused_sub_fraction: float = 0.09
    substitute_fraction: float = 0.24

    season_aggregate_fraction: float = 0.08


@dataclass(frozen=True)
class PlantedConfig:
    """The known cases the three detectors are scored against.

    These are the point of the dataset. Precision, recall and F1 cannot be
    computed without a set of cases whose labels we already know, and there is
    no way to recover those labels after the fact from data that was generated
    without them.
    """

    # Players whose growth spurt arrives late: below their cohort at 13-15, then
    # a steep catch-up. The forecasting models should struggle with these, which
    # is exactly what makes them worth labelling.
    n_late_bloomers: int = 14

    # Age misrepresentation: the player's body and performance come from their
    # true age, but the recorded date_of_birth is younger. This is generated
    # causally rather than by nudging numbers, so the signals a detector would
    # look for (biometric outlier for stated age, performance dominance over the
    # stated age group) appear on their own.
    n_age_fraud: int = 9
    fraud_age_inflation_years: tuple[float, float] = (1.4, 3.2)

    # A handful of deliberately impossible performance rows, attributed to a
    # small number of players, as a second and much cruder fraud signal.
    n_metric_fraud_players: int = 5

    # The same human entered twice. Half are left unresolved (both rows active)
    # for the detector to find; the rest are already merged, so the merged/
    # merged_into path is exercised and the detector has resolved examples to
    # learn the shape of a true match from.
    n_duplicate_clusters: int = 12
    resolved_duplicate_fraction: float = 0.35


@dataclass(frozen=True)
class AccountConfig:
    n_coaches: int = 18
    n_scouts: int = 8
    n_federation_staff: int = 4
    n_admins: int = 2
    # Share of adult players who also hold a player-role login.
    player_account_fraction: float = 0.18
    n_audit_events: int = 320


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = DEFAULT_SEED
    # Faker locale for names. The population is Egyptian; the previous pass used
    # the default en_US locale and produced Egyptian players called Todd Smith.
    name_locale: str = "ar_EG"

    population: PopulationConfig = field(default_factory=PopulationConfig)
    organizations: OrganizationConfig = field(default_factory=OrganizationConfig)
    measurements: MeasurementConfig = field(default_factory=MeasurementConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    planted: PlantedConfig = field(default_factory=PlantedConfig)
    accounts: AccountConfig = field(default_factory=AccountConfig)

    def scaled(self, n_players: int) -> GeneratorConfig:
        """Return a copy sized for a different population.

        Planted-case counts scale with the population so the positive rate the
        detectors see stays roughly constant. A 20-player smoke-test dataset with
        14 late bloomers would be useless for measuring precision.
        """
        ratio = n_players / self.population.n_players
        scale = lambda n: max(1, round(n * ratio))  # noqa: E731
        return GeneratorConfig(
            seed=self.seed,
            name_locale=self.name_locale,
            population=PopulationConfig(
                n_players=n_players,
                minor_fraction=self.population.minor_fraction,
                diaspora_fraction_of_adults=self.population.diaspora_fraction_of_adults,
                min_age=self.population.min_age,
                max_age=self.population.max_age,
                female_fraction=self.population.female_fraction,
                table_tennis_fraction=self.population.table_tennis_fraction,
                reference_date=self.population.reference_date,
            ),
            organizations=self.organizations,
            measurements=self.measurements,
            performance=self.performance,
            planted=PlantedConfig(
                n_late_bloomers=scale(self.planted.n_late_bloomers),
                n_age_fraud=scale(self.planted.n_age_fraud),
                fraud_age_inflation_years=self.planted.fraud_age_inflation_years,
                n_metric_fraud_players=scale(self.planted.n_metric_fraud_players),
                n_duplicate_clusters=scale(self.planted.n_duplicate_clusters),
                resolved_duplicate_fraction=self.planted.resolved_duplicate_fraction,
            ),
            accounts=self.accounts,
        )
