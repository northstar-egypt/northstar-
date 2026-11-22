"""Find the next <pro>: academy players whose style looks like a professional's.

The idea in one line: a scout picks a professional, and this lists the academy players who
play the same way for their age, with a match percentage and the reasons.

Why style and not totals
------------------------
A professional and a 14 year old are measured in different leagues, at different levels, so
their numbers can never be put side by side. What can be compared is how each one stands out
among their own peers. A winger who shoots far more than other league wingers, and an academy
winger who shoots far more than other academy wingers of the same age, have the same style,
even if one shoots five times as often. So:

1. Each player gets one number per statistic both data sets have, per 90 minutes or a share.
   Rates are taken as logs, as in ml/similarity.py.
2. Each number is standardised within the player's own peer group: a professional against
   professionals in the same position group (`PRO_MIN_MINUTES`, same data source); an academy
   player against academy players of the same position group, sex and age year (against every
   age of that group and sex when their age year has fewer than `MIN_PEERS`). This is where age is used: a
   14 year old is only ever judged against 14 year olds.
3. The two profiles are compared by a weighted cosine similarity: the weights say which
   statistics matter for the position (`WEIGHTS`). Height counts lightly, against the same
   peers (`BODY_WEIGHT`), because a growing child's height says little about the adult.
4. The match is the cosine as a percentage, 0 when the styles point opposite ways. It says
   how alike the styles are, not how good the player is or will be.

What it cannot see
------------------
Only statistics both data sets have are used (`PER_90`, `SHARES`): the academy record has no
dribbles, headers, interceptions, saves or speed in matches, so wingers and strikers are
compared well, defenders on tackles and passing only, and goalkeepers not at all.

Standard library only, like the detectors.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

# Statistics the academy match record (football.match.v1) and the league season
# (football.season_aggregate.v2) both have.
PER_90 = ("goals", "assists", "shots", "shots_on_target", "key_passes", "passes_attempted", "tackles")
SHARES = {
    "pass_completion": ("passes_completed", "passes_attempted"),
    "shot_accuracy": ("shots_on_target", "shots"),
}
BODY = ("height_cm",)
BODY_WEIGHT = 0.5

PRO_MIN_MINUTES = 900
YOUTH_MIN_MINUTES = 450
MIN_PEERS = 8
SHOWN = 10
_LOG_FLOOR = 0.05

FAMILY = {
    "CB": "centre_back", "LB": "full_back", "RB": "full_back",
    "CDM": "midfielder", "CM": "midfielder", "CAM": "midfielder",
    "LW": "winger", "RW": "winger", "ST": "striker",
}
FAMILY_LABEL = {
    "centre_back": "centre backs", "full_back": "full backs", "midfielder": "midfielders",
    "winger": "wingers", "striker": "strikers",
}
_LOW = 0.5
# How much each statistic counts, by position group. Anything not listed counts `_LOW`.
WEIGHTS = {
    "striker": {"goals": 2, "shots": 2, "shots_on_target": 1.5, "shot_accuracy": 1,
                "assists": 1, "key_passes": 1},
    "winger": {"assists": 2, "key_passes": 2, "goals": 1.5, "shots": 1.5,
               "shots_on_target": 1},
    "midfielder": {"passes_attempted": 2, "pass_completion": 2, "key_passes": 1.5,
                   "assists": 1.5, "tackles": 1},
    "full_back": {"tackles": 2, "passes_attempted": 1.5, "pass_completion": 1.5,
                  "key_passes": 1, "assists": 1},
    "centre_back": {"tackles": 2, "pass_completion": 2, "passes_attempted": 1.5},
}

LABELS = {
    "goals": "goals", "assists": "assists", "shots": "shots", "shots_on_target": "shots on target",
    "key_passes": "key passes", "passes_attempted": "passes", "tackles": "tackles",
    "pass_completion": "pass completion", "shot_accuracy": "shot accuracy", "height_cm": "height",
}

@dataclass
class Player:
    """One side of the comparison, before standardising."""
    player_id: str
    position: str | None
    # The peer group key beyond position: (source,) for a pro, (sex, age year) for a youth.
    peers: tuple
    raw: dict[str, float]


@dataclass
class Match:
    player_id: str
    percent: int
    # Up to three statistics that make them alike, and the one that differs most.
    alike: list[str]
    differs: str | None


def family(position: str | None) -> str | None:
    return FAMILY.get(position or "")


def rates(metrics: dict, minutes_key: str = "minutes_played") -> dict[str, float] | None:
    """The comparable numbers from summed metrics, or None when a statistic is missing."""
    minutes = metrics.get(minutes_key) or 0
    if minutes <= 0 or any(metrics.get(k) is None for k in PER_90):
        return None
    out = {k: math.log(metrics[k] / minutes * 90 + _LOG_FLOOR) for k in PER_90}
    for key, (num, den) in SHARES.items():
        if metrics.get(den):
            out[key] = metrics.get(num, 0) / metrics[den]
    return out


def _standardise(players: list[Player]) -> dict[str, dict[str, float]]:
    """Each player's z-scores within their peer group (position group plus `peers`)."""
    groups: dict[tuple, list[Player]] = {}
    for p in players:
        groups.setdefault((family(p.position), *p.peers), []).append(p)
    out: dict[str, dict[str, float]] = {p.player_id: {} for p in players}
    for group in groups.values():
        names = {k for p in group for k in p.raw}
        for name in names:
            values = [p.raw[name] for p in group if name in p.raw]
            if len(values) < 2:
                continue
            mean, sd = statistics.fmean(values), statistics.pstdev(values)
            if not sd:
                continue
            for p in group:
                if name in p.raw:
                    out[p.player_id][name] = (p.raw[name] - mean) / sd
    return out


def youth_peers(youth: list[Player]) -> list[Player]:
    """Marks a player whose age year has fewer than `MIN_PEERS` players to be judged against
    every age of their position group (peers ``(sex, "any age")``)."""
    counts: dict[tuple, int] = {}
    for p in youth:
        counts[(family(p.position), *p.peers)] = counts.get((family(p.position), *p.peers), 0) + 1
    out = []
    for p in youth:
        if counts[(family(p.position), *p.peers)] < MIN_PEERS:
            p = Player(p.player_id, p.position, (p.peers[0], "any age"), p.raw)
        out.append(p)
    return out


def youth_z(group: list[Player]) -> dict[str, dict[str, float]]:
    """Academy z-scores within one position group: against the same sex and age year, or, for a
    player whose age year is too small, against every age of the same sex."""
    marked = youth_peers(group)
    by_year = _standardise([p for p in marked if p.peers[1] != "any age"])
    all_ages = _standardise([Player(p.player_id, p.position, (p.peers[0], "any age"), p.raw) for p in group])
    return {p.player_id: (all_ages if p.peers[1] == "any age" else by_year)[p.player_id] for p in marked}


def _weight(fam: str, key: str) -> float:
    if key in BODY:
        return BODY_WEIGHT
    return WEIGHTS[fam].get(key, _LOW)


def compare(fam: str, pro: dict[str, float], youth: dict[str, float]) -> Match | None:
    shared = [k for k in pro if k in youth]
    if len(shared) < 3:
        return None
    w = {k: _weight(fam, k) for k in shared}
    dot = sum(w[k] * pro[k] * youth[k] for k in shared)
    norm = math.sqrt(sum(w[k] * pro[k] ** 2 for k in shared)) * math.sqrt(
        sum(w[k] * youth[k] ** 2 for k in shared))
    cos = dot / norm if norm else 0.0
    # Alike: both stand out the same way on it, weighted by how much it counts.
    # Height counts in the match but is not offered as a reason: it says little about style.
    agree = sorted((k for k in shared if k not in BODY and pro[k] * youth[k] > 0 and abs(pro[k]) >= 0.5),
                   key=lambda k: -w[k] * pro[k] * youth[k])[:3]
    gaps = sorted((k for k in shared if k not in agree), key=lambda k: -w[k] * abs(pro[k] - youth[k]))
    differs = gaps[0] if gaps and abs(pro[gaps[0]] - youth[gaps[0]]) >= 1 else None
    return Match("", max(0, round(cos * 100)), agree, differs)


def matches(pro: Player, pros: list[Player], youth: list[Player], shown: int = SHOWN,
            keep_opposite: bool = False) -> list[Match]:
    """The academy players whose style is most like `pro`'s, best first.

    A 0% match (styles pointing opposite ways) is left out unless `keep_opposite`, which the
    evaluation sets so that it measures the ranking itself, not how long the list is.

    `pros` is the professional pool (the pro must be in it); `youth` is every academy player who
    may be shown, already filtered for consent and access by the caller.
    """
    fam = family(pro.position)
    if fam is None:
        return []
    peers = [p for p in pros if family(p.position) == fam and p.peers == pro.peers]
    if len(peers) < MIN_PEERS:
        return []
    pz = _standardise(peers)[pro.player_id]
    group = [y for y in youth if family(y.position) == fam]
    if len(group) < MIN_PEERS:
        return []
    yz = youth_z(group)
    out = []
    for y in group:
        m = compare(fam, pz, yz[y.player_id])
        # 0% means the styles point opposite ways: not a match, so not listed.
        if m is not None and (m.percent > 0 or keep_opposite):
            m.player_id = y.player_id
            out.append(m)
    out.sort(key=lambda m: (-m.percent, m.player_id))
    return out[:shown]


def reason(key: str, z: float) -> str:
    """"more shots per 90 than others in the position", for the sentence under a match."""
    if key == "height_cm":
        return "taller than their peers" if z > 0 else "shorter than their peers"
    if key in SHARES:
        return f"{'higher' if z > 0 else 'lower'} {LABELS[key]} than others in the position"
    return f"{'more' if z > 0 else 'fewer'} {LABELS.get(key, key)} per 90 than others in the position"


def pro_profile(pro: Player, pros: list[Player]) -> dict[str, float]:
    """The pro's standardised style, for the reasons line."""
    peers = [p for p in pros if family(p.position) == family(pro.position) and p.peers == pro.peers]
    return _standardise(peers).get(pro.player_id, {})


def percent_between(pro_id: str, youth_id: str, pros: list[Player], youth: list[Player]) -> int | None:
    """The style match between one professional and one academy player, or None when either
    cannot be compared (no position group, too few peers, too little in common)."""
    pro = next((p for p in pros if p.player_id == pro_id), None)
    if pro is None:
        return None
    for m in matches(pro, pros, youth, shown=len(youth), keep_opposite=True):
        if m.player_id == youth_id:
            return m.percent
    return None


def idol(youth_id: str, pros: list[Player], youth: list[Player]) -> tuple[str, int] | None:
    """The professional whose style an academy player matches best: (pro id, percent)."""
    me = next((y for y in youth if y.player_id == youth_id), None)
    fam = family(me.position) if me else None
    if fam is None:
        return None
    group = [y for y in youth if family(y.position) == fam]
    if len(group) < MIN_PEERS:
        return None
    yz = youth_z(group).get(youth_id, {})
    best = None
    by_source: dict[tuple, list[Player]] = {}
    for p in pros:
        if family(p.position) == fam:
            by_source.setdefault(p.peers, []).append(p)
    for peers in by_source.values():
        if len(peers) < MIN_PEERS:
            continue
        pz = _standardise(peers)
        for p in peers:
            m = compare(fam, pz[p.player_id], yz)
            if m is not None and (best is None or m.percent > best[1]):
                best = (p.player_id, m.percent)
    return best
