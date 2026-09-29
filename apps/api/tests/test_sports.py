"""Sport modules: validation, rendering, and the claim the architecture rests on.

CLAUDE.md says adding a sport should be a config change, not a schema rewrite. Until these
tests existed that was an assertion. `test_a_new_sport_is_a_config_change` makes it a fact:
it writes a module for a sport that exists nowhere else in the repository, and then logs a
player in that sport, records a match, and reads it back on the profile, with no code change.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import date

import pytest

from app import sports
from app.sports import ModuleError, load_module, validate


def football(**overrides) -> dict:
    row = {
        "minutes_played": 90,
        "shots": 3,
        "shots_on_target": 2,
        "goals": 1,
        "assists": 0,
        "key_passes": 1,
        "passes_attempted": 40,
        "passes_completed": 33,
        "tackles": 2,
        "distance_km": 10.2,
        "yellow_cards": 0,
        "red_cards": 0,
    }
    row.update(overrides)
    return row


def table_tennis(**overrides) -> dict:
    row = {"best_of": 5, "sets_won": 3, "sets_lost": 1, "points_won": 44, "points_lost": 35}
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# The committed modules
# ---------------------------------------------------------------------------


def test_both_sports_load():
    registry = sports.registry()
    assert set(registry) == {"football", "table_tennis"}
    assert "table_tennis.match.v1" in registry["table_tennis"].periods


def test_the_generators_schema_refs_all_have_a_module():
    """Every kind of record the generator writes must be something a module defines."""
    import sys
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parents[3])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from data.pipelines.synthetic import performance

    for ref in (
        performance.FOOTBALL_SCHEMA_REF,
        performance.FOOTBALL_SEASON_SCHEMA_REF,
        performance.TABLE_TENNIS_SCHEMA_REF,
    ):
        assert sports.period_for(ref) is not None, ref


def test_a_real_football_match_passes():
    assert validate(football(), "football.match.v1") == []


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"goals": 3}, "more goals than shots on target"),
        ({"passes_completed": 41}, "more passes completed than attempted"),
        ({"minutes_played": 0}, "did not play"),
        ({"distance_km": 19.0}, "above 15"),
        ({"goals": 1.5}, "must be integer"),
        ({"goals": True}, "must be integer"),
        ({"xg": 0.4}, "not a matches metric"),
    ],
)
def test_impossible_football_is_rejected(overrides, fragment):
    problems = validate(football(**overrides), "football.match.v1")
    assert any(fragment in p for p in problems), problems


def test_missing_required_metric_is_rejected():
    row = football()
    del row["shots"]
    assert "shots is missing" in validate(row, "football.match.v1")


@pytest.mark.parametrize(
    ("best_of", "won", "lost", "ok"),
    [
        (5, 3, 0, True),
        (5, 2, 3, True),
        (7, 4, 3, True),
        (5, 2, 2, False),  # nobody has won yet
        (5, 3, 3, False),  # both won
        (5, 4, 1, False),  # a best of five is over at three
        (7, 3, 1, False),  # a best of seven is not over at three
    ],
)
def test_table_tennis_matches_must_be_finished(best_of, won, lost, ok):
    row = table_tennis(best_of=best_of, sets_won=won, sets_lost=lost, points_won=11 * won, points_lost=11 * lost)
    assert (validate(row, "table_tennis.match.v1") == []) is ok


def test_a_won_set_needs_eleven_points():
    problems = validate(table_tennis(points_won=20), "table_tennis.match.v1")
    assert any("fewer than 11 points" in p for p in problems)


def test_an_unknown_schema_ref_is_rejected():
    assert validate({}, "cricket.innings.v1") == ["no sport module defines 'cricket.innings.v1'"]


def test_summary_pools_rather_than_averaging():
    """One cameo with a goal must not dominate a season of full matches."""
    period = sports.period_for("football.match.v1")
    rows = [football(minutes_played=10, goals=1, shots=1, shots_on_target=1)] + [
        football(goals=0, shots_on_target=0) for _ in range(9)
    ]
    stats = {s["key"]: s for s in sports.summarise(period, rows)}
    assert stats["goals_per_90"]["value"] == pytest.approx(90 * 1 / 820)


# ---------------------------------------------------------------------------
# A module is refused at load time if it could mean more than is checked
# ---------------------------------------------------------------------------


def _write_module(directory, sport: str, **period_overrides) -> None:
    period = {
        "periodType": "match",
        "label": "Matches",
        "schema": {
            "type": "object",
            "required": ["games_won", "games_lost"],
            "additionalProperties": False,
            "properties": {
                "games_won": {"type": "integer", "minimum": 0, "title": "Games won"},
                "games_lost": {"type": "integer", "minimum": 0, "title": "Games lost"},
            },
        },
        "invariants": [],
        "derived": [
            {
                "key": "game_win_rate",
                "label": "Games won",
                "numerator": ["games_won"],
                "denominator": ["games_won", "games_lost"],
                "format": "percent",
            }
        ],
    }
    period.update(period_overrides)
    module = {
        "sport": sport,
        "label": sport.title(),
        "roles": {"label": "Hand", "values": ["left", "right"]},
        "usesTier": False,
        "periods": {f"{sport}.match.v1": period},
    }
    (directory / f"{sport}.json").write_text(json.dumps(module), encoding="utf-8")


def test_unsupported_keyword_is_refused(tmp_path):
    _write_module(tmp_path, "squash")
    path = tmp_path / "squash.json"
    raw = json.loads(path.read_text())
    raw["periods"]["squash.match.v1"]["schema"]["properties"]["games_won"]["pattern"] = "x"
    path.write_text(json.dumps(raw))
    with pytest.raises(ModuleError, match="unsupported"):
        load_module(path)


def test_open_schema_is_refused(tmp_path):
    _write_module(tmp_path, "squash")
    path = tmp_path / "squash.json"
    raw = json.loads(path.read_text())
    raw["periods"]["squash.match.v1"]["schema"]["additionalProperties"] = True
    path.write_text(json.dumps(raw))
    with pytest.raises(ModuleError, match="additionalProperties"):
        load_module(path)


def test_rule_on_an_undefined_metric_is_refused(tmp_path):
    _write_module(tmp_path, "squash", invariants=[{"lte": ["games_won", "rallies"]}])
    with pytest.raises(ModuleError, match="undefined metric"):
        load_module(tmp_path / "squash.json")


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------


@pytest.fixture
def with_squash(tmp_path, monkeypatch):
    """The committed modules plus one for a sport the codebase has never heard of."""
    modules = tmp_path / "sports"
    shutil.copytree(sports.default_modules_dir(), modules)
    _write_module(modules, "squash")

    from app.config import get_settings

    monkeypatch.setenv("SPORT_MODULES_DIR", str(modules))
    get_settings.cache_clear()
    sports.registry.cache_clear()
    yield
    get_settings.cache_clear()
    sports.registry.cache_clear()


def test_a_new_sport_is_a_config_change(with_squash, client, auth, world, db):
    from app.models.performance_entry import PerformanceEntry

    listed = {s["sport"]: s for s in client.get("/sports", headers=auth("coach_a")).json()}
    assert listed["squash"]["roleLabel"] == "Hand"

    created = client.post(
        "/players",
        json={
            "fullName": "Squash Test Player",
            "dateOfBirth": "2010-03-01",
            "primarySport": "squash",
            "position": "left",
            "consent": {"signed": True, "guardianName": "Test Guardian"},
            "nationality": ["EG"],
        },
        headers=auth("coach_a"),
    )
    assert created.status_code == 201, created.text
    player_id = uuid.UUID(created.json()["player"]["id"])

    for won, lost in ((3, 1), (1, 3), (3, 0)):
        db.add(
            PerformanceEntry(
                player_id=player_id,
                sport="squash",
                period_type="match",
                period_start=date(2026, 5, 1),
                metrics={"games_won": won, "games_lost": lost},
                schema_ref="squash.match.v1",
                source="coach_logged",
                is_validated=True,
            )
        )
    db.flush()

    profile = client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).json()
    (section,) = profile["performance"]
    assert section["known"] is True
    assert [c["label"] for c in section["columns"]] == ["Games won", "Games lost"]
    (stat,) = section["summary"]
    assert stat["label"] == "Games won"
    assert stat["value"] == pytest.approx(7 / 11)


def test_a_role_from_another_sport_is_refused(with_squash, client, auth, world):
    response = client.post(
        "/players",
        json={
            "fullName": "Wrong Role",
            "dateOfBirth": "2010-03-01",
            "primarySport": "squash",
            "position": "ST",
            "consent": {"signed": True, "guardianName": "Test Guardian"},
        },
        headers=auth("coach_a"),
    )
    assert response.status_code == 422
    assert "not a hand in squash" in " ".join(response.json()["detail"]["problems"])


# ---------------------------------------------------------------------------
# The profile
# ---------------------------------------------------------------------------


@pytest.fixture
def table_tennis_player(world, db):
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player
    from app.models.player_organization import PlayerOrganization

    player = Player(
        full_name="Table Tennis Test",
        date_of_birth=date(2009, 1, 1),
        sex="female",
        nationality=["EG"],
        is_egypt_eligible=True,
        primary_sport="table_tennis",
        position="chopper",
        is_minor=False,
        status="active",
    )
    db.add(player)
    db.flush()
    db.add(
        PlayerOrganization(
            player_id=player.id,
            organization_id=world["orgs"]["a"].id,
            role="player",
            start_date=date(2025, 1, 1),
        )
    )
    matches = [
        table_tennis(),
        table_tennis(sets_won=1, sets_lost=3, points_won=30, points_lost=42),
        # Impossible: two sets each is not a finished match.
        table_tennis(sets_won=2, sets_lost=2, points_won=40, points_lost=40),
    ]
    for index, metrics in enumerate(matches):
        db.add(
            PerformanceEntry(
                player_id=player.id,
                sport="table_tennis",
                period_type="match",
                period_start=date(2026, 5, 1 + index),
                metrics=metrics,
                schema_ref="table_tennis.match.v1",
                source="coach_logged",
                is_validated=True,
            )
        )
    db.flush()
    return player


def test_table_tennis_renders_from_its_module(client, auth, table_tennis_player):
    profile = client.get(
        f"/players/{table_tennis_player.id}/profile", headers=auth("coach_a")
    ).json()
    (section,) = profile["performance"]
    assert section["label"] == "Matches"
    labels = [c["label"] for c in section["columns"]]
    assert labels[:3] == ["Best of", "Sets won", "Sets lost"]

    stats = {s["key"]: s for s in section["summary"]}
    # The impossible match is excluded, so one win in two, not one in three.
    assert section["excludedFromSummary"] == 1
    assert stats["match_win_rate"]["value"] == pytest.approx(0.5)
    assert stats["match_win_rate"]["basis"] == 2


def test_integrity_problems_show_only_to_those_who_see_flags(
    client, auth, table_tennis_player
):
    def problems(who: str) -> list:
        body = client.get(
            f"/players/{table_tennis_player.id}/profile", headers=auth(who)
        ).json()
        return [e["problems"] for e in body["performance"][0]["entries"]]

    assert any(problems("coach_a")), "the coach should see why the record is excluded"
    assert any(problems("federation"))


def test_a_player_does_not_see_integrity_problems_on_their_own_record(
    client, auth, world, db, table_tennis_player
):
    """Same rule as flags: a child is not told a machine doubts their record."""
    world["users"]["player_self"].linked_player_id = table_tennis_player.id
    db.flush()
    body = client.get(
        f"/players/{table_tennis_player.id}/profile", headers=auth("player_self")
    ).json()
    entries = body["performance"][0]["entries"]
    assert entries and all(e["problems"] is None for e in entries)
