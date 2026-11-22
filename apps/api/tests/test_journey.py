"""Parts 6 to 9 of "find the next <pro>" (app/services/journey.py).

What is pinned: who may record a drill, that XP is counted exactly by its stated rule, that the
leaderboard lists only players the caller may see with analytics consent, that only scouts and
federation staff may watch, and that an alert fires when the match has jumped since last seen.
"""

from __future__ import annotations

from sqlalchemy import select

from tests.test_next_pro import league  # noqa: F401  (fixture)


def _drill(client, auth, who, player):
    return client.post(f"/players/{player.id}/drills", headers=auth(who),
                       json={"statistic": "shots", "drill": "Shoot on sight"})


def test_the_coach_may_record_a_drill_and_a_scout_may_not(client, auth, world):
    kid = world["players"]["minor_ok_a"]
    assert _drill(client, auth, "coach_a", kid).status_code == 201
    assert _drill(client, auth, "scout", kid).status_code == 403
    assert _drill(client, auth, "coach_b", kid).status_code == 404  # not their academy


def test_xp_is_one_per_ten_minutes_and_twenty_per_drill(client, auth, league):  # noqa: F811
    kid = league["players"]["minor_ok_a"]  # six 90-minute matches in the fixture
    _drill(client, auth, "coach_a", kid)
    body = client.get(f"/players/{kid.id}/journey", headers=auth("coach_a")).json()
    assert body["minutes"] == 540 and body["drills"] == 1
    assert body["xp"] == 54 + 20
    assert body["level"]["name"] == "Academy Rookie"
    assert {b["key"]: b["earned"] for b in body["badges"]}["first_drill"] is True


def test_a_pro_has_no_journey(client, auth, world):
    response = client.get(f"/players/{world['players']['adult_a'].id}/journey", headers=auth("federation"))
    assert response.status_code == 404


def test_the_weekly_report_counts_this_weeks_drills(client, auth, world):
    kid = world["players"]["minor_ok_a"]
    _drill(client, auth, "coach_a", kid)
    body = client.get(f"/players/{kid.id}/weekly-report", headers=auth("coach_a")).json()
    assert body["week"]["drills"] == 1 and body["week"]["xp"] >= 20


def test_the_leaderboard_hides_what_the_caller_may_not_see(client, auth, world):
    ok, blocked = world["players"]["minor_ok_a"], world["players"]["minor_no_a"]
    _drill(client, auth, "coach_a", ok)
    _drill(client, auth, "coach_a", blocked)
    coach = {r["fullName"] for r in client.get("/leaderboard", headers=auth("coach_a")).json()["items"]}
    assert {"Minor Consented A", "Minor Blocked A"} <= coach
    scout = {r["fullName"] for r in client.get("/leaderboard", headers=auth("scout")).json()["items"]}
    assert "Minor Blocked A" not in scout
    other = {r["fullName"] for r in client.get("/leaderboard", headers=auth("coach_b")).json()["items"]}
    assert "Minor Consented A" not in other


def test_the_leaderboard_leaves_out_a_player_without_analytics_consent(client, auth, db, world):
    from tests.conftest import withdraw_analytics

    kid = world["players"]["minor_ok_a"]
    _drill(client, auth, "coach_a", kid)
    withdraw_analytics(db, kid)
    names = {r["fullName"] for r in client.get("/leaderboard", headers=auth("coach_a")).json()["items"]}
    assert "Minor Consented A" not in names


def test_only_scouts_and_federation_may_watch(client, auth, world):
    kid, pro = world["players"]["minor_ok_a"], world["players"]["adult_a"]
    assert client.put(f"/players/{kid.id}/watch/{pro.id}", headers=auth("coach_a")).status_code == 403
    assert client.put(f"/players/{kid.id}/watch/{pro.id}", headers=auth("scout")).status_code == 200
    assert client.get("/alerts", headers=auth("coach_a")).status_code == 403


def test_an_alert_fires_when_the_match_has_jumped(client, auth, db, league):  # noqa: F811
    from app.models.match_watch import MatchWatch

    kid, pro = league["players"]["minor_ok_a"], league["players"]["adult_a"]
    now = client.put(f"/players/{kid.id}/watch/{pro.id}", headers=auth("scout")).json()["percent"]
    assert now is not None
    body = client.get("/alerts", headers=auth("scout")).json()
    assert [i["alert"] for i in body["items"]] == [False]

    row = db.execute(select(MatchWatch).where(MatchWatch.player_id == kid.id)).scalar_one()
    row.last_percent = now - 10  # as if the scout last looked when the match was lower
    db.flush()
    assert [i["alert"] for i in client.get("/alerts", headers=auth("scout")).json()["items"]] == [True]
    client.post("/alerts/seen", headers=auth("scout"))
    assert [i["alert"] for i in client.get("/alerts", headers=auth("scout")).json()["items"]] == [False]


def test_a_scout_never_watches_a_withheld_minor(client, auth, world):
    kid, pro = world["players"]["minor_no_a"], world["players"]["adult_a"]
    assert client.put(f"/players/{kid.id}/watch/{pro.id}", headers=auth("scout")).status_code == 404
