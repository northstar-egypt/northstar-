"""Per-position age curves for professionals: how playing time and output change with age.

Read from `ml/run_age_curve_eval.py` (the evaluation and the printed tables) and
`ml/figure_age_curves.py` (the figure); checked on invented players in `ml/tests/test_age_curves.py`.

What it answers for a scout: is this 21-year-old's season normal for his age, or early? For each
position group (goalkeeper, defender, midfielder, forward) and each measure, the curve says how
much the measure typically changes from age a to age a+1.

The one trap this file exists to avoid
--------------------------------------
FootyStats' `age` field is the player's age on the day the data was downloaded, not in the
season. A player born in 1992 is "33" in the 2018/19 file. So `age` is never read. Each season's
age is computed from `birthday` on 1 September of the season's first year (the 2018/19 season
uses 1 September 2018), in whole years. Players with no birthday (0, -1 or missing) are left out
and counted.

Measures
--------
- `minutes_share`: minutes played over 38 x 90, the share of a full Premier League season.
- `goals_per90`, `assists_per90`: per 90 minutes, only from seasons with 900 or more minutes
  (below that the rate is mostly noise). Goalkeepers get the minutes curve only.

The delta method
----------------
For every player in two consecutive seasons, the change in the measure from age a to age a+1.
Average the changes at each age, weighted by the smaller of the two seasons' minutes, then add
them up from the youngest age to draw the curve. Only players who are still in the league in
both seasons enter a change, so players who declined and left do not drag the curve down at
the end, which is the survivorship bias of the simple average by age. A curve is only drawn
over ages that each have at least `MIN_PAIRS` pairs, and over one unbroken run of such ages,
because adding up changes across a gap would be inventing the gap.

The curve is a change since the youngest drawn age. To put it on the same axis as the simple
average it is anchored at the simple average of that youngest age; the prediction below uses
only the changes, so the anchor never affects a prediction.

Uncertainty
-----------
Players are resampled with replacement (`N_BOOTSTRAP` times, all of a player's pairs together),
the curve rebuilt each time, and the 10th to 90th percentile drawn as the 80% band. The band is
the uncertainty of the shape (the change since the youngest age); the anchor is held fixed.

The test it can fail (decided before the first run)
---------------------------------------------------
Curves are built only from season pairs that end in 2022/23 or earlier. For the pairs 2022/23 to
2023/24 and 2023/24 to 2024/25, a player's next season is predicted as "this season plus the
curve's change at this age", and compared by mean absolute error with two baselines:
"the same as this season" and "the average of the player's position group in this season". Both
baselines use only what was known in the season being predicted from. A player is scored only if
his age has a drawn change and, for per-90 measures, both seasons have 900 or more minutes; all
three predictions are scored on exactly the same rows. If the curve does not beat "the same as
this season", that is the result and it is reported.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

# The seven Premier League seasons the FootyStats test key unlocks, 2018/19 to 2024/25. Liga MX
# (season id 2270) is deliberately absent: a different league has a different age profile.
PREMIER_LEAGUE_SEASON_IDS = (1625, 2012, 4759, 6135, 7704, 9660, 12325)

POSITIONS = ("goalkeeper", "defender", "midfielder", "forward")
MEASURES = ("minutes_share", "goals_per90", "assists_per90")
MEASURE_LABELS = {"minutes_share": "Share of season minutes", "goals_per90": "Goals per 90",
                  "assists_per90": "Assists per 90"}

FULL_SEASON_MINUTES = 38 * 90
MIN_PER90_MINUTES = 900
MIN_PAIRS = 30
N_BOOTSTRAP = 1000
BAND = (10, 90)

# Curves use pairs whose second season starts in this year or earlier (2022/23 starts in 2022).
TRAIN_LAST_SEASON_START = 2022
# (first season start, second season start) of the pairs that are predicted.
TEST_PAIRS = ((2022, 2023), (2023, 2024))

LEFT_OUT_REASONS = ("not a player (coach)", "no birthday", "missing fields", "never played (0 minutes)",
                    "unknown position", "duplicate row in a season")


def measures_for(position: str) -> tuple[str, ...]:
    """Goalkeepers get the minutes curve only; goals and assists say nothing about them."""
    return ("minutes_share",) if position == "goalkeeper" else MEASURES


@dataclass(frozen=True)
class SeasonRecord:
    player_id: int
    # The calendar year the season starts in: 2018 for 2018/19.
    start_year: int
    position: str
    # Whole years on 1 September of start_year.
    age: int
    minutes: int
    goals: int
    assists: int


def age_on_first_of_september(birthday: date, start_year: int) -> int:
    """Whole years on 1 September of `start_year`. Born on 1 September counts as having turned."""
    years = start_year - birthday.year
    if (birthday.month, birthday.day) > (9, 1):
        years -= 1
    return years


def measure_value(record: SeasonRecord, measure: str) -> float | None:
    """The record's value of a measure, or None when the season is too short for a per-90 rate."""
    if measure == "minutes_share":
        return record.minutes / FULL_SEASON_MINUTES
    if record.minutes < MIN_PER90_MINUTES:
        return None
    count = record.goals if measure == "goals_per90" else record.assists
    return count * 90 / record.minutes


# ---------------------------------------------------------------------------------------------
# Reading the cache
# ---------------------------------------------------------------------------------------------

@dataclass
class LoadReport:
    """What was read and what was left out, with the reason. Every row is accounted for."""
    seasons: list[dict] = field(default_factory=list)
    rows_read: int = 0
    used: int = 0
    left_out: dict[str, int] = field(default_factory=lambda: {r: 0 for r in LEFT_OUT_REASONS})

    def skip(self, reason: str) -> None:
        self.left_out[reason] += 1


def _birthday(value) -> date | None:
    """A FootyStats Unix timestamp as a date; None for 0, -1, missing or not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).date()


def _count(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def record_from_row(row: dict, start_year: int, report: LoadReport) -> SeasonRecord | None:
    """One `players.json` row as a record, or None (counted in the report with its reason)."""
    report.rows_read += 1
    position = str(row.get("position") or "").lower()
    if position == "coach":
        report.skip("not a player (coach)")
        return None
    if position not in POSITIONS:
        report.skip("unknown position")
        return None
    birthday = _birthday(row.get("birthday"))
    if birthday is None:
        report.skip("no birthday")
        return None
    minutes = _count(row.get("minutes_played_overall"))
    goals = _count(row.get("goals_overall"))
    assists = _count(row.get("assists_overall"))
    if minutes is None or goals is None or assists is None or not isinstance(row.get("id"), int):
        report.skip("missing fields")
        return None
    if minutes == 0:
        report.skip("never played (0 minutes)")
        return None
    report.used += 1
    return SeasonRecord(row["id"], start_year, position, age_on_first_of_september(birthday, start_year),
                        minutes, goals, assists)


def load_records(cache_dir: Path, season_ids=PREMIER_LEAGUE_SEASON_IDS) -> tuple[list[SeasonRecord], LoadReport]:
    """Read the Premier League seasons from a FootyStats cache (see data/pipelines/footystats).

    The cache holds data about real people, so a folder inside the repository is refused, the
    same rule the download script applies. A player id appearing twice in one season (a mid-season
    move inside the league) is one row in FootyStats; if it ever appears twice the first is kept
    and the other counted, so no player is counted twice in a season.
    """
    from data.pipelines.footystats.fetch import check_outside_repo

    cache_dir = check_outside_repo(Path(cache_dir))
    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))["seasons"]
    report = LoadReport()
    records: list[SeasonRecord] = []
    for season_id in season_ids:
        info = manifest.get(str(season_id))
        folder = cache_dir / str(season_id)
        if info is None or not (folder / "players.json").exists():
            continue
        start_year = int(str(info["label"]).split("/")[0])
        rows = json.loads((folder / "players.json").read_text(encoding="utf-8"))["data"]
        seen: set[int] = set()
        before = report.used
        for row in rows:
            record = record_from_row(row, start_year, report)
            if record is None:
                continue
            if record.player_id in seen:
                report.used -= 1
                report.skip("duplicate row in a season")
                continue
            seen.add(record.player_id)
            records.append(record)
        report.seasons.append({"season_id": season_id, "label": info["label"], "league": info.get("league"),
                               "start_year": start_year, "rows": len(rows), "used": report.used - before})
    return records, report


# ---------------------------------------------------------------------------------------------
# Pairs, curves
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Pair:
    """One player in two consecutive seasons; `age` is the age in the first."""
    player_id: int
    position: str
    age: int
    first: SeasonRecord
    second: SeasonRecord


def consecutive_pairs(records: list[SeasonRecord]) -> list[Pair]:
    """Every player's pairs of seasons one year apart. A player is in at most one row per season,
    so a mid-season move inside the league cannot make a pair twice. The position and age are
    those of the first season."""
    by_key = {(r.player_id, r.start_year): r for r in records}
    pairs = []
    for (player_id, year), first in by_key.items():
        second = by_key.get((player_id, year + 1))
        if second is not None:
            pairs.append(Pair(player_id, first.position, first.age, first, second))
    pairs.sort(key=lambda p: (p.player_id, p.first.start_year))
    return pairs


@dataclass
class Curve:
    """One position group and one measure. `ages` are the first ages of the changes, in order;
    `delta[i]` is the average change from ages[i] to ages[i] + 1, `pairs[i]` how many pairs it
    rests on. `level` has one more point than `delta`: the curve itself, at ages[0] ... ages[-1] + 1,
    anchored at the simple average of the youngest age. `low` and `high` are the 80% band."""
    position: str
    measure: str
    ages: list[int]
    delta: list[float]
    pairs: list[int]
    level: list[float]
    low: list[float] | None = None
    high: list[float] | None = None
    ages_left_out: dict[int, int] = field(default_factory=dict)
    players: int = 0

    def delta_at(self, age: int) -> float | None:
        if age in self.ages:
            return self.delta[self.ages.index(age)]
        return None


def _longest_run(ages: list[int]) -> list[int]:
    """The longest stretch of consecutive ages (the youngest if tied)."""
    best: list[int] = []
    current: list[int] = []
    for age in sorted(ages):
        current = current + [age] if current and age == current[-1] + 1 else [age]
        if len(current) > len(best):
            best = current
    return best


def _arrays(pairs: list[Pair], position: str, measure: str):
    """Player index, age, change and weight for every usable pair of a position and measure."""
    ids: dict[int, int] = {}
    player, age, change, weight = [], [], [], []
    for pair in pairs:
        if pair.position != position:
            continue
        a, b = measure_value(pair.first, measure), measure_value(pair.second, measure)
        if a is None or b is None:
            continue
        player.append(ids.setdefault(pair.player_id, len(ids)))
        age.append(pair.age)
        change.append(b - a)
        weight.append(min(pair.first.minutes, pair.second.minutes))
    return (np.array(player, dtype=int), np.array(age, dtype=int), np.array(change, dtype=float),
            np.array(weight, dtype=float), len(ids))


def _weighted_deltas(age, change, weight, multiplicity, ages: list[int]) -> np.ndarray:
    """Average change at each wanted age, weighted by minutes and by how often each pair was drawn."""
    w = weight * multiplicity
    out = np.zeros(len(ages))
    for i, a in enumerate(ages):
        at = age == a
        total = w[at].sum()
        out[i] = (w[at] * change[at]).sum() / total if total > 0 else 0.0
    return out


def simple_average(records: list[SeasonRecord], position: str, measure: str,
                   min_n: int = MIN_PAIRS) -> dict[int, tuple[float, int]]:
    """The plain mean of a measure by age over player-seasons: {age: (mean, n)}, ages with at
    least `min_n` seasons. It rises late in a career only because the players who declined left
    the league, which is why the delta method exists."""
    values: dict[int, list[float]] = {}
    for record in records:
        if record.position != position:
            continue
        value = measure_value(record, measure)
        if value is not None:
            values.setdefault(record.age, []).append(value)
    return {a: (float(np.mean(v)), len(v)) for a, v in sorted(values.items()) if len(v) >= min_n}


def build_curve(records: list[SeasonRecord], position: str, measure: str, *, n_bootstrap: int = N_BOOTSTRAP,
                min_pairs: int = MIN_PAIRS, seed: int = 0, last_season_start: int | None = None) -> Curve | None:
    """The delta-method curve for one position group and measure, or None if no age has enough pairs.

    `last_season_start` keeps only pairs whose second season starts in that year or earlier
    (how the prediction test keeps the future out of the curve).
    """
    pairs = consecutive_pairs(records)
    if last_season_start is not None:
        pairs = [p for p in pairs if p.second.start_year <= last_season_start]
    player, age, change, weight, n_players = _arrays(pairs, position, measure)
    if len(age) == 0:
        return None
    counts = {int(a): int((age == a).sum()) for a in np.unique(age)}
    enough = [a for a, n in counts.items() if n >= min_pairs]
    ages = _longest_run(enough)
    if not ages:
        return None
    left_out = {a: n for a, n in counts.items() if a not in ages}

    delta = _weighted_deltas(age, change, weight, np.ones(len(age)), ages)
    relative = np.concatenate([[0.0], np.cumsum(delta)])
    start_average = simple_average(records if last_season_start is None
                                   else [r for r in records if r.start_year <= last_season_start],
                                   position, measure, min_n=1).get(ages[0])
    anchor = start_average[0] if start_average else 0.0
    curve = Curve(position, measure, ages, [float(d) for d in delta], [counts[a] for a in ages],
                  [float(anchor + x) for x in relative], ages_left_out=left_out,
                  players=len({int(p) for p, a in zip(player, age) if int(a) in ages}))
    if n_bootstrap > 0:
        rng = np.random.default_rng(seed)
        draws = np.empty((n_bootstrap, len(ages) + 1))
        for i in range(n_bootstrap):
            sampled = rng.integers(0, n_players, size=n_players)
            multiplicity = np.bincount(sampled, minlength=n_players)[player].astype(float)
            d = _weighted_deltas(age, change, weight, multiplicity, ages)
            draws[i] = np.concatenate([[0.0], np.cumsum(d)])
        curve.low = [float(anchor + x) for x in np.percentile(draws, BAND[0], axis=0)]
        curve.high = [float(anchor + x) for x in np.percentile(draws, BAND[1], axis=0)]
    return curve


def all_curves(records: list[SeasonRecord], *, n_bootstrap: int = N_BOOTSTRAP,
               seed: int = 0) -> dict[tuple[str, str], tuple[Curve | None, dict[int, tuple[float, int]]]]:
    """Every position group and measure from all the seasons given: the curve (or None) and the
    simple average by age beside it. What the report and the figure draw."""
    return {(position, measure): (build_curve(records, position, measure, n_bootstrap=n_bootstrap, seed=seed),
                                  simple_average(records, position, measure))
            for position in POSITIONS for measure in measures_for(position)}


# ---------------------------------------------------------------------------------------------
# The test it can fail
# ---------------------------------------------------------------------------------------------

@dataclass
class PredictionResult:
    position: str
    measure: str
    n: int
    players: int
    mae_curve: float
    mae_same: float
    mae_group: float
    # 80% intervals (player bootstrap) of the difference in MAE; negative means the curve is better.
    curve_minus_same: tuple[float, float]
    curve_minus_group: tuple[float, float]
    # Pairs of the test seasons that could not be scored, with the reason.
    not_scored: dict[str, int] = field(default_factory=dict)


def _bootstrap_mean_interval(player, value, n_players: int, n_bootstrap: int, seed: int) -> tuple[float, float]:
    if n_bootstrap <= 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    out = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        sampled = rng.integers(0, n_players, size=n_players)
        multiplicity = np.bincount(sampled, minlength=n_players)[player].astype(float)
        out[i] = (value * multiplicity).sum() / multiplicity.sum()
    return float(np.percentile(out, BAND[0])), float(np.percentile(out, BAND[1]))


def evaluate_prediction(records: list[SeasonRecord], *, n_bootstrap: int = N_BOOTSTRAP, seed: int = 0,
                        train_last_season_start: int = TRAIN_LAST_SEASON_START,
                        test_pairs=TEST_PAIRS) -> tuple[list[PredictionResult], dict[tuple[str, str], Curve]]:
    """Build curves from pairs up to `train_last_season_start`, predict the test pairs, score them.

    Returns one result per position and measure, and the curves that were used. The curves for the
    test come only from the early pairs; the records of the test seasons are read only to know the
    player's age, this season's value and the position group's average of this season.
    """
    curves: dict[tuple[str, str], Curve] = {}
    results: list[PredictionResult] = []
    by_key = {(r.player_id, r.start_year): r for r in records}
    for position in POSITIONS:
        for measure in measures_for(position):
            curve = build_curve(records, position, measure, n_bootstrap=n_bootstrap, seed=seed,
                                last_season_start=train_last_season_start)
            if curve is None:
                continue
            curves[(position, measure)] = curve
            group_mean: dict[int, float] = {}
            for year in {first for first, _ in test_pairs}:
                values = [v for r in records if r.start_year == year and r.position == position
                          if (v := measure_value(r, measure)) is not None]
                if values:
                    group_mean[year] = float(np.mean(values))
            ids: dict[int, int] = {}
            player, e_curve, e_same, e_group = [], [], [], []
            not_scored = {"age without a drawn change": 0, "under 900 minutes in a season": 0}
            for first_year, second_year in test_pairs:
                for (pid, year), first in by_key.items():
                    if year != first_year or first.position != position:
                        continue
                    second = by_key.get((pid, second_year))
                    if second is None:
                        continue
                    a, b = measure_value(first, measure), measure_value(second, measure)
                    if a is None or b is None:
                        not_scored["under 900 minutes in a season"] += 1
                        continue
                    delta = curve.delta_at(first.age)
                    if delta is None:
                        not_scored["age without a drawn change"] += 1
                        continue
                    player.append(ids.setdefault(pid, len(ids)))
                    e_curve.append(abs(a + delta - b))
                    e_same.append(abs(a - b))
                    e_group.append(abs(group_mean[first_year] - b))
            if not player:
                continue
            p = np.array(player)
            ec, es, eg = np.array(e_curve), np.array(e_same), np.array(e_group)
            results.append(PredictionResult(
                position, measure, len(p), len(ids), float(ec.mean()), float(es.mean()), float(eg.mean()),
                _bootstrap_mean_interval(p, ec - es, len(ids), n_bootstrap, seed),
                _bootstrap_mean_interval(p, ec - eg, len(ids), n_bootstrap, seed + 1),
                not_scored))
    return results, curves
