"""Scoring the pro tier analyses against the synthetic league's answer key.

Breakouts
---------
The population is every (player, season) after the league's first season that has a record,
plus any planted breakout whose player did not play that season (it counts as missed: closed
world, as for the other detectors, see ml/evaluation/metrics.py). Every variant is scored on
the same population, so the numbers compare directly.

Finishing
---------
Two questions, both against each player's true finishing, which the league plants (1.0 is an
ordinary finisher; about 4% are near 1.3 and 4% near 0.75):

1. **Does "above expected" find real finishers?** Of the verdicts "above", how many belong to a
   player who truly finishes better than ordinary (true finishing at least `GOOD`)? Once for a
   single season, once for all seasons pooled.
2. **What predicts next season's goals?** For consecutive seasons with `trends.MIN_MINUTES` each,
   in the same competition: next season's non-penalty goals per 90 predicted by this season's
   goals per 90, by this season's npxG per 90, and by the average for the position. Mean absolute
   error. This is the number behind "do not buy the hot striker on goals alone".
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from ml.evaluation.metrics import Score, score_ids
from ml.pro import breakout, sustainability, trends
from ml.pro.seasons import SeasonRow, by_player, consecutive, from_league

REFERENCE = date(2026, 10, 26)
# True finishing at or above this is a genuinely better finisher (the planted ones are near 1.3;
# ordinary finishers spread about 6% either side of 1.0).
GOOD = 1.15
GROUPS = {"GK": "goalkeeper", "CB": "defender", "LB": "defender", "RB": "defender",
          "CDM": "midfielder", "CM": "midfielder", "CAM": "midfielder",
          "LW": "forward", "RW": "forward", "ST": "forward"}


@dataclass
class LeagueData:
    seed: int
    rows: list[SeasonRow]
    first_year: int
    breakouts: set[str]
    finishing: dict[str, float]


def league_data(seed: int, reference: date = REFERENCE) -> LeagueData:
    from data.pipelines.synthetic import pro_league

    clubs, players = pro_league.synthetic_inputs(seed, reference)
    league = pro_league.build_league(seed, clubs, players, reference)
    return LeagueData(
        seed=seed,
        rows=from_league(league, players),
        first_year=league.seasons[0].end.year,
        breakouts={f"{pid}|{season}" for pid, season in league.breakouts},
        finishing=dict(league.finishing),
    )


def _population(data: LeagueData) -> set[str]:
    pairs = {
        f"{this.player_id}|{this.season}"
        for seasons in by_player(data.rows).values()
        for _, this in consecutive(seasons, data.first_year)
    }
    return pairs | data.breakouts


def score_breakouts(
    data: LeagueData,
    threshold: float = breakout.THRESHOLD,
    age_window: bool = True,
    name: str = "breakout v1",
) -> Score:
    found = breakout.detect(data.rows, data.first_year, threshold, age_window)
    predicted = {f"{a.player_id}|{a.season}" for a in found if a.flagged}
    return score_ids(name, predicted, data.breakouts, _population(data))


def score_per90(data: LeagueData, threshold: float = 0.15, minutes_weight: float = 0.1) -> Score:
    predicted = {f"{p}|{s}" for p, s in breakout.per90_detect(data.rows, data.first_year, threshold, minutes_weight)}
    return score_ids("per 90 rate (first version)", predicted, data.breakouts, _population(data))


def score_minutes_only(data: LeagueData, threshold: float) -> Score:
    predicted = {f"{p}|{s}" for p, s in breakout.minutes_only(data.rows, data.first_year, threshold)}
    return score_ids(f"minutes only (rise >= {threshold:.2f})", predicted, data.breakouts, _population(data))


def unscorable(data: LeagueData) -> dict[str, int]:
    """Why planted breakouts could not be scored: what v1 cannot see, counted."""
    out: dict[str, int] = {}
    found = {f"{a.player_id}|{a.season}": a for a in breakout.detect(data.rows, data.first_year)}
    for key in data.breakouts:
        reason = "no record that season" if key not in found else found[key].reason
        if key in found and found[key].score is not None:
            continue
        out[reason] = out.get(reason, 0) + 1
    return out


@dataclass
class FinishingReport:
    # verdict "above": (how many, how many truly better finishers), single season and pooled.
    above_single: tuple[int, int]
    above_career: tuple[int, int]
    # Truly better finishers with enough chances pooled to judge, and how many were "above".
    good_judgeable: int
    good_found: int
    # Ordinary finishers' single seasons judged, and how many were called above or below.
    ordinary_seasons: int
    ordinary_flagged: int
    # Next season's np goals per 90: mean absolute error by predictor, over `pairs` cases.
    pairs: int
    mae: dict[str, float]


def score_finishing(data: LeagueData) -> FinishingReport:
    true = data.finishing
    above_single = [0, 0]
    ordinary = [0, 0]
    for row in data.rows:
        verdict = sustainability.season(row).verdict
        if verdict == "too few chances":
            continue
        good = true[row.player_id] >= GOOD
        if verdict == "above":
            above_single[0] += 1
            above_single[1] += good
        if 1 / GOOD < true[row.player_id] < GOOD:
            ordinary[0] += 1
            ordinary[1] += verdict != "in line"

    above_career = [0, 0]
    good_judgeable = good_found = 0
    for pid, seasons in by_player(data.rows).items():
        verdict = sustainability.career(seasons).verdict
        good = true[pid] >= GOOD
        if verdict == "above":
            above_career[0] += 1
            above_career[1] += good
        if good and verdict != "too few chances":
            good_judgeable += 1
            good_found += verdict == "above"

    # Average np goals per 90 for each position group, from this season's qualifying rows.
    pairs = []
    for seasons in by_player(data.rows).values():
        for previous, this in consecutive(seasons, data.first_year):
            if (previous is None or previous.competition != this.competition
                    or min(previous.minutes, this.minutes) < trends.MIN_MINUTES):
                continue
            pairs.append((previous, this))
    group_mean: dict[tuple[str, str], float] = {}
    for season in {p.season for p, _ in pairs}:
        for group in set(GROUPS.values()):
            values = [p.np_goals * 90 / p.minutes for p, _ in pairs
                      if p.season == season and GROUPS.get(p.position or "") == group]
            if values:
                group_mean[(season, group)] = statistics.fmean(values)
    errors: dict[str, list[float]] = {"goals per 90": [], "npxG per 90": [], "position average": []}
    for previous, this in pairs:
        actual = this.np_goals * 90 / this.minutes
        errors["goals per 90"].append(abs(previous.np_goals * 90 / previous.minutes - actual))
        errors["npxG per 90"].append(abs(previous.metrics["npxg"] * 90 / previous.minutes - actual))
        errors["position average"].append(
            abs(group_mean[(previous.season, GROUPS.get(previous.position or ""))] - actual))
    return FinishingReport(
        above_single=tuple(above_single), above_career=tuple(above_career),
        good_judgeable=good_judgeable, good_found=good_found,
        ordinary_seasons=ordinary[0], ordinary_flagged=ordinary[1],
        pairs=len(pairs), mae={k: statistics.fmean(v) for k, v in errors.items()},
    )
