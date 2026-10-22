"""The explorer: comparable players on two statistics at once, and the leaders of a group.

A scout's question is rarely "how good is this one player" and usually "who stands out on
these two things together": a forward who shoots a lot and scores, a midfielder who passes a
lot and completes them. The scatter plot answers that. The leaders answer the question before
it: "which midfielders of 15 and 16 are best at each thing".

Both use the radar's statistics (`radar.AXES`, from the same match profiles in
ml/similarity.py: per 90 minutes in football, per set in table tennis), so a number here is the
number on the profile. Both pick their group the same way (`_resolve`), and both follow the
radar's and the profile's rules:

- Only players whose analytics consent is in effect are in it at all.
- A player is named only to a caller who may open them (`access.may_view`). The others are
  still counted in the group, its medians and its percentiles, the way a percentile on the
  profile counts everyone, but nothing identifies them.
- Medians and percentiles come only from `cohort.MIN_COHORT` players or more. "Above the
  median of five" is not a finding.
- The group is always named, with how many are in it and how many are shown.

TODO: profiles come from `similar._profiles`, which rebuilds per request when data changes.
At national scale this belongs in a batch job.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sports
from app.models.player import Player
from app.services import radar, similar
from app.services.access import Caller, may_view, visible_players
from app.services.cohort import MIN_COHORT, age_label, age_years, percentile_of

from ml import similarity  # noqa: E402  (similar puts ml/ on the path)

GROUPS = ("goalkeeper", "defender", "midfielder", "forward")
# What the plot opens on before anyone picks: the two statistics a scout looks at first.
DEFAULT_AXES = {
    "football": ("shots", "goals"),
    "table_tennis": ("point_share", "unforced_errors"),
}
LEADERS = 5


class ExploreError(ValueError):
    """A request the explorer cannot answer, with a message fit for the screen."""


def stats_for(sport: str, group: str | None) -> list[tuple[str, str, str, bool]]:
    axes = radar.AXES.get(sport, [])
    if group == "goalkeeper":
        return [a for a in axes if a[0] in radar.GOALKEEPER_AXES]
    return list(axes)


@dataclass
class _Group:
    sport: str
    gender: str
    group: str | None
    age_from: int | None
    age_to: int | None
    genders: list[str]
    stats: list[tuple[str, str, str, bool]]
    # Everyone in the group with a match profile, and the subset the caller may open.
    members: list[str]
    shown: set[str]
    profiles: dict[str, similarity.Profile]
    players: dict[str, Player]
    focus: str | None

    def words(self, count: int) -> str:
        gender = {"male": "men and boys", "female": "women and girls"}[self.gender]
        if self.age_from is not None and self.age_to is not None:
            ages = (
                f"aged {self.age_from}" if self.age_from == self.age_to
                else f"aged {self.age_from} to {self.age_to}"
            )
        elif self.age_from is not None:
            ages = f"aged {self.age_from} and over"
        elif self.age_to is not None:
            ages = f"aged {self.age_to} and under"
        else:
            ages = "of every age"
        role = f"{radar.GROUP_WORDS[self.group]}, " if self.group else ""
        return f"{role}{gender} {ages}: {count} with enough on record"

    def enough(self) -> str:
        needed = "450 minutes of football" if self.sport == "football" else "20 sets"
        return f" A player needs {needed} on record and analytics consent to be included."

    def echo(self) -> dict:
        return {
            "sport": self.sport,
            "gender": self.gender,
            "group": self.group,
            "age_from": self.age_from,
            "age_to": self.age_to,
            "stats": [
                {"key": k, "label": label, "unit": unit, "higher_is_better": higher}
                for k, label, unit, higher in self.stats
            ],
            "genders": self.genders,
            "groups": list(GROUPS) if self.sport == "football" else [],
        }

    def person(self, pid: str, today: date) -> dict:
        player = self.players[pid]
        return {
            "player_id": pid,
            "full_name": player.full_name,
            "position": player.position,
            "age_label": age_label(player.date_of_birth, today),
        }


def _resolve(
    db: Session,
    caller: Caller,
    *,
    sport: str | None,
    gender: str | None,
    group: str | None,
    age_from: int | None,
    age_to: int | None,
    focus: Player | None,
    today: date,
) -> _Group:
    every = similar._profiles(db)

    # A focus player (from a profile's link) sets whatever was not asked for.
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

    candidates = {
        pid: p for pid, p in every.items() if p.sport == sport and p.gender == gender
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

    # Named only to a caller who may open them. The rest are counted, not identified.
    visible_ids = {
        str(p.id)
        for p in db.execute(
            visible_players(caller).where(Player.id.in_(members))
        ).scalars()
    } if members else set()
    shown = {
        pid for pid in members if pid in visible_ids and may_view(db, caller, players[pid])[0]
    }

    return _Group(
        sport=sport,
        gender=gender,
        group=group,
        age_from=age_from,
        age_to=age_to,
        genders=list(module.genders),
        stats=stats_for(sport, group),
        members=members,
        shown=shown,
        profiles=candidates,
        players=players,
        focus=str(focus.id) if focus_profile is not None and str(focus.id) in shown else None,
    )


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
    g = _resolve(
        db, caller, sport=sport, gender=gender, group=group, age_from=age_from,
        age_to=age_to, focus=focus, today=today,
    )

    keys = [s[0] for s in g.stats]
    default_x, default_y = DEFAULT_AXES[g.sport]
    if g.group == "goalkeeper":
        default_x, default_y = "passes_attempted", "pass_completion"
    x = x or default_x
    y = y or default_y
    for chosen in (x, y):
        if chosen not in keys:
            raise ExploreError(f"{chosen!r} is not a statistic on this plot.")

    raw = g.profiles
    members = [pid for pid in g.members if x in raw[pid].raw and y in raw[pid].raw]
    shown = [pid for pid in members if pid in g.shown]

    points = [
        {
            **g.person(pid, today),
            "x": radar._display(x, raw[pid].raw[x]),
            "y": radar._display(y, raw[pid].raw[y]),
        }
        for pid in shown
    ]
    points.sort(key=lambda p: p["full_name"])

    medians = None
    if len(members) >= MIN_COHORT:
        medians = {
            "x": radar._display(x, statistics.median(raw[p].raw[x] for p in members)),
            "y": radar._display(y, statistics.median(raw[p].raw[y] for p in members)),
        }

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
    lower = [s[1] for s in g.stats if not s[3] and s[0] in (x, y)]
    if lower:
        note += f" Lower is better for {', '.join(l.lower() for l in lower)}."
    note += g.enough()

    return {
        **g.echo(),
        "x": x,
        "y": y,
        "points": points,
        "medians": medians,
        "total": len(members),
        "population": g.words(len(members)),
        "focus": g.focus if g.focus in shown else None,
        "note": note,
    }


def leaders(
    db: Session,
    caller: Caller,
    *,
    sport: str | None = None,
    gender: str | None = None,
    group: str | None = None,
    age_from: int | None = None,
    age_to: int | None = None,
    focus: Player | None = None,
    today: date | None = None,
) -> dict:
    """For each statistic: the group's median and its best players the caller may open.

    A leader's percentile is among the whole group, not among the players shown, so it means
    what the same number means on the profile. A statistic whose group is too small, or where
    everyone has the same value, has no median, no percentiles and no leaders: ranking players
    who cannot be told apart would be inventing an order.
    """
    today = today or date.today()
    g = _resolve(
        db, caller, sport=sport, gender=gender, group=group, age_from=age_from,
        age_to=age_to, focus=focus, today=today,
    )

    boards = []
    for key, label, unit, higher in g.stats:
        have = [pid for pid in g.members if key in g.profiles[pid].raw]
        values = sorted(g.profiles[pid].raw[key] for pid in have)
        board = {
            "key": key,
            "label": label,
            "unit": unit,
            "higher_is_better": higher,
            "compared_with": len(values),
            "median": None,
            "leaders": [],
            "focus": None,
        }
        if len(values) >= MIN_COHORT and values[0] != values[-1]:
            board["median"] = radar._display(key, statistics.median(values))

            def entry(pid: str) -> dict:
                value = g.profiles[pid].raw[key]
                percentile = percentile_of(values, value)
                return {
                    **g.person(pid, today),
                    "value": radar._display(key, value),
                    "percentile": percentile if higher else 100 - percentile,
                }

            ranked = sorted(
                (pid for pid in have if pid in g.shown),
                key=lambda pid: g.profiles[pid].raw[key],
                reverse=higher,
            )
            board["leaders"] = [entry(pid) for pid in ranked[:LEADERS]]
            # The focus player's own place, so a coach sees where their player stands even
            # when they are not among the leaders.
            if g.focus in ranked:
                board["focus"] = {**entry(g.focus), "rank": ranked.index(g.focus) + 1}
        boards.append(board)

    note = (
        f"The best {LEADERS} on each statistic among the players you may open. Each percentile "
        "is among the whole group named above, so it reads the same as on a profile."
    )
    hidden = len(g.members) - len(g.shown)
    if hidden:
        note += (
            f" {hidden} of the {len(g.members)} are counted in medians and percentiles but not "
            "listed, because you may not open their records."
        )
    empty = sum(b["median"] is None for b in boards)
    if empty:
        note += (
            f" {empty} of {len(boards)} statistics have no leaders: fewer than {MIN_COHORT} "
            "players have them on record, or they all have the same value."
        )
    note += g.enough()

    return {
        **g.echo(),
        "boards": boards,
        "total": len(g.members),
        "shown": len(g.shown),
        "population": g.words(len(g.members)),
        "focus": g.focus,
        "note": note,
    }
