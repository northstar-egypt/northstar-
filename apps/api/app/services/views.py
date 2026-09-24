"""Assembling the view models the screens ask for.

Each function here turns rows into one of the shapes in `app.schemas.views`. They are kept
out of the routers so the routers stay about HTTP, and out of the models so the models stay
about the schema.

Two rules hold throughout, both taken from `apps/web/lib/api.ts`:

  Aggregates are computed here. The web app must never fetch rows in order to count them, so
  anything that is a count, a median or a percentage is computed before the response leaves.

  Whatever the caller may not see is not sent. `app.services.access` decides; this module
  applies. There is no field that arrives and is then hidden by the frontend.
"""

from __future__ import annotations

import statistics
import uuid
from datetime import date, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.enums import ConsentPurpose, PlayerStatus
from app.models.measurement import Measurement
from app.models.organization import Organization
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.services import cohort, flags
from app.services.access import Caller, consent_complete, consent_state, may_view, permissions

# How many recent height readings the squad sparkline shows.
TREND_POINTS = 6

# A squad row is "stale" past this. The oversight screen counts them.
STALE_AFTER_DAYS = 90


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def current_organization(db: Session, player_id: uuid.UUID) -> Organization | None:
    """The organization a player is currently at, if any."""
    return db.execute(
        select(Organization)
        .join(PlayerOrganization, PlayerOrganization.organization_id == Organization.id)
        .where(PlayerOrganization.player_id == player_id)
        .where(PlayerOrganization.end_date.is_(None))
        .order_by(PlayerOrganization.start_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def organization_names(db: Session, player_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Current organization name per player, in one query rather than one per row."""
    if not player_ids:
        return {}
    rows = db.execute(
        select(PlayerOrganization.player_id, Organization.name)
        .join(Organization, Organization.id == PlayerOrganization.organization_id)
        .where(PlayerOrganization.player_id.in_(player_ids))
        .where(PlayerOrganization.end_date.is_(None))
    ).all()
    return {player_id: name for player_id, name in rows}


def measurement_series(
    db: Session, player_ids: list[uuid.UUID], metric: str
) -> dict[uuid.UUID, list[tuple[date, float]]]:
    """Ascending (date, value) series per player for one metric, in one query."""
    if not player_ids:
        return {}
    rows = db.execute(
        select(Measurement.player_id, Measurement.measured_at, Measurement.value)
        .where(Measurement.player_id.in_(player_ids))
        .where(Measurement.metric == metric)
        .order_by(Measurement.player_id, Measurement.measured_at)
    ).all()
    series: dict[uuid.UUID, list[tuple[date, float]]] = {}
    for player_id, measured_at, value in rows:
        if value is not None:
            series.setdefault(player_id, []).append((measured_at, float(value)))
    return series


def latest_value(series: list[tuple[date, float]] | None) -> float | None:
    return series[-1][1] if series else None


# ---------------------------------------------------------------------------
# Squad
# ---------------------------------------------------------------------------


def build_squad(db: Session, caller: Caller, stmt: Select) -> list[dict]:
    """The coach's squad table.

    Everything the table needs travels with the row. Days since the last log and the
    sparkline are the two that would otherwise become a request per player, which is what the
    TODO in `apps/web/lib/api.ts` warns about.
    """
    players = list(db.execute(stmt).scalars().unique())
    player_ids = [player.id for player in players]

    heights = measurement_series(db, player_ids, "height_cm")
    org_names = organization_names(db, player_ids)
    flag_map = flags.flags_for_players(db, player_ids)

    last_log = dict(
        db.execute(
            select(Measurement.player_id, func.max(Measurement.measured_at))
            .where(Measurement.player_id.in_(player_ids))
            .group_by(Measurement.player_id)
        ).all()
        if player_ids
        else []
    )

    today = date.today()
    rows: list[dict] = []
    for player in players:
        series = heights.get(player.id, [])
        logged_on = last_log.get(player.id)
        state = consent_state(db, player.id)
        rows.append(
            {
                "player": player,
                "age_label": cohort.age_label(player.date_of_birth, today),
                "height_cm": latest_value(series),
                "days_since_last_log": (today - logged_on).days if logged_on else None,
                "height_trend": [value for _, value in series[-TREND_POINTS:]],
                "flags": flag_map.get(player.id, []),
                "consent_complete": consent_complete(state),
                "_organization_name": org_names.get(player.id),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Player profile
# ---------------------------------------------------------------------------


def build_profile(db: Session, caller: Caller, player: Player) -> dict:
    """Everything the player profile screen renders, already filtered for the caller."""
    today = date.today()
    reference = cohort.get_reference(db)

    heights = measurement_series(db, [player.id], "height_cm").get(player.id, [])
    weights = measurement_series(db, [player.id], "weight_kg").get(player.id, [])
    sprints = measurement_series(db, [player.id], "sprint_10m_s").get(player.id, [])

    age = cohort.age_years(player.date_of_birth, today)

    # Population band behind the growth line: the cohort's p25/p50/p75 at each date the
    # player was actually measured, so the band lines up with their points.
    population: list[dict] = []
    if player.date_of_birth and player.sex:
        for measured_at, _ in heights:
            at_age = (measured_at - player.date_of_birth).days / cohort.DAYS_PER_YEAR
            quantile = cohort.quantiles(
                reference.observations("height_cm", player.sex, at_age)
            )
            if quantile:
                p25, p50, p75 = quantile
                population.append(
                    {"date": measured_at, "p25": p25, "p50": p50, "p75": p75}
                )

    percentiles: list[dict] = []
    if age is not None:
        for metric, series in (
            ("height_cm", heights),
            ("weight_kg", weights),
            ("sprint_10m_s", sprints),
        ):
            value = latest_value(series)
            if value is None:
                continue
            observations, age_low, age_high = reference.cohort_for(metric, player.sex, age)
            if len(observations) < cohort.MIN_COHORT:
                # Too few comparable players to quote a percentile. Omitting it is the
                # honest move; the screen simply shows one bar fewer.
                continue
            label, unit, higher_is_better = cohort.METRIC_DEFINITIONS[metric]
            percentiles.append(
                {
                    "metric": metric,
                    "label": label,
                    "value": value,
                    "unit": unit,
                    "percentile": cohort.percentile_of(observations, value),
                    "population": cohort.population_label(
                        player.sex, age_low, age_high, len(observations)
                    ),
                    "higher_is_better": higher_is_better,
                }
            )

    performance = list(
        db.execute(
            select(PerformanceEntry)
            .where(PerformanceEntry.player_id == player.id)
            .order_by(PerformanceEntry.period_start.desc())
            .limit(50)
        ).scalars()
    )

    state = consent_state(db, player.id)
    organization = current_organization(db, player.id)

    # Flags are withheld rather than sent-and-hidden. While `flags.py` returned nothing this
    # was moot; now that it returns real rows it is access control, and the rule from
    # apps/web/lib/api.ts applies: if a field must not be seen by the current role, the API
    # must not send it. A player looking at their own record is the case this protects, since
    # there is no route for them to dispute a flag.
    granted = permissions(db, caller, player)
    visible_flags = flags.flags_for_player(db, player.id) if granted["can_see_flags"] else []
    visible_reason = flags.flag_reason(db, player.id) if granted["can_see_flags"] else None

    measurement_count = db.execute(
        select(func.count())
        .select_from(Measurement)
        .where(Measurement.player_id == player.id)
    ).scalar_one()
    performance_count = db.execute(
        select(func.count())
        .select_from(PerformanceEntry)
        .where(PerformanceEntry.player_id == player.id)
    ).scalar_one()

    return {
        "player": player,
        "organization_name": organization.name if organization else None,
        "age_label": cohort.age_label(player.date_of_birth, today),
        "latest": {
            "heightCm": latest_value(heights),
            "weightKg": latest_value(weights),
        },
        "growth": {
            "measured": [{"date": at, "value": value} for at, value in heights],
            # Empty until the forecasting deliverable lands. The screen draws nothing
            # rather than drawing a line, which is right for "we do not know yet".
            "forecast": [],
            "population": population,
            "unit": "cm",
        },
        # The maturity-offset method is an open board item for the ML track. Returning null
        # makes the screen say there is no estimate, which is true, instead of showing a
        # placeholder number that looks like a result.
        "maturity": None,
        "percentiles": percentiles,
        "performance": performance,
        "flags": visible_flags,
        "flag_reason": visible_reason,
        # The assistant summary is generated by the Ollama-hosted model, which is not wired
        # up. Null rather than a stub sentence: a fabricated summary on a child's profile is
        # exactly the failure this project should not ship.
        "summary": None,
        "provenance": {
            "measurement_count": measurement_count,
            "performance_count": performance_count,
            "consents": [
                {"purpose": purpose, "granted": granted} for purpose, granted in state.items()
            ],
        },
        "permissions": granted,
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def build_comparison(
    db: Session, caller: Caller, players: list[Player], basis: str
) -> dict:
    """Side by side metrics for two to four players.

    Percentiles are deliberately not used here. Every column has to be computed against the
    same stated population or the columns are not comparable, and two players of different
    ages do not share one. Raw values with a unit and a direction are honest; a percentile
    per player against a different cohort would not be.
    """
    today = date.today()
    player_ids = [player.id for player in players]
    heights = measurement_series(db, player_ids, "height_cm")
    weights = measurement_series(db, player_ids, "weight_kg")
    sprints = measurement_series(db, player_ids, "sprint_10m_s")

    metrics: list[dict] = []
    for metric, series_map in (
        ("height_cm", heights),
        ("weight_kg", weights),
        ("sprint_10m_s", sprints),
    ):
        label, unit, higher_is_better = cohort.METRIC_DEFINITIONS[metric]
        values = [latest_value(series_map.get(player.id)) for player in players]
        present = [value for value in values if value is not None]
        # When the spread across players is smaller than ordinary measurement noise, say so
        # instead of ranking them. Two boys 4mm apart are the same height.
        indistinguishable = (
            len(present) > 1 and (max(present) - min(present)) < _NOISE_FLOOR[metric]
        )
        metrics.append(
            {
                "label": label,
                "unit": unit,
                "higher_is_better": higher_is_better,
                "values": values,
                "indistinguishable": indistinguishable or None,
                "note": (
                    "Closer together than a single measurement is accurate to."
                    if indistinguishable
                    else None
                ),
            }
        )

    caveat = None
    ages = [cohort.age_years(player.date_of_birth, today) for player in players]
    known = [age for age in ages if age is not None]
    if basis == "maturity":
        # The maturity-offset method is unsettled, so this basis cannot be honoured yet.
        # Saying so beats quietly returning age-based numbers under a maturity heading.
        caveat = (
            "Maturity-adjusted comparison is not available yet: the ML track has not "
            "settled the maturity-offset method. These figures are raw and age-based."
        )
    elif len(known) > 1 and (max(known) - min(known)) > 1.5:
        caveat = (
            f"These players are {max(known) - min(known):.1f} years apart. At this age "
            f"that difference is larger than most of the gaps below."
        )

    return {
        "players": [
            {
                "player": player,
                "age_label": cohort.age_label(player.date_of_birth, today),
                "maturity_offset_years": None,
            }
            for player in players
        ],
        "basis": basis,
        "caveat": caveat,
        "metrics": metrics,
        "growth": [
            {
                "player_id": player.id,
                "points": [
                    {"date": at, "value": value}
                    for at, value in heights.get(player.id, [])
                ],
            }
            for player in players
        ],
    }


# Below this spread, the players are reporting the same number. Height and weight are the
# generator's measurement noise; sprint is the timing resolution of a handheld stopwatch.
_NOISE_FLOOR = {"height_cm": 1.0, "weight_kg": 1.5, "sprint_10m_s": 0.05}


# ---------------------------------------------------------------------------
# Oversight
# ---------------------------------------------------------------------------


def build_oversight(db: Session, caller: Caller, sport: str) -> dict:
    """Federation-level aggregates. Counts only, no player rows leave this endpoint."""
    today = date.today()
    stale_cutoff = today - timedelta(days=STALE_AFTER_DAYS)

    players_tracked = db.execute(
        select(func.count())
        .select_from(Player)
        .where(Player.primary_sport == sport)
        .where(Player.status != PlayerStatus.MERGED)
    ).scalar_one()

    last_log_per_player = (
        select(
            Measurement.player_id.label("player_id"),
            func.max(Measurement.measured_at).label("last_at"),
        )
        .join(Player, Player.id == Measurement.player_id)
        .where(Player.primary_sport == sport)
        .group_by(Measurement.player_id)
        .subquery()
    )
    stale_players = db.execute(
        select(func.count()).select_from(last_log_per_player).where(
            last_log_per_player.c.last_at < stale_cutoff
        )
    ).scalar_one()
    logged_players = db.execute(
        select(func.count()).select_from(last_log_per_player)
    ).scalar_one()

    age_tier_rows = db.execute(
        select(Player.tier, Player.date_of_birth)
        .where(Player.primary_sport == sport)
        .where(Player.status != PlayerStatus.MERGED)
        .where(Player.date_of_birth.is_not(None))
    ).all()
    by_age: dict[int, dict[str, int]] = {}
    for tier, dob in age_tier_rows:
        age = int((today - dob).days / cohort.DAYS_PER_YEAR)
        bucket = by_age.setdefault(age, {"pro": 0, "youth": 0, "diaspora": 0})
        if tier in bucket:
            bucket[tier] += 1

    academies = _academy_coverage(db, sport, today)

    diaspora_total = db.execute(
        select(func.count())
        .select_from(Player)
        .where(Player.primary_sport == sport)
        .where(Player.tier == "diaspora")
        .where(Player.status != PlayerStatus.MERGED)
    ).scalar_one()
    diaspora_u21 = db.execute(
        select(func.count())
        .select_from(Player)
        .where(Player.primary_sport == sport)
        .where(Player.tier == "diaspora")
        .where(Player.status != PlayerStatus.MERGED)
        .where(Player.date_of_birth > today - timedelta(days=int(21 * cohort.DAYS_PER_YEAR)))
    ).scalar_one()

    return {
        "sport": sport,
        "players_tracked": players_tracked,
        "academies_reporting": len([row for row in academies if row["player_count"] > 0]),
        "stale_pct": round(100 * stale_players / logged_players, 1) if logged_players else 0.0,
        "open_flags": flags.open_flag_count(db),
        # Always empty. Coverage by governorate needs a region field on Organization that
        # the schema does not have. Raised in docs/wireframes/README.md.
        "by_region": [],
        "by_age_tier": [
            {"age": age, **counts} for age, counts in sorted(by_age.items())
        ],
        "academies": academies,
        "diaspora": {
            "total": diaspora_total,
            # "Uncapped" needs national-team appearance data, which nothing ingests yet, so
            # this is every under-21 diaspora player rather than the uncapped subset.
            "uncapped_under21": diaspora_u21,
            "new_this_month": db.execute(
                select(func.count())
                .select_from(Player)
                .where(Player.primary_sport == sport)
                .where(Player.tier == "diaspora")
                .where(Player.created_at > today - timedelta(days=30))
            ).scalar_one(),
        },
    }


def _academy_coverage(db: Session, sport: str, today: date) -> list[dict]:
    """Per-organization coverage: how many players, how stale, how much consent."""
    organizations = list(
        db.execute(
            select(Organization)
            .where(Organization.type.in_(("academy", "club")))
            .order_by(Organization.name)
        ).scalars()
    )

    rows: list[dict] = []
    for organization in organizations:
        player_ids = list(
            db.execute(
                select(PlayerOrganization.player_id)
                .join(Player, Player.id == PlayerOrganization.player_id)
                .where(PlayerOrganization.organization_id == organization.id)
                .where(PlayerOrganization.end_date.is_(None))
                .where(Player.primary_sport == sport)
                .where(Player.status != PlayerStatus.MERGED)
            ).scalars()
        )
        if not player_ids:
            continue

        last_logs = db.execute(
            select(Measurement.player_id, func.max(Measurement.measured_at))
            .where(Measurement.player_id.in_(player_ids))
            .group_by(Measurement.player_id)
        ).all()
        staleness = [(today - last_at).days for _, last_at in last_logs]

        consented = db.execute(
            select(func.count(func.distinct(PlayerOrganization.player_id)))
            .select_from(PlayerOrganization)
            .where(PlayerOrganization.player_id.in_(player_ids))
        ).scalar_one()
        complete = sum(
            1 for player_id in player_ids if consent_complete(consent_state(db, player_id))
        )

        rows.append(
            {
                "organization": organization,
                "player_count": len(player_ids),
                "last_submission_days": min(staleness) if staleness else 0,
                "median_staleness_days": int(statistics.median(staleness)) if staleness else 0,
                "consent_complete_pct": (
                    round(100 * complete / len(player_ids), 1) if player_ids else 0.0
                ),
                "open_flags": flags.open_flag_count(db, organization.id),
            }
        )
    return rows
