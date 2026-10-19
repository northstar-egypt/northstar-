"""Grade player similarity (ml/similarity.py) against what the generator hides.

    python -m ml.run_similarity_eval --seed-sweep 101 202 303              # tuning
    python -m ml.run_similarity_eval --seed-sweep 20260827 7 99 404 555    # reported

For every player with a profile, take their K most similar players and ask two questions.

Role (football): what share of them play the same kind of position (goalkeeper, defender,
midfielder, forward)? The profile never reads position, so this is whether the statistics
alone find players of the same role. Against chance, which is the share of that role among
the candidates. For table tennis the same question is asked of playing style, which the
generator does not use when it draws a match: there the right answer is chance, and a method
that beat it would be finding something that is not there.

Level: among players of the same role group, how far is their hidden ability (from the answer
key) from the player's own, on average? Against three references: random players of the same
group (what no method gives), the single obvious number (shots per 90 for football, share of
points won for table tennis), and the best possible (the K closest in true ability, which no
method can know). Reported as the share of the gap between random and best that a method
closes: 0% is no better than random, 100% is perfect.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path

from ml import similarity
from ml.detectors.features import FeatureSet
from ml.run_backtest import _generate

K = 5


def _gap_closed(method: float, random: float, best: float) -> float:
    return (random - method) / (random - best) if random > best else 0.0


def evaluate(data_dir: Path) -> dict:
    features = FeatureSet(data_dir)
    truth = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    ability = {**truth.get("football_ability", {}), **truth.get("table_tennis_ability", {})}
    every = similarity.profiles(features)
    position = {pid: features.players[pid].player.get("position") for pid in every}

    def group(pid: str) -> str:
        p = every[pid]
        return similarity.POSITION_GROUPS.get(position[pid], "?") if p.sport == "football" else (
            position[pid] or "?"
        )

    result = {"football": [], "table_tennis": []}
    for pid, me in every.items():
        if pid not in ability:
            continue
        # Role: unfiltered neighbours.
        near = similarity.nearest(pid, every, K)
        pool = [q for q, p in every.items() if q != pid and p.sport == me.sport and p.gender == me.gender]
        if len(pool) < K or not near:
            continue
        same_role = sum(group(q) == group(pid) for q, _ in near) / len(near)
        chance = sum(group(q) == group(pid) for q in pool) / len(pool)

        # Level: within the same role group (football) or everyone of the gender (table tennis).
        peers = {q for q in pool if q in ability and (me.sport != "football" or group(q) == group(pid))}
        if len(peers) < K:
            continue
        mine = ability[pid]
        level = statistics.fmean(abs(ability[q] - mine) for q, _ in similarity.nearest(pid, every, K, peers))
        random = statistics.fmean(abs(ability[q] - mine) for q in peers)
        best = statistics.fmean(sorted(abs(ability[q] - mine) for q in peers)[:K])
        key = "shots" if me.sport == "football" else "point_share"
        if key in me.raw:
            one = sorted(
                (q for q in peers if key in every[q].raw),
                key=lambda q: abs(every[q].raw[key] - me.raw[key]),
            )[:K]
            single = statistics.fmean(abs(ability[q] - mine) for q in one)
        else:
            single = random
        result[me.sport].append(
            {"same_role": same_role, "chance": chance, "level": level, "random": random,
             "best": best, "single": single}
        )
    return result


def summarise(rows: list[dict], sport: str) -> list[str]:
    if not rows:
        return [f"{sport}: no players with a profile"]
    mean = lambda k: statistics.fmean(r[k] for r in rows)  # noqa: E731
    role_name = "role (position group)" if sport == "football" else "playing style (not used by the generator)"
    lines = [f"{sport}: {len(rows)} players with a profile and a hidden ability"]
    lines.append(
        f"  {role_name}: {mean('same_role'):.0%} of the {K} most similar share it, chance {mean('chance'):.0%}"
    )
    gap = lambda k: _gap_closed(mean(k), mean("random"), mean("best"))  # noqa: E731
    single = "shots per 90" if sport == "football" else "share of points won"
    lines.append(
        f"  level, mean ability gap to the {K} most similar: similarity {mean('level'):.3f} "
        f"({gap('level'):.0%} of the way from random to best), {single} alone {mean('single'):.3f} "
        f"({gap('single'):.0%}), random {mean('random'):.3f}, best possible {mean('best'):.3f}"
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_similarity_eval", description=__doc__.split("\n")[0])
    parser.add_argument("--seed-sweep", type=int, nargs="+", required=True, metavar="SEED")
    args = parser.parse_args(argv)
    pooled = {"football": [], "table_tennis": []}
    with tempfile.TemporaryDirectory(prefix="northstar-similarity-") as tmp:
        for seed in args.seed_sweep:
            print(f"generating seed {seed} ...", file=sys.stderr)
            out = Path(tmp) / str(seed)
            _generate(seed, out, attrition=False, players=None)
            for sport, rows in evaluate(out).items():
                pooled[sport] += rows
    print(f"Player similarity, seeds {', '.join(map(str, args.seed_sweep))}, pooled, K = {K}")
    for sport in ("football", "table_tennis"):
        print("\n".join(summarise(pooled[sport], sport)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
