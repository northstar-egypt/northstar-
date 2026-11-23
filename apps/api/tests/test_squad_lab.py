"""Squad Lab (app/routers/squad_lab.py, app/services/squad_lab.py).

Managers save squads for their own club; scouts and federation staff try line-ups but cannot
save; nobody sees a player through a line-up they could not see anyway; and a score is only
drawn from numbers that are really there.
"""

from __future__ import annotations

from tests.conftest import _add_player

from app import sports
from app.services import squad_lab


def _lineup(slots, formation="4-3-3"):
    return {"formation": formation, "slots": {k: str(v.id) for k, v in slots.items()}}


def _evaluate(client, auth, who, slots, formation="4-3-3"):
    return client.post("/squad-lab/evaluate", json=_lineup(slots, formation), headers=auth(who))


def _slot(result, slot_id):
    (slot,) = [s for s in result["slots"] if s["slotId"] == slot_id]
    return slot


# ---------------------------------------------------------------- configuration


def test_every_formation_link_has_a_rule_and_every_trait_exists():
    cfg = squad_lab.config()
    module = sports.registry()["football"]
    for name, shape in cfg["formations"].items():
        ids = [s["id"] for s in shape["slots"]]
        assert len(ids) == 11 and len(set(ids)) == 11, name
        assert len({tuple(sorted(link)) for link in shape["links"]}) == len(shape["links"]), name
        assert all(s["role"] in module.roles for s in shape["slots"]), name
        roles = {s["id"]: s["role"] for s in shape["slots"]}
        for a, b in shape["links"]:
            ga, gb = squad_lab.group_of(roles[a]), squad_lab.group_of(roles[b])
            if "GK" in (roles[a], roles[b]):
                continue  # drawn grey, never scored
            assert squad_lab._rule(ga, gb)[0] is not None, f"{name}: no rule for {ga} and {gb}"
    used = {t for rule in cfg["links"] for t in rule["a"] + rule["b"]}
    used |= {t for traits in cfg["roleTraits"].values() for t in traits}
    assert used <= set(cfg["traits"])
    for trait in cfg["traits"].values():
        for schema, source in trait["sources"].items():
            fields = set(module.periods[schema].schema["properties"])
            assert set(source["numerator"]) | set(source.get("denominator", [])) <= fields, trait


def test_percentile_counts_ties_half():
    assert squad_lab.percentile([1, 2, 3, 4], 5) == 100
    assert squad_lab.percentile([1, 2, 3, 4], 0) == 0
    assert squad_lab.percentile([1, 2, 2, 3], 2) == 50


# ---------------------------------------------------------------- who may do what


def test_players_and_admins_cannot_use_the_lab(client, auth, world):
    for who in ("player_self", "admin"):
        assert _evaluate(client, auth, who, {}).status_code == 403


def test_a_scout_can_try_a_line_up_but_not_save_one(client, auth, world):
    adult = world["players"]["adult_a"]
    assert _evaluate(client, auth, "scout", {"ST": adult}).status_code == 200
    body = {**_lineup({"ST": adult}), "name": "Trial"}
    for who in ("scout", "federation"):
        assert client.post("/squad-lab/squads", json=body, headers=auth(who)).status_code == 403
        assert client.get("/squad-lab/squads", headers=auth(who)).json() == {"maySave": False, "squads": []}


def test_a_slot_never_shows_a_player_the_caller_may_not_see(client, auth, world):
    blocked = world["players"]["minor_no_a"]
    slot = _slot(_evaluate(client, auth, "scout", {"ST": blocked}).json(), "ST")
    assert slot["state"] == "unavailable" and slot["player"] is None
    other_club = world["players"]["adult_b"]
    slot = _slot(_evaluate(client, auth, "coach_a", {"ST": other_club}).json(), "ST")
    assert slot["state"] == "unavailable" and slot["player"] is None


def test_candidates_are_only_players_the_caller_may_see(client, auth, world):
    names = {p["fullName"] for p in client.get("/squad-lab/candidates?role=ST", headers=auth("coach_a")).json()["players"]}
    assert "Adult A" in names and "Adult B" not in names
    names = {p["fullName"] for p in client.get("/squad-lab/candidates?role=ST&q=Minor",
                                                  headers=auth("scout")).json()["players"]}
    assert "Minor Consented A" in names and "Minor Blocked A" not in names


def test_a_manager_saves_edits_and_deletes_a_squad_for_his_club_only(client, auth, world):
    body = {**_lineup({"ST": world["players"]["adult_a"]}), "name": "Saturday"}
    created = client.post("/squad-lab/squads", json=body, headers=auth("coach_a"))
    assert created.status_code == 201
    squad_id = created.json()["id"]

    listed = client.get("/squad-lab/squads", headers=auth("coach_a")).json()
    assert listed["maySave"] and [s["name"] for s in listed["squads"]] == ["Saturday"]
    assert client.get("/squad-lab/squads", headers=auth("coach_b")).json()["squads"] == []
    assert client.get(f"/squad-lab/squads/{squad_id}", headers=auth("coach_b")).status_code == 404
    assert client.delete(f"/squad-lab/squads/{squad_id}", headers=auth("coach_b")).status_code == 404

    body["name"] = "Saturday, back four"
    assert client.put(f"/squad-lab/squads/{squad_id}", json=body, headers=auth("coach_a")).json()["name"] == body["name"]
    assert client.delete(f"/squad-lab/squads/{squad_id}", headers=auth("coach_a")).status_code == 204
    assert client.get("/squad-lab/squads", headers=auth("coach_a")).json()["squads"] == []


def test_a_squad_cannot_hold_a_player_from_another_club(client, auth, world):
    body = {**_lineup({"ST": world["players"]["adult_b"]}), "name": "Poached"}
    assert client.post("/squad-lab/squads", json=body, headers=auth("coach_a")).status_code == 400


def test_a_bad_line_up_is_refused(client, auth, world):
    adult = world["players"]["adult_a"]
    assert _evaluate(client, auth, "coach_a", {"ST": adult}, formation="9-0-1").status_code == 400
    assert _evaluate(client, auth, "coach_a", {"XX": adult}).status_code == 400
    assert _evaluate(client, auth, "coach_a", {"ST": adult, "LW": adult}).status_code == 400


# ---------------------------------------------------------------- scores


def _youth(db, org, name, *, position, shots, consent=True):
    player = _add_player(db, org, name, age=15.5, position=position, shots=shots, consent=consent)
    player.tier = "youth"
    return player


def test_a_better_finisher_scores_higher_and_an_empty_neighbour_leaves_the_link_unknown(client, auth, world, db):
    org = world["orgs"]["a"]
    strikers = [_youth(db, org, f"Lab Striker {i}", position="ST", shots=i) for i in range(1, 8)]
    db.flush()
    low = _slot(_evaluate(client, auth, "coach_a", {"ST": strikers[0]}).json(), "ST")
    high = _slot(_evaluate(client, auth, "coach_a", {"ST": strikers[-1]}).json(), "ST")
    assert low["state"] == high["state"] == "scored"
    assert high["score"] > low["score"]
    assert {t["trait"] for t in high["traits"]} <= set(squad_lab.config()["roleTraits"]["strikers"])

    result = _evaluate(client, auth, "coach_a", {"ST": strikers[-1]}).json()
    (link,) = [lk for lk in result["links"] if {lk["from"], lk["to"]} == {"LW", "ST"}]
    assert link["score"] is None and link["band"] == "unknown"
    assert result["team"]["chemistry"]["score"] is None
    assert result["team"]["rating"]["score"] is None  # 1 of 10 outfield players is not enough


def test_no_analytics_consent_means_no_score(client, auth, world, db):
    player = _youth(db, world["orgs"]["a"], "Lab No Consent", position="ST", shots=4, consent=False)
    db.flush()
    slot = _slot(_evaluate(client, auth, "coach_a", {"ST": player}).json(), "ST")
    assert slot["state"] == "no_consent" and slot["score"] is None and slot["traits"] == []


def test_the_goalkeeper_is_placed_but_never_scored(client, auth, world, db):
    keeper = _youth(db, world["orgs"]["a"], "Lab Keeper", position="GK", shots=0)
    db.flush()
    slot = _slot(_evaluate(client, auth, "coach_a", {"GK": keeper}).json(), "GK")
    assert slot["state"] == "not_scored" and slot["score"] is None and slot["player"]["fullName"] == "Lab Keeper"
    result = _evaluate(client, auth, "coach_a", {"GK": keeper}).json()
    keeper_links = [lk for lk in result["links"] if "GK" in (lk["from"], lk["to"])]
    assert keeper_links and all(lk["score"] is None and lk["band"] == "unknown" for lk in keeper_links)
    assert result["team"]["chemistry"]["links"] == len(result["links"]) - len(keeper_links)
