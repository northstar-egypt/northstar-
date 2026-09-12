"""Planted ground truth: the labelled cases the three detectors are scored on.

This module is the reason the dataset is worth generating. Precision, recall and
F1 are not properties of a model, they are properties of a model *and a labelled
set*. Without known positives there is no recall, and the ML track's evaluation
harness has nothing to report.

The design principle throughout is **generate causally, then label**. A planted
age-fraud case is not "a normal player with the height column nudged up". It is a
player whose body and performance were generated from their true age, with a
younger date of birth recorded against them. Every downstream signal a detector
might use, biometric outlier for stated age, dominance over the stated age
group, a maturity profile that does not fit the cohort, appears on its own,
because the underlying lie is real. Labelling a hand-nudged column teaches a
detector to find the nudge; labelling a real inconsistency teaches it to find the
inconsistency.

Three case types, matching the three detectors:

late bloomer   a delayed maturity offset: short for the cohort at 13-15, then a
               steep spurt and full catch-up. Forecasters trained on the flat
               early series systematically under-predict them.
age fraud      recorded date of birth younger than the true one, plus a small
               number of players carrying deliberately implausible match rows.
duplicate      the same human entered twice, differing by Arabic orthography, a
               dropped grandfather's name, a date of birth off by a few days, and
               different external ids. Some clusters are left unresolved for the
               detector to find; the rest are already merged, which is what puts
               `status="merged"` and `merged_into` into the data at all.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import timedelta

from . import growth
from .config import GeneratorConfig
from .orm import Player, enums
from .players import MINOR_AGE, PlayerProfile
from .reference import drop_middle_name, orthographic_variant
from .rng import Rng


@dataclass
class LateBloomerCase:
    player_id: str
    maturity_offset_years: float
    height_deficit_cm_at_14: float
    projected_adult_height_cm: float

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "maturity_offset_years": round(self.maturity_offset_years, 2),
            "height_deficit_cm_at_14": round(self.height_deficit_cm_at_14, 1),
            "projected_adult_height_cm": round(self.projected_adult_height_cm, 1),
        }


@dataclass
class FraudCase:
    player_id: str
    fraud_type: str
    signals: list[str]
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "fraud_type": self.fraud_type,
            "signals": self.signals,
            "detail": self.detail,
        }


@dataclass
class DuplicateCluster:
    cluster_id: str
    player_ids: list[str]
    canonical_player_id: str
    resolved: bool
    variations: list[str]

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "player_ids": self.player_ids,
            "canonical_player_id": self.canonical_player_id,
            "resolved": self.resolved,
            "variations": self.variations,
        }


@dataclass
class PlantedCases:
    late_bloomers: list[LateBloomerCase] = field(default_factory=list)
    fraud: list[FraudCase] = field(default_factory=list)
    duplicates: list[DuplicateCluster] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Late bloomers
# ---------------------------------------------------------------------------


def plant_late_bloomers(
    rng: Rng, config: GeneratorConfig, profiles: list[PlayerProfile]
) -> list[LateBloomerCase]:
    """Delay maturity for a known set of adolescents.

    Only players who are still on the steep part of the curve are eligible: a
    24-year-old cannot be a late bloomer, because the phenomenon is about *when*
    the spurt arrived and theirs already did.
    """
    reference = config.population.reference_date
    eligible = [
        p
        for p in profiles
        if 11.5 <= p.recorded_age(reference) <= 17.0 and not p.is_planted_age_fraud
    ]
    chosen = rng.sample(eligible, config.planted.n_late_bloomers)

    cases: list[LateBloomerCase] = []
    for profile in chosen:
        offset = rng.uniform(1.3, 2.6)
        profile.maturity_offset_years = offset
        profile.is_planted_late_bloomer = True
        # Late maturers grow for longer and tend to end up slightly taller.
        profile.adult_height_cm += rng.uniform(0.5, 3.5)

        normal_at_14 = growth.height_cm(14.0, profile.sex, profile.adult_height_cm, 0.0)
        delayed_at_14 = growth.height_cm(14.0, profile.sex, profile.adult_height_cm, offset)

        cases.append(
            LateBloomerCase(
                player_id=str(profile.id),
                maturity_offset_years=offset,
                height_deficit_cm_at_14=normal_at_14 - delayed_at_14,
                projected_adult_height_cm=profile.adult_height_cm,
            )
        )
    return cases


# ---------------------------------------------------------------------------
# Age fraud
# ---------------------------------------------------------------------------


def plant_age_fraud(
    rng: Rng, config: GeneratorConfig, profiles: list[PlayerProfile]
) -> list[FraudCase]:
    """Record a younger date of birth than the player's real one.

    The player's `true_date_of_birth` stays as generated, so the measurement and
    performance generators keep producing a body and a season that belong to the
    older age. Only `player.date_of_birth` moves. Everything a detector would
    flag follows from that single edit.
    """
    cfg = config.planted
    reference = config.population.reference_date
    # The fraud that matters is a player passing as a youth. Candidates are
    # players whose true age is near or just over the age-group boundaries.
    eligible = [
        p
        for p in profiles
        if 14.0 <= p.true_age(reference) <= 21.0 and not p.is_planted_late_bloomer
    ]
    chosen = rng.sample(eligible, cfg.n_age_fraud)

    cases: list[FraudCase] = []
    for profile in chosen:
        inflation = rng.uniform(*cfg.fraud_age_inflation_years)
        recorded_dob = profile.true_date_of_birth + timedelta(
            days=int(inflation * growth.DAYS_PER_YEAR)
        )
        player = profile.player
        player.date_of_birth = recorded_dob
        profile.is_planted_age_fraud = True

        recorded_age = profile.recorded_age(reference)
        player.is_minor = recorded_age < MINOR_AGE
        player.tier = (
            enums.FootballTier.DIASPORA.value
            if profile.notes.get("based_abroad")
            else (
                enums.FootballTier.YOUTH.value
                if recorded_age < MINOR_AGE
                else enums.FootballTier.PRO.value
            )
        )

        signals = ["biometric_outlier_for_stated_age", "performance_outlier_for_stated_age"]
        # Real age-fraud cases usually come with paperwork problems too. Roughly
        # half get one, so a detector cannot simply key on the document field.
        if rng.chance(0.5):
            player.external_ids = dict(player.external_ids or {})
            player.external_ids["federation_ref"] = f"EFA-{rng.randint(10000, 99999)}"
            player.external_ids["footystats"] = f"FS{rng.randint(100000, 999999)}"
            signals.append("conflicting_external_ids")

        cases.append(
            FraudCase(
                player_id=str(player.id),
                fraud_type="age_misrepresentation",
                signals=signals,
                detail={
                    "recorded_date_of_birth": recorded_dob.isoformat(),
                    "true_date_of_birth": profile.true_date_of_birth.isoformat(),
                    "years_understated": round(inflation, 2),
                    "recorded_age_at_reference": round(recorded_age, 2),
                    "true_age_at_reference": round(profile.true_age(reference), 2),
                },
            )
        )
    return cases


def plant_metric_fraud(
    rng: Rng, config: GeneratorConfig, profiles: list[PlayerProfile]
) -> list[FraudCase]:
    """Mark a few players as carriers of implausible self-reported match rows.

    The rows themselves are injected after performance generation (see
    `inject_metric_fraud_rows`). This is the crude end of the fraud spectrum:
    self-submitted entries whose numbers do not survive arithmetic. It exists so
    the detector has an easy class as well as a hard one, and so the easy class
    is *labelled* rather than being indistinguishable from generator bugs.
    """
    eligible = [
        p for p in profiles if not p.is_planted_age_fraud and not p.is_planted_late_bloomer
    ]
    chosen = rng.sample(eligible, config.planted.n_metric_fraud_players)
    for profile in chosen:
        profile.is_planted_metric_fraud = True
    return [
        FraudCase(
            player_id=str(p.id),
            fraud_type="implausible_self_reported_performance",
            signals=["self_submitted_only", "impossible_metric_combination"],
            detail={},
        )
        for p in chosen
    ]


def inject_metric_fraud_rows(
    rng: Rng,
    config: GeneratorConfig,
    profiles: list[PlayerProfile],
    entries: list,
    cases: list[FraudCase],
) -> list:
    """Add the implausible rows for players marked by `plant_metric_fraud`.

    These rows deliberately violate the invariants in `performance.assert_consistent`.
    That is the whole point, and it is why they are injected here rather than
    generated in `performance.py`: everything that module produces is consistent
    by construction, and the only inconsistent rows in the dataset are the ones
    that are labelled as fraud.

    The id of every injected row is recorded on its case. A carrier also has
    perfectly ordinary rows, so "this player has a self-submitted entry" does not
    identify the planted ones; a detector that works row by row needs to be
    scored against the rows themselves.
    """
    from .orm import PerformanceEntry

    reference = config.population.reference_date
    carriers = [p for p in profiles if p.is_planted_metric_fraud]
    by_player = {}
    for e in entries:
        by_player.setdefault(e.player_id, e)
    case_by_player = {
        c.player_id: c
        for c in cases
        if c.fraud_type == "implausible_self_reported_performance"
    }

    new_rows = []
    for profile in carriers:
        template = by_player.get(profile.id)
        case = case_by_player.get(str(profile.id))
        injected_ids: list[str] = []
        for _ in range(rng.randint(2, 4)):
            shots = rng.randint(1, 4)
            metrics = {
                "minutes_played": rng.choice([0, 12, 90]),
                "shots": shots,
                # More goals than shots: arithmetically impossible.
                "shots_on_target": shots,
                "goals": shots + rng.randint(1, 3),
                "assists": rng.randint(2, 5),
                "key_passes": rng.randint(0, 2),
                "passes_attempted": rng.randint(10, 30),
                "passes_completed": rng.randint(31, 60),  # more completed than attempted
                "tackles": rng.randint(0, 4),
                "distance_km": round(rng.uniform(14.5, 19.0), 2),  # beyond human range
                "yellow_cards": 0,
                "red_cards": 0,
            }
            entry_id = rng.uuid()
            injected_ids.append(str(entry_id))
            new_rows.append(
                PerformanceEntry(
                    id=entry_id,
                    player_id=profile.id,
                    sport=profile.player.primary_sport,
                    period_type=enums.PeriodType.MATCH.value,
                    period_start=reference - timedelta(days=rng.randint(0, 400)),
                    period_end=None,
                    organization_id=template.organization_id if template else None,
                    opponent_org_id=template.opponent_org_id if template else None,
                    metrics=metrics,
                    schema_ref="football.match.v1",
                    source=enums.PerformanceSource.SELF_SUBMITTED.value,
                    is_validated=False,
                )
            )
        if case is not None:
            case.detail["performance_entry_ids"] = injected_ids
    return new_rows


# ---------------------------------------------------------------------------
# Duplicate identities
# ---------------------------------------------------------------------------


def plant_duplicates(
    rng: Rng, config: GeneratorConfig, profiles: list[PlayerProfile]
) -> tuple[list[PlayerProfile], list[DuplicateCluster]]:
    """Clone players into near-identical second records.

    The clone is a new `PlayerProfile` sharing the original's biology, so its
    measurements and performance are consistent with the same human. That is what
    makes it a genuine duplicate rather than two unrelated players who happen to
    share a name, and it is what a duplicate detector should be able to see.
    """
    cfg = config.planted
    # Players already carrying another planted label are excluded. A duplicate of
    # a late bloomer would be physiologically a late bloomer too, and would then
    # need to appear in two label sets at once; keeping each planted player to a
    # single case type keeps the answer key unambiguous.
    eligible = [
        p
        for p in profiles
        if not p.is_planted_age_fraud
        and not p.is_planted_metric_fraud
        and not p.is_planted_late_bloomer
    ]
    chosen = rng.sample(eligible, cfg.n_duplicate_clusters)

    clones: list[PlayerProfile] = []
    clusters: list[DuplicateCluster] = []

    for i, original in enumerate(chosen):
        resolved = rng.chance(cfg.resolved_duplicate_fraction)
        variations: list[str] = []

        name = original.player.full_name
        if rng.chance(0.85):
            name = orthographic_variant(name, rng)
            variations.append("arabic_orthography")
        if rng.chance(0.45):
            name = drop_middle_name(name, rng)
            variations.append("dropped_name_part")

        dob = original.player.date_of_birth
        if rng.chance(0.6):
            shift = rng.randint(1, 4) * rng.choice([-1, 1])
            dob = dob + timedelta(days=shift)
            variations.append("date_of_birth_off_by_days")
        if rng.chance(0.25):
            # The classic: day and month transposed on re-entry.
            try:
                dob = dob.replace(day=dob.month, month=dob.day)
                variations.append("day_month_transposed")
            except ValueError:
                pass

        external_ids = {}
        if rng.chance(0.7):
            external_ids["footystats"] = f"FS{rng.randint(100000, 999999)}"
            variations.append("different_external_ids")

        cluster_id = f"dup-{i + 1:03d}"
        clone_player = Player(
            id=rng.uuid(),
            full_name=name,
            known_as=None if rng.chance(0.6) else original.player.known_as,
            date_of_birth=dob,
            sex=original.player.sex,
            nationality=list(original.player.nationality),
            is_egypt_eligible=original.player.is_egypt_eligible,
            primary_sport=original.player.primary_sport,
            tier=original.player.tier,
            position=(
                original.player.position
                if rng.chance(0.75)
                else None  # the second clerk left it blank
            ),
            is_minor=original.player.is_minor,
            external_ids=external_ids,
            status=(
                enums.PlayerStatus.MERGED.value
                if resolved
                else enums.PlayerStatus.ACTIVE.value
            ),
            merged_into=original.id if resolved else None,
        )
        if not variations:
            variations.append("exact_name_match")

        clone_profile = PlayerProfile(
            player=clone_player,
            true_date_of_birth=original.true_date_of_birth,
            sex=original.sex,
            adult_height_cm=original.adult_height_cm,
            build_offset=original.build_offset,
            talent_offset=original.talent_offset,
            maturity_offset_years=original.maturity_offset_years,
            ability=original.ability,
            position=clone_player.position or original.position,
            is_planted_late_bloomer=original.is_planted_late_bloomer,
            duplicate_cluster_id=cluster_id,
            notes=copy.deepcopy(original.notes),
        )
        original.duplicate_cluster_id = cluster_id

        clones.append(clone_profile)
        clusters.append(
            DuplicateCluster(
                cluster_id=cluster_id,
                player_ids=[str(original.id), str(clone_player.id)],
                canonical_player_id=str(original.id),
                resolved=resolved,
                variations=sorted(set(variations)),
            )
        )

    return clones, clusters
