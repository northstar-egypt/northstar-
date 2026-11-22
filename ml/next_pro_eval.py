"""Is "find the next <pro>" stable? (ml/next_pro.py)

There is no answer key for "this child plays like that professional", so this cannot measure
whether a match is right. What it can measure is whether the list depends on the professional's
style or on chance: build each professional's season in two halves (pro_league.build_halves),
find the ten closest academy players from each half, and count how many are on both lists.
If the method only matched noise, the overlap would be what two random draws of ten from the
same academy position group share (10 / group size).

Synthetic data on both sides: the academy from the generator (`ml.run_backtest._generate`),
the league from `data/pipelines/synthetic/pro_league.py`. The weights in `next_pro.WEIGHTS`
were set by hand from football sense, not tuned on any seed.

    python -m ml.next_pro_eval            # seeds 101 202 303 404 505
"""

from __future__ import annotations

import statistics
import sys
import tempfile
from datetime import date
from pathlib import Path

from ml import next_pro as N

SHOWN = 10
REFERENCE = date(2026, 7, 1)


def youth_pool(data_dir: Path) -> list[N.Player]:
    from ml.detectors.features import FeatureSet

    features = FeatureSet(data_dir)
    out = []
    for pid, pf in features.players.items():
        p = pf.player
        if p.get("primary_sport") != "football" or p.get("status") == "merged":
            continue
        totals: dict[str, float] = {}
        for e in pf.performance:
            if e.get("period_type", "match") != "match":
                continue
            for k, v in (e.get("metrics") or {}).items():
                if isinstance(v, (int, float)):
                    totals[k] = totals.get(k, 0) + v
        if totals.get("minutes_played", 0) < N.YOUTH_MIN_MINUTES:
            continue
        r = N.rates(totals)
        if r:
            out.append(N.Player(pid, p.get("position"), (p.get("sex"), (p.get("date_of_birth") or "")[:4]), r))
    return out


def pro_pool(league, players) -> list[N.Player]:
    from ml.pro.seasons import from_league

    best = {}
    for r in from_league(league, players):
        if r.minutes >= N.PRO_MIN_MINUTES and (r.player_id not in best or r.end > best[r.player_id].end):
            best[r.player_id] = r
    return [N.Player(r.player_id, r.position, (r.source,), N.rates(r.metrics))
            for r in best.values() if N.rates(r.metrics)]


def evaluate(seed: int) -> dict:
    from data.pipelines.synthetic import pro_league
    from ml.run_backtest import _generate

    with tempfile.TemporaryDirectory() as tmp:
        _generate(seed, Path(tmp), attrition=False, players=None)
        youth = youth_pool(Path(tmp))
    clubs, players = pro_league.synthetic_inputs(seed, REFERENCE)
    first, second = pro_league.build_halves(seed, clubs, players, REFERENCE)
    a = {p.player_id: p for p in pro_pool(first, players)}
    b = {p.player_id: p for p in pro_pool(second, players)}
    sizes: dict[str, int] = {}
    for y in N.youth_peers(youth):
        fam = N.family(y.position)
        if fam:
            sizes[fam] = sizes.get(fam, 0) + 1
    overlap, chance = [], []
    for pid in a.keys() & b.keys():
        top_a = {m.player_id for m in N.matches(a[pid], list(a.values()), youth, shown=SHOWN, keep_opposite=True)}
        top_b = {m.player_id for m in N.matches(b[pid], list(b.values()), youth, shown=SHOWN, keep_opposite=True)}
        if top_a and top_b:
            overlap.append(len(top_a & top_b) / SHOWN)
            chance.append(min(1.0, SHOWN / sizes[N.family(a[pid].position)]))
    return {"seed": seed, "pros": len(overlap), "overlap": statistics.fmean(overlap),
            "chance": statistics.fmean(chance)}


def main(argv: list[str] | None = None) -> int:
    seeds = [int(s) for s in (argv if argv is not None else sys.argv[1:])] or [101, 202, 303, 404, 505]
    print(f"{'seed':>5} {'pros':>5} {'overlap of top 10':>18} {'by chance':>10}")
    for seed in seeds:
        r = evaluate(seed)
        print(f"{r['seed']:>5} {r['pros']:>5} {r['overlap']:>17.1%} {r['chance']:>10.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
