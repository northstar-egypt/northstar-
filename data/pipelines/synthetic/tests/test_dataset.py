"""Tests for the synthetic generator.

The organising idea: every point raised in review is a test, named after the
thing it protects. If someone changes a generator and reintroduces adults who
keep growing, or a youth-tier 32-year-old, or a match row with more goals than
shots, the suite says so and says which invariant broke.

The dataset is built once per session because building it is the expensive part
and every test reads the same one.
"""

from __future__ import annotations

import collections
import json
import statistics
import uuid
from datetime import date

import pytest

from data.pipelines.synthetic import growth
from data.pipelines.synthetic.affiliations import find_overlaps
from data.pipelines.synthetic.config import GeneratorConfig
from data.pipelines.synthetic.dataset import build_dataset
from data.pipelines.synthetic.ground_truth import duplicate_pairs, label_vectors
from data.pipelines.synthetic.performance import assert_consistent
from data.pipelines.synthetic.players import MINOR_AGE
from data.pipelines.synthetic.writer import row_to_dict, verify_round_trip

CONFIG = GeneratorConfig()
REFERENCE = CONFIG.population.reference_date


@pytest.fixture(scope="session")
def ds():
    return build_dataset(CONFIG)


@pytest.fixture(scope="session")
def players_by_id(ds):
    return {p.id: p for p in ds.players}


def age_of(player, on: date = REFERENCE) -> float:
    return growth.age_in_years(player.date_of_birth, on)


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_same_seed_produces_identical_data():
    """The committed seed is the whole reason the output can be gitignored."""
    a = build_dataset(GeneratorConfig(seed=99))
    b = build_dataset(GeneratorConfig(seed=99))
    assert [p.full_name for p in a.players] == [p.full_name for p in b.players]
    assert [str(p.id) for p in a.players] == [str(p.id) for p in b.players]
    assert a.ground_truth["labels"] == b.ground_truth["labels"]


def test_different_seeds_produce_different_data():
    a = build_dataset(GeneratorConfig(seed=1))
    b = build_dataset(GeneratorConfig(seed=2))
    assert [p.full_name for p in a.players] != [p.full_name for p in b.players]


# ---------------------------------------------------------------------------
# Demographics: tier, minors, eligibility
# ---------------------------------------------------------------------------


def test_tier_is_consistent_with_age(ds):
    """No youth-tier adults, and no pro-tier children."""
    for player in ds.players:
        age = age_of(player)
        if player.tier == "youth":
            assert age < MINOR_AGE, f"{player.full_name} is {age:.1f} and youth tier"
        if player.tier == "pro":
            assert age >= MINOR_AGE, f"{player.full_name} is {age:.1f} and pro tier"


def test_is_minor_matches_date_of_birth(ds):
    for player in ds.players:
        assert player.is_minor == (age_of(player) < MINOR_AGE)


def test_population_is_weighted_toward_minors(ds):
    minors = sum(1 for p in ds.players if p.is_minor)
    share = minors / len(ds.players)
    assert share > 0.5, f"only {share:.0%} of players are minors"


def test_egypt_eligibility_is_not_hardcoded(ds):
    values = {p.is_egypt_eligible for p in ds.players}
    assert values == {True, False}, "is_egypt_eligible must vary, not be constant"
    ineligible = [p for p in ds.players if not p.is_egypt_eligible]
    # A player who is not Egypt-eligible should not be carrying Egyptian
    # nationality; that combination is what the flag exists to rule out.
    for player in ineligible:
        assert "EG" not in player.nationality


def test_diaspora_tier_is_populated(ds):
    tiers = collections.Counter(p.tier for p in ds.players)
    assert tiers["diaspora"] > 0
    assert tiers["youth"] > 0
    assert tiers["pro"] > 0


def test_names_are_egyptian(ds):
    """Faker's ar_EG locale has no person provider; see names.py.

    Checking for Arabic script is the cheapest way to assert that the fallback to
    en_US did not silently come back.
    """
    def is_arabic(text: str) -> bool:
        return any("؀" <= ch <= "ۿ" for ch in text)

    assert all(is_arabic(p.full_name) for p in ds.players)
    assert all(is_arabic(u.full_name) for u in ds.users)


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------


def test_adults_do_not_grow(ds, players_by_id):
    """The review's clearest symptom: 14 players over 21 all gaining height."""
    series = collections.defaultdict(list)
    for m in ds.measurements:
        if m.metric == "height_cm":
            series[m.player_id].append((m.measured_at, float(m.value)))

    deltas = []
    for pid, points in series.items():
        if age_of(players_by_id[pid]) <= 22:
            continue
        points.sort()
        if len(points) >= 2:
            deltas.append(points[-1][1] - points[0][1])

    assert deltas, "no adult players with a measurement history"
    # Individual readings still move, because measurements have noise. What must
    # not happen is a systematic upward drift.
    assert abs(statistics.mean(deltas)) < 0.35, (
        f"adults drift by {statistics.mean(deltas):+.2f} cm on average"
    )
    assert max(deltas) < 3.0, "an adult gained more than noise can explain"


def test_growth_scales_with_elapsed_time(ds, players_by_id):
    """Two readings a week apart must not move as much as two a year apart."""
    short, long = [], []
    series = collections.defaultdict(list)
    for m in ds.measurements:
        if m.metric == "height_cm":
            series[m.player_id].append((m.measured_at, float(m.value)))

    for pid, points in series.items():
        player = players_by_id[pid]
        if not (11 <= age_of(player) <= 15):
            continue
        points.sort()
        for (d0, h0), (d1, h1) in zip(points, points[1:]):
            gap = (d1 - d0).days
            if gap <= 35:
                short.append(h1 - h0)
            elif gap >= 120:
                long.append(h1 - h0)

    assert short and long
    assert statistics.mean(long) > 2 * statistics.mean(short), (
        "growth over long gaps is not proportionally larger than over short ones"
    )


def test_height_and_weight_are_coherent(ds):
    by_player_date = collections.defaultdict(dict)
    for m in ds.measurements:
        by_player_date[(m.player_id, m.measured_at)][m.metric] = float(m.value)
    for metrics in by_player_date.values():
        if "height_cm" in metrics and "weight_kg" in metrics:
            bmi = metrics["weight_kg"] / (metrics["height_cm"] / 100) ** 2
            assert 11 < bmi < 34, f"implausible BMI {bmi:.1f}"


def test_growth_curve_is_monotone_and_saturates():
    previous = 0.0
    for age in [x / 4 for x in range(0, 120)]:
        value = growth.height_fraction(age, "male")
        assert value >= previous - 1e-9
        previous = value
    assert growth.height_fraction(25, "male") == growth.height_fraction(40, "male") == 1.0


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------


def test_ordinary_match_rows_are_internally_consistent(ds):
    """Every row except the deliberately planted, labelled fraud rows."""
    planted = set(ds.ground_truth["flagged_performance_entry_ids"])
    checked = 0
    for entry in ds.performance_entries:
        if entry.schema_ref != "football.match.v1":
            continue
        if str(entry.id) in planted:
            continue  # planted, labelled, and expected to be impossible
        assert_consistent(entry.metrics)
        checked += 1
    assert checked > 100


def test_zero_minutes_means_zero_of_everything(ds):
    planted = set(ds.ground_truth["flagged_performance_entry_ids"])
    for entry in ds.performance_entries:
        if entry.metrics.get("minutes_played") != 0:
            continue
        if str(entry.id) in planted:
            continue
        assert all(
            v == 0
            for k, v in entry.metrics.items()
            if k != "minutes_played" and isinstance(v, (int, float))
        )


def test_planted_metric_fraud_rows_actually_are_impossible(ds):
    """The labelled bad rows must genuinely violate the invariants.

    A label that points at a perfectly ordinary row is worse than no label.
    """
    planted = set(ds.ground_truth["flagged_performance_entry_ids"])
    assert planted, "no performance rows were flagged as planted"
    offenders = 0
    for entry in ds.performance_entries:
        if str(entry.id) in planted:
            with pytest.raises(AssertionError):
                assert_consistent(entry.metrics)
            offenders += 1
    assert offenders == len(planted)


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


def test_foreign_keys_resolve(ds):
    player_ids = {p.id for p in ds.players}
    org_ids = {o.id for o in ds.organizations}
    user_ids = {u.id for u in ds.users}

    for m in ds.measurements:
        assert m.player_id in player_ids
        assert m.recorded_by is None or m.recorded_by in user_ids
    for e in ds.performance_entries:
        assert e.player_id in player_ids
        assert e.organization_id is None or e.organization_id in org_ids
        assert e.opponent_org_id is None or e.opponent_org_id in org_ids
    for a in ds.affiliations:
        assert a.player_id in player_ids
        assert a.organization_id in org_ids
    for c in ds.consents:
        assert c.player_id in player_ids
    for u in ds.users:
        assert u.organization_id is None or u.organization_id in org_ids
        assert u.linked_player_id is None or u.linked_player_id in player_ids
    for log in ds.audit_logs:
        assert log.actor_user_id is None or log.actor_user_id in user_ids
    for o in ds.organizations:
        assert o.parent_org_id is None or o.parent_org_id in org_ids
    for p in ds.players:
        assert p.merged_into is None or p.merged_into in player_ids


def test_measurements_are_recorded_by_coaches_or_admins(ds):
    users = {u.id: u for u in ds.users}
    for m in ds.measurements:
        if m.recorded_by:
            assert users[m.recorded_by].role in ("coach", "admin")


def test_opponent_is_never_the_home_org(ds):
    for e in ds.performance_entries:
        if e.organization_id and e.opponent_org_id:
            assert e.organization_id != e.opponent_org_id


def test_linked_player_id_is_unique(ds):
    linked = [u.linked_player_id for u in ds.users if u.linked_player_id]
    assert len(linked) == len(set(linked))


def test_no_overlapping_active_affiliations(ds):
    """docs/schema.md wants this; PlayerOrganization leaves it as a TODO."""
    assert find_overlaps(ds.affiliations) == []


def test_affiliation_dates_are_ordered(ds):
    for a in ds.affiliations:
        assert a.end_date is None or a.end_date > a.start_date


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def test_minors_consent_requires_a_named_guardian(ds):
    minor_ids = {p.id for p in ds.players if p.is_minor}
    minor_consents = [c for c in ds.consents if c.player_id in minor_ids]
    assert minor_consents
    for c in minor_consents:
        assert c.guardian_name, "a minor's consent has no guardian"
        assert c.granted_by.startswith("guardian:")


def test_adults_consent_for_themselves(ds):
    adult_ids = {p.id for p in ds.players if not p.is_minor}
    for c in ds.consents:
        if c.player_id in adult_ids:
            assert c.guardian_name is None
            assert c.granted_by == "player"


# ---------------------------------------------------------------------------
# Planted ground truth
# ---------------------------------------------------------------------------


def test_all_three_detectors_have_positives(ds):
    labels = ds.ground_truth["labels"]
    for detector in ("late_bloomer", "fraud", "duplicate"):
        assert labels[detector], f"{detector} has no planted positives to score against"


def test_labelled_ids_exist_in_the_population(ds):
    population = set(ds.ground_truth["population"]["player_ids"])
    for detector, ids in ds.ground_truth["labels"].items():
        assert set(ids) <= population, f"{detector} labels reference unknown players"


def test_label_sets_are_disjoint(ds):
    """One planted player carries one label, so the answer key is unambiguous."""
    labels = ds.ground_truth["labels"]
    late, fraud, dupe = (set(labels[k]) for k in ("late_bloomer", "fraud", "duplicate"))
    assert late & fraud == set()
    assert late & dupe == set()
    assert fraud & dupe == set()


def test_duplicates_include_merged_and_unresolved(ds):
    """Both are needed: merged rows exercise the status, unresolved ones are the task."""
    clusters = ds.ground_truth["cases"]["duplicates"]
    assert any(c["resolved"] for c in clusters)
    assert any(not c["resolved"] for c in clusters)

    merged = [p for p in ds.players if p.status == "merged"]
    assert merged, 'no player has status="merged"'
    for player in merged:
        assert player.merged_into is not None


def test_duplicate_pairs_really_are_similar(ds, players_by_id):
    """A labelled duplicate pair must be recognisably the same person."""
    for a_id, b_id in duplicate_pairs(ds.ground_truth):
        a = players_by_id[uuid.UUID(a_id)]
        b = players_by_id[uuid.UUID(b_id)]
        assert a.sex == b.sex
        assert a.primary_sport == b.primary_sport
        assert abs((a.date_of_birth - b.date_of_birth).days) <= 400
        # Same person, so at least the family name survives both spellings.
        assert set(a.full_name.split()) & set(b.full_name.split())


def test_age_fraud_cases_carry_a_real_biometric_signal(ds, players_by_id):
    """The planted lie must show up in the data, not only in the label.

    A fraud case is a player whose body was generated from an older age than the
    one recorded. Their height should therefore sit above what their recorded age
    predicts. If it does not, the label is asserting something the data does not
    contain and any detector scored against it is being scored on noise.
    """
    fraud = [
        c
        for c in ds.ground_truth["cases"]["fraud"]
        if c["fraud_type"] == "age_misrepresentation"
    ]
    assert fraud

    latest_height = {}
    for m in ds.measurements:
        if m.metric != "height_cm":
            continue
        current = latest_height.get(m.player_id)
        if current is None or m.measured_at > current[0]:
            latest_height[m.player_id] = (m.measured_at, float(m.value))

    flagged = 0
    for case in fraud:
        player = players_by_id[uuid.UUID(case["player_id"])]
        when, observed = latest_height[player.id]
        recorded_age = growth.age_in_years(player.date_of_birth, when)
        expected = growth.height_cm(
            recorded_age, player.sex, growth.ADULT_HEIGHT_MEAN_CM[player.sex]
        )
        if observed > expected:
            flagged += 1
    # Not every case has to be a visible outlier - a 14-month understatement on
    # an already-tall player may not be - but most should be, or the planted
    # signal is too weak to score against.
    assert flagged >= 0.7 * len(fraud), (
        f"only {flagged}/{len(fraud)} age-fraud cases are taller than their stated age predicts"
    )


def test_late_bloomers_are_short_for_their_age(ds, players_by_id):
    cases = ds.ground_truth["cases"]["late_bloomers"]
    assert cases
    for case in cases:
        assert case["maturity_offset_years"] > 1.0
        assert case["height_deficit_cm_at_14"] > 0


def test_label_vectors_align_with_the_player_list(ds):
    ids = ds.ground_truth["population"]["player_ids"]
    vectors = label_vectors(ds.ground_truth, ids)
    for detector, vector in vectors.items():
        assert len(vector) == len(ids)
        assert sum(vector) == len(ds.ground_truth["labels"][detector])


def test_ground_truth_is_json_serialisable(ds):
    payload = json.dumps(ds.ground_truth, ensure_ascii=False)
    assert json.loads(payload)["labels"]


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------


def test_rows_round_trip_through_their_models(ds):
    """The regression test for the metadata / event_metadata bug.

    `AuditLog(**row)` raised because the JSON used the column name rather than
    the attribute name. Serialising through the mapper and rebuilding the model
    is what makes that class of mistake impossible.
    """
    verify_round_trip(ds)


def test_audit_log_uses_the_renamed_attribute(ds):
    from data.pipelines.synthetic.orm import AuditLog

    row = row_to_dict(ds.audit_logs[0])
    assert "event_metadata" in row
    assert "metadata" not in row
    AuditLog(**row)  # must not raise


def test_no_real_looking_credentials(ds):
    """CLAUDE.md: no secrets in anything committed."""
    for user in ds.users:
        assert user.password_hash.startswith("$synthetic$")
        assert user.email.endswith("@northstar.test")
