"""Scout search.

Filters only. The natural language half needs an embedding model the ML track has not
chosen, and rather than fake it the query box reports which of the scout's words it actually
used. See `app.services.search`.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.player import Player
from app.schemas.views import SearchRequest, SearchResponse, SearchResultOut
from app.services import cohort, search as search_service, views
from app.services.access import Caller, may_view, redact

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> SearchResponse:
    """Search players the caller is allowed to reach.

    Results a scout may not see because the player is a minor without scouting consent come
    back marked `withheld`, with the identifying fields stripped, so the screen renders a
    locked card. Whether that is the right behaviour is still open (see
    `docs/wireframes/README.md`); the wireframe drew the locked card, so that is what this
    does, and switching to omitting them entirely is one filter here.
    """
    today = date.today()
    parsed_filters, chips, name_terms = search_service.parse_query(request.query)

    stmt = search_service.apply_filters(
        _base_query(caller), request, parsed_filters, today, name_terms
    )

    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()

    players = list(
        db.execute(
            stmt.order_by(Player.full_name).offset(request.offset).limit(request.limit)
        )
        .scalars()
        .unique()
    )

    player_ids = [player.id for player in players]
    heights = views.measurement_series(db, player_ids, "height_cm")
    org_names = views.organization_names(db, player_ids)

    results: list[SearchResultOut] = []
    for player in players:
        series = heights.get(player.id, [])
        height_cm = views.latest_value(series)
        age = cohort.age_years(player.date_of_birth, today)
        allowed, reason = may_view(db, caller, player)

        if not allowed:
            # Enough to say a record exists, nothing that identifies the child.
            results.append(
                SearchResultOut(
                    player=redact(player),
                    organization_name=None,
                    age_label="",
                    height_cm=None,
                    match_score=0.0,
                    highlights=[],
                    trend=[],
                    withheld=True,
                    withheld_reason=reason,
                )
            )
            continue

        results.append(
            SearchResultOut(
                player=player,
                organization_name=org_names.get(player.id),
                age_label=cohort.age_label(player.date_of_birth, today),
                height_cm=height_cm,
                # Every result satisfies every filter equally, so there is nothing to rank
                # by. A fabricated relevance score would imply an ordering the filters do
                # not produce. This becomes real with the embedding half.
                match_score=1.0,
                highlights=search_service.highlights(player, height_cm, age),
                trend=[value for _, value in series[-views.TREND_POINTS :]],
                withheld=False,
            )
        )

    return SearchResponse(
        parsed={"chips": chips}, results=results, total=total
    )


def _base_query(caller: Caller):
    """Players this caller may reach at all, before filters.

    Scouts and federation staff see the whole active population here; the per-player consent
    gate is applied above so a withheld player is reported rather than silently dropped.
    """
    from app.services.access import visible_players

    return visible_players(caller)
