"""Whom to measure next: schedules for a coach's measuring sessions, and an optimiser for them.

Every model in the project gets better the more often a player is measured, and the
late-bloomer backtest showed the cost of too few readings: the detector needs three, and more
than half the late bloomers a size cut would have released had fewer. Measuring sessions are
limited, so the question is whom to measure in each one.

The setting
-----------
Each academy holds a measuring session every SESSION_DAYS days. A session can measure a fixed
number of players (its capacity). A player can be measured while they are at the academy. Every
schedule below gets the same capacity, so they are compared at the same cost.

The schedules
-------------
- ``rota``: a fixed rotation through the squad, the simplest fair schedule.
- ``nudge``: longest since the last reading first, never-measured first of all. This is what
  the squad screen's "due a reading" nudge does today.
- ``random``: the floor.
- ``optimised``: an integer program, re-solved at every session over the next HORIZON
  sessions (a rolling horizon). Each player has a value for being measured (below); the
  program picks who to measure in which session to maximise the value, subject to:
    * each session's capacity;
    * at most one reading per player within the horizon;
    * a policy rule: nobody goes longer than MAX_GAP_DAYS without a reading (a soft
      constraint with a large penalty, so it holds whenever capacity allows).
  Only the first session's choice is carried out; the next session plans again with what was
  learned. Solved with ``scipy.optimize.milp``.

The value of measuring a player now uses only what a coach could see: the recorded date of
birth and the readings so far, never the generator's hidden truth.

- **Age:** the size cut that releases late developers happens between 12 and 16, so a player
  aged AGE_WINDOW (recorded age) counts fully, anyone else at OUT_OF_WINDOW.
- **Size:** smaller for their age group, more at stake: a logistic in the height z-score among
  the players measured lately, of the same sex and age year.
- **Need:** the late-bloomer detector needs three readings in a year; the first three are
  worth most, a fourth less, more than that little (NEED).
- **Staleness:** a little extra the longer since the last reading.

Every constant in version 1 was set before the first evaluation run and has not been tuned.
Version 2 (`value_span`, schedule ``optimised-span``) was written after version 1's reported
result, from the detector's own definition of a growth rate, with its constants set before it
was run. On the calibration seeds it lost to version 1 (it flags fewer late bloomers), so it
was never run on a reported seed and is not the method; it is kept so the result can be
reproduced (ml/README.md, "Who to measure next").
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

SESSION_DAYS = 28
HORIZON = 3
MAX_GAP_DAYS = 183
MIN_GAP_DAYS = 21
AGE_WINDOW = (11.0, 16.5)
OUT_OF_WINDOW = 0.15
SIZE_SLOPE = 1.5
NEED = {0: 1.0, 1: 1.0, 2: 1.0, 3: 0.6}
NEED_MORE = 0.3
STALE_WEIGHT = 0.25
STALE_DAYS = 180
LATER = 0.9          # a reading planned for a later session is worth this much less per session
GAP_PENALTY = 100.0  # the price of breaking the six-month rule, far above any value

# Version 2 of the value (see `value_span`): the window and span the late-bloomer detector's
# growth rate uses (ml/detectors/features.py: readings of the last 400 days, nothing under 60).
VELOCITY_WINDOW_DAYS = 400
FULL_SPAN_DAYS = 365
COUNT_WEIGHT = 0.5
COUNT_DONE = 0.2

POLICIES = ("rota", "nudge", "random", "optimised", "optimised-span")


@dataclass
class Player:
    id: str
    sex: str
    date_of_birth: date | None
    present_from: date
    present_to: date
    readings: list[tuple[date, float]] = field(default_factory=list)  # (date, height)

    def present(self, on: date) -> bool:
        return self.present_from <= on <= self.present_to

    def last_reading(self) -> date | None:
        return self.readings[-1][0] if self.readings else None

    def age(self, on: date) -> float | None:
        if self.date_of_birth is None:
            return None
        return (on - self.date_of_birth).days / 365.25


def height_z(players: list[Player], on: date) -> dict[str, float]:
    """Each player's latest height as a z-score among players of the same sex and age year
    measured in the last MAX_GAP_DAYS. A group under 5 gives no z (treated as average)."""
    groups: dict[tuple[str, int], list[tuple[str, float]]] = {}
    for p in players:
        last = p.last_reading()
        age = p.age(last) if last else None
        if last is None or age is None or (on - last).days > MAX_GAP_DAYS:
            continue
        groups.setdefault((p.sex, int(age)), []).append((p.id, p.readings[-1][1]))
    out = {}
    for rows in groups.values():
        if len(rows) < 5:
            continue
        heights = [h for _, h in rows]
        mean = sum(heights) / len(heights)
        sd = math.sqrt(sum((h - mean) ** 2 for h in heights) / len(heights)) or 1.0
        for pid, h in rows:
            out[pid] = (h - mean) / sd
    return out


def value(p: Player, on: date, z: float | None) -> float:
    """What measuring `p` on `on` is worth (see the module docstring)."""
    age = p.age(on)
    in_window = age is not None and AGE_WINDOW[0] <= age <= AGE_WINDOW[1]
    stake = 1.0 if in_window else OUT_OF_WINDOW
    small = 1 / (1 + math.exp(SIZE_SLOPE * (z if z is not None else 0.0)))
    recent = sum(1 for d, _ in p.readings if (on - d).days <= 365)
    need = NEED.get(recent, NEED_MORE)
    last = p.last_reading()
    stale = 1.0 if last is None else min(1.0, (on - last).days / STALE_DAYS)
    return stake * (0.5 + small) * need + STALE_WEIGHT * stale


def value_span(p: Player, on: date, z: float | None) -> float:
    """Version 2: a reading is worth what it adds to the growth rate's evidence.

    Version 1 (`value`) counted readings. The late-bloomer detector does not use a count: it
    measures growth over the readings of the last VELOCITY_WINDOW_DAYS, and over a span under
    60 days it measures nothing. Three readings in three consecutive monthly sessions give it
    almost nothing to go on. So the need here is the gain in span, as a share of a full year,
    squared because a rate's uncertainty falls with the square of the span it is measured
    over; plus a smaller term for reaching three readings at all. A reading a month after the
    last one adds little span and is worth little; one that stretches the window to a year is
    worth most. Age, size and staleness as in version 1."""
    age = p.age(on)
    in_window = age is not None and AGE_WINDOW[0] <= age <= AGE_WINDOW[1]
    stake = 1.0 if in_window else OUT_OF_WINDOW
    small = 1 / (1 + math.exp(SIZE_SLOPE * (z if z is not None else 0.0)))
    recent = [d for d, _ in p.readings if (on - d).days <= VELOCITY_WINDOW_DAYS]
    before = (recent[-1] - recent[0]).days if recent else 0
    after = (on - recent[0]).days if recent else 0
    span_gain = min(1.0, after / FULL_SPAN_DAYS) ** 2 - min(1.0, before / FULL_SPAN_DAYS) ** 2
    count = 1.0 if len(recent) < 3 else COUNT_DONE
    need = COUNT_WEIGHT * count + span_gain
    last = p.last_reading()
    stale = 1.0 if last is None else min(1.0, (on - last).days / STALE_DAYS)
    return stake * (0.5 + small) * need + STALE_WEIGHT * stale


def _eligible(players: list[Player], on: date) -> list[Player]:
    return [p for p in players if p.present(on)
            and (p.last_reading() is None or (on - p.last_reading()).days >= MIN_GAP_DAYS)]


def choose_rota(players: list[Player], on: date, capacity: int, state: dict) -> list[str]:
    """A fixed rotation: the squad in a fixed order, the next `capacity` each session."""
    pool = sorted(_eligible(players, on), key=lambda p: p.id)
    if not pool:
        return []
    start = state.get("rota", 0) % len(pool)
    picked = (pool[start:] + pool[:start])[:capacity]
    state["rota"] = start + len(picked)
    return [p.id for p in picked]


def choose_nudge(players: list[Player], on: date, capacity: int, state: dict) -> list[str]:
    """Longest since the last reading first; never measured first of all."""
    pool = _eligible(players, on)
    pool.sort(key=lambda p: (p.last_reading() or date.min, p.id))
    return [p.id for p in pool[:capacity]]


def choose_random(players: list[Player], on: date, capacity: int, state: dict) -> list[str]:
    pool = sorted(_eligible(players, on), key=lambda p: p.id)
    rng: random.Random = state.setdefault("rng", random.Random(state.get("seed", 0)))
    return [p.id for p in rng.sample(pool, min(capacity, len(pool)))]


def choose_optimised(players: list[Player], on: date, capacity: int, state: dict,
                     zs: dict[str, float] | None = None, worth=None) -> list[str]:
    """The rolling-horizon integer program; returns who to measure in this session. `worth`
    is the value function (version 1, `value`, by default)."""
    worth = worth or value
    pool = _eligible(players, on)
    if not pool or capacity <= 0:
        return []
    zs = zs if zs is not None else height_z(players, on)
    sessions = [on + timedelta(days=SESSION_DAYS * h) for h in range(HORIZON)]
    n, H = len(pool), HORIZON
    # Variables: x[i, h] for i in pool, h in horizon (index i * H + h), then one slack per player.
    n_x = n * H
    cost = np.zeros(n_x + n)
    for i, p in enumerate(pool):
        for h, when in enumerate(sessions):
            cost[i * H + h] = -worth(p, when, zs.get(p.id)) * LATER ** h if p.present(when) else 0.0
        cost[n_x + i] = GAP_PENALTY
    rows: list[tuple[dict[int, float], float, float]] = []
    # Capacity per session. This session is happening: every place in it is used (a place left
    # empty now is a reading lost, whatever the plan says about later). Later sessions are plans.
    rows.append(({i * H: 1.0 for i in range(n)}, float(min(capacity, n)), float(capacity)))
    for h in range(1, H):
        rows.append(({i * H + h: 1.0 for i in range(n)}, 0.0, float(capacity)))
    for i in range(n):  # at most one reading per player in the horizon
        rows.append(({i * H + h: 1.0 for h in range(H)}, 0.0, 1.0))
    for i, p in enumerate(pool):  # the six-month rule, soft
        last = p.last_reading()
        for h, when in enumerate(sessions):
            overdue = last is None or (when - last).days > MAX_GAP_DAYS
            if overdue and p.present(when):
                coeffs = {i * H + k: 1.0 for k in range(h + 1)}
                coeffs[n_x + i] = 1.0
                rows.append((coeffs, 1.0, np.inf))
                break
    a = lil_matrix((len(rows), n_x + n))
    lo, hi = np.zeros(len(rows)), np.zeros(len(rows))
    for r, (coeffs, lower, upper) in enumerate(rows):
        for col, v in coeffs.items():
            a[r, col] = v
        lo[r], hi[r] = lower, upper
    upper_bounds = np.ones(n_x + n)
    for i, p in enumerate(pool):
        for h, when in enumerate(sessions):
            if not p.present(when):
                upper_bounds[i * H + h] = 0.0
    result = milp(cost, constraints=LinearConstraint(a.tocsr(), lo, hi),
                  integrality=np.concatenate([np.ones(n_x), np.zeros(n)]),
                  bounds=Bounds(np.zeros(n_x + n), upper_bounds))
    if result.x is None:  # should not happen: every constraint can be met with slack
        return choose_nudge(players, on, capacity, state)
    chosen = [p.id for i, p in enumerate(pool) if result.x[i * H] > 0.5]
    state["overdue_breaks"] = state.get("overdue_breaks", 0) + int(sum(result.x[n_x:] > 0.5))
    return chosen


def choose_optimised_span(players: list[Player], on: date, capacity: int, state: dict,
                          zs: dict[str, float] | None = None) -> list[str]:
    """The same program with the version 2 value."""
    return choose_optimised(players, on, capacity, state, zs=zs, worth=value_span)


CHOOSERS = {"rota": choose_rota, "nudge": choose_nudge, "random": choose_random, "optimised": choose_optimised,
            "optimised-span": choose_optimised_span}


def noise(seed: int, player_id: str, on: date, metric: str, sd: float) -> float:
    """Measurement noise that depends only on who, when and what: a player measured on a
    given day gets the same error under every schedule, so schedules differ only in who is
    measured when."""
    digest = hashlib.sha256(f"{seed}|{player_id}|{on.isoformat()}|{metric}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big")).gauss(0.0, sd)


def session_dates(start: date, end: date) -> list[date]:
    out, cursor = [], start
    while cursor <= end:
        out.append(cursor)
        cursor += timedelta(days=SESSION_DAYS)
    return out
