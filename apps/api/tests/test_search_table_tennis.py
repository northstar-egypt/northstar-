"""Scout search reads table tennis the way it reads football (app/services/search.py).

Before this, "table tennis", "ping pong", "chopper", "girls" and "few unforced errors" were all
searched as parts of a player's name and found nobody, while every football equivalent worked.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app import sports
from app.services.search import parse_query


# ---------------------------------------------------------------------------
# Reading the query
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query, expected",
    [
        ("table tennis", {"sport": "table_tennis"}),
        ("ping pong", {"sport": "table_tennis"}),
        ("table-tennis players", {"sport": "table_tennis"}),
        ("تنس طاولة", {"sport": "table_tennis"}),
        ("girls table tennis", {"sport": "table_tennis", "sex": "female"}),
        ("تنس طاولة بنات", {"sport": "table_tennis", "sex": "female"}),
        ("chopper", {"sport": "table_tennis", "position": "chopper"}),
        ("all-round players", {"sport": "table_tennis", "position": "all_round"}),
        ("table tennis defender", {"sport": "table_tennis", "position": "defender"}),
        ("soccer", {"sport": "football"}),
        ("كرة القدم", {"sport": "football"}),
    ],
)
def test_the_sport_style_and_gender_are_read_from_plain_words(query, expected):
    filters, chips, names = parse_query(query)
    assert {k: v for k, v in filters.items() if k in expected} == expected
    assert names == [], "none of these words is part of a name"
    assert all(chip["understood"] for chip in chips)


def test_football_searches_read_as_they_did_before():
    """"defender" is a football position and a table tennis style. Unless the scout names table
    tennis, it stays the football position it always was."""
    assert parse_query("defender under 17")[0] == {"max_age": 17.0, "position": "CB"}
    assert parse_query("football striker u17")[0] == {
        "max_age": 17.0,
        "sport": "football",
        "position": "ST",
    }


def test_a_style_only_one_sport_has_says_so_in_its_chip():
    _, chips, _ = parse_query("chopper")
    assert [c["label"] for c in chips] == [
        "playing style: chopper",
        "sport: table tennis (from the playing style)",
    ]


def test_boys_and_girls_together_filter_on_neither():
    filters, chips, _ = parse_query("boys and girls")
    assert "sex" not in filters
    assert chips == [{"label": "gender: boys and girls, both kept", "understood": False}]


def test_a_man_is_not_found_inside_a_woman():
    """Whole words only: "women" is not "men", "female" is not "male"."""
    assert parse_query("women")[0] == {"sex": "female"}
    assert parse_query("female")[0] == {"sex": "female"}


def test_playing_styles_come_from_the_sport_module():
    """No table tennis word is hard-coded in the search: a style added to the module is
    searchable without touching the search code."""
    module = sports.registry()["table_tennis"]
    for role in module.roles:
        filters, _, _ = parse_query(f"table tennis {role.replace('_', ' ')}")
        assert filters["position"] == role


# ---------------------------------------------------------------------------
# Optional fields in a ratio
# ---------------------------------------------------------------------------


def test_a_ratio_uses_only_the_matches_that_record_its_fields():
    """Unforced errors are optional. A match without them is not a match with none."""
    period = sports.registry()["table_tennis"].periods["table_tennis.match.v1"]
    rows = [
        {"best_of": 5, "sets_won": 3, "sets_lost": 1, "points_won": 44, "points_lost": 30,
         "unforced_errors": 8},
        {"best_of": 5, "sets_won": 3, "sets_lost": 0, "points_won": 33, "points_lost": 20},
    ]
    stats = {s["key"]: s for s in sports.summarise(period, rows)}
    assert stats["unforced_errors_per_set"]["value"] == pytest.approx(8 / 4)
    assert stats["unforced_errors_per_set"]["basis"] == 1
    # A statistic every match records still counts every match.
    assert stats["set_win_rate"]["basis"] == 2
    # Nothing records service winners, so there is no figure rather than a zero.
    assert "service_winners_per_set" not in stats


# ---------------------------------------------------------------------------
# Through the search endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def table_tennis_squad(db):
    """Three table tennis players with six matches each, built so the extremes are certain
    whatever else the database holds: one who never errs and serves winners all day, one who
    errs constantly and never wins a point on serve, and a girl in between."""
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player
    from tests.conftest import TODAY, grant_analytics

    def player(name, sex, style, errors, service_winners):
        row = Player(
            id=uuid.uuid4(),
            full_name=name,
            date_of_birth=TODAY - timedelta(days=int(15.5 * 365.25)),
            sex=sex,
            nationality=["EG"],
            is_egypt_eligible=True,
            primary_sport="table_tennis",
            position=style,
            is_minor=True,
            status="active",
        )
        db.add(row)
        db.flush()
        grant_analytics(db, row)
        for week in range(6):
            db.add(
                PerformanceEntry(
                    player_id=row.id,
                    sport="table_tennis",
                    period_type="match",
                    period_start=TODAY - timedelta(weeks=week + 1),
                    metrics={
                        "best_of": 5, "sets_won": 3, "sets_lost": 1,
                        "points_won": 44, "points_lost": 33,
                        "unforced_errors": errors, "service_winners": service_winners,
                    },
                    schema_ref="table_tennis.match.v1",
                    source="coach_logged",
                    is_validated=True,
                )
            )
        return row

    squad = {
        "steady": player("Steady Chopper", "male", "chopper", 0, 30),
        "erratic": player("Erratic Attacker", "male", "attacker", 60, 0),
        "girl": player("Middle Defender", "female", "defender", 10, 4),
    }
    # A percentile needs at least cohort.MIN_COHORT players, and the test database may hold no
    # other table tennis players, so the group is filled out with middling ones.
    for i in range(8):
        player(f"Middling Player {i}", "male", "all_round", 10 + i, 3 + i)
    db.flush()
    from app.services import concept_filter

    concept_filter.reset_cache()
    return squad


def _search(client, auth, query: str) -> dict:
    return client.post(
        "/search",
        json={"query": query, "limit": 200, "includeMinors": True},
        headers=auth("admin"),
    ).json()


def _ids(body) -> set[str]:
    return {r["player"]["id"] for r in body["results"]}


def test_table_tennis_finds_table_tennis_players_only(client, auth, table_tennis_squad):
    body = _search(client, auth, "table tennis")
    assert {str(p.id) for p in table_tennis_squad.values()} <= _ids(body)
    assert {r["player"]["primarySport"] for r in body["results"]} == {"table_tennis"}


def test_a_playing_style_filters_on_it(client, auth, table_tennis_squad):
    body = _search(client, auth, "chopper")
    assert str(table_tennis_squad["steady"].id) in _ids(body)
    assert {r["player"]["position"] for r in body["results"]} == {"chopper"}


def test_girls_table_tennis_finds_girls(client, auth, table_tennis_squad):
    body = _search(client, auth, "girls table tennis")
    assert str(table_tennis_squad["girl"].id) in _ids(body)
    assert {r["player"]["sex"] for r in body["results"]} == {"female"}


def test_few_unforced_errors_means_the_lowest_rate(client, auth, table_tennis_squad):
    body = _search(client, auth, "few unforced errors")
    assert str(table_tennis_squad["steady"].id) in _ids(body)
    assert str(table_tennis_squad["erratic"].id) not in _ids(body)
    assert [c["label"] for c in body["parsed"]["chips"]][0].startswith(
        "unforced errors per set: best quarter"
    )


def test_a_strong_serve_means_the_most_service_winners(client, auth, table_tennis_squad):
    body = _search(client, auth, "strong serve")
    assert str(table_tennis_squad["steady"].id) in _ids(body)
    assert str(table_tennis_squad["erratic"].id) not in _ids(body)


def test_the_screens_default_tier_does_not_hide_table_tennis(client, auth, table_tennis_squad):
    """The search screen starts on the "youth" tier. Tiers are football's, so a table tennis
    player has none, and that default used to hide every one of them."""
    body = client.post(
        "/search",
        json={"query": "table tennis", "tier": "youth", "limit": 200, "includeMinors": True},
        headers=auth("admin"),
    ).json()
    assert {str(p.id) for p in table_tennis_squad.values()} <= _ids(body)
    football = client.post(
        "/search",
        json={"query": "football", "tier": "youth", "limit": 200, "includeMinors": True},
        headers=auth("admin"),
    ).json()
    assert {r["player"]["tier"] for r in football["results"]} == {"youth"}
