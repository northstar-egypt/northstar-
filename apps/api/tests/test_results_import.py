"""Table tennis results import (app/services/results_import.py, routers/results.py).

Every name and score here is made up; real results never enter the repository.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.services import results_import as ri

TODAY = date.today()
PLAYED = (TODAY - timedelta(days=20)).isoformat()
HEADER = "date,event,player_a,player_b,games\n"


def _tt_player(db, org, name, *, sex="male", age=17.0):
    from app.models.player import Player
    from app.models.player_organization import PlayerOrganization

    player = Player(
        id=uuid.uuid4(), full_name=name, sex=sex, nationality=["EG"], is_egypt_eligible=True,
        date_of_birth=TODAY - timedelta(days=int(age * 365.25)), primary_sport="table_tennis",
        position="attacker", is_minor=age < 18, status="active",
    )
    db.add(player)
    db.flush()
    db.add(PlayerOrganization(
        id=uuid.uuid4(), player_id=player.id, organization_id=org.id, role="player",
        start_date=TODAY - timedelta(days=400), end_date=None,
    ))
    db.flush()
    return player


@pytest.fixture
def pair(db, world):
    """Two registered table tennis players with made-up names, one written in Arabic."""
    return (
        _tt_player(db, world["orgs"]["a"], "أحمد السيد"),
        _tt_player(db, world["orgs"]["b"], "Karim Zorgani Test"),
    )


def _post(client, auth, path, csv, who="federation"):
    return client.post(path, json={"csv": csv}, headers=auth(who))


@pytest.mark.parametrize(
    "games, problem",
    [
        ("11-7, 9-11, 11-5", None),
        ("12-10 11-13 11-9", None),
        ("11-10, 11-5", "not a finished game"),
        ("13-10", "not a finished game"),
        ("eleven to seven", "Could not read the scores"),
    ],
)
def test_game_scores_must_be_finished_games(games, problem):
    _, problems = ri.parse_games(games)
    assert (problem is None and not problems) or any(problem in p for p in problems)


def test_a_match_record_is_worked_out_from_the_scores():
    metrics, problems = ri.match_metrics([(11, 7), (9, 11), (11, 5), (11, 8)], None)
    assert not problems
    assert metrics == {"best_of": 5, "sets_won": 3, "sets_lost": 1, "points_won": 42, "points_lost": 31}
    assert ri.mirrored(metrics)["sets_won"] == 1


@pytest.mark.parametrize(
    "games, best_of, problem",
    [
        ([(11, 7), (11, 5), (11, 8), (2, 11)], 5, "more games follow"),
        ([(11, 7), (9, 11)], None, "Not a finished match"),
        ([(11, 7), (11, 5)], 5, "Not a finished best of 5"),
    ],
)
def test_an_unfinished_or_overlong_match_is_refused(games, best_of, problem):
    metrics, problems = ri.match_metrics(games, best_of)
    assert metrics is None and any(problem in p for p in problems)


def test_both_registered_get_mirrored_records_and_a_second_import_is_skipped(
    client, auth, db, pair
):
    from app.models.audit_log import AuditLog
    from app.models.performance_entry import PerformanceEntry

    a, b = pair
    # The published name is in Latin capitals; the player is registered in Arabic.
    csv = HEADER + f"{PLAYED},Test Open,ELSAYED Ahmed,{b.full_name},\"11-7, 9-11, 11-5, 11-8\"\n"
    preview = _post(client, auth, "/results/import/preview", csv).json()
    assert preview["counts"] == {"ready": 1, "duplicate": 0, "rejected": 0}
    assert preview["rows"][0]["score"].startswith("3-1 (42-31 points), best of 5")

    done = _post(client, auth, "/results/import", csv).json()
    assert done["saved"] and done["recordsWritten"] == 2
    rows = db.execute(
        select(PerformanceEntry).where(PerformanceEntry.player_id.in_([a.id, b.id]))
    ).scalars().all()
    by_player = {r.player_id: r for r in rows}
    assert by_player[a.id].opponent_player_id == b.id and by_player[a.id].metrics["sets_won"] == 3
    assert by_player[b.id].opponent_player_id == a.id and by_player[b.id].metrics["sets_won"] == 1
    assert by_player[a.id].source == "import"
    assert db.execute(select(AuditLog).where(AuditLog.action == "results.import")).scalars().first()

    again = _post(client, auth, "/results/import", csv).json()
    assert again["counts"]["duplicate"] == 1 and again["recordsWritten"] == 0


def test_an_unregistered_opponent_leaves_no_trace(client, auth, db, pair):
    from app.models.performance_entry import PerformanceEntry

    a, _ = pair
    csv = HEADER + f"{PLAYED},Test Open,{a.full_name},Nobody Unregisteredson,\"11-3 11-4 11-5\"\n"
    body = _post(client, auth, "/results/import", csv).json()
    assert body["recordsWritten"] == 1
    assert any("not on NorthStar" in w for w in body["rows"][0]["warnings"])
    entry = db.execute(select(PerformanceEntry).where(PerformanceEntry.player_id == a.id)).scalar_one()
    assert entry.opponent_player_id is None
    assert "Unregisteredson" not in str(entry.metrics)


def test_rows_that_cannot_be_saved_say_why(client, auth, db, world, pair):
    a, b = pair
    woman = _tt_player(db, world["orgs"]["a"], "Test Woman Player", sex="female")
    _tt_player(db, world["orgs"]["a"], "Karim Zorgani Second")
    csv = HEADER + "".join([
        f"{PLAYED},X,Nobody One,Nobody Two,11-3 11-4\n",                     # neither registered
        f"{PLAYED},X,{a.full_name},{woman.full_name},11-3 11-4\n",           # man against woman
        f"{PLAYED},X,{a.full_name},Karim Zorgani,11-3 11-4\n",               # ambiguous name
        f"{(TODAY + timedelta(days=3)).isoformat()},X,{a.full_name},{b.full_name},11-3 11-4\n",
        f"{PLAYED},=HYPERLINK(1),{a.full_name},{b.full_name},11-3 11-4\n",   # formula
    ])
    rows = _post(client, auth, "/results/import/preview", csv).json()["rows"]
    assert [r["status"] for r in rows] == ["rejected"] * 5
    reasons = [" ".join(r["problems"]) for r in rows]
    assert "Neither player is registered" in reasons[0]
    assert "Men and women are not compared" in reasons[1]
    assert "matches 2 registered players" in reasons[2]
    assert "in the future" in reasons[3]
    assert "formula" in reasons[4]


def test_an_id_settles_an_ambiguous_name(client, auth, db, world, pair):
    a, b = pair
    _tt_player(db, world["orgs"]["a"], "Karim Zorgani Second")
    csv = ("date,player_a,player_b,games,player_b_id\n"
           f"{PLAYED},{a.full_name},Karim Zorgani,11-3 11-4,{b.id}\n")
    assert _post(client, auth, "/results/import/preview", csv).json()["counts"]["ready"] == 1


@pytest.mark.parametrize("who", ["coach_a", "scout", "player_self"])
def test_only_federation_staff_and_admins_import(client, auth, who):
    csv = HEADER + f"{PLAYED},X,A,B,11-3 11-4\n"
    assert _post(client, auth, "/results/import/preview", csv, who=who).status_code == 403


def test_a_file_with_the_wrong_columns_saves_nothing(client, auth):
    response = _post(client, auth, "/results/import", "when,who,score\n2026-01-01,a,11-3\n")
    assert response.status_code == 422
    assert "Missing required column" in str(response.json()["detail"])
