"""Details on tagged events, and the rates read from them (decision 0007).

Details are the sport module's: a tag carries only the details its type lists, with their
values, and a detail recorded only for some outcomes (where in the goal: goals and saves) is
refused on the others. The analysis counts only players with analytics consent, names only
players the caller may open, and shows no rate from too few attempts.

The test database also holds the seeded dataset, so the analysis tests measure what a test's
own tags add, not absolute totals.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from app import sports
from app.services import event_analysis
from tests.conftest import withdraw_analytics

TODAY = date.today()
MATCH = TODAY - timedelta(days=3)


def _tag(client, auth, player, who="coach_a", **fields):
    body = {
        "playerId": str(player.id), "matchDate": MATCH.isoformat(), "matchLabel": "vs Test FC",
        "eventType": "shot", "outcome": "goal", "x": 88.0, "y": 47.5, "videoSeconds": 754.2,
    }
    body.update(fields)
    return client.post("/events", json=body, headers=auth(who))


def _shots(db, player, goals: int, misses: int, details: dict | None = None, coach=None):
    from app.models.match_event import MatchEvent

    for i in range(goals + misses):
        db.add(MatchEvent(
            player_id=player.id, sport="football", match_date=MATCH, match_label="vs Test FC",
            event_type="shot", outcome="goal" if i < goals else "off_target", x=85.0, y=50.0,
            source="coach_tagged", tagged_by=coach.id if coach else None, details=details,
        ))
    db.flush()


def _finishing(client, auth, who="federation", **params):
    response = client.get("/analysis/football/finishing", params=params, headers=auth(who))
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The module
# ---------------------------------------------------------------------------


def _football_with(tmp_path, change):
    raw = json.loads(sports.default_modules_dir().joinpath("football.json").read_text(encoding="utf-8"))
    change(raw)
    path = tmp_path / "football.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "change, problem",
    [
        (lambda raw: raw["events"]["types"]["shot"]["details"]["placement"].update(grid=[2, 2]),
         "grid"),
        (lambda raw: raw["events"]["types"]["shot"]["details"]["placement"].update(outcomes=["own_goal"]),
         "own_goal"),
        (lambda raw: raw["events"]["analyses"]["finishing"].update(success=["shot.screamer"]),
         "screamer"),
        (lambda raw: raw["events"]["analyses"]["finishing"].update(events=["header"]),
         "event types"),
    ],
)
def test_a_module_with_a_broken_detail_or_analysis_does_not_load(tmp_path, change, problem):
    with pytest.raises(sports.ModuleError, match=problem):
        sports.load_module(_football_with(tmp_path, change))


def test_the_sport_modules_list_their_details_and_analyses(client, auth):
    body = {s["sport"]: s for s in client.get("/sports", headers=auth("coach_a")).json()}
    shot = next(e for e in body["football"]["events"] if e["key"] == "shot")
    placement = next(d for d in shot["details"] if d["key"] == "placement")
    assert placement["grid"] == [2, 3] and placement["outcomes"] == ["goal", "on_target"]
    assert [a["key"] for a in body["football"]["analyses"]] == ["finishing"]
    point = next(e for e in body["table_tennis"]["events"] if e["key"] == "point_won")
    assert [d["key"] for d in point["details"]] == ["stroke"]


# ---------------------------------------------------------------------------
# Tagging with details
# ---------------------------------------------------------------------------


def test_a_tag_keeps_its_details(client, auth, world):
    """Detail keys are the module's, as written there: the request's camelCase does not reach
    inside `details`, so "keeperDistance" is no detail of a shot."""
    camel = _tag(client, auth, world["players"]["adult_a"], details={"keeperDistance": "over_6"})
    assert camel.status_code == 422
    response = _tag(client, auth, world["players"]["adult_a"], details={
        "placement": "bottom_left", "technique": "placed", "situation": "one_on_one",
        "keeper_distance": "from_3_to_6",
    })
    assert response.status_code == 201, response.text
    assert response.json()["details"]["placement"] == "bottom_left"


@pytest.mark.parametrize(
    "outcome, details, problem",
    [
        ("goal", {"placement": "in_the_net"}, "is not a where in the goal"),
        ("goal", {"spin": "lots"}, "has no detail"),
        ("off_target", {"placement": "top_left"}, "only recorded for goal or saved"),
    ],
)
def test_details_the_module_does_not_allow_are_refused(client, auth, world, outcome, details, problem):
    response = _tag(client, auth, world["players"]["adult_a"], outcome=outcome, details=details)
    assert response.status_code == 422
    assert problem in " ".join(response.json()["detail"])


def test_details_are_added_after_the_outcome_by_who_may_tag(client, auth, db, world):
    """The tagging screen saves a tag at its outcome; the coach adds the details after."""
    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    event_id = _tag(client, auth, world["players"]["adult_a"]).json()["id"]
    put = lambda who, details: client.put(  # noqa: E731
        f"/events/{event_id}/details", json={"details": details}, headers=auth(who)
    )
    assert put("scout", {"technique": "chip"}).status_code == 404
    assert put("coach_a", {"technique": "bicycle"}).status_code == 422
    saved = put("coach_a", {"technique": "chip", "placement": "top_middle"})
    assert saved.status_code == 200 and saved.json()["details"] == {"technique": "chip", "placement": "top_middle"}
    assert db.execute(
        select(AuditLog).where(AuditLog.action == "match_event.details")
    ).scalars().first() is not None


def test_a_table_tennis_point_takes_its_own_detail(client, auth, db, world):
    player = world["players"]["adult_a"]
    player.primary_sport = "table_tennis"
    player.position = "attacker"
    db.flush()
    ok = _tag(client, auth, player, eventType="point_won", outcome="winner", details={"stroke": "backhand"})
    assert ok.status_code == 201, ok.text
    bad = _tag(client, auth, player, eventType="point_won", outcome="winner", details={"technique": "chip"})
    assert bad.status_code == 422


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------


def test_a_players_own_rate_and_the_breakdown_count_their_tags(client, auth, db, world):
    adult_a = world["players"]["adult_a"]
    before = _finishing(client, auth)
    _shots(db, adult_a, goals=4, misses=8, details={"situation": "one_on_one"},
           coach=world["users"]["coach_a"])
    after = _finishing(client, auth, player=str(adult_a.id))

    assert after["attempts"] - before["attempts"] == 12
    assert after["successes"] - before["successes"] == 4
    assert after["player"] == {
        "playerId": str(adult_a.id), "fullName": "Adult A", "attempts": 12, "successes": 4,
        "rate": round(4 / 12, 3), "percentile": after["player"]["percentile"],
    }
    one_on_one = lambda body: next(  # noqa: E731
        v for b in body["breakdown"] if b["key"] == "situation" for v in b["values"]
        if v["key"] == "one_on_one"
    )
    assert one_on_one(after)["attempts"] - one_on_one(before)["attempts"] == 12


def test_a_player_without_analytics_consent_is_not_counted(client, auth, db, world):
    adult_a = world["players"]["adult_a"]
    _shots(db, adult_a, goals=3, misses=9)
    counted = _finishing(client, auth)
    withdraw_analytics(db, adult_a)
    after = _finishing(client, auth, player=str(adult_a.id))
    assert counted["attempts"] - after["attempts"] == 12
    assert after["player"] is None


def test_a_qualifying_player_is_counted_but_not_named_to_a_coach_of_another_club(client, auth, db, world):
    adult_a = world["players"]["adult_a"]
    _shots(db, adult_a, goals=12, misses=0)  # a perfect rate, so first among the leaders
    federation = _finishing(client, auth)
    coach_b = _finishing(client, auth, who="coach_b")
    assert federation["leaders"][0]["playerId"] == str(adult_a.id)
    assert str(adult_a.id) not in {row["playerId"] for row in coach_b["leaders"]}
    assert coach_b["qualifying"] == federation["qualifying"]


def test_no_rate_from_too_few_attempts():
    assert event_analysis._rate(2, 3) is None
    assert event_analysis._rate(5, event_analysis.MIN_FOR_A_RATE) == round(5 / event_analysis.MIN_FOR_A_RATE, 3)


def test_generated_tags_are_counted_and_said(client, auth, db, world):
    adult_a = world["players"]["adult_a"]
    before = _finishing(client, auth)
    _shots(db, adult_a, goals=1, misses=1)  # no tagger: made by the generator
    after = _finishing(client, auth)
    assert after["generated"] - before["generated"] == 2
    assert "synthetic data generator" in after["note"]


@pytest.mark.parametrize(
    "params, problem",
    [({"group": "libero"}, "position group"), ({"gender": "female"}, "does not register"),
     ({"ageFrom": 16, "ageTo": 12}, "youngest age")],
)
def test_a_question_the_analysis_cannot_answer_says_why(client, auth, params, problem):
    response = client.get("/analysis/football/finishing", params=params, headers=auth("scout"))
    assert response.status_code == 400 and problem in response.json()["detail"]
    assert client.get("/analysis/football/nonsense", headers=auth("scout")).status_code == 400
