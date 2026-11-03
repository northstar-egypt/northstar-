"""View models: shapes the screens need, assembled from several tables.

These have no equivalent in `docs/schema.md`. They exist because a screen needs one request,
not eleven, and because two rules from `apps/web/lib/api.ts` have to hold on the server side:

  1. Scoping and consent filtering happen here. If a field must not be seen by the current
     role, the API does not send it. Hiding it in the browser is not access control.
  2. Aggregates are computed here. The web app must never fetch rows in order to count them.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import Field

from app.schemas.core import CamelModel, OrganizationOut, PerformanceEntryOut, PlayerOut


class FlagSummaryOut(CamelModel):
    type: str
    label: str
    confidence: float | None = None


class SquadRowOut(CamelModel):
    """One row in the coach's squad table."""

    player: PlayerOut
    age_label: str
    height_cm: float | None = None
    days_since_last_log: int | None = None
    # Last six height readings, oldest first, for the sparkline.
    height_trend: list[float] = []
    # All height readings, not only the six above.
    height_readings: int = 0
    # Height gained per year over the last months (app/services/views.py growth_cm_per_year);
    # null for adults and without two readings far enough apart.
    growth_cm_per_year: float | None = None
    # How many more height readings the late-bloomer check needs; 0 when none
    # (app/services/views.py height_readings_needed).
    height_readings_needed: int = 0
    flags: list[FlagSummaryOut] = []
    consent_complete: bool = False


class ForecastPointOut(CamelModel):
    """A forecast point. The band is what makes it honest, so it is not optional."""

    date: date
    value: float
    lower: float
    upper: float


class GrowthPointOut(CamelModel):
    date: date
    value: float


class PopulationBandOut(CamelModel):
    date: date
    p25: float
    p50: float
    p75: float


class GrowthSeriesOut(CamelModel):
    measured: list[GrowthPointOut] = []
    # From the graded model in ml/forecasting, every point with its 80% band. Empty when there
    # is not enough to forecast from; `forecast_note` then says why.
    forecast: list[ForecastPointOut] = []
    # The date the forecast was made from (today), which is not the last measurement date.
    forecast_from: date | None = None
    # Which model and how its band was checked, or why there is no forecast.
    forecast_note: str | None = None
    population: list[PopulationBandOut] = []
    unit: str = "cm"


class PercentileOut(CamelModel):
    metric: str
    label: str
    value: float
    unit: str
    percentile: int
    # Stated population. A percentile without one is meaningless.
    population: str
    # False for metrics where a lower number is better, such as sprint time.
    higher_is_better: bool = True


class MaturityEstimateOut(CamelModel):
    # Negative means behind peers, which is the late bloomer signal.
    offset_years: float
    predicted_adult_height_cm: float
    error_cm: float
    method: str


class ProvenanceOut(CamelModel):
    measurement_count: int = 0
    performance_count: int = 0
    consents: list[dict] = []


class PermissionsOut(CamelModel):
    """What the caller may do, decided here rather than inferred in the browser."""

    can_edit: bool = False
    can_log: bool = False
    can_see_flags: bool = False


class MetricColumnOut(CamelModel):
    key: str
    label: str
    unit: str | None = None


class SummaryStatOut(CamelModel):
    key: str
    label: str
    value: float
    # "percent" (value is a 0 to 1 share) or "number".
    format: str
    # How many records the statistic was computed from.
    basis: int


class PointShareOut(CamelModel):
    """A share of points against an average registered opponent, with its range (0 to 1)."""

    point_share: float
    low: float
    high: float


class OpponentOut(CamelModel):
    """Who a one-on-one match was against, as far as the caller may know."""

    # False for an opponent who is not on the platform; nothing else about them is stored.
    registered: bool
    # Only when the caller could open the opponent's own profile. Otherwise both are null and
    # the screen says "a registered player".
    id: uuid.UUID | None = None
    name: str | None = None
    # How strong they were going into that month. Null when not yet reliably known.
    strength: PointShareOut | None = None
    # Whether this match counted toward ratings (confirmed, see services/rating.py).
    counted: bool = False


class PerformanceRecordOut(PerformanceEntryOut):
    # Why the record fails its sport module. Null when it passes, and also null when the
    # caller may not see integrity findings, because "this record is impossible" is one.
    problems: list[str] | None = None
    # One-on-one sports only.
    opponent: OpponentOut | None = None


class PerformanceSectionOut(CamelModel):
    """One kind of performance record, laid out by its sport module.

    Columns, labels, units and summary statistics all come from
    `packages/shared/sports/<sport>.json`. The frontend renders whatever is here and knows
    nothing about any sport.
    """

    schema_ref: str
    sport: str
    period_type: str
    label: str
    # False when no sport module defines this schema_ref. The records are still shown, with
    # their raw keys as columns, rather than hidden.
    known: bool
    columns: list[MetricColumnOut]
    summary: list[SummaryStatOut] = []
    # Records left out of the summary because they fail their module.
    excluded_from_summary: int = 0
    entries: list[PerformanceRecordOut] = []


class RatingOut(CamelModel):
    """The table tennis rating (services/rating.py). `shown` false means no number: `note` says why."""

    shown: bool
    point_share: float | None = None
    low: float | None = None
    high: float | None = None
    # Chance of winning a best-of-five match against an average registered opponent.
    match_win: float | None = None
    rated_matches: int = 0
    # Who "an average registered opponent" is drawn from.
    population: str
    note: str | None = None


class MergedRecordOut(CamelModel):
    """A record merged into this one: a second registration of the same player."""

    id: str
    full_name: str
    # Null for a merge made before merges were recorded (the generated data has some).
    merged_on: str | None = None
    merged_by: str | None = None
    # True when the caller may undo it and the merge was recorded, so it can be.
    undoable: bool = False


class PlayerProfileOut(CamelModel):
    player: PlayerOut
    organization_name: str | None = None
    age_label: str
    latest: dict
    growth: GrowthSeriesOut
    maturity: MaturityEstimateOut | None = None
    percentiles: list[PercentileOut] = []
    # Set when percentiles are withheld on purpose (analytics consent), so the screen says why.
    percentiles_note: str | None = None
    rating: RatingOut | None = None
    performance: list[PerformanceSectionOut] = []
    flags: list[FlagSummaryOut] = []
    flag_reason: str | None = None
    merged_records: list[MergedRecordOut] = []
    provenance: ProvenanceOut
    permissions: PermissionsOut


class RadarAxisOut(CamelModel):
    key: str
    label: str
    # The player's own value, as a screen shows it (a rate, or a percentage).
    value: float
    unit: str
    # Null when fewer than cohort.MIN_COHORT comparable players have this statistic.
    percentile: int | None = None
    compared_with: int


class RadarOut(CamelModel):
    """GET /players/{id}/radar. `axes` may be empty; `note` always says why or how to read it."""

    axes: list[RadarAxisOut] = []
    # Who the percentiles are among, in words. Null when there is no radar.
    population: str | None = None
    note: str


class FinishingOut(CamelModel):
    """Non-penalty goals against non-penalty xG (ml/pro/sustainability.py)."""

    np_goals: int
    npxg: float
    # The 10th to 90th percentile of goals an ordinary finisher scores from these chances;
    # null when there are too few chances to judge.
    low: int | None = None
    high: int | None = None
    # "above", "below", "in line" or "too few chances".
    verdict: str
    seasons: int


class BreakoutOut(CamelModel):
    """The breakout detector's view of one season (ml/pro/breakout.py)."""

    flagged: bool
    score: float | None = None
    reason: str
    # False when the season could not be scored; `reason` says why.
    considered: bool


class ProSeasonOut(CamelModel):
    season: str
    competition: str
    club: str | None = None
    minutes: int
    finishing: FinishingOut
    # Null for the first season the league data covers: nothing before it to compare with.
    breakout: BreakoutOut | None = None


class TrendChangeOut(CamelModel):
    key: str
    label: str
    before: float
    after: float
    unit: str


class TrendOut(CamelModel):
    season: str
    previous: str
    minutes_before: int
    minutes_after: int
    changes: list[TrendChangeOut]


class ProSeasonsOut(CamelModel):
    """GET /players/{id}/pro-seasons. Newest season first. `note` says why there is nothing."""

    seasons: list[ProSeasonOut] = []
    career: FinishingOut | None = None
    trends: list[TrendOut] = []
    note: str | None = None


class SimilarPlayerOut(CamelModel):
    player_id: uuid.UUID
    full_name: str
    position: str | None = None
    age_label: str
    # Distance between the two profiles, in standard deviations on a typical statistic.
    distance: float
    # The statistics on which the two are most alike, in words.
    alike: list[str] = []


class SimilarPlayersOut(CamelModel):
    """GET /players/{id}/similar. `items` may be empty; `note` always says what this is or why."""

    items: list[SimilarPlayerOut] = []
    note: str


class ProfileSummaryOut(CamelModel):
    """The written summary for the profile, from GET /players/{id}/summary.

    `summary` is null when there is none, and `note` always says why or where it came from.
    """

    summary: str | None = None
    note: str
    model: str | None = None
    # Still being written: ask again shortly. The request does not wait for the model.
    pending: bool = False


class SearchResultOut(CamelModel):
    player: PlayerOut
    organization_name: str | None = None
    age_label: str
    height_cm: float | None = None
    match_score: float = 0.0
    highlights: list[str] = []
    trend: list[float] = []
    # True when the viewer may not see this player, so the card renders locked.
    withheld: bool = False
    withheld_reason: str | None = None


class QueryChipOut(CamelModel):
    label: str
    understood: bool


class ParsedQueryOut(CamelModel):
    chips: list[QueryChipOut] = []


class SearchRequest(CamelModel):
    """Filters map to Player columns. The natural language half is not built.

    The embedding model choice is still open (see docs/wireframes/README.md), so `query` is
    parsed for the handful of patterns that map cleanly onto columns and every other term is
    returned as a chip marked `understood: false`. Saying which parts of a query were ignored
    is better than silently ignoring them.
    """

    query: str = ""
    sport: str | None = None
    tier: str | None = None
    position: str | None = None
    sex: str | None = None
    min_age: float | None = None
    max_age: float | None = None
    min_height_cm: float | None = None
    max_height_cm: float | None = None
    organization_id: uuid.UUID | None = None
    egypt_eligible_only: bool = False
    include_minors: bool = True
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class SearchResponse(CamelModel):
    parsed: ParsedQueryOut
    results: list[SearchResultOut] = []
    total: int = 0


class ComparisonPlayerOut(CamelModel):
    player: PlayerOut
    age_label: str
    maturity_offset_years: float | None = None


class ComparisonMetricOut(CamelModel):
    label: str
    unit: str
    higher_is_better: bool = True
    values: list[float | None] = []
    # Set when the values are too close to separate, so the interface reports rather
    # than ranks.
    indistinguishable: bool | None = None
    note: str | None = None


class ComparisonGrowthOut(CamelModel):
    player_id: uuid.UUID
    points: list[GrowthPointOut] = []


class ComparisonOut(CamelModel):
    players: list[ComparisonPlayerOut] = []
    basis: str = "age"
    caveat: str | None = None
    metrics: list[ComparisonMetricOut] = []
    growth: list[ComparisonGrowthOut] = []


class CoverageRowOut(CamelModel):
    organization: OrganizationOut
    player_count: int = 0
    last_submission_days: int = 0
    median_staleness_days: int = 0
    consent_complete_pct: float = 0.0
    open_flags: int = 0


class RegionRowOut(CamelModel):
    # ISO 3166-2:EG code (app/regions.py), and the governorate's name in English and Arabic.
    code: str
    region: str
    region_ar: str
    players: int
    # Millions, from app/regions.py (an estimate; see its source note).
    population_m: float


class AgeTierRowOut(CamelModel):
    age: int
    pro: int = 0
    youth: int = 0
    diaspora: int = 0


class DiasporaSummaryOut(CamelModel):
    total: int = 0
    uncapped_under21: int = 0
    new_this_month: int = 0


class OversightSummaryOut(CamelModel):
    sport: str
    players_tracked: int = 0
    academies_reporting: int = 0
    stale_pct: float = 0.0
    open_flags: int = 0
    # All 27 governorates, empty ones included, by players per million (services/views.py).
    by_region: list[RegionRowOut] = []
    # Players at an Egyptian club with no governorate set, so they are not silently dropped.
    players_without_governorate: int = 0
    by_age_tier: list[AgeTierRowOut] = []
    academies: list[CoverageRowOut] = []
    diaspora: DiasporaSummaryOut


# ---------------------------------------------------------------------------
# Integrity board
# ---------------------------------------------------------------------------


class FlagDiffFieldOut(CamelModel):
    field: str
    a: str
    b: str
    differs: bool


class FlagRecordsOut(CamelModel):
    """The field-by-field diff of a suspected duplicate pair.

    Populated for duplicate flags only. The wireframe is explicit that this is the whole
    decision for a duplicate, and that it has to show which record has more history, because
    that determines which one survives the merge.
    """

    label: str
    player_id: str
    # Record B, the flag's related player.
    other_player_id: str
    created_at: str
    measurement_count: int
    source: str
    fields: list[FlagDiffFieldOut] = []


class FlagHistoryEntryOut(CamelModel):
    at: str
    who: str
    what: str


class IntegrityFlagOut(CamelModel):
    id: str
    type: str
    status: str
    player_name: str
    organization_name: str | None = None
    raised_at: str
    age_days: int
    # Which rule raised it (`flag.detector_name`), so the board can say what was checked.
    detector: str | None = None
    # Null for a rule with no calibrated probability, which is every detector today.
    confidence: float | None = None
    reason: str
    evidence: list[str] = []
    records: FlagRecordsOut | None = None
    history: list[FlagHistoryEntryOut] = []


class FlagDecisionRequest(CamelModel):
    """A reviewer's decision.

    The reason is required and is validated as non-empty. Not bureaucracy: each decision plus
    its reason is a labelled example, and labelled examples are what the detectors' precision
    and recall are computed from. A dismissal with no reason teaches nothing.
    """

    decision: str
    reason: str = Field(min_length=3, max_length=2000)
    # Confirming a duplicate merges its two records; this is the one to keep. Left out, the
    # record with more history is kept.
    keep_player_id: uuid.UUID | None = None


class UndoMergeRequest(CamelModel):
    """Undoing a merge needs a reason, like every decision."""

    reason: str = Field(min_length=3, max_length=2000)


# ---------------------------------------------------------------------------
# Scatter explorer
# ---------------------------------------------------------------------------


class ScatterStatOut(CamelModel):
    key: str
    label: str
    unit: str
    higher_is_better: bool = True


class ScatterPointOut(CamelModel):
    player_id: uuid.UUID
    full_name: str
    position: str | None = None
    age_label: str
    x: float
    y: float


class ScatterMediansOut(CamelModel):
    x: float
    y: float


class ScatterOut(CamelModel):
    """GET /explore/scatter (app/services/explore.py). Echoes the filters it actually used."""

    sport: str
    gender: str
    group: str | None = None
    age_from: int | None = None
    age_to: int | None = None
    x: str
    y: str
    stats: list[ScatterStatOut] = []
    genders: list[str] = []
    groups: list[str] = []
    # Only players the caller may open. `total` counts the whole group.
    points: list[ScatterPointOut] = []
    # Null when the group has fewer than cohort.MIN_COHORT players.
    medians: ScatterMediansOut | None = None
    total: int = 0
    population: str
    focus: uuid.UUID | None = None
    note: str


class LeaderOut(CamelModel):
    player_id: uuid.UUID
    full_name: str
    position: str | None = None
    age_label: str
    value: float
    # Among the whole group, higher is better, as on the profile's radar.
    percentile: int
    # Only on a board's `focus`: their place among the players the caller may open.
    rank: int | None = None


class LeaderBoardOut(CamelModel):
    key: str
    label: str
    unit: str
    higher_is_better: bool = True
    compared_with: int = 0
    # Null when fewer than cohort.MIN_COHORT players have this statistic, or all are equal;
    # `leaders` is then empty too.
    median: float | None = None
    leaders: list[LeaderOut] = []
    focus: LeaderOut | None = None


class LeadersOut(CamelModel):
    """GET /explore/leaders (app/services/explore.py). Echoes the filters it actually used."""

    sport: str
    gender: str
    group: str | None = None
    age_from: int | None = None
    age_to: int | None = None
    stats: list[ScatterStatOut] = []
    genders: list[str] = []
    groups: list[str] = []
    boards: list[LeaderBoardOut] = []
    total: int = 0
    shown: int = 0
    population: str
    focus: uuid.UUID | None = None
    note: str
