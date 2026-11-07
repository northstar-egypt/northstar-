"""Does the scouting report's level track how good a player really is?

The synthetic league plants each player's true quality (pro_league.League.quality, by season),
which no real data offers. So for every adult in the league's latest season with a report:

- **Rank agreement**: the Spearman correlation between the report's current level and true
  quality, within each position group (a level is a rank among the group), averaged over groups.
- **Against a baseline**: minutes played, ranked the same way. Better players play more, so
  minutes alone rank players; a report that cannot beat that adds nothing.
- **Recommendations**: of the players recommended Shortlist, the share whose true quality is in
  the top third of their group (chance: a third); of those marked Not now, the share in the
  bottom third.

The report's thresholds were fixed before this was first run and were not tuned on it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from ml.pro import report as reports
from ml.pro.seasons import from_league

REFERENCE = date(2026, 10, 26)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    if statistics.pstdev(ra) == 0 or statistics.pstdev(rb) == 0:
        return None
    return statistics.correlation(ra, rb)


@dataclass
class ReportValidity:
    seed: int
    reports: int
    # Group -> Spearman between level and true quality.
    by_group: dict[str, float | None]
    # The baseline: group -> Spearman between minutes played and true quality. Better players
    # play more, so minutes alone rank players; the report must do better to be worth reading.
    minutes_by_group: dict[str, float | None]
    # Recommendation -> (players, of them in the matching third of true quality).
    recommendations: dict[str, tuple[int, int]]


def evaluate(seed: int, module, reference: date = REFERENCE) -> ReportValidity:
    from data.pipelines.synthetic import pro_league

    clubs, players = pro_league.synthetic_inputs(seed, reference)
    league = pro_league.build_league(seed, clubs, players, reference)
    rows = from_league(league, players)
    season = league.seasons[-1].label
    built = []
    for pid in {r.player_id for r in rows if r.season == season}:
        try:
            rep = reports.build(module, rows, pid)
        except reports.NoReport:
            continue
        if rep.level is not None and rep.season == season:
            built.append((rep, league.quality[(pid, season)]))

    by_group, minutes, recs = {}, {}, {"Shortlist": [0, 0], "Monitor": [0, 0], "Not now": [0, 0]}
    for group in sorted({r.group for r, _ in built}):
        members = [(r, q) for r, q in built if r.group == group]
        by_group[group] = spearman([r.level for r, _ in members], [q for _, q in members])
        minutes[group] = spearman([float(r.minutes) for r, _ in members], [q for _, q in members])
        qualities = sorted(q for _, q in members)
        third = len(qualities) // 3
        top, bottom = qualities[-third] if third else None, qualities[third - 1] if third else None
        for r, q in members:
            recs[r.recommendation][0] += 1
            if r.recommendation == "Shortlist" and top is not None and q >= top:
                recs[r.recommendation][1] += 1
            if r.recommendation == "Not now" and bottom is not None and q <= bottom:
                recs[r.recommendation][1] += 1
    return ReportValidity(seed, len(built), by_group, minutes, {k: tuple(v) for k, v in recs.items()})
