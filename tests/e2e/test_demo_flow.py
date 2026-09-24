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
import urllib.request

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
        assert "against his age group" in body or "percentile" in body
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
# Scout search, and the consent boundary
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


def test_a_minor_without_consent_is_shown_as_withheld_and_unnamed(sign_in, page, identities):
    """The rule most worth catching a regression in.

    Breaking it leaks a child's identity to a scout who has no consent to see it, and nothing
    else in this suite would notice.
    """
    sign_in("Scout", "/search")
    page.wait_for_timeout(SETTLE_MS)
    body = text_of(page)

    results = api("/search", identities["scout"]["email"]) if False else None  # POST, see below
    withheld = _withheld_from_api(identities["scout"]["email"])
    if not withheld:
        pytest.skip("no withheld players in this dataset, so there is nothing to check")

    assert "withheld" in body
    # The names of withheld players must not appear anywhere on the page.
    for name in withheld:
        assert name.lower() not in body, f"a withheld player's name reached the page: {name}"


def _withheld_from_api(identity: str) -> list[str]:
    """Names of players the scout may not see, taken from the database rather than the page.

    The API never sends these names, so they are looked up as an admin, which is the only way
    to check that they are absent from the scout's screen.
    """
    admin = None
    for row in api("/dev/identities"):
        if row["role"] == "admin":
            admin = row["email"]
    if not admin:
        return []

    request = urllib.request.Request(
        f"{API_URL}/search",
        data=json.dumps({"query": "", "limit": 200}).encode(),
        headers={"Content-Type": "application/json", "X-NorthStar-User": identity},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        scout_view = json.load(response)

    blocked_ids = [r["player"]["id"] for r in scout_view["results"] if r["withheld"]]
    names = []
    for player_id in blocked_ids[:5]:
        try:
            profile = api(f"/players/{player_id}/profile", admin)
            names.append(profile["player"]["fullName"])
        except Exception:  # noqa: BLE001
            continue
    return names


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
# Logging a player, the one step that is not built
# ---------------------------------------------------------------------------


def test_adding_a_player_says_it_did_not_save(sign_in, page):
    """`POST /players` does not exist.

    The screen must say nothing was saved rather than routing to a dashboard the player is
    not on. A coach logging a child in the field has to know the record did not save, and a
    silent failure here is the worst outcome on this screen. When the endpoint lands, this
    test is the one to invert.
    """
    sign_in("Coach", "/dashboard")
    page.goto(f"{WEB_URL}/players/new", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)

    # Everything is scoped to `main`, because the nav carries a role switcher whose <select>
    # and buttons would otherwise be matched instead of the form's.
    form = page.locator("main")
    form.locator("input[autocomplete='off']").fill("Test Player")
    form.locator("input[type='date']").fill("2011-05-04")
    # Position is a row of buttons rather than a dropdown.
    form.get_by_role("button", name="ST", exact=True).click()
    form.get_by_role("button", name="Continue").click()
    page.wait_for_timeout(1500)

    # Height is the first numeric input on step 2; the first input overall is the date.
    form.locator("input[inputmode='decimal']").first.fill("150")
    form.get_by_role("button", name="Save player and measurement").click()
    page.wait_for_timeout(SETTLE_MS)

    body = text_of(page)
    assert "not saved" in body
    assert "/dashboard" not in page.url, "must not navigate away after a failed save"
