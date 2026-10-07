"""Orchestration: build the whole dataset, in dependency order.

The order below is not arbitrary and changing it changes the data:

1. organizations, because affiliations need somewhere to point
2. players, the base population
3. planted age fraud, which rewrites `date_of_birth` and must happen before any
   measurement or performance row is generated from it
4. planted late bloomers, which set the maturity offset the growth curves read
5. planted metric-fraud carriers (marking only; the rows come at step 10)
6. duplicate clones, which are added to the population and then generate their
   own measurements and performance like any other player
7. users, because measurements carry `recorded_by`
8. affiliations, because performance entries carry the player's organization
9. measurements and performance
10. injected fraud rows, consent and audit
11. optionally, simulated release at 14 (attrition.py), off by default
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .accounts import generate_audit_log, generate_consents, generate_users
from .attrition import apply_attrition
from .affiliations import generate_affiliations
from .config import GeneratorConfig
from .ground_truth import build as build_ground_truth
from .measurements import generate_measurements
from .orm import enums
from .organizations import generate_organizations
from .performance import generate_performance_entries
from .planted import (
    PlantedCases,
    inject_metric_fraud_rows,
    plant_age_fraud,
    plant_duplicates,
    plant_late_bloomers,
    plant_metric_fraud,
)
from .players import PlayerProfile, generate_players
from .rng import Rng


@dataclass
class Dataset:
    """Every row, as ORM instances, plus the answer key."""

    organizations: list = field(default_factory=list)
    players: list = field(default_factory=list)
    affiliations: list = field(default_factory=list)
    measurements: list = field(default_factory=list)
    performance_entries: list = field(default_factory=list)
    users: list = field(default_factory=list)
    consents: list = field(default_factory=list)
    audit_logs: list = field(default_factory=list)

    profiles: list[PlayerProfile] = field(default_factory=list)
    cases: PlantedCases = field(default_factory=PlantedCases)
    ground_truth: dict = field(default_factory=dict)

    def counts(self) -> dict:
        return {
            "organizations": len(self.organizations),
            "players": len(self.players),
            "affiliations": len(self.affiliations),
            "measurements": len(self.measurements),
            "performance_entries": len(self.performance_entries),
            "users": len(self.users),
            "consents": len(self.consents),
            "audit_logs": len(self.audit_logs),
        }

    # Insert order for the database: parents before children.
    def in_insert_order(self) -> list[tuple[str, list]]:
        return [
            ("organizations", self.organizations),
            ("players", self.players),
            ("users", self.users),
            ("affiliations", self.affiliations),
            ("measurements", self.measurements),
            ("performance_entries", self.performance_entries),
            ("consents", self.consents),
            ("audit_logs", self.audit_logs),
        ]


def build_dataset(config: GeneratorConfig) -> Dataset:
    rng = Rng(config.seed, config.name_locale)
    ds = Dataset()

    ds.organizations = generate_organizations(rng, config)
    ds.profiles = generate_players(rng, config)

    cases = PlantedCases()
    cases.fraud = plant_age_fraud(rng, config, ds.profiles)
    cases.late_bloomers = plant_late_bloomers(rng, config, ds.profiles)
    cases.fraud += plant_metric_fraud(rng, config, ds.profiles)

    clones, clusters = plant_duplicates(rng, config, ds.profiles)
    ds.profiles.extend(clones)
    cases.duplicates = clusters

    ds.players = [p.player for p in ds.profiles]

    ds.users = generate_users(rng, config, ds.profiles, ds.organizations)
    ds.affiliations, current_org = generate_affiliations(
        rng, config, ds.profiles, ds.organizations
    )
    ds.measurements = generate_measurements(rng, config, ds.profiles, ds.users)
    ds.performance_entries = generate_performance_entries(
        rng, config, ds.profiles, ds.organizations, current_org
    )
    injected = inject_metric_fraud_rows(
        rng, config, ds.profiles, ds.performance_entries, cases.fraud
    )
    ds.performance_entries += injected
    releases = []
    if config.attrition:
        # Last among the row generators, and on its own random stream, so the default
        # dataset is byte-identical whether or not this module exists. The planted fraud
        # rows are exempt: they are in the answer key, and a released player can still
        # self-submit.
        injected_ids = {row.id for row in injected}
        ds.measurements, kept, releases = apply_attrition(
            config,
            ds.profiles,
            ds.measurements,
            [e for e in ds.performance_entries if e.id not in injected_ids],
        )
        ds.performance_entries = kept + injected
    ds.consents = generate_consents(rng, config, ds.profiles)
    ds.audit_logs = generate_audit_log(rng, config, ds.users, ds.profiles)

    ds.cases = cases
    ds.ground_truth = build_ground_truth(
        cases,
        seed=config.seed,
        counts=ds.counts(),
        all_player_ids=[str(p.id) for p in ds.players],
        table_tennis_ability={
            str(p.id): round(p.effective_ability(config.population.reference_date), 4)
            for p in ds.profiles
            if p.player.primary_sport == enums.Sport.TABLE_TENNIS.value
        },
    )
    if config.attrition:
        ds.ground_truth["attrition"] = {
            "description": (
                "Players released at their age-14 review, with every measurement and "
                "performance row after the review removed. See attrition.py."
            ),
            "released": [case.to_dict() for case in releases],
        }
    return ds
