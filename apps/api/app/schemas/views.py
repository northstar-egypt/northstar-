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
    # Empty until the forecasting deliverable lands. The web app draws nothing rather than
    # drawing a line, which is the correct behaviour for "we do not know yet".
    forecast: list[ForecastPointOut] = []
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


class PlayerProfileOut(CamelModel):
    player: PlayerOut
    organization_name: str | None = None
    age_label: str
    latest: dict
    growth: GrowthSeriesOut
    maturity: MaturityEstimateOut | None = None
    percentiles: list[PercentileOut] = []
    performance: list[PerformanceEntryOut] = []
    flags: list[FlagSummaryOut] = []
    flag_reason: str | None = None
    summary: str | None = None
    provenance: ProvenanceOut
    permissions: PermissionsOut


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
    region: str
    players: int
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
    # Always empty. Coverage by governorate needs a region field on Organization that the
    # schema does not have. See OrganizationOut.region.
    by_region: list[RegionRowOut] = []
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
    confidence: float
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
