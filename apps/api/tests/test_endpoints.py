"""Behaviour of the read endpoints, beyond who is allowed to call them.

The recurring theme is that this API is expected to say what it does not know. A forecast
that does not exist is an empty list, a maturity estimate that has not been chosen is null,
and a percentile computed from four people is omitted. Several tests below exist only to stop
a future change replacing one of those with a plausible-looking placeholder.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Squad
# ---------------------------------------------------------------------------


def test_squad_row_carries_everything_the_table_needs(client, auth, world):
    """One request per screen, not one per row.

    Days since the last log and the sparkline are on the row precisely because fetching them
    per player is what the frontend TODO warned would make this screen slow.
    """
    rows = client.get("/players", headers=auth("coach_a")).json()
    assert rows
    row = rows[0]
    assert set(row) == {
        "player",
        "ageLabel",
        "heightCm",
        "daysSinceLastLog",
        "heightTrend",
        "flags",
        "consentComplete",
    }
    assert row["daysSinceLastLog"] is not None
    assert row["heightCm"] is not None


def test_sparkline_is_capped_and_oldest_first(client, auth, world):
    rows = client.get("/players", headers=auth("coach_a")).json()
    trend = rows[0]["heightTrend"]
    assert 0 < len(trend) <= 6
    assert trend == sorted(trend), "the fixture grows monotonically, so the order is checkable"


def test_consent_complete_ignores_scouting_visibility(client, auth, world):
    """Declining to be visible to scouts is a legitimate choice, not an incomplete record.

    If it counted, a coach's dashboard would nag them to chase a consent the family has
    already considered and refused.
    """
    rows = {
        row["player"]["fullName"]: row
        for row in client.get("/players", headers=auth("coach_a")).json()
    }
    assert rows["Minor Blocked A"]["consentComplete"] is True


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def test_profile_reports_no_forecast_rather_than_inventing_one(client, auth, world):
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).json()
    assert body["growth"]["forecast"] == []
    assert body["growth"]["measured"], "measured history should be present"


def test_profile_reports_no_maturity_estimate_and_no_summary(client, auth, world):
    """Both are null until the work behind them lands.

    The maturity-offset method is an open ML board item, and the assistant is not wired up. A
    placeholder number on a child's profile reads as a finding, and a fabricated summary is
    exactly the failure this project should not ship.
    """
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).json()
    assert body["maturity"] is None
    assert body["summary"] is None


def test_profile_flags_are_empty_until_the_flag_table_exists(client, auth, world):
    """Not an oversight. See `app/services/flags.py`: there is nowhere to store a flag."""
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).json()
    assert body["flags"] == []
    assert body["flagReason"] is None


def test_profile_provenance_counts_are_computed_server_side(client, auth, world):
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).json()
    assert body["provenance"]["measurementCount"] == 6
    purposes = {row["purpose"] for row in body["provenance"]["consents"]}
    assert {"data_storage", "analytics", "scouting_visibility"} <= purposes


def test_every_percentile_states_its_population(client, auth, world):
    """A percentile without a stated population is meaningless, so the field is not optional."""
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).json()
    for percentile in body["percentiles"]:
        assert percentile["population"].strip()
        assert 1 <= percentile["percentile"] <= 99


def test_sprint_percentile_is_marked_as_lower_being_better(client, auth, world):
    """Getting this backwards would rank the fastest child last on the profile screen."""
    from app.services.cohort import METRIC_DEFINITIONS

    assert METRIC_DEFINITIONS["sprint_10m_s"][2] is False
    assert METRIC_DEFINITIONS["height_cm"][2] is True


# ---------------------------------------------------------------------------
# Cohort statistics
# ---------------------------------------------------------------------------


def test_percentile_clamps_away_from_zero_and_one_hundred():
    """Being the tallest player in the database is not being taller than everyone."""
    from app.services.cohort import percentile_of

    observations = [float(value) for value in range(100)]
    assert percentile_of(observations, -999) == 1
    assert percentile_of(observations, 999) == 99


def test_percentile_of_an_empty_cohort_does_not_divide_by_zero():
    from app.services.cohort import percentile_of

    assert percentile_of([], 170.0) == 50


def test_a_thin_cohort_gets_no_quantiles():
    """Better one bar fewer on the screen than a p75 computed from four people."""
    from app.services.cohort import MIN_COHORT, quantiles

    assert quantiles([1.0, 2.0, 3.0]) is None
    assert quantiles([float(value) for value in range(MIN_COHORT)]) is not None


def test_population_label_names_a_pooled_span_honestly():
    """A cohort pooled across three years must not be reported as a single age."""
    from app.services.cohort import population_label

    assert population_label("male", 14, 14, 30) == "30 boys aged 14 in the database"
    assert population_label("male", 13, 15, 30) == "30 boys aged 13 to 15 in the database"


def test_age_label_shows_months_for_children_only(client, world):
    from datetime import date, timedelta

    from app.services.cohort import age_label

    today = date.today()
    assert age_label(today - timedelta(days=int(14.5 * 365.25)), today) == "14y 6m"
    assert age_label(today - timedelta(days=int(24.5 * 365.25)), today) == "24"
    assert age_label(None, today) == "age unknown"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_query_terms_marked_not_understood_change_nothing(client, auth, world):
    """The contract behind the "How this was read" panel.

    A greyed-out chip means the term was ignored. If it also filtered, the screen would show
    an empty result list while claiming the word had no effect.
    """
    baseline = client.post("/search", json={"query": ""}, headers=auth("scout")).json()
    noisy = client.post(
        "/search", json={"query": "xg potential breakout"}, headers=auth("scout")
    ).json()

    assert noisy["total"] == baseline["total"]
    assert noisy["parsed"]["chips"]
    assert all(chip["understood"] is False for chip in noisy["parsed"]["chips"])


def test_recognised_filters_do_narrow_the_results(client, auth, world):
    baseline = client.post("/search", json={"query": ""}, headers=auth("admin")).json()
    narrowed = client.post(
        "/search", json={"query": "under 16"}, headers=auth("admin")
    ).json()
    assert narrowed["total"] < baseline["total"]
    assert any(chip["label"].startswith("age:") for chip in narrowed["parsed"]["chips"])


def test_every_typed_term_is_accounted_for_in_a_chip(client, auth, world):
    body = client.post(
        "/search", json={"query": "under 17 striker xg zzzz"}, headers=auth("scout")
    ).json()
    labels = [chip["label"] for chip in body["parsed"]["chips"]]
    assert "age: under 17" in labels
    assert "position: ST" in labels
    assert "expected goals: no data" in labels
    assert "name: zzzz" in labels


@pytest.mark.parametrize(
    "query,expected_key",
    [
        ("u15", "age: under 15"),
        ("13 to 15", "age: 13 to 15"),
        ("over 170cm", "height: over 170cm"),
        ("egypt eligible", "eligibility: Egypt"),
        ("goalkeeper", "position: GK"),
    ],
)
def test_query_patterns_parse(query, expected_key):
    from app.services.search import parse_query

    _, chips, _ = parse_query(query)
    assert expected_key in [chip["label"] for chip in chips]


def test_empty_query_produces_no_chips():
    from app.services.search import parse_query

    filters, chips, names = parse_query("   ")
    assert (filters, chips, names) == ({}, [], [])


def test_search_total_counts_all_matches_not_just_the_page(client, auth, world):
    body = client.post(
        "/search", json={"query": "", "limit": 1}, headers=auth("admin")
    ).json()
    assert len(body["results"]) == 1
    assert body["total"] > 1


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def test_comparison_warns_when_the_players_are_years_apart(client, auth, world):
    """An age gap is the thing that makes a side-by-side misleading, so it is said out loud."""
    adult = world["players"]["adult_a"].id
    minor = world["players"]["minor_ok_a"].id
    body = client.get(f"/compare?players={adult},{minor}", headers=auth("coach_a")).json()
    assert body["caveat"]
    assert "years apart" in body["caveat"]


def test_maturity_basis_says_it_is_not_available_rather_than_faking_it(client, auth, world):
    adult = world["players"]["adult_a"].id
    minor = world["players"]["minor_ok_a"].id
    body = client.get(
        f"/compare?players={adult},{minor}&basis=maturity", headers=auth("coach_a")
    ).json()
    assert body["basis"] == "maturity"
    assert "not available" in body["caveat"]


def test_comparison_reports_rather_than_ranks_when_values_are_too_close(client, auth, world):
    """Two players 4mm apart are the same height, and the screen should not rank them."""
    a = world["players"]["minor_ok_a"].id
    b = world["players"]["minor_no_a"].id
    body = client.get(f"/compare?players={a},{b}", headers=auth("coach_a")).json()
    height = next(metric for metric in body["metrics"] if metric["label"] == "Height")
    # The fixture gives both players identical height series.
    assert height["indistinguishable"] is True
    assert height["note"]


def test_comparison_preserves_the_requested_order(client, auth, world):
    a = world["players"]["adult_a"].id
    b = world["players"]["minor_ok_a"].id
    body = client.get(f"/compare?players={b},{a}", headers=auth("coach_a")).json()
    assert [row["player"]["id"] for row in body["players"]] == [str(b), str(a)]


def test_comparison_rejects_a_malformed_id(client, auth, world):
    assert client.get("/compare?players=not-a-uuid,x", headers=auth("admin")).status_code == 400


# ---------------------------------------------------------------------------
# Oversight
# ---------------------------------------------------------------------------


def test_oversight_returns_aggregates_and_no_player_rows(client, auth, world):
    """A broad-read endpoint over a population of children may return counts and nothing else."""
    body = client.get("/oversight", headers=auth("federation")).json()
    serialised = str(body)
    for player in world["players"].values():
        assert player.full_name not in serialised
        assert str(player.id) not in serialised


def test_oversight_region_breakdown_is_empty_because_the_schema_has_no_region(client, auth):
    body = client.get("/oversight", headers=auth("federation")).json()
    assert body["byRegion"] == []


def test_oversight_rejects_an_unknown_sport(client, auth):
    assert client.get("/oversight?sport=quidditch", headers=auth("federation")).status_code == 400


def test_oversight_counts_are_internally_consistent(client, auth, world):
    body = client.get("/oversight", headers=auth("federation")).json()
    assert body["playersTracked"] >= len(world["players"])
    assert 0 <= body["stalePct"] <= 100
    assert body["academiesReporting"] <= len(body["academies"])


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_me_reports_the_resolved_caller(client, auth, world):
    body = client.get("/me", headers=auth("coach_a")).json()
    assert body["role"] == "coach"
    assert body["organizationName"] == "Test Academy A"
    assert body["linkedPlayerId"] is None


def test_me_reports_the_linked_player_for_a_player_account(client, auth, world):
    body = client.get("/me", headers=auth("player_self")).json()
    assert body["linkedPlayerId"] == str(world["players"]["adult_a"].id)
