"""The late-bloomer backtest: what would the system have said at the moment it mattered?

The project's premise is that talent is lost when academies release players at around 14 for
being small, when some of them are late maturers who would have caught up. This module goes
back to past dates, gives the system only what was known on each one, and asks:

  1. When a late bloomer was small enough to be cut, did the system flag them?
  2. Did it also flag the small players who were simply small?
  3. What did the forecast say would happen to them, and what did happen?

It is built to run on real data unchanged. The answer key is optional: with one, the report
scores against the planted truth; without one, it scores against what can be observed
afterwards (did the player climb their age group?) and says how many players have no
afterwards at all.

The moment of decision
----------------------
Cutoffs are calendar dates every 91 days, from a year after the first measurement to a year
before the last, so every cutoff has history behind it and at least a year of future. On each
cutoff the detector runs on the data as it stood that day (`FeatureSet` built from the tables
cut off at that date, so the cohort reference is the one that existed then too).

The **size cut** stands in for current practice: among players aged 12 to 16 by their recorded
date of birth and measured in the last six months, the shortest quarter of each sex for their
age. A player's **decision moment** is the first cutoff at which they fall in it. Per sex,
because a single cut would be mostly girls.

Observable outcome, for when there is no answer key
---------------------------------------------------
A player **caught up** if, at their last reading at least a year after the decision moment,
they sit at least 0.5 standard deviations higher relative to their age group than they did at
the decision moment. A child who is simply small stays on their line; a late maturer climbs.
Against synthetic data the report measures how well this observable label agrees with the
planted truth, which is the number that says how far to trust it on real data.

No outcome
----------
A player with no reading a year or more after their decision moment has no outcome. In real
data that is mostly players who left, and players who leave after a size cut are not a random
sample. The report counts them, compares them with the players who stayed, and, where the
answer key allows, shows how much a backtest scored only on the stayers overstates recall.
Run it on a dataset generated with `--attrition` to see the effect planted deliberately.

Every constant below was set before the backtest was first run and has not been changed to
improve a result. The late-bloomer detector's own thresholds were tuned on seeds 101, 202 and
303, which none of the reported datasets use.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ml.detectors import late_bloomer
from ml.detectors.features import TABLES, FeatureSet, PlayerFeatures
from ml.evaluation.metrics import wilson_interval
from ml.forecasting.models import PlayerHistory, Snapshot, cohort_velocity

CUTOFF_STEP_DAYS = 91
MIN_HISTORY_DAYS = 365
MIN_FUTURE_DAYS = 365

# Who is in front of the academy on a cutoff, and who the size cut applies to.
ACTIVE_WITHIN_DAYS = 183
SIZE_CUT_MIN_AGE = 12.0
SIZE_CUT_MAX_AGE = 16.0
SIZE_CUT_FRACTION = 0.25

# The observable outcome.
OUTCOME_MIN_DAYS = 365
CATCH_UP_Z = 0.5

# How far ahead the forecast made at the decision moment is scored.
FORECAST_HORIZON_DAYS = 730


def _as_date(value) -> date:
    return date.fromisoformat(str(value)[:10])


@dataclass
class Decision:
    """One player, at the first cutoff where the size cut would have released them."""

    player_id: str
    cutoff: date
    sex: str
    stated_age: float
    height_z: float
    readings: int
    flagged: bool
    # Why the detector did not fire, in its own terms. Empty when it did.
    not_flagged_because: str = ""

    # Observable afterwards.
    has_outcome: bool = False
    follow_up_years: float | None = None
    z_change: float | None = None
    caught_up: bool | None = None
    forecast_errors: list[float] = field(default_factory=list)

    # From the answer key, when there is one. None means unknown, not False.
    planted_late_bloomer: bool | None = None
    released: bool | None = None


@dataclass
class BacktestReport:
    data_dir: str
    seed: int | None
    cutoffs: list[date]
    decisions: list[Decision]
    has_answer_key: bool
    has_release_record: bool
    # Planted late bloomers who never reached the size cut, and why.
    never_cut: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "data_dir": self.data_dir,
            "seed": self.seed,
            "cutoffs": [c.isoformat() for c in self.cutoffs],
            "has_answer_key": self.has_answer_key,
            "has_release_record": self.has_release_record,
            "never_cut": self.never_cut,
            "decisions": [
                {
                    **{k: v for k, v in d.__dict__.items() if k != "cutoff"},
                    "cutoff": d.cutoff.isoformat(),
                }
                for d in self.decisions
            ],
        }


# ---------------------------------------------------------------------------
# Loading and cutting off
# ---------------------------------------------------------------------------


def load_tables(data_dir: str | Path) -> tuple[dict[str, list[dict]], dict]:
    data_dir = Path(data_dir)
    tables = {}
    for name in TABLES:
        path = data_dir / f"{name}.json"
        tables[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    truth_path = data_dir / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else {}
    return tables, truth


def as_of(tables: dict[str, list[dict]], cutoff: date) -> dict[str, list[dict]]:
    """The tables as they stood at the end of `cutoff`. Nothing dated later survives."""
    return {
        **tables,
        "measurements": [
            m for m in tables["measurements"] if _as_date(m["measured_at"]) <= cutoff
        ],
        "performance_entries": [
            e for e in tables["performance_entries"] if _as_date(e["period_start"]) <= cutoff
        ],
    }


def cutoffs_for(tables: dict[str, list[dict]]) -> list[date]:
    dates = [_as_date(m["measured_at"]) for m in tables["measurements"]]
    if not dates:
        return []
    first, last = min(dates), max(dates)
    out, cursor = [], first + timedelta(days=MIN_HISTORY_DAYS)
    while cursor <= last - timedelta(days=MIN_FUTURE_DAYS):
        out.append(cursor)
        cursor += timedelta(days=CUTOFF_STEP_DAYS)
    return out


def _histories(features: FeatureSet) -> dict[str, PlayerHistory]:
    return {
        pid: PlayerHistory(pid, pf.sex, pf.date_of_birth, list(pf.heights))
        for pid, pf in features.players.items()
        if pf.date_of_birth is not None and pf.player.get("status") != "merged"
    }


def _why_not(pf: PlayerFeatures, params: late_bloomer.LateBloomerParams) -> str:
    """The detector's first failing gate, in the order it checks them."""
    if len(pf.heights) < params.min_measurements:
        return f"only {len(pf.heights)} height readings so far"
    if pf.height_z_mean is None:
        return "no cohort reference for this age yet"
    if not params.min_age <= pf.stated_age <= params.max_age:
        return f"age {pf.stated_age:.1f} outside the detector's range"
    if pf.height_z_mean > params.max_height_z_mean:
        return f"not short enough on average (z {pf.height_z_mean:+.2f})"
    if pf.recent_velocity < params.min_recent_velocity:
        return f"not growing fast yet ({pf.recent_velocity:.1f} cm/yr)"
    return "unknown"


# ---------------------------------------------------------------------------
# The backtest
# ---------------------------------------------------------------------------


def run(data_dir: str | Path) -> BacktestReport:
    tables, truth = load_tables(data_dir)
    full = FeatureSet(data_dir, raw=tables)
    cutoffs = cutoffs_for(tables)
    params = late_bloomer.LateBloomerParams()

    planted = {c["player_id"] for c in truth.get("cases", {}).get("late_bloomers", [])}
    releases = truth.get("attrition", {}).get("released")
    released = {r["player_id"] for r in releases} if releases is not None else None
    merged = {p["id"] for p in tables["players"] if p.get("status") == "merged"}

    decisions: dict[str, Decision] = {}
    seen_in_window: set[str] = set()

    for cutoff in cutoffs:
        then = FeatureSet(data_dir, raw=as_of(tables, cutoff))
        flagged = late_bloomer.detect(then, params)

        eligible: dict[str, list[PlayerFeatures]] = {}
        for pid, pf in then.players.items():
            if pid in merged or not pf.heights or pf.height_z_last is None:
                continue
            if (cutoff - pf.heights[-1][0]).days > ACTIVE_WITHIN_DAYS:
                continue
            age = pf.age_at(cutoff)
            if not SIZE_CUT_MIN_AGE <= age < SIZE_CUT_MAX_AGE:
                continue
            seen_in_window.add(pid)
            eligible.setdefault(pf.sex, []).append(pf)

        snapshot = None
        for group in eligible.values():
            group.sort(key=lambda pf: pf.height_z_last)
            cut = group[: max(1, math.floor(len(group) * SIZE_CUT_FRACTION))] if len(group) >= 4 else []
            for pf in cut:
                if pf.player_id in decisions:
                    continue
                if snapshot is None:
                    snapshot = Snapshot(cutoff, _histories(then))
                decisions[pf.player_id] = _decide(
                    pf, cutoff, flagged, params, full, snapshot, planted, released, bool(truth)
                )

    never_cut: dict[str, str] = {}
    for pid in sorted(planted - set(decisions)):
        never_cut[pid] = (
            "in the 12 to 16 window, never among the shortest quarter"
            if pid in seen_in_window
            else "never measured at 12 to 16 inside the cutoff range"
        )

    return BacktestReport(
        data_dir=str(data_dir),
        seed=truth.get("seed"),
        cutoffs=cutoffs,
        decisions=sorted(decisions.values(), key=lambda d: (d.cutoff, d.player_id)),
        has_answer_key=bool(truth.get("cases")),
        has_release_record=released is not None,
        never_cut=never_cut,
    )


def _decide(
    pf: PlayerFeatures,
    cutoff: date,
    flagged: dict[str, str],
    params: late_bloomer.LateBloomerParams,
    full: FeatureSet,
    snapshot: Snapshot,
    planted: set[str],
    released: set[str] | None,
    has_key: bool,
) -> Decision:
    decision = Decision(
        player_id=pf.player_id,
        cutoff=cutoff,
        sex=pf.sex,
        stated_age=pf.age_at(cutoff),
        height_z=pf.height_z_last,
        readings=len(pf.heights),
        flagged=pf.player_id in flagged,
        not_flagged_because="" if pf.player_id in flagged else _why_not(pf, params),
        planted_late_bloomer=(pf.player_id in planted) if has_key else None,
        released=(pf.player_id in released) if released is not None else None,
    )

    # Afterwards, judged against the full dataset's reference. This is evaluation, not
    # prediction: nothing here feeds back into what the system said on the cutoff.
    later = full.players[pf.player_id]
    before = [(w, cm) for w, cm in later.heights if w <= cutoff]
    after = [(w, cm) for w, cm in later.heights if (w - cutoff).days >= OUTCOME_MIN_DAYS]
    if before and after:
        decision.has_outcome = True
        decision.follow_up_years = (after[-1][0] - cutoff).days / 365.25
        z_then = full.height_z(later, *before[-1])
        z_now = full.height_z(later, *after[-1])
        if z_then is not None and z_now is not None:
            decision.z_change = z_now - z_then
            decision.caught_up = decision.z_change >= CATCH_UP_Z

    history = snapshot.players.get(pf.player_id)
    if history is not None:
        for when, actual in later.heights:
            if 0 < (when - cutoff).days <= FORECAST_HORIZON_DAYS:
                predicted = cohort_velocity(snapshot, history, when)
                if predicted is not None:
                    decision.forecast_errors.append(predicted - actual)
    return decision


# ---------------------------------------------------------------------------
# Summaries. Everything is counts first, rates second, so reports from several datasets can
# be pooled by adding counts rather than averaging rates of different sizes.
# ---------------------------------------------------------------------------


@dataclass
class Rate:
    hits: int
    total: int

    def __str__(self) -> str:
        if not self.total:
            return "n/a (0 cases)"
        lo, hi = wilson_interval(self.hits, self.total)
        return f"{self.hits} of {self.total} ({self.hits / self.total:.0%}, 95% CI {lo:.0%} to {hi:.0%})"


def summarise(decisions: list[Decision], never_cut: dict[str, str]) -> dict:
    lb = [d for d in decisions if d.planted_late_bloomer]
    other = [d for d in decisions if d.planted_late_bloomer is False]
    with_outcome = [d for d in decisions if d.caught_up is not None]
    observed_up = [d for d in with_outcome if d.caught_up]
    observed_flat = [d for d in with_outcome if not d.caught_up]
    lb_with_outcome = [d for d in lb if d.has_outcome]

    def mae(rows: list[Decision]) -> tuple[float, float, int] | None:
        errors = [e for d in rows for e in d.forecast_errors]
        if not errors:
            return None
        return statistics.fmean(abs(e) for e in errors), statistics.fmean(errors), len(errors)

    enough = late_bloomer.LateBloomerParams().min_measurements
    follow_ups = sorted(d.follow_up_years for d in decisions if d.follow_up_years is not None)

    return {
        "decisions": len(decisions),
        "min_readings": enough,
        "caught_with_history": Rate(
            sum(d.flagged for d in lb if d.readings >= enough),
            sum(1 for d in lb if d.readings >= enough),
        ),
        "caught_without_history": Rate(
            sum(d.flagged for d in lb if d.readings < enough),
            sum(1 for d in lb if d.readings < enough),
        ),
        "false_alarms_with_history": Rate(
            sum(d.flagged for d in other if d.readings >= enough),
            sum(1 for d in other if d.readings >= enough),
        ),
        "median_follow_up": statistics.median(follow_ups) if follow_ups else None,
        "planted_late_bloomers_cut": len(lb),
        "planted_late_bloomers_never_cut": len(never_cut),
        # With the answer key.
        "caught": Rate(sum(d.flagged for d in lb), len(lb)),
        "false_alarms": Rate(sum(d.flagged for d in other), len(other)),
        "caught_among_stayers": Rate(sum(d.flagged for d in lb_with_outcome), len(lb_with_outcome)),
        # Observable, no answer key needed.
        "with_outcome": Rate(len(with_outcome), len(decisions)),
        "flagged_of_caught_up": Rate(sum(d.flagged for d in observed_up), len(observed_up)),
        "caught_up_of_flagged": Rate(
            sum(bool(d.caught_up) for d in with_outcome if d.flagged),
            sum(1 for d in with_outcome if d.flagged),
        ),
        "flagged_of_stayed_flat": Rate(sum(d.flagged for d in observed_flat), len(observed_flat)),
        # How far the observable label can be trusted.
        "label_recall": Rate(
            sum(bool(d.caught_up) for d in with_outcome if d.planted_late_bloomer),
            sum(1 for d in with_outcome if d.planted_late_bloomer),
        ),
        "label_precision": Rate(
            sum(bool(d.planted_late_bloomer) for d in observed_up), len(observed_up)
        ),
        # Who has no outcome.
        "no_outcome": [d for d in decisions if not d.has_outcome],
        "stayed": [d for d in decisions if d.has_outcome],
        "released": Rate(
            sum(bool(d.released) for d in decisions if not d.has_outcome),
            sum(1 for d in decisions if not d.has_outcome),
        ),
        "forecast_lb": mae(lb),
        "forecast_other": mae(other),
        "forecast_all": mae(decisions),
    }


def _mean_z(rows: list[Decision]) -> str:
    return f"{statistics.fmean(d.height_z for d in rows):+.2f}" if rows else "n/a"


def _forecast(value: tuple[float, float, int] | None) -> str:
    if value is None:
        return "n/a"
    mae, bias, n = value
    return f"MAE {mae:.2f} cm, bias {bias:+.2f} cm, over {n} readings"


def render(
    reports: list[BacktestReport], title: str, *, misses: bool = True
) -> str:
    decisions = [d for r in reports for d in r.decisions]
    never_cut = {f"{r.seed}:{k}": v for r in reports for k, v in r.never_cut.items()}
    s = summarise(decisions, never_cut)
    keyed = all(r.has_answer_key for r in reports)
    released_known = all(r.has_release_record for r in reports)
    width = 100

    out = ["=" * width, title, "=" * width]
    out.append(
        f"{len(reports)} dataset(s), {sum(len(r.cutoffs) for r in reports)} cutoffs, "
        f"{s['decisions']} players reached the size cut (shortest quarter of their sex, aged "
        f"12 to 16)."
    )

    if keyed:
        out += ["", "At the moment of the size cut, against the answer key", "-" * width]
        out.append(f"late bloomers the system flagged        {s['caught']}")
        out.append(f"other small players it also flagged     {s['false_alarms']}")
        out.append(
            f"  with {s['min_readings']}+ height readings at the cut: late bloomers flagged "
            f"{s['caught_with_history']}, others flagged {s['false_alarms_with_history']}"
        )
        out.append(
            f"  with fewer, the detector cannot fire at all: late bloomers flagged "
            f"{s['caught_without_history']}"
        )
        out.append(
            f"late bloomers who never reached the cut {s['planted_late_bloomers_never_cut']} "
            f"(the cut would not have released them, so they are not in the rates above)"
        )

    out += ["", "What can be measured without an answer key, as on real data", "-" * width]
    out.append(f"players with an outcome a year or more later  {s['with_outcome']}")
    if s["median_follow_up"] is not None:
        out.append(
            f"median follow-up from the cut to the outcome   {s['median_follow_up']:.1f} years"
        )
    out.append(f"of those who caught up, flagged at the time   {s['flagged_of_caught_up']}")
    out.append(f"of those flagged, went on to catch up         {s['caught_up_of_flagged']}")
    out.append(f"of those who stayed small, flagged anyway     {s['flagged_of_stayed_flat']}")
    if keyed:
        out.append(
            f"'caught up' vs the planted truth: recall {s['label_recall']}, "
            f"precision {s['label_precision']}"
        )
        label = s["label_recall"]
        if label.total and label.hits / label.total < 0.5:
            out.append(
                "WARNING: at this follow-up length most late bloomers have not caught up yet, "
                "so 'caught up' misses most of them."
            )
            out.append(
                "The four rows above describe that label, not the system. A real-data "
                "backtest needs several years of follow-up."
            )
    else:
        out.append(
            "'caught up' needs several years of follow-up to mean anything; on synthetic data "
            "with 1 to 2 years it finds about a fifth of true late bloomers. Check the median "
            "follow-up above before reading these rows."
        )

    out += ["", "Players with no outcome", "-" * width]
    out.append(
        f"{len(s['no_outcome'])} of {s['decisions']} have no reading a year or more after "
        f"the cut. Mean height z at the cut: {_mean_z(s['no_outcome'])} without an outcome, "
        f"{_mean_z(s['stayed'])} with one."
    )
    if released_known:
        out.append(f"of those, released by the simulated academy review: {s['released']}")
    if keyed:
        out.append(
            f"late bloomers caught, scored on everyone     {s['caught']}\n"
            f"late bloomers caught, scored on stayers only {s['caught_among_stayers']}\n"
            f"A backtest on real data can only compute the second line."
        )

    out += ["", "Forecast made at the moment of the cut (cohort velocity, up to 2 years)", "-" * width]
    if keyed:
        out.append(f"late bloomers        {_forecast(s['forecast_lb'])}")
        out.append(f"other small players  {_forecast(s['forecast_other'])}")
    else:
        out.append(f"all small players    {_forecast(s['forecast_all'])}")

    if misses and keyed:
        missed = [d for d in decisions if d.planted_late_bloomer and not d.flagged]
        if missed:
            out += ["", f"Late bloomers not flagged at the cut ({len(missed)})", "-" * width]
            for d in missed:
                out.append(
                    f"  {d.player_id[:8]}  age {d.stated_age:.1f}, z {d.height_z:+.2f}: "
                    f"{d.not_flagged_because}"
                )
        if never_cut:
            out += ["", f"Late bloomers who never reached the cut ({len(never_cut)})", "-" * width]
            for key, reason in never_cut.items():
                seed, pid = key.split(":", 1)
                out.append(f"  {pid[:8]} (seed {seed})  {reason}")
    return "\n".join(out)
