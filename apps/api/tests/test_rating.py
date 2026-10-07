"""The table tennis rating on the profile (app/services/rating.py), and who may see whom.

The numbers themselves are graded in ml/ (python -m ml.run_rating_eval). These tests are
about the rules around them: a rating appears only with enough evidence, an opponent's name
appears only to someone allowed to open their profile, a withdrawn analytics consent takes a
player out of every rating, and a win nobody confirmed moves nobody.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from tests.conftest import TODAY


@pytest.fixture
def tt(db, world):
    """Table tennis players at academy A, with a season of matches between them."""
    from app.models.consent import Consent
    from app.models.enums import ConsentPurpose
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player
    from app.models.player_organization import PlayerOrganization
    from app.services import rating

    academy_a, academy_b = world["orgs"]["a"], world["orgs"]["b"]

    def player(name, *, minor, org, scouting=True, analytics=True):
        row = Player(
            id=uuid.uuid4(),
            full_name=name,
            date_of_birth=TODAY - timedelta(days=int((15 if minor else 25) * 365.25)),
            sex="male",
            nationality=["EG"],
            is_egypt_eligible=True,
            primary_sport="table_tennis",
            tier=None,
            position="attacker",
            is_minor=minor,
            status="active",
        )
        db.add(row)
        db.flush()
        db.add(
            PlayerOrganization(
                id=uuid.uuid4(),
                player_id=row.id,
                organization_id=org.id,
                role="player",
                start_date=TODAY - timedelta(days=800),
                end_date=None,
            )
        )
        for purpose, granted in (
            (ConsentPurpose.DATA_STORAGE.value, True),
            (ConsentPurpose.ANALYTICS.value, analytics),
            (ConsentPurpose.SCOUTING_VISIBILITY.value, scouting),
        ):
            db.add(
                Consent(
                    id=uuid.uuid4(),
                    player_id=row.id,
                    purpose=purpose,
                    granted=granted,
                    granted_by="guardian",
                    guardian_name="Test Guardian",
                    valid_from=TODAY - timedelta(days=800),
                    valid_until=None,
                )
            )
        return row

    def match(a, b, days_ago, *, a_points, b_points, a_sets, b_sets, source="api", mirror=True):
        rows = []
        sides = [(a, b, a_sets, b_sets, a_points, b_points)]
        if mirror:
            sides.append((b, a, b_sets, a_sets, b_points, a_points))
        for me, other, won, lost, pw, pl in sides:
            row = PerformanceEntry(
                id=uuid.uuid4(),
                player_id=me.id,
                opponent_player_id=other.id,
                sport="table_tennis",
                period_type="match",
                period_start=TODAY - timedelta(days=days_ago),
                metrics={
                    "best_of": 5,
                    "sets_won": won,
                    "sets_lost": lost,
                    "points_won": pw,
                    "points_lost": pl,
                },
                schema_ref="table_tennis.match.v1",
                source=source,
                is_validated=source in ("api", "coach_logged"),
            )
            db.add(row)
            rows.append(row)
        return rows

    people = {
        "strong": player("TT Strong", minor=False, org=academy_a),
        "steady": player("TT Steady", minor=False, org=academy_a),
        "hidden_minor": player("TT Minor No Scouting", minor=True, org=academy_b, scouting=False),
        "no_analytics": player("TT No Analytics", minor=False, org=academy_a, analytics=False),
        "newcomer": player("TT Newcomer", minor=False, org=academy_a),
    }
    # A league of eight, so "an average registered player" is something the data can pin
    # down. An isolated group of three is rated against nobody else, and correctly gets no
    # number on screen.
    pool = [people["strong"], people["steady"]] + [
        player(f"TT Pool {i}", minor=False, org=academy_a) for i in range(6)
    ]
    rows = {"league": [], "minor": []}
    day = 20
    for _ in range(6):
        for i, a in enumerate(pool):
            for b in pool[i + 1:]:
                day += 2
                # The strong player wins 57% of their points; everyone else is even.
                if a is people["strong"]:
                    pts = dict(a_points=44, b_points=33, a_sets=3, b_sets=1)
                else:
                    pts = dict(a_points=40, b_points=38, a_sets=3, b_sets=2) if day % 4 else dict(
                        a_points=38, b_points=40, a_sets=2, b_sets=3
                    )
                rows["league"].extend(match(a, b, day % 600, **pts))
    for i in range(25):
        rows["minor"].extend(
            match(people["hidden_minor"], people["steady"], 5 + i * 15, a_points=38, b_points=37, a_sets=3, b_sets=2)
        )
    rows["no_analytics"] = match(
        people["strong"], people["no_analytics"], 30, a_points=33, b_points=20, a_sets=3, b_sets=0
    )
    # The newcomer's one win, self-submitted and never confirmed by the opponent.
    rows["unconfirmed"] = match(
        people["newcomer"], people["strong"], 10, a_points=33, b_points=25, a_sets=3, b_sets=0,
        source="self_submitted", mirror=False,
    )
    db.flush()
    rating.reset_cache()
    yield {"people": people, "rows": rows}
    rating.reset_cache()


def _profile(client, auth, who, player):
    response = client.get(f"/players/{player.id}/profile", headers=auth(who))
    assert response.status_code == 200, response.text
    return response.json()


def _opponents(profile):
    """Entry id -> opponent block, for the records on the page (the profile lists the latest 50)."""
    section = next(s for s in profile["performance"] if s["sport"] == "table_tennis")
    return {e["id"]: e["opponent"] for e in section["entries"]}


def _on_page(ids, seen):
    shown = [i for i in ids if i in seen]
    assert shown, "none of these records is on the page, so the test proves nothing"
    return shown


def test_a_well_measured_player_has_a_rating_with_a_range(client, auth, tt):
    r = _profile(client, auth, "scout", tt["people"]["strong"])["rating"]
    assert r["shown"] is True
    assert r["low"] < r["pointShare"] < r["high"]
    assert r["high"] - r["low"] <= 0.07
    assert r["pointShare"] > 0.5, "they won 57% of their points"
    assert r["matchWin"] > 0.5
    assert r["population"] == "registered boys and men in table tennis"
    assert r["note"] is None


def test_too_little_evidence_shows_no_number_and_says_why(client, auth, tt):
    r = _profile(client, auth, "scout", tt["people"]["newcomer"])["rating"]
    assert r["shown"] is False
    assert r["pointShare"] is None and r["low"] is None and r["matchWin"] is None
    assert r["note"]


def test_a_football_player_has_no_rating(client, auth, world, tt):
    assert _profile(client, auth, "scout", world["players"]["adult_a"])["rating"] is None


def test_an_opponent_is_named_only_to_someone_who_may_open_their_profile(client, auth, tt):
    steady = tt["people"]["steady"]
    minor_rows = {str(r.id) for r in tt["rows"]["minor"] if r.player_id == steady.id}
    strong_rows = {
        str(r.id)
        for r in tt["rows"]["league"]
        if r.player_id == steady.id and r.opponent_player_id == tt["people"]["strong"].id
    }

    # A scout: the adult is named; the minor without scouting consent is not.
    seen = _opponents(_profile(client, auth, "scout", steady))
    assert all(seen[i]["name"] == "TT Strong" for i in _on_page(strong_rows, seen))
    for i in _on_page(minor_rows, seen):
        assert seen[i]["registered"] is True
        assert seen[i]["name"] is None and seen[i]["id"] is None

    # Coach A: the minor is at academy B, so coach A cannot open their profile either.
    seen = _opponents(_profile(client, auth, "coach_a", steady))
    assert all(seen[i]["name"] is None for i in _on_page(minor_rows, seen))
    # Federation staff may open anyone's profile.
    seen = _opponents(_profile(client, auth, "federation", steady))
    assert all(seen[i]["name"] == "TT Minor No Scouting" for i in _on_page(minor_rows, seen))


def test_opponent_strength_is_sent_even_when_their_name_is_not(client, auth, tt):
    """How strong someone was is not identifying; it is what makes the result readable."""
    steady = tt["people"]["steady"]
    minor_rows = [str(r.id) for r in tt["rows"]["minor"] if r.player_id == steady.id]
    seen = _opponents(_profile(client, auth, "scout", steady))
    assert any(seen[i]["strength"] is not None for i in _on_page(minor_rows, seen))


def test_withdrawn_analytics_consent_takes_a_player_out_of_every_rating(client, auth, tt):
    no_analytics = tt["people"]["no_analytics"]
    r = _profile(client, auth, "federation", no_analytics)["rating"]
    assert r["shown"] is False and "analytics consent" in r["note"]

    strong = tt["people"]["strong"]
    their_match = [str(x.id) for x in tt["rows"]["no_analytics"] if x.player_id == strong.id]
    seen = _opponents(_profile(client, auth, "federation", strong))
    for i in _on_page(their_match, seen):
        assert seen[i]["counted"] is False
        assert seen[i]["strength"] is None


def test_an_unconfirmed_self_submitted_win_does_not_count(client, auth, tt):
    newcomer = tt["people"]["newcomer"]
    (row,) = tt["rows"]["unconfirmed"]
    seen = _opponents(_profile(client, auth, "federation", newcomer))
    assert seen[str(row.id)]["counted"] is False
    confirmed = [str(x.id) for x in tt["rows"]["league"] if x.player_id == tt["people"]["strong"].id]
    seen = _opponents(_profile(client, auth, "federation", tt["people"]["strong"]))
    assert all(seen[i]["counted"] for i in _on_page(confirmed, seen))


def test_a_match_against_a_merged_duplicate_belongs_to_the_surviving_record(db, client, auth, tt):
    """Found by eye on the real screen: a coach-logged match against a duplicate record that
    was later merged was dropped from the ratings ("not counted") and shown under the
    duplicate's old spelling. It is the same person, so it counts, under the current record."""
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player
    from app.services import rating

    steady = tt["people"]["steady"]
    duplicate = Player(
        id=uuid.uuid4(),
        full_name="TT Steddy",
        date_of_birth=steady.date_of_birth,
        sex="male",
        nationality=["EG"],
        is_egypt_eligible=True,
        primary_sport="table_tennis",
        position="attacker",
        is_minor=False,
        status="merged",
        merged_into=steady.id,
    )
    db.add(duplicate)
    db.flush()
    row = PerformanceEntry(
        id=uuid.uuid4(),
        player_id=tt["people"]["strong"].id,
        opponent_player_id=duplicate.id,
        sport="table_tennis",
        period_type="match",
        period_start=TODAY - timedelta(days=1),
        metrics={"best_of": 5, "sets_won": 3, "sets_lost": 0, "points_won": 33, "points_lost": 20},
        schema_ref="table_tennis.match.v1",
        source="coach_logged",
        is_validated=True,
    )
    db.add(row)
    db.flush()
    rating.reset_cache()

    seen = _opponents(_profile(client, auth, "federation", tt["people"]["strong"]))
    opponent = seen[str(row.id)]
    assert opponent["counted"] is True
    assert opponent["name"] == "TT Steady"
    assert opponent["id"] == str(steady.id)


# ---------------------------------------------------------------------------
# Search: "highly rated", "beats strong opponents"
# ---------------------------------------------------------------------------


def _search_ids(client, auth, query: str) -> tuple[set[str], list[dict]]:
    body = client.post(
        "/search",
        json={"query": query, "limit": 200, "includeMinors": True},
        headers=auth("admin"),
    ).json()
    return {r["player"]["id"] for r in body["results"]}, body["parsed"]["chips"]


@pytest.mark.parametrize("query", ["highly rated", "beats strong opponents"])
def test_search_for_strong_players_uses_the_profile_rating(db, client, auth, tt, query):
    from app.services import rating

    found, chips = _search_ids(client, auth, query)
    assert any(c["understood"] and "strength against other players" in c["label"] for c in chips)
    assert str(tt["people"]["strong"].id) in found
    # No rating on the profile, so never a match: too few matches, or consent withdrawn.
    assert str(tt["people"]["newcomer"].id) not in found
    assert str(tt["people"]["no_analytics"].id) not in found
    # Only players whose rating is shown, in their gender's top quarter.
    shown = rating.shown_strengths(db)
    for pid in found:
        assert pid in shown


def test_strong_opponents_is_not_read_as_physical_strength(client, auth, tt):
    _, chips = _search_ids(client, auth, "beats strong opponents")
    assert not any("strength: no data" in c["label"] for c in chips)
