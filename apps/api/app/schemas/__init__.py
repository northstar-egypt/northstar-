"""Response schemas for the read API.

These mirror `apps/web/lib/types.ts`, which the application track wrote as a proposal for
what the endpoints should return. Treating that file as the contract rather than inventing a
second shape is deliberate: the eight screens are already built against it, so an endpoint
that matches it needs no frontend change beyond deleting a fixture import.

Everything serialises to camelCase. The database and the Python layer stay snake_case, the
wire is camelCase, and `CamelModel` is the one place that conversion happens.
"""

from app.schemas.core import (
    CamelModel,
    ConsentOut,
    MeasurementOut,
    OrganizationOut,
    PerformanceEntryOut,
    PlayerOut,
    SessionUserOut,
)
from app.schemas.views import (
    ComparisonMetricOut,
    ComparisonOut,
    CoverageRowOut,
    FlagSummaryOut,
    ForecastPointOut,
    GrowthSeriesOut,
    MaturityEstimateOut,
    OversightSummaryOut,
    ParsedQueryOut,
    PercentileOut,
    PlayerProfileOut,
    SearchRequest,
    SearchResponse,
    SearchResultOut,
    SquadRowOut,
)

__all__ = [
    "CamelModel",
    "ComparisonMetricOut",
    "ComparisonOut",
    "ConsentOut",
    "CoverageRowOut",
    "FlagSummaryOut",
    "ForecastPointOut",
    "GrowthSeriesOut",
    "MaturityEstimateOut",
    "MeasurementOut",
    "OrganizationOut",
    "OversightSummaryOut",
    "ParsedQueryOut",
    "PercentileOut",
    "PerformanceEntryOut",
    "PlayerOut",
    "PlayerProfileOut",
    "SearchRequest",
    "SearchResponse",
    "SearchResultOut",
    "SessionUserOut",
    "SquadRowOut",
]
