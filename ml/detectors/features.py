"""Loading the dataset and turning it into per-player features.

Input is the JSON export written by `data.pipelines.synthetic.generate`, not the
database, so the harness runs with nothing but a Python interpreter and a
generated `out/` directory. The column names are the ORM attribute names by
construction (see `data/pipelines/synthetic/writer.py`), so anything here that
reads a field is reading the same name the API will.

Everything is plain dicts, lists and floats. The population is 212 players and a
few thousand measurements, which is small enough that pandas would cost more in
review effort than it saves in runtime, and keeping `ml/detectors` importable
with only the standard library means the harness never fails to run for an
environment reason on the day of a demo.

The reference date is derived from the data rather than imported from the
generator's config. The harness should stay runnable against any export,
including one produced at a different reference date or, later, a dump of real
rows from Postgres.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DAYS_PER_YEAR = 365.25

TABLES = (
    "players",
    "measurements",
    "performance_entries",
    "organizations",
    "affiliations",
)


@dataclass(frozen=True)
class OutputRates:
    """Which counts in a sport's performance rows measure how much a player produces.

    Counts are read per unit of playing time (`exposure`), so a substitute's 20 minutes and a
    full match are comparable. `higher` counts are better when they rise, `lower` ones when
    they fall. These are volume measures that a bigger, stronger, more experienced player
    racks up against a younger field: shots and chances created in football, service winners
    and few unforced errors in table tennis. Skill ratios (conversion, pass completion) and
    results (sets won) are left out on purpose. Ratios barely move with physical dominance,
    and a result depends on who the opponent was.

    TODO: this belongs in the sport module files (`packages/shared/sports`) next to `derived`,
    so a new sport brings its own. Until a second consumer needs it, it lives here.
    """

    exposure: tuple[str, ...]
    min_exposure: float
    higher: tuple[str, ...] = ()
    lower: tuple[str, ...] = ()


OUTPUT_RATES: dict[str, OutputRates] = {
    # Season rows carry shots but not key passes, so they add to the shot rate only.
    "football": OutputRates(
        exposure=("minutes_played",), min_exposure=450, higher=("shots", "key_passes")
    ),
    "table_tennis": OutputRates(
        exposure=("sets_won", "sets_lost"),
        min_exposure=20,
        higher=("service_winners",),
        lower=("unforced_errors",),
    ),
}


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _pooled_reference(
    buckets: dict[tuple, list[float]],
    *,
    min_spread: float,
    min_members: int = 5,
    window: int = 1,
) -> dict[tuple, tuple[float, float]]:
    """Median and spread per (sex, age) bucket, pooling neighbouring ages.

    Any key works as long as age is its last element, so (sport, sex, age) pools the
    same way.

    A bucket borrows from the years either side of it before deciding it has too
    few members to be a reference at all. Without this the population thins out at
    the top of the youth range, buckets at 18 and 19 fall below the minimum, and
    every player that age silently loses their z scores. That is not a small
    detail: on one calibration seed it removed three of the nine age-fraud cases
    from the candidate set entirely, capping recall at 0.67 before any threshold
    was applied.

    Pooling is a defensible smoothing rather than a workaround. Height and growth
    rate change gradually with age, so a 19-year-old compared against 18 to 20 is
    still being compared against the right thing.
    """
    reference: dict[tuple[str, int], tuple[float, float]] = {}
    for key in buckets:
        *group, age = key
        pooled: list[float] = []
        for offset in range(-window, window + 1):
            pooled.extend(buckets.get((*group, age + offset), ()))
        if len(pooled) < min_members:
            continue
        spread = statistics.pstdev(pooled)
        reference[key] = (
            statistics.median(pooled),
            spread if spread > min_spread else min_spread,
        )
    return reference


@dataclass
class PlayerFeatures:
    """Everything the detectors need about one player, computed once."""

    player_id: str
    player: dict

    # Height time series, ascending, as (date, cm).
    heights: list[tuple[date, float]] = field(default_factory=list)
    weights: list[tuple[date, float]] = field(default_factory=list)
    performance: list[dict] = field(default_factory=list)

    # Filled in by FeatureSet once the cohort reference exists.
    stated_age: float = 0.0
    height_z_last: float | None = None
    height_z_mean: float | None = None
    height_z_min: float | None = None
    growth_velocity: float = 0.0
    recent_velocity: float = 0.0
    velocity_z: float | None = None
    maturity_mismatch: float | None = None
    # How much a player produces for the time they play, against others in the same role, and
    # then against their stated-age cohort. See `OUTPUT_RATES` and `_fill_output`.
    output_index: float | None = None
    output_z: float | None = None

    @property
    def date_of_birth(self) -> date | None:
        return _as_date(self.player.get("date_of_birth"))

    @property
    def sex(self) -> str:
        return self.player.get("sex") or "unknown"

    @property
    def full_name(self) -> str:
        return self.player.get("full_name") or ""

    def age_at(self, when: date) -> float:
        dob = self.date_of_birth
        return (when - dob).days / DAYS_PER_YEAR if dob else 0.0


class FeatureSet:
    """The loaded dataset plus the derived per-player features."""

    def __init__(self, data_dir: str | Path, *, raw: dict[str, list[dict]] | None = None):
        """Load an export from `data_dir`, or build from tables already in memory.

        `raw` is how the backtest builds the features the system would have had on a past
        date: the same tables, cut off at that date, with nothing written to disk.
        """
        self.data_dir = Path(data_dir)
        if raw is None:
            raw = {}
            for name in TABLES:
                path = self.data_dir / f"{name}.json"
                raw[name] = (
                    json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
                )
        self.raw = {name: raw.get(name, []) for name in TABLES}

        self.players: dict[str, PlayerFeatures] = {
            p["id"]: PlayerFeatures(player_id=p["id"], player=p)
            for p in self.raw["players"]
        }

        for m in self.raw["measurements"]:
            pf = self.players.get(m["player_id"])
            if pf is None or m.get("value") is None:
                continue
            when = _as_date(m.get("measured_at"))
            if when is None:
                continue
            if m.get("metric") == "height_cm":
                pf.heights.append((when, float(m["value"])))
            elif m.get("metric") == "weight_kg":
                pf.weights.append((when, float(m["value"])))

        for e in self.raw["performance_entries"]:
            pf = self.players.get(e["player_id"])
            if pf is not None:
                pf.performance.append(e)

        for pf in self.players.values():
            pf.heights.sort()
            pf.weights.sort()

        self.reference_date = self._derive_reference_date()
        self.height_reference = self._build_height_reference()
        self._fill_derived()
        self.velocity_reference = self._build_velocity_reference()
        self._fill_maturity_mismatch()
        self._fill_output()

    # ------------------------------------------------------------------
    # Population reference
    # ------------------------------------------------------------------

    def _derive_reference_date(self) -> date:
        """Latest date anywhere in the dataset, treated as the present."""
        candidates = [when for pf in self.players.values() for when, _ in pf.heights]
        for e in self.raw["performance_entries"]:
            when = _as_date(e.get("period_start"))
            if when is not None:
                candidates.append(when)
        return max(candidates) if candidates else date.today()

    def _build_height_reference(self) -> dict[tuple[str, int], tuple[float, float]]:
        """Median and spread of height by (sex, whole year of stated age).

        Built from the dataset itself rather than from published growth charts.
        Two reasons. It keeps the harness self-contained, and more importantly the
        comparison a detector actually wants is against this population, which is
        what a scout comparing a player to their age group is doing.

        The planted cases sit inside this reference, which biases it slightly
        toward whatever they are. At roughly 7% prevalence, and using the median
        rather than the mean, the effect is small. More to the point it is the
        same problem any real deployment has, because there is no clean cohort to
        borrow.
        """
        buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
        for pf in self.players.values():
            for when, height in pf.heights:
                buckets[(pf.sex, round(pf.age_at(when)))].append(height)
        # A floor on the spread stops a thinly populated age bucket, where everyone
        # happens to be a similar height, from turning ordinary variation into a
        # huge z score.
        return _pooled_reference(buckets, min_spread=0.5)

    def height_z(self, pf: PlayerFeatures, when: date, height: float) -> float | None:
        """How far this height sits from the median for the player's stated age.

        Stated age, deliberately. Age fraud is a lie about the date of birth, so
        the whole signal is that the body does not match the age on the record.
        Using a true age here, which a real deployment would not have, would erase
        the thing being detected.
        """
        key = (pf.sex, round(pf.age_at(when)))
        entry = self.height_reference.get(key)
        if entry is None:
            return None
        median, spread = entry
        return (height - median) / spread

    def _fill_derived(self) -> None:
        for pf in self.players.values():
            pf.stated_age = pf.age_at(self.reference_date)
            zs = []
            for when, height in pf.heights:
                z = self.height_z(pf, when, height)
                if z is not None:
                    zs.append(z)
            if zs:
                pf.height_z_last = zs[-1]
                pf.height_z_mean = sum(zs) / len(zs)
                pf.height_z_min = min(zs)
            pf.growth_velocity = self._velocity(pf.heights)
            pf.recent_velocity = self._velocity(
                [(w, h) for w, h in pf.heights if (self.reference_date - w).days <= 400]
            )

    def _build_velocity_reference(self) -> dict[tuple[str, int], tuple[float, float]]:
        """Median and spread of recent growth velocity by (sex, whole year of stated age).

        The same construction as the height reference, over cm per year instead of
        cm. Growth velocity is strongly age dependent, peaking in mid adolescence
        and falling to nothing by the early twenties, so "fast" only means anything
        relative to a cohort.
        """
        buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
        for pf in self.players.values():
            if len(pf.heights) >= 3 and pf.recent_velocity:
                buckets[(pf.sex, round(pf.stated_age))].append(pf.recent_velocity)
        return _pooled_reference(buckets, min_spread=0.2)

    def _fill_maturity_mismatch(self) -> None:
        """Height and growth rate pulling in opposite directions.

        `maturity_mismatch = height_z - velocity_z`, both taken against the
        player's *stated* age. It is the single most useful number in this module
        and it reads in both directions:

          strongly positive   big for the stated age and no longer growing much.
                              A body that has finished a spurt the record says has
                              not started. This is what age misrepresentation looks
                              like from the outside.

          strongly negative   small for the stated age and still growing fast. A
                              spurt that arrived late and is still running, which
                              is the late bloomer.

          near zero           height and growth rate agree with each other and with
                              the record, which is almost everybody.

        Height alone cannot make this distinction. A tall 14-year-old and a
        17-year-old passing as 14 are the same height, and only one of them has
        stopped growing.

        Measured rather than assumed, the velocity term is a modest gain and not a
        breakthrough. Across the three calibration seeds it moved age-fraud F1
        from 0.574 to 0.596, and its real contribution was stability: the worst
        seed went from 0.40 to 0.53. It does nothing for the late-bloomer
        detector, where height and raw velocity already carry the signal, which is
        why that detector does not use it.
        """
        for pf in self.players.values():
            key = (pf.sex, round(pf.stated_age))
            entry = self.velocity_reference.get(key)
            if entry is None or not pf.recent_velocity or len(pf.heights) < 3:
                continue
            median, spread = entry
            pf.velocity_z = (pf.recent_velocity - median) / spread
            if pf.height_z_mean is not None:
                pf.maturity_mismatch = pf.height_z_mean - pf.velocity_z

    def _fill_output(self) -> None:
        """How much each player produces for the time they play, against their stated age.

        Two steps. First, against the role: a striker shoots more than a centre back for
        reasons that have nothing to do with age, so each count is divided by what the
        median player in the same sport and position produces in the same playing time. The
        log of that ratio, averaged over the sport's counts (with `lower` ones negated), is
        `output_index`: 0 is a typical player for the role, +0.3 is about a third more.

        Second, against the stated-age cohort, the same pooled (sport, gender, age)
        construction as height, giving `output_z`. A 17-year-old passing as 14 plays
        against 14-year-olds and dominates them; this is the number that says so.

        Rows that their sport module says cannot be true are skipped: an impossible row says
        nothing about output, and those are caught by the arithmetic rule anyway.
        """
        from ml import sport_modules  # needs apps/api on the path; only this method uses it

        # (sport, metric) -> counts and exposure per player
        totals: dict[str, dict[str, list[float]]] = {}
        for pf in self.players.values():
            per_metric: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
            for e in pf.performance:
                rates = OUTPUT_RATES.get(e.get("sport") or pf.player.get("primary_sport"))
                metrics = e.get("metrics")
                if rates is None or not isinstance(metrics, dict):
                    continue
                if sport_modules.impossibilities(metrics, e.get("schema_ref", "")):
                    continue
                exposure = [_number(metrics.get(k)) for k in rates.exposure]
                if any(x is None for x in exposure) or sum(exposure) <= 0:
                    continue
                for metric in rates.higher + rates.lower:
                    count = _number(metrics.get(metric))
                    if count is None:
                        continue
                    per_metric[metric][0] += count
                    per_metric[metric][1] += sum(exposure)
            totals[pf.player_id] = dict(per_metric)

        # Median rate per (sport, position, metric), falling back to the whole sport when a
        # position has too few players to be a reference.
        role_rates: dict[tuple, list[float]] = defaultdict(list)
        for pf in self.players.values():
            sport = pf.player.get("primary_sport")
            rates = OUTPUT_RATES.get(sport)
            if rates is None:
                continue
            for metric, (count, exposure) in totals[pf.player_id].items():
                if exposure >= rates.min_exposure:
                    rate = count / exposure
                    role_rates[(sport, pf.player.get("position"), metric)].append(rate)
                    role_rates[(sport, None, metric)].append(rate)
        role_median = {k: statistics.median(v) for k, v in role_rates.items() if len(v) >= 5}

        for pf in self.players.values():
            sport = pf.player.get("primary_sport")
            rates = OUTPUT_RATES.get(sport)
            if rates is None:
                continue
            logs = []
            for metric, (count, exposure) in totals[pf.player_id].items():
                if exposure < rates.min_exposure:
                    continue
                median = role_median.get((sport, pf.player.get("position"), metric))
                if median is None:
                    median = role_median.get((sport, None, metric))
                if median is None:
                    continue
                # +0.5 on both sides keeps a zero count finite without moving a real one much.
                ratio = math.log((count + 0.5) / (median * exposure + 0.5))
                logs.append(-ratio if metric in rates.lower else ratio)
            if logs:
                pf.output_index = sum(logs) / len(logs)

        buckets: dict[tuple, list[float]] = defaultdict(list)
        for pf in self.players.values():
            if pf.output_index is not None:
                buckets[self._output_key(pf)].append(pf.output_index)
        self.output_reference = _pooled_reference(buckets, min_spread=0.05)
        for pf in self.players.values():
            entry = self.output_reference.get(self._output_key(pf))
            if pf.output_index is None or entry is None:
                continue
            median, spread = entry
            pf.output_z = (pf.output_index - median) / spread

    @staticmethod
    def _output_key(pf: PlayerFeatures) -> tuple:
        return (pf.player.get("primary_sport"), pf.sex, round(pf.stated_age))

    @staticmethod
    def _velocity(series: list[tuple[date, float]]) -> float:
        """Centimetres per year across the span.

        Returns 0.0 when the span is too short for the number to mean anything,
        rather than dividing by a few days and reporting a growth rate of 200cm a
        year.
        """
        if len(series) < 2:
            return 0.0
        span_days = (series[-1][0] - series[0][0]).days
        if span_days < 60:
            return 0.0
        return (series[-1][1] - series[0][1]) / (span_days / DAYS_PER_YEAR)

    # ------------------------------------------------------------------

    @property
    def population(self) -> set[str]:
        return set(self.players)

    def __len__(self) -> int:
        return len(self.players)
