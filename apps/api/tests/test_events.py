"""Match events tagged from video (app/services/events.py, routers/events.py).

Who may tag is who may log for the player; who may read is who may open the player; what may
be tagged is what the sport module lists.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

TODAY = date.today()
MATCH = TODAY - timedelta(days=3)


def _tag(client, auth, player, who="coach_a", **fields):
    body = {
        "playerId": str(player.id), "matchDate": MATCH.isoformat(), "matchLabel": "vs Test FC",
        "eventType": "shot", "outcome": "goal", "x": 88.0, "y": 47.5, "videoSeconds": 754.2,
    }
    body.update(fields)
    return client.post("/events", json=body, headers=auth(who))


def test_a_coach_tags_their_own_player_and_the_tag_is_audited(client, auth, db, world):
    from app.models.audit_log import AuditLog

    player = world["players"]["adult_a"]
    response = _tag(client, auth, player)
    assert response.status_code == 201, response.text
    event = response.json()
    assert (event["eventType"], event["outcome"], event["x"], event["videoSeconds"]) == (
        "shot", "goal", 88.0, 754.2,
    )
    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "match_event.create")
        .where(AuditLog.entity_id == player.id)
    ).scalars().all()
    assert any(a.event_metadata["match_event_id"] == event["id"] for a in audit)


@pytest.mark.parametrize(
    "who, player_key, status",
    [
        ("coach_b", "adult_a", 404),   # another club's player: not visible to that coach
        ("scout", "adult_a", 403),     # visible, but a scout does not log
        ("federation", "adult_a", 403),
        ("player_self", "adult_a", 403),
    ],
)
def test_only_those_who_may_log_for_the_player_may_tag(client, auth, world, who, player_key, status):
    assert _tag(client, auth, world["players"][player_key], who=who).status_code == status


@pytest.mark.parametrize(
    "fields, problem",
    [
        ({"eventType": "dribble"}, "is not an event type"),
        ({"outcome": "complete"}, "is not an outcome of a shot"),
        ({"matchDate": (TODAY + timedelta(days=1)).isoformat()}, "in the future"),
        ({"x": 120.0}, "from 0 to 100"),
        ({"y": None}, "both coordinates"),
        ({"videoSeconds": -3}, "cannot be negative"),
    ],
)
def test_a_tag_the_module_does_not_allow_is_refused_with_the_reason(client, auth, world, fields, problem):
    response = _tag(client, auth, world["players"]["adult_a"], **fields)
    assert response.status_code == 422
    assert any(problem in p for p in response.json()["detail"])


def test_the_match_list_sets_tags_beside_the_logged_totals(client, auth, db, world):
    from app.models.performance_entry import PerformanceEntry

    player = world["players"]["adult_a"]
    db.add(PerformanceEntry(
        id=uuid.uuid4(), player_id=player.id, sport="football", period_type="match",
        period_start=MATCH, schema_ref="football.match.v1", source="coach_logged",
        is_validated=True,
        metrics={"minutes_played": 90, "shots": 3, "shots_on_target": 2, "goals": 1,
                 "assists": 0, "key_passes": 1, "passes_attempted": 30, "passes_completed": 25,
                 "tackles": 2, "distance_km": 10.0, "yellow_cards": 0, "red_cards": 0},
    ))
    db.flush()
    _tag(client, auth, player)  # a goal
    _tag(client, auth, player, outcome="off_target", x=70.0, y=20.0, videoSeconds=100.0)
    _tag(client, auth, player, eventType="pass", outcome="key_pass", x=60.0, y=50.0)

    body = client.get(
        "/events", params={"matchDate": MATCH.isoformat(), "matchLabel": "vs Test FC"},
        headers=auth("coach_a"),
    ).json()
    assert len(body["events"]) == 3
    # Ordered by the time in the video.
    assert body["events"][0]["videoSeconds"] == 100.0
    row = next(p for p in body["players"] if p["playerId"] == str(player.id))
    assert row["tagged"] == {"shots": 2, "shots_on_target": 1, "goals": 1,
                             "passes_attempted": 1, "passes_completed": 1, "key_passes": 1}
    assert row["logged"]["shots"] == 3 and row["logged"]["passes_attempted"] == 30


def test_another_club_never_sees_a_clubs_match_list(client, auth, world):
    _tag(client, auth, world["players"]["adult_a"])
    body = client.get(
        "/events", params={"matchDate": MATCH.isoformat(), "matchLabel": "vs Test FC"},
        headers=auth("coach_b"),
    ).json()
    assert body["events"] == []


def test_untagging_is_for_those_who_may_tag(client, auth, db, world):
    from app.models.audit_log import AuditLog

    event_id = _tag(client, auth, world["players"]["adult_a"]).json()["id"]
    assert client.delete(f"/events/{event_id}", headers=auth("coach_b")).status_code == 404
    assert client.delete(f"/events/{event_id}", headers=auth("scout")).status_code == 404
    assert client.delete(f"/events/{event_id}", headers=auth("coach_a")).status_code == 204
    assert client.delete(f"/events/{event_id}", headers=auth("coach_a")).status_code == 404
    assert db.execute(
        select(AuditLog).where(AuditLog.action == "match_event.delete")
    ).scalars().first() is not None


def test_a_players_events_are_for_whoever_may_open_them(client, auth, world):
    player = world["players"]["adult_a"]
    _tag(client, auth, player)
    _tag(client, auth, player, eventType="tackle", outcome="won", x=30.0, y=40.0)

    shots = client.get(f"/players/{player.id}/events", params={"type": "shot"}, headers=auth("scout")).json()
    assert [e["eventType"] for e in shots["events"]] == ["shot"]
    assert shots["matches"] == 1 and shots["counts"] == {"shot.goal": 1}
    assert "Tagged by coaches from match video" in shots["note"]

    blocked = world["players"]["minor_no_a"]
    assert client.get(f"/players/{blocked.id}/events", headers=auth("scout")).status_code == 404


def test_the_sport_modules_say_what_can_be_tagged(client, auth):
    body = {s["sport"]: s for s in client.get("/sports", headers=auth("coach_a")).json()}
    shot = next(e for e in body["football"]["events"] if e["key"] == "shot")
    assert shot["shortcut"] == "s" and [o["key"] for o in shot["outcomes"]][0] == "goal"
    assert {e["key"] for e in body["table_tennis"]["events"]} == {"point_won", "point_lost"}


def test_a_module_whose_counts_name_no_match_total_does_not_load(tmp_path):
    import json

    from app import sports

    raw = json.loads(sports.default_modules_dir().joinpath("football.json").read_text(encoding="utf-8"))
    raw["events"]["types"]["shot"]["outcomes"]["goal"]["counts"].append("xg")
    bad = tmp_path / "football.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(sports.ModuleError, match="xg"):
        sports.load_module(bad)


def test_a_table_tennis_point_is_tagged_with_the_modules_own_types(client, auth, db, world):
    """The same table and endpoints, another sport's event types: the engine knows no sport."""
    from app.models.performance_entry import PerformanceEntry

    player = world["players"]["adult_a"]
    player.primary_sport = "table_tennis"
    player.position = "attacker"
    db.add(PerformanceEntry(
        id=uuid.uuid4(), player_id=player.id, sport="table_tennis", period_type="match",
        period_start=MATCH, schema_ref="table_tennis.match.v1", source="coach_logged",
        is_validated=True,
        metrics={"best_of": 5, "sets_won": 3, "sets_lost": 1, "points_won": 44,
                 "points_lost": 35, "service_winners": 3, "unforced_errors": 6},
    ))
    db.flush()
    assert _tag(client, auth, player, eventType="shot", outcome="goal").status_code == 422
    won = _tag(client, auth, player, eventType="point_won", outcome="service_winner", x=80.0, y=30.0)
    assert won.status_code == 201, won.text
    _tag(client, auth, player, eventType="point_lost", outcome="unforced_error", x=50.0, y=50.0)

    body = client.get(
        "/events", params={"matchDate": MATCH.isoformat(), "matchLabel": "vs Test FC"},
        headers=auth("coach_a"),
    ).json()
    row = next(p for p in body["players"] if p["playerId"] == str(player.id))
    assert row["tagged"] == {"points_won": 1, "service_winners": 1, "points_lost": 1,
                             "unforced_errors": 1}
    assert row["logged"]["points_won"] == 44
