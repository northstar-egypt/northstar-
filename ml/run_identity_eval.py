"""Grade the player identity engine (ml/identity) against the duplicate detector v1.

    python -m ml.run_identity_eval                       # reported seeds, both worlds
    python -m ml.run_identity_eval --seeds 101 202 303   # calibration seeds, picks the threshold
    python -m ml.run_identity_eval --tune
    python -m ml.run_identity_eval --fit-m                # measure m on the calibration seeds
    python -m ml.run_identity_eval --real-export DIR      # the label-free check on a DB export

Two worlds from the same generated datasets:

- **as generated**: the duplicates the generator plants (easy, as ml/README.md says);
- **hard**: the same datasets with some duplicates spelled in Latin, some without a date of
  birth, some at another club, and some ordinary players changed the same way so that none of
  it is a give-away (ml/identity/hard.py).

Scored pairwise (precision, recall and F1 over pairs of records that are one person) and per
person (B-cubed: for each record, how much of the group it was put in is right, and how much
of its true group it was put with). Two ways of fitting the engine are graded side by side
(ml/identity/engine.py, `score`): `em`, everything estimated with no labels, and `measured`,
the default, with m measured on the calibration seeds' known pairs. Both m and the link
threshold come from the calibration seeds (101, 202, 303) only.

`--real-export` runs the engine on an export of the database (ml/export_db.py; keep it outside
the repository) and counts the links it would propose by source. Each StatsBomb id is one
record, so a link between two StatsBomb records is certainly wrong: a count of mistakes that
needs no labels. It is a lower bound, not a precision.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from ml.detectors import duplicate
from ml.detectors.features import TABLES, FeatureSet
from ml.identity import engine, hard

REPORTED = [20260827, 7, 99, 404, 555] + list(range(1000, 1015))
CALIBRATION = [101, 202, 303]
# Chosen on the calibration seeds. With m measured (the default), every value from 0.3 to 0.7
# gave the best mean F1 there (0.986 in both worlds); the middle of that plateau is taken, the
# less fitted choice. Fitted with no labels, the plateau is 0.3 to 0.8, so 0.5 is on it too.
# (#117, before the name field left out the given name: 0.6 to 0.95, and 0.8 was taken.)
LINK = engine.LINK
GRID = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]


def _dataset(seed: int, players: int | None) -> tuple[dict, dict]:
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    config = GeneratorConfig(seed=seed)
    if players:
        config = config.scaled(players)
    ds = build_dataset(config)
    with tempfile.TemporaryDirectory(prefix="northstar-identity-") as tmp:
        out = Path(tmp)
        write_ground_truth(ds.ground_truth, out / "ground_truth.json")
        export_json(ds, out)
        tables = {name: json.loads((out / f"{name}.json").read_text(encoding="utf-8")) for name in TABLES}
        truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    return tables, truth


def _true_groups(truth: dict) -> list[set[str]]:
    return [set(c["player_ids"]) for c in truth["cases"]["duplicates"]]


def _v1_pairs(tables: dict) -> set[tuple[str, str]]:
    return {tuple(sorted(k)) for k in duplicate.detect_pairs(FeatureSet(".", raw=tables))}


def _groups_from_pairs(ids: list[str], pairs: set[tuple[str, str]]) -> list[set[str]]:
    return engine._components(ids, list(pairs))


def pairwise(found: set[tuple[str, str]], true: set[tuple[str, str]]) -> dict:
    tp = len(found & true)
    p = tp / len(found) if found else 0.0
    r = tp / len(true) if true else 0.0
    return {"tp": tp, "fp": len(found - true), "fn": len(true - found),
            "precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


def bcubed(ids: list[str], found: list[set[str]], true: list[set[str]]) -> dict:
    """B-cubed over the records in a true or found group (singletons elsewhere score 1 and
    would only dilute the number)."""
    f_of = {x: g for g in found for x in g}
    t_of = {x: g for g in true for x in g}
    involved = set(f_of) | set(t_of)
    if not involved:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    ps, rs = [], []
    for x in involved:
        fg, tg = f_of.get(x, {x}), t_of.get(x, {x})
        overlap = len(fg & tg)
        ps.append(overlap / len(fg))
        rs.append(overlap / len(tg))
    p, r = sum(ps) / len(ps), sum(rs) / len(rs)
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


METHODS = ("em", "measured")


def evaluate_seed(seed: int, players: int | None, links: list[float]) -> list[dict]:
    tables, truth = _dataset(seed, players)
    worlds = [("as generated", tables, {})]
    hard_tables, counts, changed = hard.harden(tables, truth, seed)
    worlds.append(("hard", hard_tables, changed))
    true_groups = _true_groups(truth)
    true_pairs = engine.pairs_of(true_groups)
    out = []
    for world, t, changed in worlds:
        ids = [p["id"] for p in t["players"]]
        v1 = _v1_pairs(t)
        row = {"seed": seed, "world": world, "hard_counts": counts if world == "hard" else {},
               "v1": {**pairwise(v1, true_pairs), "bcubed": bcubed(ids, _groups_from_pairs(ids, v1), true_groups)}}
        records = engine.records_from_tables(t)
        row["true_pairs"] = len(true_pairs)
        row["model"] = {}
        for method in METHODS:
            scored, model = engine.score(records, method=method)
            row["candidates"] = len(scored)
            row["true_pairs_in_candidates"] = len({tuple(sorted((s.a, s.b))) for s in scored} & true_pairs)
            for link in links:
                groups = engine.group(records, scored, link)
                found = engine.pairs_of(groups)
                row[f"{method}@{link}"] = {**pairwise(found, true_pairs), "bcubed": bcubed(ids, groups, true_groups)}
            # Recall by what made the pair hard (hard world, at the default link).
            if changed:
                groups = engine.group(records, scored, links[0] if len(links) == 1 else LINK)
                found = engine.pairs_of(groups)
                by_kind = row.setdefault("by_kind", {})
                for c in truth["cases"]["duplicates"]:
                    for pid in c["player_ids"]:
                        if pid == c["canonical_player_id"]:
                            continue
                        pair = tuple(sorted((pid, c["canonical_player_id"])))
                        for kind in changed.get(pid) or ["none"]:
                            k = by_kind.setdefault(kind, {"v1": 0, "n": 0, **{m: 0 for m in METHODS}})
                            if method == METHODS[0]:
                                k["n"] += 1
                                k["v1"] += pair in v1
                            k[method] += pair in found
            row["model"][method] = {
                "prior": model.prior, "iterations": model.iterations,
                "weights": {f: {lvl: round(model.weight(f, lvl), 2) for lvl in engine.LEVELS[f]}
                            for f in engine.FIELDS},
            }
        out.append(row)
    return out


def _pool(rows: list[dict], key: str) -> dict:
    tp = sum(r[key]["tp"] for r in rows)
    fp = sum(r[key]["fp"] for r in rows)
    fn = sum(r[key]["fn"] for r in rows)
    p = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    b = [r[key]["bcubed"]["f1"] for r in rows]
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": rc,
            "f1": 2 * p * rc / (p + rc) if p + rc else 0.0, "bcubed_f1": sum(b) / len(b)}


def render(rows: list[dict], link: float) -> str:
    lines = []
    for world in ("as generated", "hard"):
        rs = [r for r in rows if r["world"] == world]
        if not rs:
            continue
        v1 = _pool(rs, "v1")
        cand = sum(r["true_pairs_in_candidates"] for r in rs), sum(r["true_pairs"] for r in rs)
        lines.append(f"{world}: {len(rs)} seeds, {cand[1]} true pairs, {cand[0]} of them among the engine's candidates")
        lines.append("                 pairs: found  wrong  missed  precision  recall    F1   | per person (B-cubed) F1")
        for name, s in (("duplicate v1", v1), *((f"engine, {m}", _pool(rs, f"{m}@{link}")) for m in METHODS)):
            lines.append(f"  {name:<15}        {s['tp']:>5}  {s['fp']:>5}  {s['fn']:>6}  {s['precision']:9.3f}  {s['recall']:6.3f}  "
                         f"{s['f1']:5.3f}  | {s['bcubed_f1']:.3f}")
        if world == "hard":
            kinds = defaultdict(lambda: defaultdict(int))
            for r in rs:
                for k, v in r.get("by_kind", {}).items():
                    for f, x in v.items():
                        kinds[k][f] += x
            lines.append("  recall by what the clone got:  v1      " + "  ".join(f"{m:>8}" for m in METHODS))
            for k in ("none", "latin", "no_dob", "other_club"):
                if k in kinds and kinds[k]["n"]:
                    n = kinds[k]["n"]
                    lines.append(f"    {k:<12} ({n:>3} pairs)  {kinds[k]['v1'] / n:6.1%}  "
                                 + "  ".join(f"{kinds[k][m] / n:8.1%}" for m in METHODS))
        lines.append("")
    return "\n".join(lines)


SMOOTHING = 0.5


def fit_m(players: int | None) -> int:
    """m, how often a true pair shows each level, counted on the calibration seeds' known
    duplicate pairs in both worlds, with a small count added to every level."""
    counts = {f: {lvl: SMOOTHING for lvl in engine.LEVELS[f]} for f in engine.FIELDS}
    n = 0
    for seed in CALIBRATION:
        print(f"seed {seed} ...", file=sys.stderr, flush=True)
        tables, truth = _dataset(seed, players)
        hard_tables, _, _ = hard.harden(tables, truth, seed)
        for t in (tables, hard_tables):
            records = {r.id: r for r in engine.records_from_tables(t)}
            for a, b in sorted(engine.pairs_of(_true_groups(truth))):
                for f, lvl in engine.compare(records[a], records[b]).items():
                    counts[f][lvl] += 1
                n += 1
    m = {f: {lvl: round(c / sum(cs.values()), 6) for lvl, c in cs.items()} for f, cs in counts.items()}
    engine.M_FILE.write_text(json.dumps({
        "about": "m for ml/identity/engine.py, written by python -m ml.run_identity_eval --fit-m",
        "seeds": CALIBRATION, "true_pairs": n, "smoothing": SMOOTHING, "m": m,
    }, indent=1) + "\n", encoding="utf-8")
    print(f"{n} true pairs from seeds {CALIBRATION}, both worlds; wrote {engine.M_FILE}")
    return 0


def _source(player: dict) -> str:
    ids = player.get("external_ids") or {}
    return next((k for k in ("statsbomb", "footystats") if k in ids), "register")


def real_check(folder: Path, link: float = LINK) -> str:
    """Links proposed on a database export, by the sources of the two records."""
    tables = {n: json.loads((folder / f"{n}.json").read_text(encoding="utf-8"))
              for n in ("players", "affiliations", "organizations")}
    tables["players"] = [p for p in tables["players"] if p.get("status") != "merged"]
    source = {p["id"]: _source(p) for p in tables["players"]}
    records = engine.records_from_tables(tables)
    per = defaultdict(int)
    for s in source.values():
        per[s] += 1
    lines = [f"{len(records)} records: " + ", ".join(f"{k} {v}" for k, v in sorted(per.items()))]
    for method in METHODS:
        scored, model = engine.score(records, method=method)
        found = engine.pairs_of(engine.group(records, scored, link))
        kinds: dict[tuple, int] = defaultdict(int)
        for a, b in found:
            kinds[tuple(sorted((source[a], source[b])))] += 1
        lines.append(f"{method}: {len(found)} links at {link}; certainly wrong (two StatsBomb records) "
                     f"{kinds[('statsbomb', 'statsbomb')]}")
        lines.append("  " + ", ".join(f"{a}-{b} {n}" for (a, b), n in sorted(kinds.items(), key=lambda x: -x[1])))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="run_identity_eval", description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, nargs="+", default=None)
    parser.add_argument("--players", type=int, default=None)
    parser.add_argument("--tune", action="store_true", help="the calibration seeds, every link in the grid")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--fit-m", action="store_true", help="measure m on the calibration seeds and save it")
    parser.add_argument("--real-export", type=Path, default=None, help="the label-free check on a DB export")
    args = parser.parse_args(argv)
    if args.fit_m:
        return fit_m(args.players)
    if args.real_export:
        print(real_check(args.real_export))
        return 0
    seeds = args.seeds or (CALIBRATION if args.tune else REPORTED)
    links = GRID if args.tune else [LINK]
    rows = []
    for seed in seeds:
        print(f"seed {seed} ...", file=sys.stderr, flush=True)
        rows += evaluate_seed(seed, args.players, links)
    if args.tune:
        print("Link threshold on the calibration seeds (mean of the two worlds' pairwise F1):")
        for method in METHODS:
            print(f" {method}:")
            for link in links:
                f1s = [_pool([r for r in rows if r["world"] == w], f"{method}@{link}")["f1"]
                       for w in ("as generated", "hard")]
                print(f"  {link:<5} as generated {f1s[0]:.3f}   hard {f1s[1]:.3f}   mean {(f1s[0] + f1s[1]) / 2:.3f}")
        print()
    print(render(rows, links[0] if len(links) == 1 else LINK))
    for method in METHODS:
        weights = rows[-1]["model"][method]["weights"]
        print(f"Weights, {method} (log odds, last dataset, hard world):", json.dumps(weights, ensure_ascii=False))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
