"""Walk-forward evaluation of the height forecasters.

The graded target is "walk-forward validation, MAE / RMSE against last-value and
population-average baselines". Walk-forward here means:

  1. Pick an origin date. Everything measured on or before it, for every player, is the
     training data. Everything after it is hidden.
  2. Learn the population curves from the training data only, and forecast every player's
     hidden readings up to a year ahead.
  3. Move the origin forward a quarter and repeat, until the origins run out of future.

The origin is a calendar date shared by all players, not a per-player cut. A per-player cut
would let the population curves learn from other players' readings that are later in time
than the reading being forecast, which is a leak a real deployment on a real date could
never have.

What is reported
----------------
The headline is players **under 18 at the origin**. An adult's height does not change, so
last value is close to perfect for them and adding adults to the pool would make every
forecaster look good for a reason that has nothing to do with forecasting. The all-players
figure is printed too, labelled.

Below the headline: by horizon, by sex, and two groups taken from the answer key that are
never shown to a forecaster. Late bloomers, because they break the assumption the centile
model rests on, and age-fraud cases, because their stated age is wrong and every model here
uses stated age.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ml.evaluation import fairness
from ml.evaluation.metrics import ErrorScore, error_score
from ml.forecasting.models import FORECASTERS, PlayerHistory, Snapshot, age_at

# How far ahead a forecast is scored. The profile screen shows a year ahead, and beyond
# that this dataset has too few origins with a full year of future to say anything.
MAX_HORIZON_DAYS = 365
ORIGIN_STEP_DAYS = 91
# The first origin needs enough history behind it for the population curves to exist.
MIN_TRAINING_DAYS = 365
# A player needs this many readings before the origin to be forecast at all.
MIN_READINGS = 2

HORIZON_BANDS = (
    ("0 to 3 months", 0, 91),
    ("3 to 6 months", 92, 182),
    ("6 to 12 months", 183, MAX_HORIZON_DAYS),
)

HEADLINE = "under 18 at origin"

# The model the uncertainty band is built around, and the band's nominal coverage.
INTERVAL_MODEL = "cohort velocity"
INTERVAL_COVERAGE = 0.80
# Fewer past errors than this in a horizon band and no band is given, rather than a band
# drawn from a handful of cases.
MIN_INTERVAL_HISTORY = 30


def _as_date(value) -> date:
    return date.fromisoformat(str(value)[:10])


@dataclass
class Case:
    player_id: str
    origin: date
    target: date
    actual: float
    stated_age: float
    sex: str
    predictions: dict[str, float | None]
    # INTERVAL_MODEL's band, or None when there was not yet enough history to draw one.
    interval: tuple[float, float] | None = None

    @property
    def horizon_days(self) -> int:
        return (self.target - self.origin).days


@dataclass
class ForecastReport:
    data_dir: str
    seed: int
    origins: list[date]
    players_forecast: int
    cases: int
    # The forecasters scored, in order: the core four plus any challengers.
    forecasters: list[str] = field(default_factory=list)
    # Group name, then one score per forecaster, in `forecasters` order.
    groups: dict[str, list[ErrorScore]] = field(default_factory=dict)
    # Of the headline forecasts that got a band: how many landed inside it, and the mean width.
    interval_cases: int = 0
    interval_hits: int = 0
    interval_width: float = 0.0
    interval_missing: int = 0
    # The band learned per gender, the way the profile learns it: model -> gender ->
    # [inside, banded, summed width]. For INTERVAL_MODEL and any challenger scored.
    gender_bands: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "data_dir": self.data_dir,
            "seed": self.seed,
            "origins": [o.isoformat() for o in self.origins],
            "players_forecast": self.players_forecast,
            "cases": self.cases,
            "forecasters": self.forecasters,
            "groups": {k: [s.as_dict() for s in v] for k, v in self.groups.items()},
            "interval": {
                "model": INTERVAL_MODEL,
                "nominal_coverage": INTERVAL_COVERAGE,
                "cases": self.interval_cases,
                "observed_coverage": round(self.interval_hits / self.interval_cases, 4)
                if self.interval_cases
                else None,
                "mean_width_cm": round(self.interval_width, 4),
                "without_interval": self.interval_missing,
            },
            "interval_per_gender": {
                model: {
                    sex: {
                        "cases": int(n),
                        "observed_coverage": round(hits / n, 4),
                        "mean_width_cm": round(width / n, 4),
                    }
                    for sex, (hits, n, width) in by_sex.items()
                }
                for model, by_sex in self.gender_bands.items()
            },
            "notes": self.notes,
        }


def load(data_dir: str | Path) -> tuple[dict[str, PlayerHistory], dict]:
    """Height histories from a generated export, and the answer key for grouping only."""
    data_dir = Path(data_dir)
    players = json.loads((data_dir / "players.json").read_text(encoding="utf-8"))
    measurements = json.loads((data_dir / "measurements.json").read_text(encoding="utf-8"))
    truth_path = data_dir / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else {}

    histories = {
        p["id"]: PlayerHistory(
            player_id=p["id"],
            sex=p.get("sex") or "unknown",
            dob=_as_date(p["date_of_birth"]),
            heights=[],
        )
        for p in players
        if p.get("date_of_birth") and p.get("status") != "merged"
    }
    for m in measurements:
        history = histories.get(m["player_id"])
        if history is None or m.get("metric") != "height_cm" or m.get("value") is None:
            continue
        history.heights.append((_as_date(m["measured_at"]), float(m["value"])))
    for history in histories.values():
        history.heights.sort()
    return histories, truth


def origins_for(histories: dict[str, PlayerHistory]) -> list[date]:
    dates = [when for h in histories.values() for when, _ in h.heights]
    if not dates:
        return []
    first, last = min(dates), max(dates)
    origins = []
    cursor = first + timedelta(days=MIN_TRAINING_DAYS)
    # The last origin still has at least one quarter of future to be scored against.
    while cursor <= last - timedelta(days=ORIGIN_STEP_DAYS):
        origins.append(cursor)
        cursor += timedelta(days=ORIGIN_STEP_DAYS)
    return origins


def horizon_band(days: int) -> str:
    for label, low, high in HORIZON_BANDS:
        if low <= days <= high:
            return label
    return HORIZON_BANDS[-1][0]


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def _interval_errors(cases: list[Case], origin: date) -> dict[str, list[float]]:
    """Errors of earlier forecasts whose outcome had been measured by `origin`, per band.

    This is what makes the band walk-forward too. On the origin date, a forecast made a year
    earlier for a reading taken last month has a known error; a forecast for a reading taken
    next month does not, and using it would be calibrating on the future.
    """
    errors: dict[str, list[float]] = {}
    for case in cases:
        predicted = case.predictions.get(INTERVAL_MODEL)
        if case.target <= origin and case.stated_age < 18 and predicted is not None:
            errors.setdefault(horizon_band(case.horizon_days), []).append(case.actual - predicted)
    return errors


def band_coverage(cases: list[Case], predicted, key) -> dict[tuple, list[float]]:
    """How often an 80% band around any model's forecasts held, checked walk-forward.

    `predicted(case)` is the model's forecast (None to skip the case) and `key(case)` the
    group a band is learned for, for example (gender, horizon band). At each origin a case's
    band comes only from the errors of earlier forecasts in the same group whose outcome had
    been measured by then, as in `_interval_errors`. Returns key -> [readings inside the band,
    forecasts that had a band, summed band width in cm].

    The player profile checks its band with this (apps/api/app/services/forecast.py), and the
    evaluation reports it per gender, so the coverage the profile states and the one in
    ml/README.md are the same computation.
    """
    tail = (1 - INTERVAL_COVERAGE) / 2
    tallies: dict[tuple, list[float]] = {}
    for origin in sorted({case.origin for case in cases}):
        past: dict[tuple, list[float]] = {}
        for case in cases:
            value = predicted(case)
            if case.target <= origin and value is not None:
                past.setdefault(key(case), []).append(case.actual - value)
        for case in cases:
            value = predicted(case)
            errors = past.get(key(case), [])
            if case.origin != origin or value is None or len(errors) < MIN_INTERVAL_HISTORY:
                continue
            low, high = value + quantile(errors, tail), value + quantile(errors, 1 - tail)
            tally = tallies.setdefault(key(case), [0, 0, 0.0])
            tally[0] += low <= case.actual <= high
            tally[1] += 1
            tally[2] += high - low
    return tallies


def build_cases(
    histories: dict[str, PlayerHistory], forecasters: dict | None = None
) -> tuple[list[date], list[Case]]:
    """Every forecast case, walk-forward. `forecasters` defaults to the core four; the
    evaluation adds the challengers (ml/challengers), the API never does."""
    forecasters = forecasters or FORECASTERS
    origins = origins_for(histories)
    cases: list[Case] = []
    tail = (1 - INTERVAL_COVERAGE) / 2
    for origin in origins:
        past_errors = _interval_errors(cases, origin)
        visible = {
            pid: PlayerHistory(h.player_id, h.sex, h.dob, [r for r in h.heights if r[0] <= origin])
            for pid, h in histories.items()
        }
        snapshot = Snapshot(origin, visible)
        horizon_end = origin + timedelta(days=MAX_HORIZON_DAYS)
        for pid, seen in visible.items():
            if len(seen.heights) < MIN_READINGS:
                continue
            for target, actual in histories[pid].heights:
                if not origin < target <= horizon_end:
                    continue
                predictions = {
                    name: forecast(snapshot, seen, target)
                    for name, forecast in forecasters.items()
                }
                errors = past_errors.get(horizon_band((target - origin).days), [])
                centre = predictions[INTERVAL_MODEL]
                interval = (
                    (centre + quantile(errors, tail), centre + quantile(errors, 1 - tail))
                    if centre is not None and len(errors) >= MIN_INTERVAL_HISTORY
                    else None
                )
                cases.append(
                    Case(
                        player_id=pid,
                        origin=origin,
                        target=target,
                        actual=actual,
                        stated_age=age_at(seen.dob, origin),
                        sex=seen.sex,
                        predictions=predictions,
                        interval=interval,
                    )
                )
    return origins, cases


def _score_group(
    cases: list[Case], note: str = "", names: list[str] | None = None
) -> list[ErrorScore]:
    return [
        error_score(
            name,
            [(c.player_id, c.predictions[name], c.actual) for c in cases],
            note=note,
        )
        for name in (names or list(FORECASTERS))
    ]


def evaluate(data_dir: str | Path, forecasters: dict | None = None) -> ForecastReport:
    forecasters = forecasters or FORECASTERS
    histories, truth = load(data_dir)
    origins, cases = build_cases(histories, forecasters)
    names = list(forecasters)

    def _score_group_n(group: list[Case], note: str = "") -> list[ErrorScore]:
        return _score_group(group, note, names)

    report = ForecastReport(
        data_dir=str(data_dir),
        seed=truth.get("seed", -1),
        origins=origins,
        players_forecast=len({c.player_id for c in cases}),
        cases=len(cases),
        forecasters=names,
    )
    if not cases:
        report.notes.append("No forecast cases. The dataset spans too little time.")
        return report

    growing = [c for c in cases if c.stated_age < 18]
    report.groups[HEADLINE] = _score_group_n(growing)
    banded = [c for c in growing if c.interval is not None]
    report.interval_cases = len(banded)
    report.interval_missing = len(growing) - len(banded)
    report.interval_hits = sum(1 for c in banded if c.interval[0] <= c.actual <= c.interval[1])
    report.interval_width = (
        sum(c.interval[1] - c.interval[0] for c in banded) / len(banded) if banded else 0.0
    )
    for name in [INTERVAL_MODEL] + [n for n in names if n not in FORECASTERS]:
        tallies = band_coverage(
            growing,
            lambda case, name=name: case.predictions.get(name),
            lambda case: (case.sex, horizon_band(case.horizon_days)),
        )
        by_sex: dict[str, list[float]] = {}
        for (sex, _), (hits, n, width) in tallies.items():
            total = by_sex.setdefault(sex, [0, 0, 0.0])
            total[0] += hits
            total[1] += n
            total[2] += width
        report.gender_bands[name] = by_sex
    for label, low, high in HORIZON_BANDS:
        report.groups[f"  {label} ahead"] = _score_group_n(
            [c for c in growing if low <= c.horizon_days <= high]
        )
    for sex in ("female", "male"):
        report.groups[f"  {sex}"] = _score_group_n([c for c in growing if c.sex == sex])
    # The relative age audit (ml/evaluation/fairness.py): is a child born late in the
    # selection year forecast worse than one born early? Stated date of birth, as everywhere.
    for quarter in fairness.QUARTERS:
        report.groups[f"  born {fairness.QUARTER_LABELS[quarter]}"] = _score_group_n(
            [c for c in growing if fairness.birth_quarter(histories[c.player_id].dob) == quarter]
        )

    cases_by_kind = truth.get("cases", {})
    late = {c["player_id"] for c in cases_by_kind.get("late_bloomers", [])}
    fraud = {
        c["player_id"]
        for c in cases_by_kind.get("fraud", [])
        if c.get("fraud_type") == "age_misrepresentation"
    }
    if late:
        report.groups["  planted late bloomers"] = _score_group_n(
            [c for c in growing if c.player_id in late],
            note="from the answer key, never shown to a forecaster",
        )
    if fraud:
        report.groups["  planted age fraud"] = _score_group_n(
            [c for c in growing if c.player_id in fraud],
            note="stated age is wrong, and every model uses stated age",
        )
    report.groups["18 and over at origin"] = _score_group_n(
        [c for c in cases if c.stated_age >= 18],
        note="adults stop growing, so last value is close to perfect here",
    )
    report.groups["all players"] = _score_group_n(cases)
    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_WIDTH = 104


def render(report: ForecastReport) -> str:
    out = ["=" * _WIDTH]
    out.append(
        f"Height forecast evaluation, seed {report.seed}: walk-forward over "
        f"{len(report.origins)} origins, {report.players_forecast} players, "
        f"{report.cases} forecasts"
    )
    out.append(f"dataset: {report.data_dir}")
    if report.origins:
        out.append(
            f"origins: {report.origins[0]} to {report.origins[-1]}, every "
            f"{ORIGIN_STEP_DAYS} days; horizon up to {MAX_HORIZON_DAYS} days; "
            f"errors in cm"
        )
    out.append("=" * _WIDTH)

    for group, scores in report.groups.items():
        n = scores[0].n + scores[0].missing if scores else 0
        out.append("")
        out.append(f"{group}  ({n} forecasts)")
        out.append("-" * _WIDTH)
        out.append(
            f"{'':34} {'MAE':>7} {'RMSE':>7} {'bias':>7}  {'MAE 95% CI':>16} "
            f"{'vs last value':>14} {'missing':>8}"
        )
        reference = scores[0].mae if scores else 0.0
        for s in scores:
            lo, hi = s.mae_ci
            change = (
                f"{(s.mae - reference) / reference:+.0%}" if reference and s is not scores[0] else ""
            )
            out.append(
                f"{s.forecaster:34} {s.mae:>7.2f} {s.rmse:>7.2f} {s.bias:>+7.2f}  "
                f"{f'{lo:.2f} to {hi:.2f}':>16} {change:>14} {s.missing:>8}"
            )
        if scores and scores[0].note:
            out.append(f"{'':34} {scores[0].note}")

    if report.interval_cases:
        out.append("")
        out.append(f"Uncertainty band: {INTERVAL_MODEL}, {HEADLINE}")
        out.append("-" * _WIDTH)
        out.append(
            f"nominal {INTERVAL_COVERAGE:.0%}, observed "
            f"{report.interval_hits / report.interval_cases:.1%} "
            f"({report.interval_hits} of {report.interval_cases} readings inside), "
            f"mean width {report.interval_width:.2f} cm. "
            f"{report.interval_missing} forecasts from the earliest origins had too little "
            f"history for a band and got none."
        )

    if report.gender_bands:
        out.append("")
        out.append(
            f"Uncertainty band learned per gender, as the player profile learns it, {HEADLINE}"
        )
        out.append("-" * _WIDTH)
        for model, by_sex in report.gender_bands.items():
            for sex, (hits, n, width) in sorted(by_sex.items()):
                out.append(
                    f"{model:34} {sex:7} nominal {INTERVAL_COVERAGE:.0%}, observed "
                    f"{hits / n:.1%} ({int(hits)} of {int(n)}), mean width {width / n:.2f} cm"
                )

    for note in report.notes:
        out.append(f"NOTE: {note}")
    return "\n".join(out)


def render_sweep(reports: list[ForecastReport]) -> str:
    out = ["", "=" * _WIDTH, f"Seed sweep over {len(reports)} datasets: headline MAE (cm), {HEADLINE}"]
    out.append("=" * _WIDTH)
    out.append(
        f"{'forecaster':34} "
        + " ".join(f"{r.seed:>9}" for r in reports)
        + f" {'mean':>8} {'min':>8} {'max':>8}"
    )
    out.append("-" * _WIDTH)
    for index, name in enumerate(reports[0].forecasters or list(FORECASTERS)):
        maes = [r.groups[HEADLINE][index].mae for r in reports if HEADLINE in r.groups]
        if not maes:
            continue
        out.append(
            f"{name:34} "
            + " ".join(f"{v:>9.2f}" for v in maes)
            + f" {sum(maes) / len(maes):>8.2f} {min(maes):>8.2f} {max(maes):>8.2f}"
        )

    pooled: dict[tuple[str, str], list[float]] = {}
    for report in reports:
        for model, by_sex in report.gender_bands.items():
            for sex, tally in by_sex.items():
                total = pooled.setdefault((model, sex), [0, 0, 0.0])
                for i in range(3):
                    total[i] += tally[i]
    if pooled:
        out.append("")
        out.append(f"Band learned per gender, pooled over the {len(reports)} datasets")
        out.append("-" * _WIDTH)
        for (model, sex), (hits, n, width) in pooled.items():
            out.append(
                f"{model:34} {sex:7} observed {hits / n:.1%} ({int(hits)} of {int(n)}), "
                f"mean width {width / n:.2f} cm"
            )
    return "\n".join(out)
