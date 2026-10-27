"""The synthetic Egyptian league (pro_league.py): what the pro tier's analyses are built and scored on.

Every point here protects something an analysis relies on: records the sport module accepts,
team and player figures that agree, a planted answer key that is only where it should be, and
finishing that behaves like football's (scoring above your xG mostly does not last).
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from datetime import date

import pytest

from data.pipelines.synthetic import pro_league as pl

REFERENCE = date(2026, 10, 26)


@pytest.fixture(scope="module")
def league():
    clubs, players = pl.synthetic_inputs(101, REFERENCE)
    return pl.build_league(101, clubs, players, REFERENCE), {p.id: p for p in players}


def test_the_same_seed_makes_the_same_league():
    clubs, players = pl.synthetic_inputs(7, REFERENCE)
    a = pl.build_league(7, clubs, players, REFERENCE)
    b = pl.build_league(7, clubs, players, REFERENCE)
    assert [r.metrics for r in a.player_seasons] == [r.metrics for r in b.player_seasons]
    assert a.breakouts == b.breakouts
    c = pl.build_league(8, clubs, players, REFERENCE)
    assert [r.metrics for r in a.player_seasons] != [r.metrics for r in c.player_seasons]


def test_three_completed_seasons_before_the_reference():
    assert [s.label for s in pl.seasons_before(REFERENCE)] == ["2023/24", "2024/25", "2025/26"]
    assert [s.label for s in pl.seasons_before(date(2026, 3, 1))][-1] == "2024/25"


def test_every_record_is_one_the_sport_module_accepts(league):
    from app import sports

    built, _ = league
    modules = sports.registry()
    assert not [r for r in built.player_seasons if sports.validate(r.metrics, pl.SCHEMA_PLAYER, modules)]
    assert not [r for r in built.team_seasons if sports.validate(r.metrics, pl.SCHEMA_TEAM, modules)]


def test_a_teams_players_score_the_teams_goals(league):
    built, _ = league
    goals = defaultdict(int)
    for row in built.player_seasons:
        goals[(row.club_id, row.season.label)] += row.metrics["goals"]
    for team in built.team_seasons:
        assert goals[(team.club_id, team.season.label)] == team.metrics["goals_for"]


def test_the_league_table_adds_up(league):
    built, _ = league
    for team in built.team_seasons:
        m = team.metrics
        assert m["matches"] == 2 * (pl.LEAGUE_SIZE - 1)
        assert m["wins"] + m["draws"] + m["losses"] == m["matches"]
        assert m["points"] == 3 * m["wins"] + m["draws"] == m["home_points"] + m["away_points"]
    for season in built.seasons:
        rows = [t.metrics for t in built.team_seasons if t.season.label == season.label]
        assert sum(r["goals_for"] for r in rows) == sum(r["goals_against"] for r in rows)
        assert sum(r["wins"] for r in rows) == sum(r["losses"] for r in rows)


def test_breakouts_are_planted_only_on_young_players_after_the_first_season(league):
    built, players = league
    first = built.seasons[0].label
    ends = {s.label: s.end for s in built.seasons}
    assert built.breakouts, "the answer key needs cases"
    for player_id, season in built.breakouts:
        assert season != first
        age = (ends[season] - players[uuid.UUID(player_id)].date_of_birth).days / 365.25
        assert 18 <= age < 24


def test_finishing_behaves_like_football():
    """Over three calibration leagues: goals track expected goals overall, and scoring above
    your xG one season says little about the next (published figures on real leagues are
    around 0.1 to 0.2). If this drifts, the sustainability analysis is scored on a league
    that does not behave like football."""
    goals = xg = 0.0
    this, following = [], []
    for seed in (101, 202, 303):
        clubs, players = pl.synthetic_inputs(seed, REFERENCE)
        built = pl.build_league(seed, clubs, players, REFERENCE)
        goals += sum(t.metrics["goals_for"] for t in built.team_seasons)
        xg += sum(t.metrics["xg_for"] for t in built.team_seasons)
        labels = [s.label for s in built.seasons]
        gap = {
            (r.player_id, r.season.label): (r.metrics["goals"] - r.metrics["penalty_goals"]) - r.metrics["npxg"]
            for r in built.player_seasons
            if r.competition == pl.COMPETITION and r.metrics["minutes_played"] >= 900 and r.metrics["npxg"] >= 2
        }
        for (pid, season), value in gap.items():
            i = labels.index(season)
            if i + 1 < len(labels) and (pid, labels[i + 1]) in gap:
                this.append(value)
                following.append(gap[(pid, labels[i + 1])])
    assert 0.92 <= goals / xg <= 1.08
    assert len(this) > 300
    assert statistics.correlation(this, following) < 0.3
