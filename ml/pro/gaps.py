"""Team gap analysis (decision 0003): where a team is weak, and which players are strong there.

Three steps, each shown with its numbers:

1. **Team profile.** Every team statistic in the sport module's `teamGaps` config is ranked
   against the other teams in the same league and season. A rank in the bottom third is a
   weakness. Each statistic has a declared direction (more chances allowed is worse).
2. **Squad coverage.** For each position group, who plays the group's minutes and where they
   stand among the league's players of that group, per statistic.
3. **Candidates.** For a weakness, players outside the team ranked on the player statistics the
   config links to it. The ranking is the mean of those percentiles, and every one of them is
   shown: there is no fit score. A weakness with no honest player counterpart (finishing, late
   goals) is a finding with no candidates, and says why.

National team mode skips step 1: the federation names the needs by hand, because a national
team plays too few matches for its own statistics to mean much. The pool is every
Egypt-eligible player, and each is ranked only among players of their own league and season:
a 90th percentile in Egypt is not a 90th percentile in Germany, so leagues are never pooled.

The rules every percentile here keeps:

- Only seasons with `MIN_MINUTES` count, for the player being ranked and for the population
  they are ranked in. The number comes from the split-half reliability check (ml/README.md,
  "Team gap analysis"), not from taste.
- A population smaller than `MIN_COHORT` gives no percentile at all.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ml.pro.seasons import SeasonRow

# Set by the split-half reliability check on the tuning seeds (ml/pro/gap_eval.py).
MIN_MINUTES = 450
MIN_COHORT = 8


@dataclass(frozen=True)
class TeamRow:
    club: str
    competition: str
    season: str
    metrics: dict


def percentile_of(others: list[float], value: float) -> int:
    """Where `value` sits among `others`, 1 to 99 (the same rule as the profile's percentiles)."""
    below = sum(1 for o in others if o < value)
    equal = sum(1 for o in others if o == value)
    return max(1, min(99, round(100 * (below + equal / 2) / len(others))))


# ---------------------------------------------------------------------------
# 1. Team profile
# ---------------------------------------------------------------------------


@dataclass
class MetricRank:
    key: str
    label: str
    value: float | None
    # 1 is the best in the league on this statistic; None when the value cannot be computed.
    rank: int | None
    of: int
    better: str
    # In the bottom third on a statistic stable enough to act on.
    weak: bool
    percent: bool = False
    links: list = field(default_factory=list)
    no_player_link: str | None = None
    # In the bottom third, but on a statistic that barely repeats from one half season to the
    # next, so it is shown and not acted on.
    bottom_unstable: bool = False


def team_profile(gaps, teams: list[TeamRow], club: str, competition: str, season: str) -> list[MetricRank]:
    league = [t for t in teams if t.competition == competition and t.season == season]
    mine = next((t for t in league if t.club == club), None)
    out = []
    for metric in gaps.metrics:
        values = {t.club: metric.value(t.metrics) for t in league}
        values = {k: v for k, v in values.items() if v is not None}
        value = values.get(club) if mine else None
        rank = None
        if value is not None and len(values) >= MIN_COHORT:
            better_than_me = sum(1 for v in values.values() if (v > value if metric.better == "higher" else v < value))
            rank = better_than_me + 1
        bottom = rank is not None and rank > len(values) * 2 / 3
        out.append(MetricRank(metric.key, metric.label, value, rank, len(values), metric.better,
                              bottom and metric.stable, metric.percent, metric.links, metric.no_player_link,
                              bottom and not metric.stable))
    return out


# ---------------------------------------------------------------------------
# Percentiles within one league, season and position group
# ---------------------------------------------------------------------------


def _population(gaps, rows: list[SeasonRow], competition: str, season: str, group: str,
                min_minutes: int) -> list[SeasonRow]:
    return [r for r in rows if r.competition == competition and r.season == season
            and gaps.group_of(r.position) == group and r.minutes >= min_minutes]


def percentiles(gaps, population: list[SeasonRow], row: SeasonRow, attributes: list[str]) -> dict[str, int | None]:
    """The row's percentile on each attribute among `population` (the row itself excluded).
    None for an attribute with fewer than MIN_COHORT others to compare with."""
    out = {}
    for key in attributes:
        attr = gaps.attributes[key]
        mine = attr.value(row.metrics)
        others = [v for r in population if r.player_id != row.player_id
                  for v in [attr.value(r.metrics)] if v is not None]
        out[key] = percentile_of(others, mine) if mine is not None and len(others) >= MIN_COHORT else None
    return out


# ---------------------------------------------------------------------------
# 2. Squad coverage
# ---------------------------------------------------------------------------


@dataclass
class SquadPlayer:
    player_id: str
    minutes: int
    # Share of the minutes this club's players of the group played.
    share: float
    # Null for every attribute when the player has fewer than MIN_MINUTES.
    percentiles: dict[str, int | None]
    ranked: bool


@dataclass
class GroupCoverage:
    group: str
    label: str
    attributes: list[str]
    players: list[SquadPlayer]
    # Players ranked in the group across the league: the population each percentile is among.
    population: int


def squad_coverage(gaps, rows: list[SeasonRow], club: str, competition: str, season: str,
                   min_minutes: int = MIN_MINUTES) -> list[GroupCoverage]:
    out = []
    for group in gaps.groups.values():
        population = _population(gaps, rows, competition, season, group.key, min_minutes)
        squad = sorted((r for r in rows if r.club == club and r.competition == competition and r.season == season
                        and gaps.group_of(r.position) == group.key and r.minutes > 0), key=lambda r: -r.minutes)
        total = sum(r.minutes for r in squad) or 1
        players = []
        for r in squad:
            ranked = r.minutes >= min_minutes
            pct = percentiles(gaps, population, r, group.attributes) if ranked else dict.fromkeys(group.attributes)
            players.append(SquadPlayer(r.player_id, r.minutes, r.minutes / total, pct, ranked))
        out.append(GroupCoverage(group.key, group.label, group.attributes, players, len(population)))
    return out


# ---------------------------------------------------------------------------
# 3. Candidates
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    player_id: str
    club: str | None
    competition: str
    season: str
    minutes: int
    # The statistics themselves, so a player who cannot be ranked still shows their numbers.
    values: dict[str, float | None]
    percentiles: dict[str, int | None]
    # The mean of the percentiles above: the ranking rule, shown as the percentiles themselves.
    mean: float | None
    # How many players of the group in the candidate's league and season they were ranked among.
    population: int


@dataclass
class Need:
    group: str
    label: str
    attributes: list[str]
    candidates: list[Candidate]
    # Candidates whose league has too few ranked players of the group to place them.
    unranked: list[Candidate] = field(default_factory=list)


def _latest(rows: list[SeasonRow]) -> dict[str, SeasonRow]:
    """Each player's most recent season, the one with more minutes if two end together."""
    out: dict[str, SeasonRow] = {}
    for r in rows:
        best = out.get(r.player_id)
        if best is None or (r.end, r.minutes) > (best.end, best.minutes):
            out[r.player_id] = r
    return out


def candidates(gaps, rows: list[SeasonRow], group: str, attributes: list[str], *, competition: str | None,
               season: str | None, exclude_club: str | None = None, pool: set[str] | None = None,
               min_minutes: int = MIN_MINUTES, limit: int = 10) -> Need:
    """Players of `group` ranked on `attributes`.

    Club mode: `competition` and `season` fixed (the club's own league), `exclude_club` its own
    players. National mode: `competition` and `season` None, `pool` the eligible players; each
    player's latest season is used and ranked among their own league and season only."""
    spec = gaps.groups[group]
    if competition is not None:
        considered = [r for r in rows if r.competition == competition and r.season == season]
    else:
        considered = list(_latest([r for r in rows if pool is None or r.player_id in pool]).values())
    considered = [r for r in considered if gaps.group_of(r.position) == group and r.minutes >= min_minutes
                  and r.club != exclude_club and (pool is None or r.player_id in pool)]
    populations: dict[tuple[str, str], list[SeasonRow]] = {}
    ranked, unranked = [], []
    for r in considered:
        key = (r.competition, r.season)
        if key not in populations:
            populations[key] = _population(gaps, rows, r.competition, r.season, group, min_minutes)
        pct = percentiles(gaps, populations[key], r, attributes)
        known = [v for v in pct.values() if v is not None]
        values = {a: gaps.attributes[a].value(r.metrics) for a in attributes}
        candidate = Candidate(r.player_id, r.club, r.competition, r.season, r.minutes, values, pct,
                              round(statistics.fmean(known), 1) if len(known) == len(attributes) else None,
                              len(populations[key]))
        (ranked if candidate.mean is not None else unranked).append(candidate)
    ranked.sort(key=lambda c: (-c.mean, -c.minutes))
    return Need(group, spec.label, attributes, ranked[:limit], unranked)


def club_needs(gaps, profile: list[MetricRank], rows: list[SeasonRow], club: str, competition: str,
               season: str, min_minutes: int = MIN_MINUTES, limit: int = 5) -> dict[str, list[Need]]:
    """For each weakness with player links, the candidates for each linked group."""
    out = {}
    for metric in profile:
        if metric.weak and metric.links:
            out[metric.key] = [
                candidates(gaps, rows, link.group, link.attributes, competition=competition, season=season,
                           exclude_club=club, min_minutes=min_minutes, limit=limit)
                for link in metric.links
            ]
    return out
