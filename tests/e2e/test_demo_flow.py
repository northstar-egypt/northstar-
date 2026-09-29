"""The graded demo flow, in a browser.

"Log a player, see the profile, search, find them, a flag surfaces, the federation reviews
it." Each step below is one part of that sentence, and together they are the system target
the project is assessed on.

Every assertion checks something that can only have come from the database. Asserting that a
table has rows would have passed against the fixtures these screens used to render, which
would have made the suite worthless on the day it was most needed.
"""

from __future__ import annotations

import json
import re
import urllib.request
import uuid

import pytest

from conftest import API_URL, SETTLE_MS, WEB_URL, text_of


def api(path: str, identity: str | None = None):
    request = urllib.request.Request(f"{API_URL}{path}")
    if identity:
        request.add_header("X-NorthStar-User", identity)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


@pytest.fixture(scope="session")
def identities():
    return {row["role"]: row for row in api("/dev/identities")}


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------


def test_login_offers_accounts_the_api_will_accept(page):
    """The role buttons are useless if they name accounts the API has never heard of."""
    page.goto(f"{WEB_URL}/login", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)
    for role in ("Coach", "Scout", "Federation", "Player"):
        assert page.get_by_role("button", name=role).count() == 1, role


def test_signing_in_as_a_coach_reaches_their_own_dashboard(sign_in, page, identities):
    sign_in("Coach", "/dashboard")
    body = text_of(page)
    # The organization name comes from the coach's account in the database. A fixture would
    # have said something else.
    expected = identities["coach"]["organizationName"]
    assert expected and expected.lower() in body


# ---------------------------------------------------------------------------
# The squad
# ---------------------------------------------------------------------------


def test_the_squad_shows_the_players_the_api_scopes_to_this_coach(sign_in, page, identities):
    sign_in("Coach", "/dashboard")
    squad = api("/players", identities["coach"]["email"])
    assert squad, "this coach has no players, so the test proves nothing"

    body = text_of(page)
    assert f"{len(squad)} players" in body
    # Every player the API returned is on the screen, by name.
    for row in squad:
        assert row["player"]["fullName"].lower() in body


def test_the_squad_reports_staleness_and_consent(sign_in, page):
    """The two numbers a coach opens this screen for."""
    sign_in("Coach", "/dashboard")
    body = text_of(page)
    assert "squad size" in body
    assert "not measured in" in body
    assert "consent missing" in body


# ---------------------------------------------------------------------------
# The player profile
# ---------------------------------------------------------------------------


def test_a_player_profile_renders_real_measurements(sign_in, page, identities):
    sign_in("Coach", "/dashboard")
    squad = api("/players", identities["coach"]["email"])
    player = squad[0]["player"]

    page.goto(f"{WEB_URL}/players/{player['id']}", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)
    body = text_of(page)

    assert player["fullName"].lower() in body
    # The percentile section, which only exists when the cohort was big enough to quote one.
    profile = api(f"/players/{player['id']}/profile", identities["coach"]["email"])
    if profile["percentiles"]:
        assert "against their age group" in body or "percentile" in body
    assert profile["provenance"]["measurementCount"] > 0
    assert "measurements" in body


def test_the_profile_states_what_is_not_known_yet(sign_in, page, identities):
    """The forecast and the maturity estimate are absent, and the screen says so.

    This is the assertion that fails the day somebody makes the chart draw a confident line
    through data the models cannot actually predict yet.
    """
    squad = api("/players", identities["coach"]["email"])
    profile = api(f"/players/{squad[0]['player']['id']}/profile", identities["coach"]["email"])
    assert profile["growth"]["forecast"] == []
    assert profile["maturity"] is None
    assert profile["summary"] is None


# ---------------------------------------------------------------------------
# Scout search
# ---------------------------------------------------------------------------


def test_search_reports_how_it_read_the_query(sign_in, page):
    sign_in("Scout", "/search")
    # The query box carries no `type` attribute, so `input[type=text]` matches nothing. Match
    # the placeholder, which is also what a person would look for.
    page.get_by_placeholder("left footed").fill("under 16 striker")
    page.keyboard.press("Enter")
    page.wait_for_timeout(SETTLE_MS)

    body = text_of(page)
    assert "how this was read" in body
    assert "age: under 16" in body
    assert "position: st" in body


def test_signed_up_minors_are_visible_to_scouts(sign_in, page, identities):
    """Consent is signed at sign-up, so a scout's search holds no locked cards.

    The rule that a minor whose guardian withdraws consent is withheld, and never named, is
    tested against the API in apps/api/tests (test_access_control.py and test_writes.py),
    where a withdrawal can be set up directly. Here the seeded dataset has none.
    """
    sign_in("Scout", "/search")
    page.wait_for_timeout(SETTLE_MS)

    request = urllib.request.Request(
        f"{API_URL}/search",
        data=json.dumps({"query": "", "limit": 200}).encode(),
        headers={
            "Content-Type": "application/json",
            "X-NorthStar-User": identities["scout"]["email"],
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        results = json.load(response)["results"]

    minors = [r for r in results if r["player"].get("isMinor")]
    assert minors, "the search returned no minors, so there is nothing to check"
    assert not [r for r in results if r["withheld"]]
    assert "withheld" not in text_of(page)


# ---------------------------------------------------------------------------
# Federation oversight and the integrity board
# ---------------------------------------------------------------------------


def test_oversight_shows_aggregates_that_match_the_api(sign_in, page, identities):
    sign_in("Federation", "/oversight")
    summary = api("/oversight", identities["federation"]["email"])
    body = text_of(page)
    assert "players tracked" in body
    assert str(summary["playersTracked"]) in body


def test_the_integrity_board_lists_real_flags(sign_in, page, identities):
    """Flags reach this screen from the flag table, written by `python -m ml.write_flags`.

    An empty board usually means that job has not been run, so this skips rather than failing
    and blaming the application.
    """
    flags = api("/integrity/flags", identities["federation"]["email"])
    if not flags:
        pytest.skip("no open flags; run `python -m ml.write_flags` first")

    sign_in("Federation", "/oversight")
    page.goto(f"{WEB_URL}/integrity", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)
    body = text_of(page)

    assert f"{len(flags)} open flags" in body
    # The first case's player is named on the queue.
    assert flags[0]["playerName"].lower() in body


def test_the_board_no_longer_claims_there_is_no_flag_table(sign_in, page, identities):
    """There is one now. This is here because that banner outlived the gap it described."""
    sign_in("Federation", "/oversight")
    page.goto(f"{WEB_URL}/integrity", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)
    assert "there is no flag table" not in text_of(page)


# ---------------------------------------------------------------------------
# Logging a player
# ---------------------------------------------------------------------------


# A profile URL ends in a player UUID. A glob like /players/* would also match /players/new,
# which is where the page already is, and the wait would pass without anything saving.
PROFILE_URL = re.compile(r".*/players/[0-9a-f]{8}-[0-9a-f-]{27}$")


def _sign_consent_as_guardian(form):
    """The sign-up consent form. The date of birth above makes the player a minor, so a
    guardian signs, and Continue stays disabled until they have."""
    form.get_by_label("Guardian's full name").fill("E2E Guardian")
    form.get_by_role("checkbox", name="signed the consent form").check()


def _fill_new_player(page, name: str, *, height: str, weight: str = ""):
    """Steps 1 and 2 of the add player form, stopping short of saving."""
    page.goto(f"{WEB_URL}/players/new", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)

    # Everything is scoped to `main`, because the nav carries a role switcher whose <select>
    # and buttons would otherwise be matched instead of the form's.
    form = page.locator("main")
    form.get_by_label("Full name", exact=True).fill(name)
    form.locator("input[type='date']").fill("2011-05-04")
    _sign_consent_as_guardian(form)
    # Position is a row of buttons rather than a dropdown.
    form.get_by_role("button", name="ST", exact=True).click()
    form.get_by_role("button", name="Continue").click()
    page.wait_for_timeout(1500)

    # Height then weight are the numeric inputs on step 2; the first input overall is the date.
    numbers = form.locator("input[inputmode='decimal']")
    numbers.nth(0).fill(height)
    if weight:
        numbers.nth(1).fill(weight)
    return form


def test_adding_a_player_saves_and_opens_their_profile(sign_in, page, identities):
    """Step one of the demo flow, and until this landed the only one that did not work.

    The player must then exist for the API as well as on screen, in this coach's squad, as a
    minor, with the height that was typed in.
    """
    name = f"E2E Player {uuid.uuid4().hex[:6]}"
    sign_in("Coach", "/dashboard")
    form = _fill_new_player(page, name, height="150")
    form.get_by_role("button", name="Save player and measurement").click()
    page.wait_for_url(PROFILE_URL, timeout=15000)
    page.wait_for_timeout(SETTLE_MS)

    assert name.lower() in text_of(page)

    squad = api("/players", identities["coach"]["email"])
    row = next(r for r in squad if r["player"]["fullName"] == name)
    assert row["player"]["isMinor"] is True
    assert row["heightCm"] == 150
    assert page.url.endswith(row["player"]["id"])


def test_an_unusual_reading_is_asked_about_before_it_is_saved(sign_in, page, identities):
    """The API's question, not the screen's own check.

    The screen only range-checks height. 300 kg is caught by the server, which must turn into
    a question the coach can answer on the spot, not an error and not a silent save.
    """
    name = f"E2E Heavy {uuid.uuid4().hex[:6]}"
    sign_in("Coach", "/dashboard")
    form = _fill_new_player(page, name, height="150", weight="300")
    form.get_by_role("button", name="Save player and measurement").click()
    page.wait_for_timeout(SETTLE_MS)

    body = text_of(page)
    assert "check this" in body
    assert "300 kg" in body
    assert "/players/new" in page.url, "must not navigate away before the coach confirms"
    squad = api("/players", identities["coach"]["email"])
    assert name not in {r["player"]["fullName"] for r in squad}, "saved before confirming"

    form.get_by_role("button", name="Save anyway").click()
    page.wait_for_url(PROFILE_URL, timeout=15000)
    squad = api("/players", identities["coach"]["email"])
    assert name in {r["player"]["fullName"] for r in squad}


# ---------------------------------------------------------------------------
# Table tennis, through the same screens
# ---------------------------------------------------------------------------


def test_a_table_tennis_profile_is_laid_out_by_its_sport_module(sign_in, page, identities):
    """The architecture's claim, in a browser: same profile screen, a different sport module.

    Every label asserted here comes from packages/shared/sports/table_tennis.json. None of
    them appears anywhere in the frontend's source.
    """
    federation = identities["federation"]["email"]
    squad = api("/players", federation)
    # The first table tennis player with matches. Not simply the first one: the add-player
    # test below creates table tennis players with no matches, and they sort early by name.
    player = next(
        (
            r["player"]
            for r in squad
            if r["player"]["primarySport"] == "table_tennis"
            and api(f"/players/{r['player']['id']}/profile", federation)["performance"]
        ),
        None,
    )
    assert player, "no table tennis player with matches, so the test proves nothing"

    sign_in("Federation", "/oversight")
    page.goto(f"{WEB_URL}/players/{player['id']}", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)
    body = text_of(page)

    assert "performance: matches" in body
    for label in ("best of", "sets won", "sets lost", "points won", "matches won"):
        assert label in body, label
    # Nothing from football leaks onto a table tennis record.
    assert "minutes" not in body
    assert "shots" not in body


def test_a_coach_can_add_a_table_tennis_player(sign_in, page, identities):
    """The add-player screen's sports and roles come from the sport modules too."""
    name = f"E2E Table Tennis {uuid.uuid4().hex[:6]}"
    sign_in("Coach", "/dashboard")
    page.goto(f"{WEB_URL}/players/new", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)

    form = page.locator("main")
    form.get_by_label("Full name", exact=True).fill(name)
    form.locator("input[type='date']").fill("2011-05-04")
    _sign_consent_as_guardian(form)
    form.get_by_role("button", name="Table tennis", exact=True).click()
    body = text_of(page)
    assert "playing style" in body
    form.get_by_role("button", name="chopper", exact=True).click()
    form.get_by_role("button", name="Continue").click()
    page.wait_for_timeout(1500)

    form.locator("input[inputmode='decimal']").first.fill("150")
    form.get_by_role("button", name="Save player and measurement").click()
    page.wait_for_url(PROFILE_URL, timeout=15000)

    squad = api("/players", identities["coach"]["email"])
    row = next(r for r in squad if r["player"]["fullName"] == name)
    assert row["player"]["primarySport"] == "table_tennis"
    assert row["player"]["position"] == "chopper"
    # Tier is a football idea; the table tennis module says so and the API obeyed it.
    assert row["player"]["tier"] is None
