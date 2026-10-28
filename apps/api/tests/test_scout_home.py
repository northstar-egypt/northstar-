"""The scout's home and shortlist (app/routers/scout.py, app/services/scout_home.py).

A shortlist is the user's own, saving a player grants no access, and a saved player who can no
longer be seen is counted, never shown.
"""

from __future__ import annotations

from tests.conftest import _add_player


def _home(client, auth, who="scout"):
    return client.get("/home/scout", headers=auth(who))


def _save(client, auth, player, note="", who="scout"):
    return client.put(f"/shortlist/{player.id}", json={"note": note}, headers=auth(who))


def test_only_scouts_and_federation_staff_have_a_shortlist(client, auth, world):
    for who in ("coach_a", "player_self", "admin"):
        assert _home(client, auth, who).status_code == 403
        assert _save(client, auth, world["players"]["adult_a"], who=who).status_code == 403
    assert _home(client, auth, "federation").status_code == 200


def test_a_saved_player_appears_with_the_note_and_can_be_changed_and_removed(client, auth, world):
    player = world["players"]["adult_a"]
    assert _save(client, auth, player, "Quick, left footed").status_code == 204
    home = _home(client, auth).json()
    (item,) = [i for i in home["shortlist"] if i["playerId"] == str(player.id)]
    assert item["note"] == "Quick, left footed" and item["fullName"] == player.full_name

    assert _save(client, auth, player, "  Watch again in March  ").status_code == 204
    home = _home(client, auth).json()
    assert [i["note"] for i in home["shortlist"] if i["playerId"] == str(player.id)] == ["Watch again in March"]
    ids = client.get("/shortlist", headers=auth("scout")).json()["playerIds"]
    assert ids.count(str(player.id)) == 1

    assert client.delete(f"/shortlist/{player.id}", headers=auth("scout")).status_code == 204
    assert client.delete(f"/shortlist/{player.id}", headers=auth("scout")).status_code == 404
    assert str(player.id) not in client.get("/shortlist", headers=auth("scout")).json()["playerIds"]


def test_one_users_shortlist_is_not_anothers(client, auth, world):
    player = world["players"]["adult_b"]
    _save(client, auth, player, "mine")
    others = _home(client, auth, "federation").json()["shortlist"]
    assert str(player.id) not in [i["playerId"] for i in others]


def test_a_player_the_scout_may_not_see_cannot_be_saved(client, auth, world):
    assert _save(client, auth, world["players"]["minor_no_a"]).status_code == 404


def test_a_saved_player_who_can_no_longer_be_seen_is_counted_not_shown(client, auth, world, db):
    from app.models.consent import Consent
    from app.models.enums import ConsentPurpose

    minor = _add_player(db, world["orgs"]["a"], "Shortlist Minor", age=14.5, position="ST", shots=1, n_matches=0)
    db.flush()
    assert _save(client, auth, minor).status_code == 204
    before = _home(client, auth).json()
    assert str(minor.id) in [i["playerId"] for i in before["shortlist"]]

    for consent in db.query(Consent).filter(Consent.player_id == minor.id,
                                            Consent.purpose == ConsentPurpose.SCOUTING_VISIBILITY.value):
        consent.granted = False
    db.flush()
    after = _home(client, auth).json()
    assert str(minor.id) not in [i["playerId"] for i in after["shortlist"]]
    assert after["withheld"] == before["withheld"] + 1


def test_a_note_too_long_is_refused(client, auth, world):
    assert _save(client, auth, world["players"]["adult_a"], "x" * 1001).status_code == 422


def test_the_home_lists_this_seasons_breakouts(client, auth, world, db):
    """A young player whose share of the team's chances tripled, in a team of their own."""
    from tests.test_pro_seasons import _season, _team, _write

    org = world["orgs"]["a"]
    previous, last = _team(db, org, "Home Mate")
    rising = _add_player(db, org, "Home Rising", age=20, position="LW", shots=1, n_matches=0)
    _write(db, rising, org, previous, _season(npxg=1.0, xa=0.5))
    _write(db, rising, org, last, _season(npxg=9.0, xa=4.5))
    db.flush()
    body = _home(client, auth).json()
    assert body["breakoutSeason"] == last.label
    (item,) = [i for i in body["breakouts"] if i["playerId"] == str(rising.id)]
    assert "team's chances" in item["reason"] and item["season"] == last.label
