"""Talent estimates on the profile: a professional's rates against their league peers, with how
sure we are. The method is ml/estimates/shrinkage.py, graded in ml/README.md, "Talent
estimates"; this file only gathers the seasons and applies it.

For each of the player's basic league seasons (`football.season_basic.v1`, FootyStats):

- the peers are every season in the same competition and season (`event`) and the same
  position group, of players whose analytics consent is in effect, with 90+ minutes;
- a prior is fitted on those peers for each statistic (non-penalty goals and assists per 90);
- the player's estimate, its 80% interval, how much of it is their own record, and their
  percentile among the peers' estimates: the estimate's own (the headline; ranking shrunk
  estimates is the standard empirical Bayes ranking) and a range from the interval's two ends
  (how far the true rate could plausibly sit from it).

There is no minutes cut-off: a short season is shown, with a wide range and a low weight, which
is the point. Goalkeepers are not compared on goals and assists, and a group with too few
peers to fit gets no estimate, with the reason.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ConsentPurpose
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services.access import consent_subquery, has_consent

from ml.estimates import shrinkage  # noqa: E402

SCHEMA = "football.season_basic.v1"
MIN_PEER_MINUTES = 90
# Fewer peers than this and the spread between players cannot be told from chance.
MIN_PEERS = 20
MEASURES = (
    ("np_goals", "Non-penalty goals per 90", "non-penalty goals"),
    ("assists", "Assists per 90", "assists"),
)
GROUP_PLURAL = {"defender": "defenders", "midfielder": "midfielders", "forward": "forwards"}
LEVEL = 0.8


def _count(metrics: dict, key: str) -> int | None:
    if key == "np_goals":
        goals, pens = metrics.get("goals"), metrics.get("penalty_goals")
        if goals is None or pens is None:
            return None
        return max(0, goals - pens)
    return metrics.get(key)


def _season_label(event: str) -> str:
    return event.rsplit(" ", 1)[-1] if event else ""


def player_estimates(db: Session, player: Player) -> dict:
    if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
        return {"seasons": [], "note": "Analytics consent is not in effect for this player, so they are not "
                                       "compared with anyone."}
    mine = db.execute(select(PerformanceEntry).where(
        PerformanceEntry.player_id == player.id, PerformanceEntry.schema_ref == SCHEMA)
        .order_by(PerformanceEntry.period_start.desc())).scalars().all()
    if not mine:
        return {"seasons": [], "note": None}

    events = {e.event for e in mine}
    consented = set(db.execute(consent_subquery(ConsentPurpose.ANALYTICS.value)).scalars())
    peers_by: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for entry in db.execute(select(PerformanceEntry).where(
            PerformanceEntry.schema_ref == SCHEMA, PerformanceEntry.event.in_(events))).scalars():
        group = entry.metrics.get("position_group")
        if entry.player_id in consented and group and entry.metrics.get("minutes_played", 0) >= MIN_PEER_MINUTES:
            peers_by[(entry.event, group)].append((entry.player_id, entry.metrics))

    seasons = []
    for entry in mine:
        group = entry.metrics.get("position_group")
        minutes = entry.metrics.get("minutes_played", 0)
        base = {"competition": entry.event.rsplit(" ", 1)[0], "season": _season_label(entry.event),
                "group": group, "minutes": minutes, "measures": [], "note": None}
        if group == "goalkeeper":
            base["note"] = "Goalkeepers are not compared on goals and assists."
            seasons.append(base)
            continue
        # The prior is the whole group's, this player included, as in the evaluation; the
        # percentile is among the others.
        group_rows = [m for _, m in peers_by.get((entry.event, group), [])]
        others = [m for pid, m in peers_by.get((entry.event, group), []) if pid != player.id]
        peers = others
        if group is None or len(peers) < MIN_PEERS:
            base["note"] = (f"Too few {GROUP_PLURAL.get(group, 'players')} with this season on record "
                            f"({len(peers)}; {MIN_PEERS} are needed) to tell real differences from chance.")
            seasons.append(base)
            continue
        exposure = minutes / 90
        for key, label, words in MEASURES:
            count = _count(entry.metrics, key)
            fit = [(c, m["minutes_played"] / 90) for m in group_rows if (c := _count(m, key)) is not None]
            pairs = [(c, m["minutes_played"] / 90) for m in others if (c := _count(m, key)) is not None]
            if count is None or len(pairs) < MIN_PEERS:
                continue
            prior = shrinkage.fit_prior([c for c, _ in fit], [e for _, e in fit])
            est = shrinkage.estimate(count, exposure, prior, LEVEL)
            # Peers' point estimates only: their intervals are never shown, and computing them
            # for a whole league made the request slow.
            peer_points = [(c + prior.k * prior.mean) / (e + prior.k) for c, e in pairs]
            low, high = shrinkage.percentile_range(est, peer_points)
            point = shrinkage.percentile_of(est.rate, peer_points)
            base["measures"].append({
                "key": key, "label": label, "count": count, "raw": est.raw, "estimate": est.rate,
                "low": est.low, "high": est.high, "weight": est.weight, "peer_rate": prior.mean,
                "k": prior.k, "percentile": point, "percentile_low": low, "percentile_high": high, "peers": len(pairs),
                "words": words,
            })
        seasons.append(base)
    return {"seasons": seasons, "note": None}
