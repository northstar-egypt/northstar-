"""Fixtures for the browser tests.

Firefox, because that is the browser the team uses. See the README.

The suite skips rather than fails when the web app or the API is not answering. A developer
who forgot a terminal should be told that, not handed twelve red assertions that look like
broken code.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest

WEB_URL = os.environ.get("E2E_WEB_URL", "http://localhost:3000")
API_URL = os.environ.get("E2E_API_URL", "http://localhost:8000")
HEADED = os.environ.get("E2E_HEADED") == "1"

# Generous, because the first paint has to wait on a round trip to the API and then on React
# hydrating. Too short here produces flakes that look like application bugs.
SETTLE_MS = 4000


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status < 500
    except (urllib.error.URLError, OSError):
        return False


@pytest.fixture(scope="session", autouse=True)
def services_up():
    if not _reachable(f"{API_URL}/health"):
        pytest.skip(
            f"No API at {API_URL}. Start it with:\n"
            f"  cd apps/api && uvicorn app.main:app --port 8000"
        )
    if not _reachable(WEB_URL):
        pytest.skip(
            f"No web app at {WEB_URL}. Start it with:\n"
            f"  npm run build --workspace @northstar/web\n"
            f"  npx next start -p 3000 --dir apps/web"
        )


@pytest.fixture(scope="session")
def browser():
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="pip install -r data/pipelines/requirements.txt, then python -m playwright install firefox",
    )
    with playwright.sync_playwright() as p:
        try:
            firefox = p.firefox.launch(headless=not HEADED)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                f"Could not launch Firefox ({exc}). Install it with:\n"
                f"  python -m playwright install firefox"
            )
        yield firefox
        firefox.close()


@pytest.fixture
def page(browser):
    """A fresh context per test, so one test's signed-in state cannot leak into another."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()

    # Anything the page throws is a failure worth seeing, even when the assertions pass.
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.errors = errors  # type: ignore[attr-defined]

    yield page

    context.close()
    assert not errors, f"the page raised: {errors}"


@pytest.fixture
def sign_in(page):
    """Sign in through the login screen as one of the demo roles.

    Goes through the real login screen rather than seeding localStorage, because the account
    it picks comes from the API and that lookup is part of what is being tested.
    """

    def _sign_in(role: str, expect_url: str) -> None:
        page.goto(f"{WEB_URL}/login", wait_until="networkidle")
        page.get_by_role("button", name=role).click()
        page.wait_for_url(f"**{expect_url}", timeout=20000)
        page.wait_for_timeout(SETTLE_MS)

    return _sign_in


def text_of(page) -> str:
    """The page as the user reads it, lowercased.

    Lowercased deliberately. Several labels are uppercased in CSS, and `inner_text` reports the
    rendered casing, so a case-sensitive assertion fails on a page that is working. That
    mistake cost an hour of chasing a bug that did not exist.
    """
    return page.locator("body").inner_text().lower()
