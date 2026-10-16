"""The late-bloomer figure: one player the size cut would have released, and what came next.

    python -m ml.figure_late_bloomer             # writes docs/figures/late-bloomer.svg
    python -m ml.figure_late_bloomer --quick     # rates from the 212-player datasets, faster

The project's whole argument in one picture. A boy small enough at about 14 to be in the
shortest quarter of his age group, the date the size cut would have released him, the same
date the system flagged him as a late bloomer, and how tall he goes on to be.

What is measured and what is not
--------------------------------
Every point on the figure is a height reading from the synthetic dataset. Filled points are
the readings the system had on the day of the cut, hollow ones were measured after it. The
dataset follows each player for at most 40 months, so the readings stop well before adulthood.
The dashed line after the last reading is the growth curve the generator planted for this
player (`ground_truth.json`, through `data/pipelines/synthetic/growth.height_cm`): the answer
key, which a real deployment would not have. The figure labels it as such.

The grey band is the age group in the same dataset: median height of boys at each age, plus
and minus one standard deviation, the reference the detectors compare against.

Which player
------------
Not picked by eye. The rule: planted late bloomers in the default dataset (seed 20260827, a
reported seed, never used for tuning) whom the backtest's size cut reached and the detector
flagged at that moment, football boys only (the premise is the football academy cut), and of
those the one whose age at the cut is closest to 14. About half of such players are flagged,
not all, so the caption carries the pooled rates from the backtest beside the example.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from html import escape
from pathlib import Path

from ml.backtest import Decision, run, summarise
from ml.detectors.features import FeatureSet
from ml.run_backtest import _generate

DEFAULT_SEED = 20260827
REPORTED_SEEDS = (20260827, 7, 99, 404, 555)
# The size ml/README.md quotes the backtest at.
POOLED_PLAYERS = 1000
DEFAULT_OUT = Path("docs/figures/late-bloomer.svg")
TARGET_AGE = 14.0
# The curve is drawn until the planted model stops growing, at most to this age.
MAX_AGE = 25.0
# His adult height is compared with men this age in the same dataset, past every growth curve.
ADULT_AGE = 21


@dataclass
class Example:
    decision: Decision
    readings: list[tuple[float, float]]  # (age, cm)
    planted_curve: list[tuple[float, float]]  # (age, cm), from the last reading to fully grown
    adult_height_cm: float
    maturity_offset_years: float
    band: list[tuple[int, float, float]]  # (age, median, spread)
    adult_median_cm: float | None
    end_age: float


def choose(decisions: list[Decision], players: dict[str, dict]) -> Decision:
    """The selection rule in the module docstring."""
    candidates = [
        d
        for d in decisions
        if d.planted_late_bloomer
        and d.flagged
        and d.sex == "male"
        and players[d.player_id].get("primary_sport") == "football"
    ]
    if not candidates:
        raise SystemExit("No flagged football late bloomer reached the size cut in this dataset.")
    return min(candidates, key=lambda d: (abs(d.stated_age - TARGET_AGE), d.player_id))


def build_example(data_dir: Path) -> Example:
    from data.pipelines.synthetic import growth

    report = run(data_dir)
    features = FeatureSet(data_dir)
    players = {pid: pf.player for pid, pf in features.players.items()}
    decision = choose(report.decisions, players)
    pf = features.players[decision.player_id]

    truth =json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    case = next(
        c for c in truth["cases"]["late_bloomers"] if c["player_id"] == decision.player_id
    )
    adult, offset = case["projected_adult_height_cm"], case["maturity_offset_years"]

    readings = [(pf.age_at(when), cm) for when, cm in pf.heights]
    curve, age = [], readings[-1][0]
    while True:
        cm = growth.height_cm(age, pf.sex, adult, offset)
        curve.append((age, cm))
        if adult - cm < 0.05 or age >= MAX_AGE:
            break
        age = min(age + 0.1, MAX_AGE)
    end_age = float(int(curve[-1][0]) + 1)
    curve.append((end_age, growth.height_cm(end_age, pf.sex, adult, offset)))

    first_age = int(min(readings[0][0], decision.stated_age)) - 1
    band = [
        (a, *features.height_reference[(pf.sex, a)])
        for a in range(first_age, int(end_age) + 1)
        if (pf.sex, a) in features.height_reference
    ]
    ref = features.height_reference.get((pf.sex, ADULT_AGE))
    adult_median = ref[0] if ref else None

    return Example(decision, readings, curve, adult, offset, band, adult_median, end_age)


def pooled_rates(seeds: tuple[int, ...], players: int | None) -> dict:
    reports = []
    with tempfile.TemporaryDirectory(prefix="northstar-figure-") as tmp:
        for seed in seeds:
            print(f"generating seed {seed} ...", file=sys.stderr)
            out_dir = Path(tmp) / str(seed)
            _generate(seed, out_dir, attrition=False, players=players)
            reports.append(run(out_dir))
    decisions = [d for r in reports for d in r.decisions]
    never_cut = {f"{r.seed}:{k}": v for r in reports for k, v in r.never_cut.items()}
    return summarise(decisions, never_cut)


# ---------------------------------------------------------------------------
# Drawing. Hand-written SVG, like apps/web/components/charts.tsx: no plotting dependency.
# ---------------------------------------------------------------------------

WIDTH, HEIGHT = 820, 600
LEFT, RIGHT, TOP, BOTTOM = 70, 790, 70, 400
INK, MUTED, GRID = "#1f2937", "#6b7280", "#e5e7eb"
BAND, MEDIAN = "#e5e7eb", "#9ca3af"
PLAYER, CUT = "#0f766e", "#b45309"


def _rate(rate) -> str:
    return f"{rate.hits} of {rate.total} ({rate.hits / rate.total:.0%})" if rate.total else "none"


def render(example: Example, rates: dict, *, seed: int, sample: str) -> str:
    d = example.decision
    ages = [a for a, _ in example.readings] + [a for a, *_ in example.band] + [example.end_age]
    heights = (
        [cm for _, cm in example.readings]
        + [cm for _, cm in example.planted_curve]
        + [m - s for _, m, s in example.band]
        + [m + s for _, m, s in example.band]
    )
    x0, x1 = min(ages), example.end_age
    y0, y1 = (min(heights) // 10) * 10, (max(heights) // 10 + 1) * 10

    def x(age: float) -> float:
        return LEFT + (age - x0) / (x1 - x0) * (RIGHT - LEFT)

    def y(cm: float) -> float:
        return BOTTOM - (cm - y0) / (y1 - y0) * (BOTTOM - TOP)

    def text(px, py, body, *, size=13, fill=INK, anchor="start", weight=400):
        return (
            f'<text x="{px:.1f}" y="{py:.1f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(body)}</text>'
        )

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="100%" style="max-width:{WIDTH}px" font-family="Segoe UI, Helvetica, Arial, sans-serif" '
        f'role="img" aria-labelledby="title desc">',
        '<title id="title">A late bloomer at the moment of the size cut</title>',
        f'<desc id="desc">Height readings of one synthetic boy, the date a size cut would '
        f'have released him at age {d.stated_age:.1f}, the same date the system flagged him as '
        f'a late bloomer, and the growth the generator planted for him afterwards.</desc>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        text(LEFT, 32, "A late bloomer at the moment of the size cut", size=18, weight=600),
        text(
            LEFT, 52,
            "Height of one synthetic boy against his age group. Solid: measured. "
            "Dashed: the answer key, never measured.",
            size=12, fill=MUTED,
        ),
    ]

    # Grid and axes.
    for cm in range(int(y0), int(y1) + 1, 10):
        out.append(
            f'<line x1="{LEFT}" y1="{y(cm):.1f}" x2="{RIGHT}" y2="{y(cm):.1f}" stroke="{GRID}"/>'
        )
        out.append(text(LEFT - 8, y(cm) + 4, f"{cm}", size=11, fill=MUTED, anchor="end"))
    for age in range(int(x0) + (x0 % 1 > 0), int(x1) + 1):
        out.append(text(x(age), BOTTOM + 18, f"{age}", size=11, fill=MUTED, anchor="middle"))
    out.append(text((LEFT + RIGHT) / 2, BOTTOM + 38, "age (years)", size=12, fill=MUTED, anchor="middle"))
    out.append(text(LEFT - 8, TOP - 10, "cm", size=11, fill=MUTED, anchor="end"))

    # Age group band and median.
    upper = " ".join(f"{x(a):.1f},{y(m + s):.1f}" for a, m, s in example.band)
    lower = " ".join(f"{x(a):.1f},{y(m - s):.1f}" for a, m, s in reversed(example.band))
    out.append(f'<polygon points="{upper} {lower}" fill="{BAND}" opacity="0.8"/>')
    median = " ".join(f"{x(a):.1f},{y(m):.1f}" for a, m, _ in example.band)
    out.append(f'<polyline points="{median}" fill="none" stroke="{MEDIAN}" stroke-width="1.5"/>')
    # Top left, above the band and left of the cut line, where nothing else is drawn.
    out.append(text(LEFT + 6, TOP + 14, "grey: his age group,", size=11, fill=MUTED))
    out.append(text(LEFT + 6, TOP + 28, "median ± 1 SD", size=11, fill=MUTED))

    # The cut.
    cut_x = x(d.stated_age)
    out.append(
        f'<line x1="{cut_x:.1f}" y1="{TOP}" x2="{cut_x:.1f}" y2="{BOTTOM}" stroke="{CUT}" '
        f'stroke-width="1.5" stroke-dasharray="4 3"/>'
    )
    out.append(text(cut_x + 6, TOP + 14, f"Age {d.stated_age:.1f}: in the shortest quarter of boys,", size=12, fill=CUT, weight=600))
    out.append(text(cut_x + 6, TOP + 30, "the size cut would release him.", size=12, fill=CUT))
    out.append(text(cut_x + 6, TOP + 50, f"Same day, from {d.readings} readings, NorthStar", size=12, fill=PLAYER, weight=600))
    out.append(text(cut_x + 6, TOP + 66, "flags him as a late bloomer.", size=12, fill=PLAYER))

    # Answer key, then the readings on top.
    curve = " ".join(f"{x(a):.1f},{y(cm):.1f}" for a, cm in example.planted_curve)
    out.append(
        f'<polyline points="{curve}" fill="none" stroke="{PLAYER}" stroke-width="2" '
        f'stroke-dasharray="6 4"/>'
    )
    measured = " ".join(f"{x(a):.1f},{y(cm):.1f}" for a, cm in example.readings)
    out.append(f'<polyline points="{measured}" fill="none" stroke="{PLAYER}" stroke-width="2"/>')
    for age, cm in example.readings:
        known = age <= d.stated_age + 1e-9
        out.append(
            f'<circle cx="{x(age):.1f}" cy="{y(cm):.1f}" r="4" stroke="{PLAYER}" '
            f'stroke-width="1.5" fill="{PLAYER if known else "#ffffff"}"/>'
        )

    end_age, end_cm = example.planted_curve[-1]
    note = f"Planted adult height {example.adult_height_cm:.1f} cm"
    if example.adult_median_cm is not None:
        diff = example.adult_height_cm - example.adult_median_cm
        side = "above" if diff >= 0 else "below"
        note2 = f"{abs(diff):.1f} cm {side} the median for men aged {ADULT_AGE}"
    else:
        note2 = f"no reference for men aged {ADULT_AGE} in this dataset"
    # Below the end of the dashed line, clear of the median line above it.
    out.append(text(x(end_age) - 4, y(end_cm) + 20, note, size=12, fill=PLAYER, anchor="end", weight=600))
    out.append(text(x(end_age) - 4, y(end_cm) + 36, note2, size=12, fill=PLAYER, anchor="end"))

    # Caption: the rule and the rates, so the example is never read as the rule.
    lines = [
        "Filled points: readings the system had on the day of the cut. Hollow: measured after it.",
        "The synthetic data follows each player for at most 40 months, so the readings stop early.",
        f"Dashed: the growth the generator planted for him, maturity delayed "
        f"{example.maturity_offset_years:.2f} years. A real deployment would not have this line.",
        f"Chosen by rule, not by eye (seed {seed}): of the flagged football late bloomers the "
        f"size cut reached,",
        "the one whose age at the cut is closest to 14. The rule is in ml/figure_late_bloomer.py.",
        f"Not every late bloomer is caught. Backtest over {sample}, at the moment of the cut:",
        f"flagged {_rate(rates['caught_with_history'])} of late bloomers measured "
        f"{rates['min_readings']}+ times, {_rate(rates['false_alarms_with_history'])} of other "
        f"small players,",
        f"and {_rate(rates['caught_without_history'])} of late bloomers measured fewer times.",
    ]
    for i, line in enumerate(lines):
        out.append(text(LEFT, BOTTOM + 66 + i * 18, line, size=11.5, fill=MUTED))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="figure_late_bloomer", description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Pool the rates over the default-size datasets (212 players) instead of the 1000 "
        "quoted in ml/README.md. Seconds instead of minutes; for checking the drawing.",
    )
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="northstar-figure-") as tmp:
        data_dir = Path(tmp) / str(DEFAULT_SEED)
        print(f"generating seed {DEFAULT_SEED} (default size) ...", file=sys.stderr)
        _generate(DEFAULT_SEED, data_dir, attrition=False, players=None)
        example = build_example(data_dir)
    # None is the default dataset, not config.scaled(212): scaling builds a slightly different
    # population, and the README's bracketed 212 figures are the default ones.
    players = None if args.quick else POOLED_PLAYERS
    rates = pooled_rates(REPORTED_SEEDS, players)
    sample = f"{len(REPORTED_SEEDS)} datasets of {players or 212} players"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # LF on every platform, so regenerating on Windows does not rewrite every line.
    args.out.write_text(
        render(example, rates, seed=DEFAULT_SEED, sample=sample), encoding="utf-8", newline="\n"
    )
    d = example.decision
    print(
        f"{args.out}: player {d.player_id[:8]}, cut at {d.stated_age:.1f} on {d.cutoff}, "
        f"{d.readings} readings, planted adult {example.adult_height_cm} cm "
        f"(median for men aged {ADULT_AGE}: {example.adult_median_cm})"
    )
    print(
        f"pooled: caught {rates['caught_with_history']}; others "
        f"{rates['false_alarms_with_history']}; too few readings {rates['caught_without_history']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
