"""A pro player's scouting report: the verdict first, then the evidence behind it.

Built on team gap analysis (ml/pro/gaps.py): the same position groups, the same statistics, the
same percentile rule, minimum minutes and population size. Each sentence on the report is a rule
over those numbers, and every rule is here:

- **Areas** (`scoutingReport` in the sport module): groups of statistics, such as defending
  (tackles, interceptions, clearances per 90). An area's score is the mean of its statistics'
  percentiles among the player's position group in their league and season.
- **Grades**: A at 85 or more, B at 70, C at 50, D below; on area scores and on the level.
- **Current level**: the mean of the areas the player's role is graded on (`roles` in the
  config: a centre back on defending, duels and passing; a winger on creation, carrying and goal
  threat). A centre back is never marked down for not scoring.
- **Recommendation**: Shortlist at a level of 70 or more, Monitor at 50, Not now below.
- **Confidence**: from minutes. High at 2,000 or more, medium at 1,000, low below.
- **Strengths and weaknesses**: statistics at the 70th percentile or above, and at the 30th or
  below, each with its value and the league median. A statistic the reliability check found
  unstable (ml/README.md, "Team gap analysis") is marked as such.

These thresholds were set before the report was ever checked and were not tuned; ml/README.md,
"Scouting report", says how well the level tracks the true quality planted in the synthetic
league.

Adults only. A child's report would grade them against an adult standard of output, which is
exactly the comparison NorthStar's late-bloomer work exists to avoid; a youth profile keeps its
growth story instead.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ml.pro import gaps as engine
from ml.pro.seasons import SeasonRow

ADULT_AGE = 18
GRADES = [(85, "A"), (70, "B"), (50, "C")]
SHORTLIST, MONITOR = 70, 50
HIGH_MINUTES, MEDIUM_MINUTES = 2000, 1000
STRONG, WEAK = 70, 30
SHOWN = 5
YOUNG = 23


def ordinal(n: float) -> str:
    """73 -> "73rd"; 11 -> "11th"."""
    whole = round(n)
    suffix = "th" if 10 <= whole % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(whole % 10, "th")
    return f"{whole}{suffix}"


def _in_a_sentence(label: str) -> str:
    """A label as it reads mid-sentence: "Key passes" -> "key passes"; "npxG" stays "npxG"."""
    return label[0].lower() + label[1:]


def grade(score: float | None) -> str | None:
    if score is None:
        return None
    return next((letter for cutoff, letter in GRADES if score >= cutoff), "D")


@dataclass
class Evidence:
    key: str
    label: str
    value: float
    # "per 90" or "%": a share is shown as a percentage.
    unit: str
    percentile: int
    median: float
    low_reliability: bool


@dataclass
class AreaScore:
    key: str
    label: str
    score: float | None
    grade: str | None
    # Whether the player's role is graded on this area.
    graded: bool
    evidence: list[Evidence]


@dataclass
class Report:
    player_id: str
    season: str
    competition: str
    group: str
    group_label: str
    minutes: int
    population: int
    level: float | None
    level_grade: str | None
    recommendation: str | None
    confidence: str
    areas: list[AreaScore]
    strengths: list[Evidence]
    weaknesses: list[Evidence]
    summary: str
    would_change: list[str]
    not_in_data: list[str] = field(default_factory=list)
    young: bool = False


def _evidence(config, population: list[SeasonRow], row: SeasonRow, key: str, pct: int) -> Evidence:
    attr = config.attributes[key]
    values = [v for r in population if r.player_id != row.player_id for v in [attr.value(r.metrics)] if v is not None]
    value = attr.value(row.metrics)
    share = not attr.per90
    scale = 100 if share else 1
    return Evidence(key, attr.label, round(value * scale, 1 if share else 2), "%" if share else "per 90", pct,
                    round(statistics.median(values) * scale, 1 if share else 2), attr.low_reliability)


def latest_season(rows: list[SeasonRow], player_id: str) -> SeasonRow | None:
    mine = [r for r in rows if r.player_id == player_id]
    return max(mine, key=lambda r: (r.end, r.minutes)) if mine else None


class NoReport(Exception):
    """Why a player has no report, in words a scout can read."""


def build(module, rows: list[SeasonRow], player_id: str, min_minutes: int = engine.MIN_MINUTES) -> Report:
    """The report on a player's latest league season. Raises NoReport with the reason."""
    config, spec = module.team_gaps, module.scouting_report
    row = latest_season(rows, player_id)
    if row is None:
        raise NoReport("No league seasons on record.")
    if row.age is None or row.age < ADULT_AGE:
        raise NoReport("Scouting reports are for adult players. A young player's profile shows how they are "
                       "growing instead, because grading a child against an adult standard is what hides late "
                       "bloomers.")
    group = config.group_of(row.position)
    if group is None:
        raise NoReport("No report for this position: the data has no goalkeeping statistics.")
    if row.minutes < min_minutes:
        raise NoReport(f"Only {row.minutes} minutes in {row.season}: a report needs {min_minutes}.")
    population = engine._population(config, rows, row.competition, row.season, group, min_minutes)
    if len(population) - 1 < engine.MIN_COHORT:
        raise NoReport(f"Too few {config.groups[group].label.lower()} in {row.competition} {row.season} "
                       "to compare with.")

    keys = list(dict.fromkeys(a for area in spec.areas.values() for a in area.attributes))
    pct = engine.percentiles(config, population, row, keys)
    evidence = {k: _evidence(config, population, row, k, p) for k, p in pct.items() if p is not None}

    graded = spec.roles[group]
    areas = []
    for area in spec.areas.values():
        items = [evidence[a] for a in area.attributes if a in evidence]
        score = round(statistics.fmean(e.percentile for e in items), 1) if items else None
        areas.append(AreaScore(area.key, area.label, score, grade(score), area.key in graded, items))
    role_scores = [a.score for a in areas if a.graded and a.score is not None]
    level = round(statistics.fmean(role_scores), 1) if len(role_scores) == len(graded) else None
    recommendation = None if level is None else (
        "Shortlist" if level >= SHORTLIST else "Monitor" if level >= MONITOR else "Not now")
    confidence = "high" if row.minutes >= HIGH_MINUTES else "medium" if row.minutes >= MEDIUM_MINUTES else "low"

    ordered = sorted(evidence.values(), key=lambda e: -e.percentile)
    strengths = [e for e in ordered if e.percentile >= STRONG][:SHOWN]
    weaknesses = [e for e in reversed(ordered) if e.percentile <= WEAK][:SHOWN]
    group_label = config.groups[group].label.lower()

    summary_bits = []
    if strengths:
        summary_bits.append(f"Standout numbers among {len(population) - 1} {group_label} in "
                            f"{row.competition} {row.season}: {', '.join(_in_a_sentence(e.label) for e in strengths[:3])}.")
    weakest = min((a for a in areas if a.graded and a.score is not None), key=lambda a: a.score, default=None)
    if weakest is not None:
        summary_bits.append(f"The weakest area the role needs is {weakest.label.lower()} "
                            f"({ordinal(weakest.score)} percentile on average).")
    would_change = []
    if weakest is not None:
        would_change.append(f"Progress in {weakest.label.lower()}, the weakest area the role needs, now the "
                            f"{ordinal(weakest.score)} percentile on average.")
    if confidence != "high":
        would_change.append(f"A fuller season: {row.minutes} minutes so far, and {HIGH_MINUTES} make a "
                            "high-confidence report.")
    would_change.append("Live scouting of what season statistics cannot see (below).")

    return Report(
        player_id=row.player_id, season=row.season, competition=row.competition, group=group,
        group_label=config.groups[group].label, minutes=row.minutes, population=len(population) - 1,
        level=level, level_grade=grade(level), recommendation=recommendation, confidence=confidence,
        areas=areas, strengths=strengths, weaknesses=weaknesses, summary=" ".join(summary_bits),
        would_change=would_change, not_in_data=list(spec.not_in_data),
        young=row.age < YOUNG,
    )
