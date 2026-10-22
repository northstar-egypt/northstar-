"""The scatter explorer: every comparable player on two statistics at once.

A scout's question is rarely "how good is this one player" and usually "who stands out on
these two things together": a forward who shoots a lot and scores, a midfielder who passes a
lot and completes them. The plot answers that. Its statistics are the radar's (`radar.AXES`,
from the same match profiles in ml/similarity.py: per 90 minutes in football, per set in table
tennis), so a number here is the number on the profile.

The rules are the radar's and the profile's:

- Only players whose analytics consent is in effect are in it at all.
- A point is drawn only for a player the caller may open (`access.may_view`). The others are
  still counted in the group and in its medians, the way a percentile counts everyone, but
  nothing identifies them.
- The median lines that split the plot into quarters are drawn only from `cohort.MIN_COHORT`
  players or more. "Above the median of five" is not a finding.
- The group is always named, with how many are in it and how many are shown.

TODO: profiles come from `similar._profiles`, which rebuilds per request when data changes.
At national scale this belongs in a batch job.
"""

from __future__ import annotations

import statistics
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sports
from app.models.player import Player
from app.services import radar, similar
from app.services.access import Caller, may_view, visible_players
from app.services.cohort import MIN_COHORT, age_label, age_years

GROUPS = ("goalkeeper", "defender", "midfielder", "forward")
# What the plot opens on before anyone picks: the two statistics a scout looks at first.
DEFAULT_AXES = {
    "football": ("shots", "goals"),
    "table_tennis": ("point_share", "unforced_errors"),
}


class ExploreError(ValueError):
    """A request the explorer cannot answer, with a message fit for the screen."""


def stats_for(sport: str, group: str | None) -> list[tuple[str, str, str, bool]]:
    axes = radar.AXES.get(sport, [])
    if group == "goalkeeper":
        return [a for a in axes if a[0] in radar.GOALKEEPER_AXES]
    return list(axes)


def scatter(
    db: Session,
    caller: Caller,
    *,
    sport: str | None = None,
    gender: str | None = None,
    group: str | None = None,
    age_from: int | None = None,
    age_to: int | None = None,
    x: str | None = None,
    y: str | None = None,
    focus: Player | None = None,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    every = similar._profiles(db)

    # A focus player (from "see on the scatter" on a profile) sets whatever was not asked for.
    focus_profile = every.get(str(focus.id)) if focus is not None else None
    if focus_profile is not None:
        sport = sport or focus_profile.sport
        gender = gender or focus_profile.gender
        if sport == "football" and group is None:
            group = radar._role(sport, focus.position)

    sport = sport or "football"
    module = sports.registry().get(sport)
    if module is None or sport not in radar.AXES:
        raise ExploreError(f"No statistics to plot for a sport called {sport!r}.")
    # Which genders a sport registers is its module's call; they are never pooled.
    gender = gender or module.genders[0]
    if gender not in module.genders:
        raise ExploreError(f"{module.label} on NorthStar does not register {gender} players.")
    if sport != "football" or group == "all":
        group = None
    if group is not None and group not in GROUPS:
        raise ExploreError(f"No position group called {group!r}.")
    if age_from is not None and age_to is not None and age_from > age_to:
        raise ExploreError("The youngest age is above the oldest.")

    stats = stats_for(sport, group)
    keys = [s[0] for s in stats]
    default_x, default_y = DEFAULT_AXES[sport]
    if group == "goalkeeper":
        default_x, default_y = "passes_attempted", "pass_completion"
    x = x or default_x
    y = y or default_y
    for chosen in (x, y):
        if chosen not in keys:
            raise ExploreError(f"{chosen!r} is not a statistic on this plot.")

    candidates = {
        pid: p for pid, p in every.items()
        if p.sport == sport and p.gender == gender and x in p.raw and y in p.raw
    }
    players = {
        str(p.id): p
        for p in db.execute(select(Player).where(Player.id.in_(list(candidates)))).scalars()
    } if candidates else {}

    def fits(pid: str) -> bool:
        player = players.get(pid)
        if player is None:
            return False
        if group is not None and radar._role(sport, player.position) != group:
            return False
        age = age_years(player.date_of_birth, today)
        if age_from is not None and (age is None or int(age) < age_from):
            return False
        if age_to is not None and (age is None or int(age) > age_to):
            return False
        return True

    members = [pid for pid in candidates if fits(pid)]

    # Points only for players the caller may open. The rest are counted, not identified.
    visible_ids = {
        str(p.id)
        for p in db.execute(
            visible_players(caller).where(Player.id.in_(members))
        ).scalars()
    } if members else set()
    shown = [pid for pid in members if pid in visible_ids and may_view(db, caller, players[pid])[0]]

    points = [
        {
            "player_id": pid,
            "full_name": players[pid].full_name,
            "position": players[pid].position,
            "age_label": age_label(players[pid].date_of_birth, today),
            "x": radar._display(x, candidates[pid].raw[x]),
            "y": radar._display(y, candidates[pid].raw[y]),
        }
        for pid in shown
    ]
    points.sort(key=lambda p: p["full_name"])

    medians = None
    if len(members) >= MIN_COHORT:
        medians = {
            "x": radar._display(x, statistics.median(candidates[p].raw[x] for p in members)),
            "y": radar._display(y, statistics.median(candidates[p].raw[y] for p in members)),
        }

    words = {"male": "men and boys", "female": "women and girls"}[gender]
    if age_from is not None and age_to is not None:
        ages = f"aged {age_from}" if age_from == age_to else f"aged {age_from} to {age_to}"
    elif age_from is not None:
        ages = f"aged {age_from} and over"
    elif age_to is not None:
        ages = f"aged {age_to} and under"
    else:
        ages = "of every age"
    role = f"{radar.GROUP_WORDS[group]}, " if group else ""
    population = f"{role}{words} {ages}: {len(members)} with enough on record"

    note = (
        "Each point is a player you may open. The dashed lines are the group's medians, so the "
        "top right quarter is above the middle on both."
    )
    if len(shown) < len(members):
        note += (
            f" {len(members) - len(shown)} of the {len(members)} are counted in the medians but "
            "not drawn, because you may not open their records."
        )
    if medians is None:
        note = (
            f"Fewer than {MIN_COHORT} players in this group, so there are no median lines. "
            "Widen the ages or the positions."
            + (" Each point is a player you may open." if points else "")
        )
    lower = [s[1] for s in stats if not s[3] and s[0] in (x, y)]
    if lower:
        note += f" Lower is better for {', '.join(l.lower() for l in lower)}."
    enough = "450 minutes of football" if sport == "football" else "20 sets"
    note += f" A player needs {enough} on record and analytics consent to be included."

    return {
        "sport": sport,
        "gender": gender,
        "group": group,
        "age_from": age_from,
        "age_to": age_to,
        "x": x,
        "y": y,
        "stats": [
            {"key": k, "label": label, "unit": unit, "higher_is_better": higher}
            for k, label, unit, higher in stats
        ],
        "genders": list(module.genders),
        "groups": list(GROUPS) if sport == "football" else [],
        "points": points,
        "medians": medians,
        "total": len(members),
        "population": population,
        "focus": str(focus.id) if focus_profile is not None and str(focus.id) in shown else None,
        "note": note,
    }
