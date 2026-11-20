"""Who to measure next: grade measuring schedules with the late-bloomer backtest.

    python -m ml.run_measurement_eval
    python -m ml.run_measurement_eval --seeds 101 202 303      # the calibration seeds

For each seed the generator builds its world as usual. Then every player's height readings are
made again, by a schedule (ml/decisions/measurement.py): each academy holds a session every 28
days, a session can measure a fixed number of players, and the schedule decides who. A reading
is the player's true growth curve on that day plus the generator's measurement noise, the noise
fixed by player and day, so a player measured on the same day reads the same under every
schedule. Players are at the academy over exactly the dates they were in the generated data.

Capacity is set so every schedule takes the same total number of readings as the generated
data took (budget 1.0), or half (0.5) or one and a half times (1.5) that. The generated data's
own dates, re-measured the same way, are printed as "as generated" for reference.

Then the unchanged backtest (ml/backtest.py) runs on each version: at each player's decision
moment (the first time a size cut would release them) was the late bloomer flagged, how many
other small players were flagged, and how many late bloomers had too few readings for the
detector to say anything. Pooled over the seeds; 95% Wilson intervals.

Reported seeds are the five the backtest reports on; no constant in the schedules was tuned.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path

from ml.backtest import run, summarise
from ml.decisions import measurement as m
from ml.evaluation.metrics import wilson_interval

REPORTED_SEEDS = [20260827, 7, 99, 404, 555]
# Seeds no evaluation in the project had used: a replication of version 1, unchanged, after its
# first report (ml/README.md, "Who to measure next").
FRESH_SEEDS = [3001, 3002, 3003, 3004, 3005]
BUDGETS = [0.5, 1.0, 1.5]


def _org_lookup(affiliations) -> dict[str, list[tuple]]:
    out = defaultdict(list)
    for a in affiliations:
        out[str(a.player_id)].append((str(a.organization_id), a.start_date, a.end_date))
    return out


def _org_on(spells: list[tuple], on: date) -> str | None:
    for org, start, end in spells:
        if (start is None or start <= on) and (end is None or on <= end):
            return org
    return max(spells, key=lambda s: s[1] or date.min)[0] if spells else None


def _reading_rows(profile, when: date, seed: int, cfg, recorder) -> tuple[float, list]:
    from data.pipelines.synthetic import growth
    from data.pipelines.synthetic.orm import Measurement, enums

    pid = str(profile.id)
    age = profile.true_age(when)
    height = growth.height_cm(age, profile.sex, profile.adult_height_cm, profile.maturity_offset_years) \
        + m.noise(seed, pid, when, "height", cfg.height_noise_cm)
    weight = growth.weight_kg(height, age, profile.sex, profile.build_offset) \
        + m.noise(seed, pid, when, "weight", cfg.weight_noise_kg)
    sprint = growth.sprint_10m_seconds(age, profile.sex, profile.talent_offset) \
        + m.noise(seed, pid, when, "sprint", cfg.sprint_noise_s)
    rows = []
    for metric, val, unit in (("height_cm", round(height, 1), "cm"), ("weight_kg", round(weight, 1), "kg"),
                              ("sprint_10m_s", round(sprint, 3), "s")):
        digest = hashlib.sha256(f"{seed}|{pid}|{when}|{metric}".encode()).digest()
        rows.append(Measurement(
            id=uuid.UUID(bytes=digest[:16]), player_id=profile.id, measured_at=when, metric=metric,
            value=val, unit=unit, source=enums.MeasurementSource.COACH_LOGGED.value,
            recorded_by=recorder, confidence=enums.MeasurementConfidence.MEASURED.value,
        ))
    return round(height, 1), rows


def simulate(ds, config, policy: str, budget: float) -> tuple[list, dict]:
    """New measurement rows for `ds` under `policy` at `budget`; and what happened."""
    cfg = config.measurements
    seed = config.seed
    coaches = [u.id for u in ds.users if u.role in ("coach", "admin")]
    recorder = coaches[0] if coaches else None
    by_player = defaultdict(set)
    for row in ds.measurements:
        by_player[str(row.player_id)].add(row.measured_at)
    profiles = {str(p.id): p for p in ds.profiles if str(p.id) in by_player}

    if policy == "as generated":
        rows = []
        for pid, dates in by_player.items():
            for when in sorted(dates):
                rows += _reading_rows(profiles[pid], when, seed, cfg, recorder)[1]
        return rows, {"readings": sum(len(d) for d in by_player.values()), "overdue_breaks": 0}

    players = {pid: m.Player(pid, p.sex, p.player.date_of_birth, min(by_player[pid]), max(by_player[pid]))
               for pid, p in profiles.items()}
    spells = _org_lookup(ds.affiliations)
    start = min(p.present_from for p in players.values())
    end = config.population.reference_date
    sessions = m.session_dates(start, end)

    # Capacity: the same total readings as generated, times the budget, shared out over the
    # sessions in proportion to who is present.
    target = budget * sum(len(d) for d in by_player.values())
    present_sessions = sum(1 for when in sessions for p in players.values() if p.present(when))
    rate = target / present_sessions
    carry: dict[str, float] = defaultdict(float)
    states: dict[str, dict] = defaultdict(lambda: {"seed": seed})
    chooser = m.CHOOSERS[policy]
    rows, readings, breaks = [], 0, 0
    for when in sessions:
        everyone = list(players.values())
        zs = m.height_z(everyone, when) if policy.startswith("optimised") else None
        squads = defaultdict(list)
        for p in everyone:
            if p.present(when):
                squads[_org_on(spells[p.id], when)].append(p)
        for org, squad in sorted(squads.items(), key=lambda kv: str(kv[0])):
            carry[org] += rate * len(squad)
            capacity = int(carry[org])
            carry[org] -= capacity
            if capacity <= 0:
                continue
            if policy.startswith("optimised"):
                chosen = chooser(squad, when, capacity, states[org], zs=zs)
            else:
                chosen = chooser(squad, when, capacity, states[org])
            for pid in chosen:
                height, new = _reading_rows(profiles[pid], when, seed, cfg, recorder)
                players[pid].readings.append((when, height))
                rows += new
                readings += 1
    breaks = sum(s.get("overdue_breaks", 0) for s in states.values())
    return rows, {"readings": readings, "overdue_breaks": breaks}


def evaluate_seed(seed: int, players: int, budgets: list[float], policies: list[str]) -> list[dict]:
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    config = GeneratorConfig(seed=seed).scaled(players)
    ds = build_dataset(config)
    original = list(ds.measurements)
    runs = [("as generated", 1.0)] + [(p, b) for b in budgets for p in policies]
    out = []
    for policy, budget in runs:
        t0 = time.time()
        rows, info = simulate(ds, config, policy, budget)
        ds.measurements = rows
        with tempfile.TemporaryDirectory(prefix="northstar-measure-") as tmp:
            write_ground_truth(ds.ground_truth, Path(tmp) / "ground_truth.json")
            export_json(ds, Path(tmp))
            report = run(Path(tmp))
        ds.measurements = original
        s = summarise(report.decisions, report.never_cut)
        lb = [d for d in report.decisions if d.planted_late_bloomer]
        out.append({
            "seed": seed, "policy": policy, "budget": budget, "readings": info["readings"],
            "overdue_breaks": info["overdue_breaks"],
            "lb_planted": len(lb) + len(report.never_cut), "lb_cut": len(lb),
            "lb_flagged": s["caught"].hits, "lb_thin": sum(1 for d in lb if d.readings < s["min_readings"]),
            "other_cut": s["false_alarms"].total, "other_flagged": s["false_alarms"].hits,
        })
        print(f"  seed {seed} {policy:<12} budget {budget:.1f}: {info['readings']} readings, "
              f"{out[-1]['lb_flagged']} of {out[-1]['lb_cut']} late bloomers flagged at the cut "
              f"({time.time() - t0:.0f} s)", file=sys.stderr, flush=True)
    return out


def _rate(hits: int, total: int) -> str:
    if not total:
        return "n/a"
    lo, hi = wilson_interval(hits, total)
    return f"{hits / total:5.1%} ({hits}/{total}, {lo:.0%} to {hi:.0%})"


def render(results: list[dict]) -> str:
    pooled = defaultdict(lambda: defaultdict(int))
    for r in results:
        key = (r["policy"], r["budget"])
        for k in ("readings", "overdue_breaks", "lb_planted", "lb_cut", "lb_flagged", "lb_thin",
                  "other_cut", "other_flagged"):
            pooled[key][k] += r[k]
    seeds = sorted({r["seed"] for r in results})
    lines = [f"Who to measure next, seeds {', '.join(map(str, seeds))}, pooled", ""]
    header = (f"  {'schedule':<12} {'budget':>6} {'readings':>9}  {'late bloomers flagged at the cut':<34}"
              f"{'of all planted':<26}{'too few readings at the cut':<34}{'other small players flagged'}")
    lines.append(header)
    order = ["as generated", *m.POLICIES]
    for budget in sorted({b for _, b in pooled}):
        for policy in order:
            p = pooled.get((policy, budget))
            if not p:
                continue
            lines.append(
                f"  {policy:<12} {budget:>6.1f} {p['readings']:>9}  {_rate(p['lb_flagged'], p['lb_cut']):<34}"
                f"{_rate(p['lb_flagged'], p['lb_planted']):<26}{_rate(p['lb_thin'], p['lb_cut']):<34}"
                f"{_rate(p['other_flagged'], p['other_cut'])}")
        lines.append("")
    for name in ("optimised", "optimised-span"):
        breaks = {k: v["overdue_breaks"] for k, v in pooled.items() if k[0] == name}
        if breaks:
            lines.append(f"Six-month rule broken by {name} (capacity too small to keep it): "
                         + ", ".join(f"budget {b:.1f}: {n}" for (_, b), n in sorted(breaks.items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="run_measurement_eval", description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, nargs="+", default=REPORTED_SEEDS)
    parser.add_argument("--fresh", action="store_true", help="the fresh seeds (version 1's replication)")
    parser.add_argument("--players", type=int, default=1000)
    parser.add_argument("--budgets", type=float, nargs="+", default=BUDGETS)
    # Version 2 lost on the calibration seeds and is not part of the default comparison; it can
    # still be run by name.
    parser.add_argument("--policies", nargs="+", default=[p for p in m.POLICIES if p != "optimised-span"],
                        choices=list(m.POLICIES))
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    results = []
    for seed in (FRESH_SEEDS if args.fresh else args.seeds):
        results += evaluate_seed(seed, args.players, args.budgets, args.policies)
    print(render(results))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
