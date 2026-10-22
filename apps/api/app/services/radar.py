"""The percentile radar on the profile and the compare screen.

Each axis is one statistic from the player's own match record (the same profiles as
`similar.py`, from ml/similarity.py: per 90 minutes in football, per set in table tennis),
placed as a percentile among comparable players:

- same sport and gender;
- same kind of position in football (goalkeeper, defender, midfielder, forward); table tennis
  has no positions that change the statistics, so everyone of the gender;
- same age: a player under 18 against their own age in whole years, pooled with the years
  either side when that age has too few players, exactly as `cohort.cohort_for` does for
  height; a player of 18 or more against adults.

The rules are the profile's own. Only players whose analytics consent is in effect are in the
reference, and a player without it gets no radar. An axis compared with fewer than
`cohort.MIN_COHORT` players gets no percentile at all: "the 90th percentile of four players"
looks like a finding and is not one. The population is always named.

Lower is better for unforced errors, so that axis is turned round: a high percentile always
means better.
"""

from __future__ import annotations

import math
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.player import Player
from app.services import similar
from app.services.cohort import MIN_COHORT, age_years, percentile_of

from ml import similarity  # noqa: E402  (similar puts ml/ on the path)

ADULT_AGE = 18

# (statistic, label, unit, higher is better). Rates are shown as the rate, not its log.
AXES: dict[str, list[tuple[str, str, str, bool]]] = {
    "football": [
        ("goals", "Goals", "per 90", True),
        ("shots", "Shots", "per 90", True),
        ("key_passes", "Key passes", "per 90", True),
        ("assists", "Assists", "per 90", True),
        ("passes_attempted", "Passes", "per 90", True),
        ("pass_completion", "Pass completion", "%", True),
        ("tackles", "Tackles", "per 90", True),
        ("distance_km", "Distance", "km per 90", True),
    ],
    "table_tennis": [
        ("point_share", "Points won", "%", True),
        ("set_share", "Sets won", "%", True),
        ("service_winners", "Service winners", "per set", True),
        ("unforced_errors", "Unforced errors", "per set", False),
    ],
}
# A goalkeeper's job is not in this data: there are no saves or goals conceded on record, so
# a goalkeeper's radar shows only the statistics that mean something for one.
GOALKEEPER_AXES = ("passes_attempted", "pass_completion", "distance_km")

GROUP_WORDS = {
    "goalkeeper": "goalkeepers",
    "defender": "defenders",
    "midfielder": "midfielders",
    "forward": "forwards",
}


def _display(key: str, raw: float) -> float:
    if key in ("pass_completion", "point_share", "set_share"):
        return round(raw * 100, 1)
    return round(max(0.0, math.exp(raw) - similarity._LOG_FLOOR), 2)


def _role(sport: str, position: str | None) -> str | None:
    return similarity.POSITION_GROUPS.get(position or "") if sport == "football" else None


def _band(age: float | None) -> int | None:
    if age is None:
        return None
    return ADULT_AGE if age >= ADULT_AGE else round(age)


def player_radar(db: Session, player: Player, today: date | None = None) -> dict:
    today = today or date.today()
    every = similar._profiles(db)
    pid = str(player.id)
    if pid not in every:
        from app.models.enums import ConsentPurpose
        from app.services.access import has_consent

        if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
            note = "Analytics consent is not in effect for this player, so they are not compared."
        else:
            note = (
                "Not enough on record to compare yet: the radar needs 450 minutes of football "
                "or 20 sets of table tennis."
            )
        return {"axes": [], "population": None, "note": note}

    me = every[pid]
    meta = {
        str(p.id): (p.position, age_years(p.date_of_birth, today))
        for p in db.execute(select(Player).where(Player.id.in_(list(every)))).scalars()
    }
    my_role = _role(me.sport, meta[pid][0])
    my_band = _band(meta[pid][1])

    def peers(bands: set[int | None]) -> list[similarity.Profile]:
        return [
            p
            for q, p in every.items()
            if p.sport == me.sport
            and p.gender == me.gender
            and _role(p.sport, meta.get(q, (None, None))[0]) == my_role
            and _band(meta.get(q, (None, None))[1]) in bands
        ]

    # One age, widened a year at a time when it has too few players, then every age under 18.
    # Table tennis needs it most: a few dozen players across all ages. The population label
    # below always names the span actually used, so a wider comparison is never passed off as
    # a narrow one.
    group, low, high = peers({my_band}), my_band, my_band
    if my_band is not None and my_band < ADULT_AGE:
        for spread in (1, 2, None):
            if len(group) >= MIN_COHORT:
                break
            if spread is None:
                low, high = None, ADULT_AGE - 1
            else:
                low, high = my_band - spread, min(my_band + spread, ADULT_AGE - 1)
            group = peers(set(range(low if low is not None else 0, high + 1)))

    axes = []
    for key, label, unit, higher in AXES.get(me.sport, []):
        if key not in me.raw or (my_role == "goalkeeper" and key not in GOALKEEPER_AXES):
            continue
        values = sorted(p.raw[key] for p in group if key in p.raw)
        percentile = None
        # When every comparable player has the same value (no goalkeeper scores), a percentile
        # would come out as 50 and look like information. It is left out instead.
        if len(values) >= MIN_COHORT and values[0] != values[-1]:
            percentile = percentile_of(values, me.raw[key])
            if not higher:
                percentile = 100 - percentile
        axes.append(
            {
                "key": key,
                "label": label,
                "value": _display(key, me.raw[key]),
                "unit": unit,
                "percentile": percentile,
                "compared_with": len(values),
            }
        )

    who = {"male": "boys", "female": "girls"}.get(me.gender, "players")
    if my_band is not None and my_band >= ADULT_AGE:
        who = {"male": "men", "female": "women"}.get(me.gender, "adults")
        ages = "aged 18 and over"
    elif low is None:
        ages = "under 18, all ages"
    elif low == high:
        ages = f"aged {low}"
    else:
        ages = f"aged {low} to {high}"
    role = f"{GROUP_WORDS[my_role]}, " if my_role else ""
    population = f"{role}{who} {ages}: {len(group)} with enough on record"
    shown = sum(a["percentile"] is not None for a in axes)
    note = (
        "Each axis is a percentile among the players named above: 50 is the middle, higher is "
        "better on every axis."
    )
    if shown < len(axes):
        note += (
            f" {len(axes) - shown} of {len(axes)} have no percentile: fewer than {MIN_COHORT} "
            "comparable players have that statistic on record, or they all have the same value."
        )
    if my_role == "goalkeeper":
        note += (
            " The data has no goalkeeping statistics (saves, goals conceded), so a goalkeeper is "
            "shown on passing and distance only."
        )
    return {"axes": axes, "population": population, "note": note}
