"""Real labels for the identity engine: draw a sample for a person to label, then score it.

    python -m ml.export_db --out D:/northstar-data/export            # outside the repository
    python -m ml.run_identity_labels sample --export D:/northstar-data/export \\
        --out D:/northstar-data/identity-labels
    # a person fills the same_person column of identity-labels/pairs.csv: yes, no or unsure
    python -m ml.run_identity_labels score --labels D:/northstar-data/identity-labels \\
        [--database-url postgresql+psycopg://...]                       # adds the board's decisions

How the sample is drawn and what the estimate means: ml/identity/labels.py and ml/README.md,
"Player identity". How to label: docs/identity-labelling.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ml.identity import labels


def _load(folder: Path) -> dict[str, list[dict]]:
    names = ("players", "affiliations", "organizations", "performance_entries")
    return {n: json.loads((folder / f"{n}.json").read_text(encoding="utf-8"))
            for n in names if (folder / f"{n}.json").exists()}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def render(result: dict) -> str:
    lines = ["stratum                 size  labelled  same   share (95% interval)"]
    for k, _ in labels.STRATA:
        s = result["strata"][k]
        lo, hi = s["interval"]
        lines.append(f"  {k:<20} {s['size']:>6}  {s['labelled']:>8}  {s['same']:>4}   "
                     f"{_pct(s['share'])} ({_pct(lo)} to {_pct(hi)})")
    p, i = result["point"], result["interval"]
    for m in ("precision", "recall"):
        band = i.get(m)
        lines.append(f"{m}: {_pct(p.get(m))}" + (f" (95% interval {_pct(band[0])} to {_pct(band[1])})" if band else ""))
    lines.append(f"unsure or not yet labelled: {result['unsure_or_blank']}")
    if result["m_changed"]:
        lines.append("note: the engine's m has changed since this sample was drawn; this scores the engine that drew it")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="run_identity_labels", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample", help="draw the pairs for a person to label")
    s.add_argument("--export", type=Path, required=True, help="a database export (ml/export_db.py)")
    s.add_argument("--out", type=Path, required=True, help="a folder outside the repository")
    s.add_argument("--per-stratum", type=int, default=labels.PER_STRATUM)
    c = sub.add_parser("score", help="precision and recall from the labels")
    c.add_argument("--labels", type=Path, required=True, help="the folder `sample` wrote")
    c.add_argument("--database-url", default=None, help="also count the board's decisions")
    args = parser.parse_args(argv)

    if args.command == "sample":
        try:
            meta = labels.sample(_load(args.export), args.out, args.per_stratum)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        for k, v in meta["strata"].items():
            n = sum(1 for p in meta["pairs"].values() if p["stratum"] == k)
            print(f"  {k:<20} {n:>3} of {v['size']:>6}  {v['about']}")
        print(f"{len(meta['pairs'])} pairs to label in {args.out / 'pairs.csv'}")
        return 0

    print(render(labels.score(args.labels)))
    if args.database_url:
        decided = labels.board_decisions(args.database_url)
        print("Board decisions on duplicate cases (not a random sample, so not in the estimate):")
        if not decided:
            print("  none yet")
        for detector, d in sorted(decided.items()):
            n = d["confirmed"] + d["dismissed"]
            print(f"  {detector:<10} confirmed {d['confirmed']}, dismissed {d['dismissed']}"
                  + (f", share confirmed {d['confirmed'] / n:.1%}" if n else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
