"""The graded demo flow, in a browser.

"Log a player, see the profile, search, find them, a flag surfaces, the federation reviews
it." Each step below is one part of that sentence, and together they are the system target
the project is assessed on.

Every assertion checks something that can only have come from the database. Asserting that a
table has rows would have passed against the fixtures these screens used to render, which
would have made the suite worthless on the day it was most needed.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pytest

from conftest import API_URL, SETTLE_MS, WEB_URL, text_of


_sessions: dict[str, urllib.request.OpenerDirector] = {}


def _session(email: str) -> urllib.request.OpenerDirector:
    """A cookie-holding client signed in as `email` through the real POST /auth/login."""
    if email not in _sessions:
        demo = {row["email"]: row for row in api("/dev/identities")}
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        body = json.dumps({"email": email, "password": demo[email]["demoPassword"]}).encode()
        request = urllib.request.Request(
            f"{API_URL}/auth/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener.open(request, timeout=10).close()
        _sessions[email] = opener
    return _sessions[email]


def open_profile(page, player_id: str) -> None:
    """Open a profile and wait for it to render, but not for the written summary.

    The summary is a separate request that can take a minute or two while a local model
    writes it, so waiting for the network to go quiet would time out whenever Ollama runs.
    The last card on the profile appears only once the profile's own data has loaded.
    """
    page.goto(f"{WEB_URL}/players/{player_id}", wait_until="load")
    page.get_by_text("Where this data came from").wait_for(timeout=30000)
    page.wait_for_timeout(SETTLE_MS)


def api(path: str, identity: str | None = None, *, body: dict | None = None, timeout: float = 10):
    """Call the API, signed in as `identity` (an email) when one is given."""
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    opener = _session(identity) if identity else urllib.request.build_opener()
    with opener.open(request, timeout=timeout) as response:
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


def test_a_wrong_password_is_refused_on_screen(page, identities):
    page.goto(f"{WEB_URL}/login", wait_until="networkidle")
    page.get_by_label("Email").fill(identities["coach"]["email"])
    page.get_by_label("Password").fill("not-the-password")
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_timeout(SETTLE_MS)
    assert "email or password is incorrect" in text_of(page)
    assert page.url.endswith("/login")


def test_typing_the_credentials_signs_in(page, identities):
    """The form itself, not only the demo buttons."""
    coach = identities["coach"]
    page.goto(f"{WEB_URL}/login", wait_until="networkidle")
    page.get_by_label("Email").fill(coach["email"])
    page.get_by_label("Password").fill(coach["demoPassword"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_url("**/dashboard", timeout=20000)


def test_the_session_cookie_is_invisible_to_page_scripts(sign_in, page):
    """HttpOnly: the one property that makes a cookie safer than a token in localStorage."""
    sign_in("Coach", "/dashboard")
    cookies = {c["name"]: c for c in page.context.cookies()}
    assert cookies["northstar_session"]["httpOnly"] is True
    assert cookies["northstar_session"]["sameSite"] == "Lax"
    assert "northstar_session" not in page.evaluate("document.cookie")
    # And nothing about the session was left in storage a script can read.
    assert page.evaluate("JSON.stringify(Object.keys(window.localStorage))") == "[]"


def test_signing_out_ends_the_session(sign_in, page):
    sign_in("Coach", "/dashboard")
    page.get_by_role("button", name="Sign out").click()
    page.wait_for_url("**/login", timeout=20000)
    # Going back to a protected screen now lands on the login page, because /me says 401.
    page.goto(f"{WEB_URL}/dashboard", wait_until="networkidle")
    page.wait_for_url("**/login", timeout=20000)


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

    open_profile(page, player["id"])
    body = text_of(page)

    assert player["fullName"].lower() in body
    # The percentile section, which only exists when the cohort was big enough to quote one.
    profile = api(f"/players/{player['id']}/profile", identities["coach"]["email"])
    if profile["percentiles"]:
        assert "against their age group" in body or "percentile" in body
    assert profile["provenance"]["measurementCount"] > 0
    assert "measurements" in body


def test_the_profile_states_what_is_not_known_yet(sign_in, page, identities):
    """No forecast point without its band, and no maturity or summary that does not exist.

    This is the assertion that fails the day somebody makes the chart draw a confident line,
    or fills the maturity and summary slots with placeholders.
    """
    squad = api("/players", identities["coach"]["email"])
    profile = api(f"/players/{squad[0]['player']['id']}/profile", identities["coach"]["email"])
    for point in profile["growth"]["forecast"]:
        assert point["lower"] < point["value"] < point["upper"]
    assert profile["growth"]["forecastNote"]
    assert profile["maturity"] is None
    # The written summary is its own request (GET /players/{id}/summary), checked number by
    # number before it is shown, so the profile carries no summary slot to fill. What that
    # endpoint returns without a model is covered in apps/api/tests/test_summary.py.
    assert "summary" not in profile


def test_the_profile_draws_the_forecast_band(sign_in, page, identities):
    """The chart draws the cone, says which model made it, and the cone is a proper shape.

    The outline check is a regression test: the cone was once traced with both edges in the
    same direction, which drew a polygon that crossed itself.
    """
    sign_in("Coach", "/dashboard")
    squad = api("/players", identities["coach"]["email"])
    player = next(
        (
            row["player"]
            for row in squad
            if api(f"/players/{row['player']['id']}/profile", identities["coach"]["email"])[
                "growth"
            ]["forecast"]
        ),
        None,
    )
    assert player, "no player in this squad has a forecast, so there is nothing to check"

    open_profile(page, player["id"])
    body = text_of(page)
    assert "forecast, 80% range" in body
    assert "xgboost" in body or "growth has finished" in body
    assert "today" in body

    chart = page.locator("svg[aria-label^='Height over time']")
    cone = chart.locator("polygon[fill='#38bdf8']").get_attribute("points")
    xs = [float(pair.split(",")[0]) for pair in cone.split()]
    # Out along the top: x rises. Back along the bottom: x falls. Anything else crosses.
    turn = xs.index(max(xs))
    assert xs[: turn + 1] == sorted(xs[: turn + 1])
    assert xs[turn + 1 :] == sorted(xs[turn + 1 :], reverse=True)


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


def test_search_reads_a_described_player(sign_in, page):
    """A phrase becomes a computed filter, and an ask with no data behind it says so."""
    sign_in("Scout", "/search")
    page.get_by_placeholder("left footed").fill("small for his age, left footed")
    page.keyboard.press("Enter")
    page.wait_for_timeout(SETTLE_MS)

    body = text_of(page)
    assert "height: bottom quarter for age and gender" in body
    assert "preferred foot: no data" in body
    assert "no players match" not in body


def test_search_finds_arabic_names_from_a_latin_spelling(sign_in, page):
    """The seeded names are in Arabic; FootyStats will send Latin. A scout typing Mohamed
    must find محمد, and see that the word was read as a name."""
    sign_in("Scout", "/search")
    page.get_by_placeholder("left footed").fill("Mohamed")
    page.keyboard.press("Enter")
    page.wait_for_timeout(SETTLE_MS)

    body = text_of(page)
    assert "name: mohamed" in body
    assert "محمد" in body
    assert "no players match" not in body


def test_signed_up_minors_are_visible_to_scouts(sign_in, page, identities):
    """Consent is signed at sign-up, so a scout's search holds no locked cards.

    The rule that a minor whose guardian withdraws consent is withheld, and never named, is
    tested against the API in apps/api/tests (test_access_control.py and test_writes.py),
    where a withdrawal can be set up directly. Here the seeded dataset has none.
    """
    sign_in("Scout", "/search")
    page.wait_for_timeout(SETTLE_MS)

    results = api(
        "/search", identities["scout"]["email"], body={"query": "", "limit": 200}
    )["results"]

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


def _fill_new_player(page, name: str, *, height: str, weight: str = "", born: str = "2011-05-04"):
    """Steps 1 and 2 of the add player form, stopping short of saving."""
    page.goto(f"{WEB_URL}/players/new", wait_until="networkidle")
    page.wait_for_timeout(SETTLE_MS)

    # Everything is scoped to `main`, because the nav carries a role switcher whose <select>
    # and buttons would otherwise be matched instead of the form's.
    form = page.locator("main")
    form.get_by_label("Full name", exact=True).fill(name)
    form.locator("input[type='date']").fill(born)
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
    # One reading is not enough to forecast from, and the profile says so instead of drawing.
    assert "at least two height measurements" in text_of(page)

    squad = api("/players", identities["coach"]["email"])
    row = next(r for r in squad if r["player"]["fullName"] == name)
    assert row["player"]["isMinor"] is True
    assert row["heightCm"] == 150
    # Football registers boys only, so the form never asked and the server recorded it.
    assert row["player"]["sex"] == "male"
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
    open_profile(page, player["id"])
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
    # Table tennis is open to boys and girls, so it asks; football never does.
    form.get_by_role("button", name="girl", exact=True).click()
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
    assert row["player"]["sex"] == "female"


def test_a_coach_imports_players_from_a_spreadsheet(sign_in, page, identities, tmp_path):
    """Bulk import, through the screen: preview, confirm one unusual row, import.

    The CSV is written to pytest's temporary folder from made-up names, never into the repo.
    """
    from datetime import date, timedelta

    # Letters only: the duplicate check reads names by sound and ignores digits, so a hex tag
    # made every run's names the same, and once an earlier run had used the same birth date
    # (one of 300) the import rightly asked to confirm a duplicate and this test failed.
    hex_tag = uuid.uuid4().hex[:6]
    tag = "".join(chr(ord("a") + int(c, 16)) for c in hex_tag)
    # A birth date of its own per run as well, so the names are not the only difference.
    dob = (date.today() - timedelta(days=14 * 365 + int(hex_tag, 16) % 300)).isoformat()
    today = date.today().isoformat()
    header = "full_name,date_of_birth,sport,position,consent_signed,guardian_name,measured_on,height_cm"
    rows = [
        f"E2E Import Ready {tag},{dob},football,CM,yes,Test Guardian,{today},155",
        f"E2E Import Tall {tag},{dob},football,ST,yes,Test Guardian,{today},230",
        f"E2E Import NoGuardian {tag},{dob},football,CB,yes,,{today},150",
    ]
    file = tmp_path / "players.csv"
    file.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")

    sign_in("Coach", "/dashboard")
    page.get_by_role("link", name="Import from spreadsheet").click()
    page.wait_for_url("**/players/import", timeout=15000)
    page.get_by_label("CSV file").set_input_files(str(file))
    page.get_by_text("I checked this, import it").wait_for(timeout=15000)

    body = text_of(page)
    assert "1 ready" in body and "1 confirm" in body and "1 rejected" in body
    assert "named guardian" in body
    assert "outside the usual range" in body

    page.get_by_text("I checked this, import it").click()
    page.get_by_role("button", name="Import 2 players").click()
    page.get_by_text("3. Imported").wait_for(timeout=15000)
    assert "2 created" in text_of(page)

    squad = {r["player"]["fullName"] for r in api("/players", identities["coach"]["email"])}
    assert f"E2E Import Ready {tag}" in squad
    assert f"E2E Import Tall {tag}" in squad
    assert f"E2E Import NoGuardian {tag}" not in squad


# A common phone width. The scope says the app is mobile-first for coach logging.
PHONE = {"width": 390, "height": 844}


def _page_overflow(page) -> int:
    """How far the page itself scrolls sideways, in pixels. A table may scroll inside its own
    box; the page must not."""
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def test_the_coach_screens_fit_a_phone(browser, identities):
    """At phone width nothing makes the page scroll sideways, and on the squad screen every
    player's marks are on screen as cards rather than in a table column off to the right."""
    context = browser.new_context(viewport=PHONE, has_touch=True)
    page = context.new_page()
    try:
        page.goto(f"{WEB_URL}/login", wait_until="networkidle")
        page.get_by_role("button", name="Coach").click()
        page.wait_for_url("**/dashboard", timeout=20000)
        page.wait_for_timeout(SETTLE_MS)

        assert _page_overflow(page) <= 1
        # The phone list is showing, the wide table is not.
        cards = page.locator(r"main ul.sm\:hidden > li")
        assert cards.count() > 0
        assert not page.locator("main table").first.is_visible()
        # Every card's link and marks sit inside the screen.
        for box in cards.evaluate_all("els => els.map(e => e.getBoundingClientRect().right)"):
            assert box <= PHONE["width"] + 1

        player = next(
            h
            for h in cards.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
            if re.search(r"/players/[0-9a-f-]{36}$", h)
        )
        for path in (player, "/players/new", "/players/import", "/compare"):
            page.goto(f"{WEB_URL}{path}", wait_until="networkidle")
            page.wait_for_timeout(SETTLE_MS)
            assert _page_overflow(page) <= 1, f"{path} scrolls sideways on a phone"
    finally:
        context.close()


def test_the_radar_shows_on_the_profile_and_overlays_on_compare(sign_in, page, identities):
    """The percentile radar: on a profile with enough match time, and two players overlaid on
    the compare screen, each named with the players they are compared among."""
    sign_in("Federation", "/oversight")
    squad = api("/players", identities["coach"]["email"])
    with_radar = []
    for row in squad:
        pid = row["player"]["id"]
        radar = api(f"/players/{pid}/radar", identities["federation"]["email"])
        if radar["axes"] and row["player"]["primarySport"] == "football":
            with_radar.append(pid)
        if len(with_radar) == 2:
            break
    if len(with_radar) < 2:
        pytest.skip("the local data has fewer than two footballers with a radar in this squad")

    page.goto(f"{WEB_URL}/players/{with_radar[0]}", wait_until="load")
    page.get_by_text("Match statistics against comparable players").wait_for(timeout=20000)
    page.get_by_text("Among ").first.wait_for(timeout=20000)
    assert page.locator("svg[role=img][aria-label*='This player']").count() == 1

    page.goto(f"{WEB_URL}/compare?players={','.join(with_radar)}", wait_until="load")
    page.get_by_text("Match statistics, overlaid").wait_for(timeout=20000)
    page.wait_for_timeout(SETTLE_MS)
    body = text_of(page)
    assert body.count(", among ") >= 2


def test_the_explorer_plots_comparable_players_and_opens_from_a_profile(sign_in, page, identities):
    """From a profile's radar to the scatter explorer: the player is marked among comparable
    players, the group is named, and changing a statistic redraws the plot."""
    sign_in("Scout", "/search")
    scout = identities["scout"]["email"]
    found = api("/search", scout, body={"query": "", "sport": "football", "limit": 200})
    pid = next(
        (
            r["player"]["id"]
            for r in found["results"]
            if not r["withheld"] and api(f"/players/{r['player']['id']}/radar", scout)["axes"]
        ),
        None,
    )
    if pid is None:
        pytest.skip("the local data has no footballer with enough match time")

    page.goto(f"{WEB_URL}/players/{pid}", wait_until="load")
    page.get_by_text("See them among all comparable players").click()
    page.wait_for_url(f"**/explore?focus={pid}", timeout=20000)
    page.get_by_text(" shown of ").wait_for(timeout=20000)
    plot = page.locator("svg[role=img][aria-label*='players by']")
    assert plot.count() == 1
    # The focus player is marked amber and named on the plot.
    assert plot.locator("circle[fill='#f59e0b']").count() >= 1
    assert "with enough on record" in text_of(page)

    page.locator("label", has=page.get_by_text("Up", exact=True)).locator("select").select_option("assists")
    page.locator("svg[role=img][aria-label*='Assists']").wait_for(timeout=20000)

    # The same group's leaders: one board per statistic, each with its median.
    page.get_by_role("tab", name="Leaders").click()
    page.get_by_text("you may open, of").wait_for(timeout=20000)
    body = text_of(page)
    assert "median " in body and "goals (per 90)" in body


def test_the_assistant_answers_from_the_records_and_shows_its_reading(sign_in, page, identities):
    """A question in Arabic: the reading is printed, the answer lists players with links, and
    "Open in Explore" opens the same group. Skips when the local model is not running."""
    scout = identities["scout"]["email"]
    try:
        # Long, because the first question loads the model, which takes most of a minute.
        api("/assistant", scout, body={"question": "warm up"}, timeout=240)
    except Exception as exc:  # noqa: BLE001
        if "503" in str(exc):
            pytest.skip("the local language model is not running (docker compose --profile llm)")
        raise

    sign_in("Scout", "/search")
    page.goto(f"{WEB_URL}/ask", wait_until="load")
    page.get_by_label("Your question").fill("مين أحسن هداف تحت ١٦ سنة")
    page.get_by_role("button", name="Ask", exact=True).click()
    page.get_by_text("How this was read:").wait_for(timeout=120000)
    page.get_by_text("Open in Explore").wait_for(timeout=20000)
    body = text_of(page)
    assert "aged 15 and under" in body and "goals" in body
    assert page.locator("main table a[href^='/players/']").count() >= 1

    page.get_by_text("Open in Explore").click()
    page.wait_for_url("**/explore?**ageTo=15**", timeout=20000)
    page.get_by_text("you may open, of").wait_for(timeout=20000)


def test_a_coach_tags_a_match_and_the_shot_shows_on_the_profile(sign_in, page, identities):
    """Tag a goal and a pass by clicking the pitch and pressing keys (no video: the tags then
    simply have no video time), check the list and the tagged totals, remove one, and see the
    shot on the player's shot map."""
    label = f"vs E2E {uuid.uuid4().hex[:6]}"
    sign_in("Coach", "/dashboard")
    page.get_by_role("link", name="Tag a match").click()
    page.wait_for_url("**/matches/tag", timeout=15000)
    page.get_by_placeholder("vs ...").fill(label)
    select = page.locator("label", has=page.get_by_text("Player", exact=True)).locator("select")
    page.wait_for_function("document.querySelectorAll('select option').length > 1", timeout=20000)
    player_id = select.locator("option").nth(1).get_attribute("value")
    select.select_option(player_id)

    pitch = page.locator("svg[aria-label^='Pitch']")
    box = pitch.bounding_box()
    pitch.click(position={"x": box["width"] * 0.9, "y": box["height"] * 0.5})
    page.keyboard.press("s")
    page.keyboard.press("1")  # goal
    page.get_by_text("Tags (1)").wait_for(timeout=15000)
    pitch.click(position={"x": box["width"] * 0.5, "y": box["height"] * 0.5})
    page.keyboard.press("p")
    page.keyboard.press("2")  # incomplete
    page.get_by_text("Tags (2)").wait_for(timeout=15000)

    from datetime import date

    query = urllib.parse.urlencode({"matchDate": date.today().isoformat(), "matchLabel": label})
    tags = api(f"/events?{query}", identities["coach"]["email"])
    row = next(p for p in tags["players"] if p["playerId"] == player_id)
    assert row["tagged"]["goals"] == 1 and row["tagged"]["passes_attempted"] == 1
    assert "passes_completed" not in row["tagged"]

    page.get_by_role("button", name=re.compile("^Remove the Pass")).click()
    page.get_by_text("Tags (1)").wait_for(timeout=15000)

    page.goto(f"{WEB_URL}/players/{player_id}", wait_until="load")
    page.get_by_text("Shot map", exact=True).wait_for(timeout=20000)
    assert page.locator("svg[aria-label^='Pitch'] circle[fill='#34d399']").count() >= 1


def test_a_coach_tags_table_tennis_points_on_the_table(sign_in, page, identities):
    """The same screen, the table tennis module's own types, drawn on a table: the engine
    knows no sport. Tag a service winner and an unforced error and check the totals."""
    label = f"vs E2E TT {uuid.uuid4().hex[:6]}"
    sign_in("Coach", "/dashboard")
    page.goto(f"{WEB_URL}/matches/tag", wait_until="load")
    sport = page.locator("label", has=page.get_by_text("Sport", exact=True)).locator("select")
    sport.wait_for(timeout=20000)
    sport.select_option("table_tennis")
    page.get_by_placeholder("vs ...").fill(label)
    select = page.locator("label", has=page.get_by_text("Player", exact=True)).locator("select")
    page.wait_for_function("document.querySelectorAll('select')[1].options.length > 1", timeout=20000)
    player_id = select.locator("option").nth(1).get_attribute("value")
    select.select_option(player_id)

    table = page.locator("svg[aria-label^='Table']")
    box = table.bounding_box()
    table.click(position={"x": box["width"] * 0.8, "y": box["height"] * 0.4})
    page.keyboard.press("w")
    page.keyboard.press("2")  # service winner
    page.get_by_text("Tags (1)").wait_for(timeout=15000)
    table.click(position={"x": box["width"] * 0.52, "y": box["height"] * 0.5})
    page.keyboard.press("l")
    page.keyboard.press("1")  # unforced error
    page.get_by_text("Tags (2)").wait_for(timeout=15000)

    from datetime import date

    query = urllib.parse.urlencode({"matchDate": date.today().isoformat(), "matchLabel": label})
    tags = api(f"/events?{query}", identities["coach"]["email"])
    row = next(p for p in tags["players"] if p["playerId"] == player_id)
    assert row["tagged"] == {"points_won": 1, "service_winners": 1, "points_lost": 1, "unforced_errors": 1}


def test_federation_imports_table_tennis_results(sign_in, page, identities, tmp_path):
    """A match between two registered table tennis players, from a CSV of made-up results:
    preview, import, and the match is on both players' records, naming each other."""
    import random
    from datetime import date, timedelta

    fed = identities["federation"]["email"]
    found = api("/search", fed, body={"query": "table tennis boys", "limit": 200})["results"]
    players = [r["player"] for r in found if not r["withheld"]][:2]
    if len(players) < 2:
        pytest.skip("the local data has fewer than two table tennis boys")
    a, b = players
    played = (date.today() - timedelta(days=random.randint(1, 200))).isoformat()
    # A score unlikely to be on record already, so the row is new.
    games = f"11-{random.randint(0, 9)}, {random.randint(0, 9)}-11, 11-{random.randint(0, 9)}, 13-11"
    file = tmp_path / "results.csv"
    file.write_text(
        "date,event,player_a,player_b,games,player_a_id,player_b_id\n"
        f"{played},E2E Test Open,{a['fullName']},{b['fullName']},\"{games}\",{a['id']},{b['id']}\n",
        encoding="utf-8",
    )

    sign_in("Federation", "/oversight")
    page.get_by_role("link", name="Import table tennis results").click()
    page.wait_for_url("**/results/import", timeout=15000)
    page.get_by_label("CSV file").set_input_files(str(file))
    page.get_by_role("button", name="Import 1 match").wait_for(timeout=15000)
    assert "3-1" in text_of(page)
    page.get_by_role("button", name="Import 1 match").click()
    page.get_by_text("3. Imported").wait_for(timeout=15000)
    assert "2 match records written" in text_of(page)

    # The event is kept with the match and shown on the player's profile.
    page.goto(f"{WEB_URL}/players/{a['id']}", wait_until="load")
    page.get_by_text("E2E Test Open").first.wait_for(timeout=20000)


def test_oversight_shows_coverage_for_every_governorate(sign_in, page):
    """All 27 governorates, with the ones the platform has not reached marked as such."""
    sign_in("Federation", "/oversight")
    page.get_by_text("Coverage by governorate").wait_for(timeout=20000)
    body = text_of(page)
    for name in ("cairo", "alexandria", "aswan", "north sinai", "new valley"):
        assert name in body
    assert "with no tracked players" in body
    assert "this panel needs a region field" not in body


def test_a_scout_picks_players_to_compare_and_changes_the_set(sign_in, page):
    """Tick two search results, compare them, add a third by name on the compare screen, then
    remove one: the page address follows each change."""
    sign_in("Scout", "/search")
    # Strikers: football, so all boys. Compare refuses to mix genders, and the first results of
    # an empty search can be anyone (a table tennis girl added by another test made this fail).
    page.get_by_placeholder("left footed").fill("striker")
    page.keyboard.press("Enter")
    page.get_by_text("position: ST").wait_for(timeout=20000)
    page.wait_for_timeout(SETTLE_MS)
    boxes = page.get_by_role("checkbox", name=re.compile("^Pick .* to compare"))
    boxes.first.wait_for(timeout=20000)
    if boxes.count() < 3:
        pytest.skip("the local data has fewer than three players a scout may open")
    names = [
        re.match(r"Pick (.*) to compare", boxes.nth(i).get_attribute("aria-label")).group(1)
        for i in range(3)
    ]
    boxes.nth(0).check()
    boxes.nth(1).check()
    page.get_by_role("link", name="Compare 2").click()
    page.wait_for_url("**/compare?players=*", timeout=20000)
    page.get_by_text("Comparing 2 players").wait_for(timeout=20000)

    # The third, found by name in the compare screen's own search box.
    page.get_by_label("Add a player").fill(names[2])
    page.locator("main li button").filter(has_text=names[2]).first.click()
    page.get_by_text("Comparing 3 players").wait_for(timeout=20000)
    assert page.url.count(",") == 2

    page.get_by_role("button", name=f"Remove {names[0]} from the comparison").click()
    page.get_by_text("Comparing 2 players").wait_for(timeout=20000)
    assert page.get_by_role("button", name=f"Remove {names[0]} from the comparison").count() == 0
    assert page.url.count(",") == 1


# ---------------------------------------------------------------------------
# The whole flow, on one player (docs/demo.md)
# ---------------------------------------------------------------------------

# A seeded academy player, registered a second time by a coach at another academy who types
# only his first and family names: the commonest way a duplicate record is made. docs/demo.md
# uses a different seeded player, so rehearsing the suite leaves no clutter on the one shown.
ORIGINAL = "مروان مصطفى فؤاد"
SECOND_ENTRY = "مروان فؤاد"
REPO = Path(__file__).resolve().parents[2]


def _run_detectors() -> str:
    """The detector run, as docs/demo.md performs it: reads the database, writes flags."""
    command = [sys.executable, "-m", "ml.write_flags", "--from-database"]
    if os.environ.get("E2E_DATABASE_URL"):
        command += ["--database-url", os.environ["E2E_DATABASE_URL"]]
    done = subprocess.run(
        command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=300,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_the_demo_flow_on_one_player(sign_in, page, browser, identities):
    """Log a player, see the profile, search, find them, a flag surfaces, the federation
    reviews it: the graded sentence, in order, on the same player, in three accounts. Then the
    merge the review ends in, and its undo."""
    scout, federation = identities["scout"]["email"], identities["federation"]["email"]
    found = api("/search", scout, body={"query": ORIGINAL, "limit": 20})["results"]
    original = next((r["player"] for r in found if r["player"]["fullName"] == ORIGINAL), None)
    if original is None:
        pytest.skip(f"{ORIGINAL} is not in this database; the flow needs the seeded dataset")

    # 1. Log a player. A coach registers him again, born the same day, measured just above his
    # last reading (as docs/demo.md has it, so the merged chart does not show him shrinking).
    last = api(f"/players/{original['id']}/profile", federation)["latest"]["heightCm"]
    height = round(last + 1)
    sign_in("Coach", "/dashboard")
    form = _fill_new_player(page, SECOND_ENTRY, height=str(height), born=original["dateOfBirth"])
    form.get_by_role("button", name="Save player and measurement").click()
    page.wait_for_url(PROFILE_URL, timeout=15000)
    new_id = page.url.rsplit("/", 1)[-1]

    # 2. See the profile: his, saying what one reading cannot show.
    open_profile(page, new_id)
    assert SECOND_ENTRY in page.locator("h1").first.inner_text()
    assert "at least two height measurements" in text_of(page)

    # 3 and 4. Search, as a scout, by the name the coach typed, and find him: both records.
    scout_page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    scout_page.goto(f"{WEB_URL}/login", wait_until="networkidle")
    scout_page.get_by_role("button", name="Scout").click()
    scout_page.wait_for_url("**/search", timeout=20000)
    scout_page.wait_for_timeout(SETTLE_MS)  # typed before the page is live, the query is lost
    scout_page.get_by_placeholder("left footed").fill(SECOND_ENTRY)
    scout_page.keyboard.press("Enter")
    scout_page.locator("main").get_by_text(ORIGINAL, exact=True).first.wait_for(timeout=20000)
    scout_page.wait_for_timeout(SETTLE_MS)
    shown = scout_page.locator("main").inner_text()
    assert ORIGINAL in shown and SECOND_ENTRY in shown
    ids = [r["player"]["id"] for r in api("/search", scout, body={"query": SECOND_ENTRY})["results"]]
    assert new_id in ids and original["id"] in ids
    scout_page.context.close()

    # 5. A flag surfaces: the detector run reads the database and finds the pair.
    assert "flags raised" in _run_detectors()
    case = next(
        (f for f in api("/integrity/flags", federation)
         if f["type"] == "duplicate" and f["records"]
         and {f["records"]["playerId"], f["records"]["otherPlayerId"]} == {new_id, original["id"]}),
        None,
    )
    assert case is not None, "the detector run raised no duplicate case for the pair"
    open_profile(page, new_id)
    assert "possible duplicate" in text_of(page)

    # 6. The federation reviews it, with a reason, on the board.
    sign_in("Federation", "/oversight")
    page.goto(f"{WEB_URL}/integrity", wait_until="networkidle")
    page.locator(f"[data-flag-id='{case['id']}']").click()
    page.get_by_text("Field by field").wait_for(timeout=20000)
    body = text_of(page)
    assert SECOND_ENTRY in body and ORIGINAL in body
    assert "has more history" in body
    # The original has years of history, so it is the one kept by default.
    page.get_by_placeholder("Rang the academy").fill("E2E: same boy, registered at two academies.")
    page.get_by_role("button", name="Confirm and merge").click()
    page.wait_for_timeout(SETTLE_MS)

    decided = next(f for f in api("/integrity/flags?status=confirmed", federation) if f["id"] == case["id"])
    assert decided["history"][-1]["what"].startswith("confirmed, E2E: same boy")
    assert case["id"] not in {f["id"] for f in api("/integrity/flags", federation)}

    # 7. One player again: the coach's reading is on the record kept, the second entry's link
    # leads there, and search finds it no more.
    kept = api(f"/players/{original['id']}/profile", federation)
    assert kept["latest"]["heightCm"] == height
    assert new_id in {r["id"] for r in kept["mergedRecords"]}
    ids = [r["player"]["id"] for r in api("/search", scout, body={"query": SECOND_ENTRY})["results"]]
    assert new_id not in ids and original["id"] in ids
    page.goto(f"{WEB_URL}/players/{new_id}", wait_until="load")
    page.wait_for_url(f"**/players/{original['id']}", timeout=20000)
    page.get_by_text("Merged into this record").wait_for(timeout=30000)

    # 8. And undone, from the kept record's profile, with a reason: both records are back.
    row = page.locator("main li").filter(has_text=SECOND_ENTRY)
    row.get_by_role("button", name="Undo merge").click()
    page.get_by_label("Why undo the merge").fill("E2E: undoing the rehearsal.")
    row.get_by_role("button", name="Undo merge").click()
    page.wait_for_timeout(SETTLE_MS)
    assert api(f"/players/{new_id}/profile", federation)["player"]["id"] == new_id
    assert api(f"/players/{original['id']}/profile", federation)["latest"]["heightCm"] == last
    assert case["id"] in {f["id"] for f in api("/integrity/flags", federation)}
