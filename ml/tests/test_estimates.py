"""ml/estimates: the shrinkage method on simulated players with known true rates, the FootyStats
reader on an invented cache, and the evaluation's season pairing. No real data."""

from __future__ import annotations

import json
import random

import pytest

from ml import run_estimate_eval
from ml.estimates import footystats, shrinkage


def _population(n=3000, shape=2.0, mean=0.3, seed=7):
    """Players whose true rates come from a known gamma, with counts drawn over random exposures."""
    rng = random.Random(seed)
    rates, counts, exposures = [], [], []
    for _ in range(n):
        rate = rng.gammavariate(shape, mean / shape)
        e = rng.uniform(2, 38)
        # Poisson by counting exponential gaps.
        y, t = 0, rng.expovariate(rate * e) if rate > 0 else float("inf")
        while t < 1:
            y += 1
            t += rng.expovariate(rate * e)
        rates.append(rate)
        counts.append(y)
        exposures.append(e)
    return rates, counts, exposures


def test_fit_recovers_a_known_spread():
    _, counts, exposures = _population()
    prior = shrinkage.fit_prior(counts, exposures)
    assert prior.mean == pytest.approx(0.3, rel=0.05)
    # True strength: shape / mean = 2 / 0.3, about 6.7 matches.
    assert prior.k == pytest.approx(2.0 / 0.3, rel=0.3)


def test_no_spread_beyond_chance_means_everyone_gets_the_peer_rate():
    rng = random.Random(3)
    counts, exposures = [], []
    for _ in range(2000):
        e = rng.uniform(5, 38)
        y, t = 0, rng.expovariate(0.2 * e)
        while t < 1:
            y += 1
            t += rng.expovariate(0.2 * e)
        counts.append(y)
        exposures.append(e)
    prior = shrinkage.fit_prior(counts, exposures)
    assert prior.k > 500
    assert shrinkage.estimate(10, 5, prior).rate == pytest.approx(prior.mean, rel=0.05)


def test_shrinkage_follows_the_evidence():
    prior = shrinkage.Prior(mean=0.1, k=20, players=100)
    nothing = shrinkage.estimate(0, 0, prior)
    assert nothing.raw is None and nothing.rate == pytest.approx(0.1) and nothing.weight == 0
    # One goal in two matches: raw 0.5, pulled most of the way back.
    short = shrinkage.estimate(1, 2, prior)
    assert short.raw == 0.5 and short.rate == pytest.approx((1 + 2) / 22)
    # A full career at 0.5: the player's own record dominates.
    long = shrinkage.estimate(190, 380, prior)
    assert long.rate == pytest.approx((190 + 2) / 400) and long.weight > 0.94
    for e in (nothing, short, long):
        assert e.low <= e.rate <= e.high
    assert (long.high - long.low) < (short.high - short.low)


def test_intervals_hold_the_true_rate_about_as_often_as_they_say():
    rates, counts, exposures = _population(n=4000, seed=11)
    prior = shrinkage.fit_prior(counts, exposures)
    inside = sum(1 for r, y, e in zip(rates, counts, exposures)
                 if (est := shrinkage.estimate(y, e, prior)).low <= r <= est.high)
    assert inside / len(rates) == pytest.approx(0.8, abs=0.04)


def test_a_group_where_nobody_scored():
    prior = shrinkage.fit_prior([0, 0, 0], [10, 20, 30])
    assert prior.mean == 0
    est = shrinkage.estimate(0, 10, prior)
    assert (est.rate, est.low, est.high) == (0, 0, 0)
    assert shrinkage.predictive_interval(0, 10, prior, 30) == (0, 0)


def test_a_group_with_no_exposure_is_an_error():
    with pytest.raises(ValueError):
        shrinkage.fit_prior([1], [0.5])


def test_predictive_interval_and_its_coverage():
    prior = shrinkage.Prior(mean=0.3, k=10, players=50)
    lo, hi = shrinkage.predictive_interval(6, 20, prior, 30)
    assert 0 <= lo <= hi
    covered = shrinkage.predictive_coverage(6, 20, prior, 30, lo, hi)
    # Whole-number counts: an "80%" interval holds at least 80%, never less.
    assert 0.8 <= covered <= 1.0


def test_percentile_range():
    est = shrinkage.Estimate(raw=0.3, rate=0.3, low=0.2, high=0.4, weight=0.5)
    peers = [0.1 * i for i in range(10)]
    low, high = shrinkage.percentile_range(est, peers)
    assert low <= high and 1 <= low and high <= 99
    assert shrinkage.percentile_range(est, []) is None


def _cache(tmp_path):
    seasons = {"1": ("Invented League", 20292030, "2029/30"), "2": ("Invented League", 20302031, "2030/31"),
               "3": ("Other League", 20302031, "2030/31")}
    manifest = {"seasons": {sid: {"league": lg, "year": yr, "label": lab} for sid, (lg, yr, lab) in seasons.items()}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def row(pid, position, minutes, goals, pens, assists):
        return {"id": pid, "position": position, "minutes_played_overall": minutes, "goals_overall": goals,
                "penalty_goals": pens, "assists_overall": assists}

    data = {
        "1": [row(1, "Forward", 2000, 10, 3, 4), row(2, "Coach", 0, 0, 0, 0), row(3, "Defender", 0, 0, 0, 0),
              row(4, "Midfielder", 900, -1, 0, 1)],
        "2": [row(1, "Forward", 1500, 5, 0, 2), row(5, "Goalkeeper", 3420, 0, 0, 0)],
        "3": [row(9, "Forward", 3000, 20, 0, 5)],
    }
    for sid, rows in data.items():
        (tmp_path / sid).mkdir()
        (tmp_path / sid / "players.json").write_text(json.dumps({"data": rows}), encoding="utf-8")
    return tmp_path


def test_reader_keeps_only_usable_seasons_of_the_league(tmp_path):
    seasons = footystats.load(_cache(tmp_path), "Invented League")
    got = {(s.player_id, s.season) for s in seasons}
    # The coach, the 0-minute player and the unknown goal count are left out; so is the other league.
    assert got == {(1, "2029/30"), (1, "2030/31"), (5, "2030/31")}
    first = next(s for s in seasons if s.player_id == 1 and s.season == "2029/30")
    assert first.np_goals == 7 and first.group == "forward" and first.start_year == 2029
    assert first.exposure == pytest.approx(2000 / 90)


def test_pairs_are_consecutive_seasons_of_one_player(tmp_path):
    seasons = footystats.load(_cache(tmp_path), "Invented League")
    pairs = list(run_estimate_eval.pairs(seasons))
    assert [(a.player_id, a.season, b.season) for a, b in pairs] == [(1, "2029/30", "2030/31")]
