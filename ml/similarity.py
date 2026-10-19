"""Player similarity: "players like this one", from each player's own statistical profile.

What a profile is
-----------------
One number per statistic, from the player's match rows, scaled to the time played so a
substitute and a starter can be compared:

- football: per 90 minutes, shots, shots on target, goals, assists, key passes, tackles,
  passes attempted and distance; and pass completion (completed over attempted). A player
  needs `FOOTBALL_MIN_MINUTES` on record.
- table tennis: per set, service winners and unforced errors; and the share of points and of
  sets won. A player needs `TABLE_TENNIS_MIN_SETS` on record.

Rates are taken as logs (a striker's 3 shots per 90 against a defender's 0.5 is a ratio,
not a difference), then each statistic is standardised across the sport, so every statistic
counts the same. Distance is Euclidean over those, divided by the square root of their
number, so a distance of 1 is one standard deviation on a typical statistic.

Rows the sport module says cannot be true are skipped, and so are a player's rows that the
opponent's own row contradicts (fraud.contradicting_matches): a profile is built only from
what the record supports. Merged records are left out.

Who is compared with whom
-------------------------
Only players of the same sport and gender. Football is not filtered by position: whether the
statistics alone find players of the same kind of role is one of the two things the
evaluation measures, and a scout may want "a midfielder who plays like a forward".

What it is graded on (python -m ml.run_similarity_eval)
--------------------------------------------------------
The generator draws every footballer's statistics from their position and one hidden number,
ability, which scales only shots and key passes; a table tennis player's from ability alone.
So in this data "similar" can only mean the same role and the same level. Real players differ
in style in ways this data does not have, and these numbers say nothing about that.

Standard library only, like the detectors.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from ml.detectors import fraud
from ml.detectors.features import FeatureSet, _number

FOOTBALL_PER_90 = (
    "shots",
    "shots_on_target",
    "goals",
    "assists",
    "key_passes",
    "tackles",
    "passes_attempted",
    "distance_km",
)
TABLE_TENNIS_PER_SET = ("service_winners", "unforced_errors")
FOOTBALL_MIN_MINUTES = 450
TABLE_TENNIS_MIN_SETS = 20
# Keeps a zero count finite in the log without moving a real rate much.
_LOG_FLOOR = 0.05

# Kinds of role, for the evaluation only: a profile never reads them.
POSITION_GROUPS = {
    "GK": "goalkeeper",
    "CB": "defender", "LB": "defender", "RB": "defender",
    "CDM": "midfielder", "CM": "midfielder", "CAM": "midfielder",
    "LW": "forward", "RW": "forward", "ST": "forward",
}


@dataclass
class Profile:
    player_id: str
    sport: str
    gender: str
    # Statistic name -> value before standardising (a log rate or a share).
    raw: dict[str, float] = field(default_factory=dict)
    # Statistic name -> standardised value, filled by `profiles`.
    z: dict[str, float] = field(default_factory=dict)


def _sport_module_ok(entry: dict) -> bool:
    from ml import sport_modules

    metrics = entry.get("metrics")
    return isinstance(metrics, dict) and not sport_modules.impossibilities(
        metrics, entry.get("schema_ref", "")
    )


def _football(rows: list[dict]) -> dict[str, float] | None:
    totals = {k: 0.0 for k in FOOTBALL_PER_90}
    minutes = completed = attempted = 0.0
    for e in rows:
        m = e["metrics"]
        played = _number(m.get("minutes_played"))
        if played is None or played <= 0 or any(_number(m.get(k)) is None for k in FOOTBALL_PER_90):
            continue  # an incomplete row: absence is not zero
        minutes += played
        for k in FOOTBALL_PER_90:
            totals[k] += _number(m[k])
        done, tried = _number(m.get("passes_completed")), _number(m.get("passes_attempted"))
        if done is not None and tried:
            completed += done
            attempted += tried
    if minutes < FOOTBALL_MIN_MINUTES:
        return None
    raw = {k: math.log(totals[k] / minutes * 90 + _LOG_FLOOR) for k in FOOTBALL_PER_90}
    if attempted:
        raw["pass_completion"] = completed / attempted
    return raw


def _table_tennis(rows: list[dict]) -> dict[str, float] | None:
    totals = {k: 0.0 for k in TABLE_TENNIS_PER_SET}
    sets_won = sets_lost = points_won = points_lost = 0.0
    for e in rows:
        m = e["metrics"]
        values = [_number(m.get(k)) for k in ("sets_won", "sets_lost", "points_won", "points_lost")]
        if any(v is None for v in values) or any(_number(m.get(k)) is None for k in TABLE_TENNIS_PER_SET):
            continue
        sw, sl, pw, pl = values
        sets_won, sets_lost, points_won, points_lost = (
            sets_won + sw, sets_lost + sl, points_won + pw, points_lost + pl,
        )
        for k in TABLE_TENNIS_PER_SET:
            totals[k] += _number(m[k])
    sets = sets_won + sets_lost
    if sets < TABLE_TENNIS_MIN_SETS or not points_won + points_lost:
        return None
    raw = {k: math.log(totals[k] / sets + _LOG_FLOOR) for k in TABLE_TENNIS_PER_SET}
    raw["point_share"] = points_won / (points_won + points_lost)
    raw["set_share"] = sets_won / sets
    return raw


def profiles(features: FeatureSet) -> dict[str, Profile]:
    """Every player with enough time on record, standardised within their sport."""
    disputed = {
        str(row.get("id")) for pair in fraud.contradicting_matches(features) for row in pair
    }
    out: dict[str, Profile] = {}
    for pid, pf in features.players.items():
        if pf.player.get("status") == "merged":
            continue
        sport = pf.player.get("primary_sport")
        rows = [
            e
            for e in pf.performance
            if e.get("period_type", "match") == "match"
            and str(e.get("id")) not in disputed
            and _sport_module_ok(e)
        ]
        raw = _football(rows) if sport == "football" else (
            _table_tennis(rows) if sport == "table_tennis" else None
        )
        if raw:
            out[pid] = Profile(pid, sport, pf.sex, raw)

    for sport in {p.sport for p in out.values()}:
        group = [p for p in out.values() if p.sport == sport]
        for name in group[0].raw:
            values = [p.raw[name] for p in group if name in p.raw]
            if len(values) < 2:
                continue
            mean, sd = statistics.fmean(values), statistics.pstdev(values) or 1.0
            for p in group:
                if name in p.raw:
                    p.z[name] = (p.raw[name] - mean) / sd
    return out


def distance(a: Profile, b: Profile) -> float:
    shared = [k for k in a.z if k in b.z]
    if not shared:
        return math.inf
    return math.sqrt(sum((a.z[k] - b.z[k]) ** 2 for k in shared) / len(shared))


def nearest(
    target: str, every: dict[str, Profile], k: int = 5, allowed: set[str] | None = None
) -> list[tuple[str, float]]:
    """The k players most like `target`: same sport and gender, closest first.

    `allowed`, when given, is who may be returned at all (consent, and who the caller may
    see); the API passes it, the evaluation does not.
    """
    me = every[target]
    candidates = [
        (pid, distance(me, p))
        for pid, p in every.items()
        if pid != target
        and p.sport == me.sport
        and p.gender == me.gender
        and (allowed is None or pid in allowed)
    ]
    candidates.sort(key=lambda item: (item[1], item[0]))
    return candidates[:k]


def closest_statistics(a: Profile, b: Profile, n: int = 3) -> list[str]:
    """The statistics on which two players are most alike, for the sentence a scout reads."""
    shared = [k for k in a.z if k in b.z]
    return sorted(shared, key=lambda k: abs(a.z[k] - b.z[k]))[:n]
