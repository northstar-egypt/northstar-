"""The table tennis ratings: the formulas, the match rules, and that nothing sees the future."""

from __future__ import annotations

import math
import tempfile
from datetime import date
from pathlib import Path

import pytest

from ml.rating import glicko2, points
from ml.rating.glicko2 import Game, Rating
from ml.rating.matches import collect, history

# ---------------------------------------------------------------------------
# Glicko-2 against the paper's worked example
# ---------------------------------------------------------------------------


def test_glicko2_matches_glickmans_worked_example():
    """Glickman, "Example of the Glicko-2 system" (2013): 1464.06, RD 151.52, volatility 0.05999."""
    player = Rating(1500, 200, 0.06)
    games = [
        Game(Rating(1400, 30), 1.0),
        Game(Rating(1550, 100), 0.0),
        Game(Rating(1700, 300), 0.0),
    ]
    after = glicko2.update(player, games, tau=0.5)
    assert after.rating == pytest.approx(1464.06, abs=0.01)
    assert after.rd == pytest.approx(151.52, abs=0.01)
    assert after.volatility == pytest.approx(0.05999, abs=0.00001)


def test_an_idle_player_grows_less_certain_but_keeps_their_rating():
    r = glicko2.idle(Rating(1600, 80, 0.06), periods=6)
    assert r.rating == 1600
    assert 80 < r.rd <= glicko2.START_RD


# ---------------------------------------------------------------------------
# Point rating
# ---------------------------------------------------------------------------


def test_set_and_match_probabilities_are_fair_and_symmetric():
    assert points.set_probability(0.5) == pytest.approx(0.5)
    assert points.match_probability(0.5) == pytest.approx(0.5)
    for p in (0.45, 0.52, 0.6):
        assert points.set_probability(p) + points.set_probability(1 - p) == pytest.approx(1.0)
        assert points.match_probability(p, 7) + points.match_probability(1 - p, 7) == pytest.approx(1.0)
    # A small edge per point is a big edge per match, and a bigger one over seven sets.
    assert points.match_probability(0.53, 5) > 0.65
    assert points.match_probability(0.53, 7) > points.match_probability(0.53, 5)


def test_point_rating_recovers_a_known_edge():
    """A wins 60% of points against B. With a weak prior the gap is the log-odds of 0.6."""
    matches = [points.PointMatch("a", "b", 60, 40) for _ in range(30)]
    fitted = points.fit(matches, prior_sd=10.0)
    gap = fitted["a"].theta - fitted["b"].theta
    assert gap == pytest.approx(math.log(0.6 / 0.4), abs=0.01)


def test_more_points_means_a_narrower_range():
    few = points.fit([points.PointMatch("a", "b", 12, 8)], prior_sd=0.15)
    many = points.fit([points.PointMatch("a", "b", 12, 8)] * 40, prior_sd=0.15)
    assert many["a"].se < few["a"].se


def test_the_prior_keeps_a_lucky_newcomer_near_average():
    """One crushing win is not enough to call someone the best in the country."""
    one = points.fit([points.PointMatch("new", "x", 33, 10)], prior_sd=0.15)
    assert one["new"].point_share() < 0.6


# ---------------------------------------------------------------------------
# Which matches count
# ---------------------------------------------------------------------------


def _row(rid, player, opponent, won, lost, day="2026-03-10", source="api", pw=None, pl=None):
    return {
        "id": rid,
        "player_id": player,
        "opponent_player_id": opponent,
        "period_start": day,
        "schema_ref": "table_tennis.match.v1",
        "source": source,
        "metrics": {
            "best_of": 5,
            "sets_won": won,
            "sets_lost": lost,
            "points_won": pw if pw is not None else 11 * won + 5 * lost,
            "points_lost": pl if pl is not None else 11 * lost + 5 * won,
        },
    }


def test_the_two_rows_of_a_match_count_once():
    rows = [_row("1", "a", "b", 3, 1, pw=40, pl=28), _row("2", "b", "a", 1, 3, pw=28, pl=40)]
    matches = collect(rows)
    assert len(matches) == 1
    assert (matches[0].winner, matches[0].loser) == ("a", "b")
    assert matches[0].confirmed


def test_an_unconfirmed_self_submitted_win_does_not_count():
    lone = collect([_row("1", "a", "b", 3, 0, source="self_submitted")])
    assert len(lone) == 1 and not lone[0].confirmed
    both = collect(
        [
            _row("1", "a", "b", 3, 0, source="self_submitted", pw=33, pl=15),
            _row("2", "b", "a", 0, 3, source="self_submitted", pw=15, pl=33),
        ]
    )
    assert both[0].confirmed, "both players logged it, so it is confirmed"


def test_an_impossible_match_never_counts():
    both_won = _row("1", "a", "b", 3, 3, pw=40, pl=40)
    assert collect([both_won]) == []


def test_outsider_matches_skip_self_submitted_and_keep_genders_apart():
    rows = [
        _row("1", "a", None, 3, 1),
        _row("2", "b", None, 3, 0),
        _row("3", "a", None, 3, 0, source="self_submitted"),
        _row("4", "a", None, 3, 0, day="2026-05-01"),
    ]
    out = points.outsider_matches(rows, {"a": "male", "b": "female"}, before=date(2026, 4, 1))
    assert sorted((m.a, m.b) for m in out) == [("a", "outsider:male"), ("b", "outsider:female")]


# ---------------------------------------------------------------------------
# No peeking: a rating at a date uses only matches before it
# ---------------------------------------------------------------------------


def test_rating_going_into_a_month_ignores_that_month_and_later():
    rows = []
    rid = 0
    for month in range(1, 10):
        for a, b in (("a", "b"), ("b", "c"), ("c", "a")):
            rid += 1
            winner_first = (month + rid) % 3 != 0
            won, lost = (3, 1) if winner_first else (1, 3)
            rows.append(_row(str(rid), a, b, won, lost, day=f"2026-{month:02d}-15"))
    full = history(collect(rows), until=date(2026, 9, 30))

    cut = date(2026, 6, 1)
    earlier = [r for r in rows if r["period_start"] < cut.isoformat()]
    truncated = history(collect(earlier), until=date(2026, 5, 31))
    for player in ("a", "b", "c"):
        assert full.before(player, date(2026, 6, 20)) == truncated.current[player]


# ---------------------------------------------------------------------------
# The evaluation runs end to end on a generated dataset
# ---------------------------------------------------------------------------


def test_evaluation_runs_and_the_point_rating_beats_chance():
    from ml.rating import evaluate as rating_eval
    from ml.run_eval import _generate

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "data"
        _generate(11, out_dir)
        report = rating_eval.evaluate(out_dir)

    assert report.rated_matches > 50
    for g in report.rankings:
        if g.players >= 8:
            assert g.rho[rating_eval.POINTS] > 0.5
    coin = report.predictions[rating_eval.COIN]
    assert coin.brier == pytest.approx(0.25)
    assert report.predictions[rating_eval.POINTS].log_loss < coin.log_loss
