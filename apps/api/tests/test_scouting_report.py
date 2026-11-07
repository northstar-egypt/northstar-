"""GET /players/{id}/scouting-report (app/services/scouting_report.py, running ml/pro/report.py).

On the team gap tests' own small league (nine clubs, a striker each, the ninth the most
dangerous): a report with a verdict and its evidence for an adult, and a reason instead of a
report for a child, a player without analytics consent, or one with no league season.
"""

from __future__ import annotations

from tests.conftest import _add_player, withdraw_analytics
from tests.test_gaps import _season, league  # noqa: F401  (league is a fixture)


def _get(client, auth, player, who="scout"):
    return client.get(f"/players/{player.id}/scouting-report", headers=auth(who))


def test_an_adult_gets_a_verdict_with_its_evidence(client, auth, league):  # noqa: F811
    _, strikers = league
    body = _get(client, auth, strikers[8]).json()
    report = body["report"]
    assert body["note"] is None and report["groupLabel"] == "Strikers"
    assert report["recommendation"] in ("Shortlist", "Monitor", "Not now")
    assert report["levelGrade"] in ("A", "B", "C", "D") and report["confidence"] == "high"
    assert report["population"] == 8 and report["minutes"] == 2000
    threat = next(a for a in report["areas"] if a["key"] == "goal_threat")
    assert threat["graded"] and threat["grade"] == "A"
    npxg = next(e for e in report["strengths"] if e["key"] == "npxg_per_90")
    assert npxg["percentile"] >= 90 and npxg["unit"] == "per 90" and npxg["median"] > 0
    assert report["notInData"] and report["wouldChange"]
    assert report["finishing"]["verdict"] in ("above", "below", "in line", "too few chances")


def test_the_least_dangerous_striker_is_graded_lower(client, auth, league):  # noqa: F811
    _, strikers = league
    best = _get(client, auth, strikers[8]).json()["report"]
    worst = _get(client, auth, strikers[0]).json()["report"]
    assert worst["level"] < best["level"]
    assert any(e["key"] == "npxg_per_90" for e in worst["weaknesses"])


def test_a_child_gets_a_reason_not_a_report(client, auth, db, league):  # noqa: F811
    clubs, _ = league
    kid = _add_player(db, clubs[0], "Report Kid", age=16, position="ST", shots=1, n_matches=0)
    _season(db, kid, clubs[0], npxg=9.0)
    db.flush()
    body = _get(client, auth, kid).json()
    assert body["report"] is None and "adult players" in body["note"]


def test_without_analytics_consent_no_report_is_written(client, auth, db, league):  # noqa: F811
    _, strikers = league
    withdraw_analytics(db, strikers[4])
    db.flush()
    body = _get(client, auth, strikers[4]).json()
    assert body["report"] is None and "consent" in body["note"]


def test_a_player_does_not_get_the_report_on_themselves(client, auth, world):
    body = _get(client, auth, world["players"]["adult_a"], who="player_self").json()
    assert body["report"] is None and "scouts and staff" in body["note"]


def test_a_player_with_no_league_season_is_told_so(client, auth, world):
    body = _get(client, auth, world["players"]["adult_a"]).json()
    assert body["report"] is None and body["note"] == "No league seasons on record."


def test_a_player_the_caller_may_not_see_is_404(client, auth, world):
    assert _get(client, auth, world["players"]["minor_no_a"]).status_code == 404
