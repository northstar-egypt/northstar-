"""The age-misrepresentation rule by stated age: v1 (growth only) against v2 (growth and performance).

    python -m ml.run_age_bands                                   # the 20 reported seeds
    python -m ml.run_age_bands --performance-follows-maturity    # the what-if world
    python -m ml.run_age_bands --seeds 101 202 303

Prints the "By stated age" table in ml/README.md, "Age misrepresentation, v2", which was first
computed by a script that was never committed (found by the results check, ml/run_results_check),
and the v1 rows of the pooled table and of the relative age audit, which no command printed once
v1 was replaced.

v1 is the growth rule alone: the same gates as `fraud.detect_age_misrepresentation` (stated age
11 to 19, three height readings, a height z score) and a flag whenever `fraud._growth_reason`
fires. That is exactly the rule v2 replaced (#51): v2 kept the growth rule unchanged and added
performance evidence on top of it. The command prints the pooled counts first, scored as the
harness scores the age subtype (the other fraud subtypes' cases left out), so they can be checked
against the published v1 and v2 rows before the bands are read.

The bands count differently, as the README says: a false accusation there is any flagged player
who is not a planted age cheat, including players planted with another kind of fraud, so the
band totals are a little higher than the pooled ones. A player's band is the stated age at the
dataset's reference date; under 13 (including the rare planted cheat stated under 11) is "11 to
13", and 17 or more is "17+".
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from ml.detectors import fraud
from ml.detectors.features import FeatureSet
from ml.detectors.fraud import FraudParams
from ml.evaluation import fairness
from ml.evaluation.metrics import score_ids

REPORTED = [20260827, 7, 99, 404, 555, *range(1000, 1015)]
BANDS = ("11 to 13", "13 to 15", "15 to 17", "17+")
OTHER_FRAUD = ("implausible_self_reported_performance", "result_tampering")


def band(stated_age: float) -> str:
    if stated_age < 13:
        return "11 to 13"
    if stated_age < 15:
        return "13 to 15"
    if stated_age < 17:
        return "15 to 17"
    return "17+"


def growth_only(features: FeatureSet, params: FraudParams | None = None) -> set[str]:
    """v1: the growth rule alone, behind the same gates as the current rule."""
    params = params or FraudParams()
    flagged = set()
    for pf in features.players.values():
        if pf.height_z_mean is None or len(pf.heights) < params.min_measurements:
            continue
        if not (params.min_age <= pf.stated_age <= params.max_age):
            continue
        if fraud._growth_reason(pf, params):
            flagged.add(pf.player_id)
    return flagged


def evaluate(features: FeatureSet, ground_truth: dict) -> dict:
    """Pooled counts and band counts for one dataset, for v1 and v2."""
    everyone = set(ground_truth["population"]["player_ids"])
    cases = ground_truth["cases"]["fraud"]
    age = {c["player_id"] for c in cases if c["fraud_type"] == "age_misrepresentation"}
    other = {c["player_id"] for c in cases if c["fraud_type"] in OTHER_FRAUD}
    stated = {pid: pf.stated_age for pid, pf in features.players.items()}
    quarters = fairness.quarters_of(features.raw["players"])
    out = {}
    for name, flagged in (("v1", growth_only(features)), ("v2", set(fraud.detect_age_misrepresentation(features)))):
        s = score_ids(name, flagged, age, everyone - other)
        bands = {b: {"planted": 0, "caught": 0, "false": 0} for b in BANDS}
        for pid in age:
            b = bands[band(stated[pid])]
            b["planted"] += 1
            b["caught"] += pid in flagged
        for pid in flagged - age:
            bands[band(stated[pid])]["false"] += 1
        out[name] = {"tp": s.tp, "fp": s.fp, "fn": s.fn, "bands": bands,
                     "quarters": fairness.audit(f"age rule {name}", flagged, age, everyone - other, quarters)}
    return out


def pool(results: list[dict]) -> dict:
    total = {}
    for name in ("v1", "v2"):
        t = {"tp": 0, "fp": 0, "fn": 0, "bands": {b: defaultdict(int) for b in BANDS}}
        for r in results:
            for k in ("tp", "fp", "fn"):
                t[k] += r[name][k]
            for b in BANDS:
                for k, v in r[name]["bands"][b].items():
                    t["bands"][b][k] += v
        t["quarters"] = fairness.pool([r[name]["quarters"] for r in results])
        total[name] = t
    return total


def render(total: dict, seeds: list[int], what_if: bool) -> str:
    world = ", what-if: performance follows maturity" if what_if else ""
    lines = [f"Age misrepresentation by stated age, {len(seeds)} datasets{world}", "",
             "Pooled, scored as the harness scores the age subtype (other fraud cases left out):",
             f"  {'rule':<22}{'caught':>8}{'false accusations':>19}{'precision':>11}{'recall':>8}{'F1':>8}"]
    for name, label in (("v1", "v1, growth only"), ("v2", "v2, with performance")):
        t = total[name]
        p = t["tp"] / (t["tp"] + t["fp"]) if t["tp"] + t["fp"] else 0.0
        r = t["tp"] / (t["tp"] + t["fn"]) if t["tp"] + t["fn"] else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        lines.append(f"  {label:<22}{t['tp']:>8}{t['fp']:>19}{p:>11.3f}{r:>8.3f}{f1:>8.3f}")
    lines += ["", "By stated age (false accusations here include players planted with other fraud):",
              f"  {'':<22}" + "".join(f"{b:>12}" for b in BANDS) + f"{'total':>10}"]
    for name in ("v1", "v2"):
        bands = total[name]["bands"]
        lines.append(f"  {name + ' caught':<22}" + "".join(
            f"{str(bands[b]['caught']) + '/' + str(bands[b]['planted']):>12}" for b in BANDS)
            + f"{sum(bands[b]['caught'] for b in BANDS):>10}")
    for name in ("v1", "v2"):
        bands = total[name]["bands"]
        lines.append(f"  {name + ' false accusations':<22}" + "".join(f"{bands[b]['false']:>12}" for b in BANDS)
                     + f"{sum(bands[b]['false'] for b in BANDS):>10}")
    lines.append(fairness.render([total["v1"]["quarters"], total["v2"]["quarters"]],
                                 f"Relative age, counts pooled over {len(seeds)} datasets"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="run_age_bands", description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, nargs="+", default=REPORTED)
    parser.add_argument("--performance-follows-maturity", action="store_true",
                        help="the what-if in which honest early maturers also outplay their age group")
    args = parser.parse_args(argv)
    if args.performance_follows_maturity:
        from data.pipelines.synthetic import players

        players.PERFORMANCE_FOLLOWS_MATURITY = True

    import json

    from ml.run_eval import _generate

    results = []
    with tempfile.TemporaryDirectory(prefix="northstar-age-bands-") as tmp:
        for seed in args.seeds:
            print(f"seed {seed} ...", file=sys.stderr, flush=True)
            out = Path(tmp) / str(seed)
            _generate(seed, out)
            truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
            results.append(evaluate(FeatureSet(out), truth))
    print(render(pool(results), args.seeds, args.performance_follows_maturity))
    return 0


if __name__ == "__main__":
    sys.exit(main())
