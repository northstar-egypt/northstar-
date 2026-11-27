"""The professional age curves as one figure for the thesis: a small multiple per position group and measure.

    python -m ml.figure_age_curves --cache-dir D:/northstar-data/footystats
    python -m ml.figure_age_curves --cache-dir D:/northstar-data/footystats --out docs/figures/age-curves.svg

Reads the same FootyStats cache as `python -m ml.run_age_curve_eval` (outside the repository, the
seven Premier League seasons) and draws the same curves, with the method in ml/pro/age_curves.py.
Hand-written SVG, like ml/figure_late_bloomer.py, so it needs no plotting library.

What each panel shows
---------------------
- the delta-method curve (solid blue) with its 80% band (pale blue): how the measure changes with
  age for players who stay in the league. The curve starts at the simple average of its youngest
  age, so the band has no width there; the band is the uncertainty of the change since then;
- the simple average by age (dashed orange), drawn beside it to show why the method matters: it
  rises after 30 only because the players who declined have left the league;
- ages with fewer than 30 player pairs are not drawn, and a panel with no such age says so.
Goalkeepers have the minutes panel only. All panels of a measure share one vertical scale, so
the positions can be compared. The figure holds aggregate curves, not player rows; as with all
output from real data, look at it before it is committed.
"""

from __future__ import annotations

import argparse
import sys
from html import escape
from pathlib import Path

from ml.pro import age_curves as ac

BLUE, ORANGE = "#257de0", "#f47230"   # validated pair: scripts/validate_palette.js, light surface
INK, MUTED, GRID = "#191919", "#666666", "#e3e3e3"

PANEL_W, PANEL_H = 300, 170
LEFT, RIGHT, TOP, BOTTOM = 56, 18, 34, 30
GAP_X, GAP_Y = 14, 34
HEADER = 70
FOOTER = 62


def _ticks(low: float, high: float, count: int = 4) -> list[float]:
    span = high - low or 1.0
    raw = span / count
    magnitude = 10 ** (len(str(int(raw * 1000))) - 4) if raw < 1 else 10 ** (len(str(int(raw))) - 1)
    step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), default=raw)
    first = int(low / step) * step
    ticks, t = [], first
    while t <= high + step * 0.01:
        if t >= low - step * 0.01:
            ticks.append(round(t, 6))
        t += step
    return ticks


def _scale_for(curves, measure) -> tuple[float, float]:
    values = []
    for (_, m), (curve, simple) in curves.items():
        if m != measure:
            continue
        if curve is not None:
            values += curve.low + curve.high + curve.level
        values += [v for v, _ in simple.values()]
    if not values:
        return 0.0, 1.0
    low, high = min(values), max(values)
    pad = (high - low) * 0.06 or 0.05
    return max(0.0, low - pad), high + pad


def _panel(curve, simple, measure, position, x0, y0, y_low, y_high, show_x_title) -> list[str]:
    w, h = PANEL_W - LEFT - RIGHT, PANEL_H - TOP - BOTTOM
    left, top = x0 + LEFT, y0 + TOP
    out = [f'<text x="{x0 + LEFT}" y="{y0 + 18}" font-size="13" font-weight="600" fill="{INK}">'
           f'{escape(position.capitalize())}</text>']
    shown = sorted(simple)
    if curve is not None:
        shown += curve.ages + [curve.ages[-1] + 1]
    if not shown:
        out.append(f'<text x="{left}" y="{top + h / 2}" font-size="11" fill="{MUTED}">'
                   f'no age has {ac.MIN_PAIRS} pairs</text>')
        return out
    a_low, a_high = min(shown), max(shown)

    def sx(age):
        return left + (age - a_low) / max(1, a_high - a_low) * w

    def sy(value):
        return top + h - (value - y_low) / (y_high - y_low) * h

    ticks = _ticks(y_low, y_high)
    for t in ticks:
        out.append(f'<line x1="{left}" x2="{left + w}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" stroke="{GRID}" stroke-width="1"/>')
        label = f"{t:.0%}" if measure == "minutes_share" else f"{t:.2f}"
        out.append(f'<text x="{left - 6}" y="{sy(t) + 3.5:.1f}" font-size="10" fill="{MUTED}" text-anchor="end">{label}</text>')
    for age in range(a_low, a_high + 1):
        if (age - a_low) % 5 == 0 or age in (a_low, a_high):
            out.append(f'<text x="{sx(age):.1f}" y="{top + h + 15}" font-size="10" fill="{MUTED}" text-anchor="middle">{age}</text>')
    if show_x_title:
        out.append(f'<text x="{left + w / 2}" y="{top + h + 28}" font-size="10" fill="{MUTED}" text-anchor="middle">age</text>')
    if curve is not None:
        ages = curve.ages + [curve.ages[-1] + 1]
        top_edge = " ".join(f"{sx(a):.1f},{sy(v):.1f}" for a, v in zip(ages, curve.high))
        bottom_edge = " ".join(f"{sx(a):.1f},{sy(v):.1f}" for a, v in reversed(list(zip(ages, curve.low))))
        out.append(f'<polygon points="{top_edge} {bottom_edge}" fill="{BLUE}" fill-opacity="0.18" stroke="none"/>')
    if simple:
        pts = " ".join(f"{sx(a):.1f},{sy(v):.1f}" for a, (v, _) in sorted(simple.items()))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{ORANGE}" stroke-width="2" '
                   f'stroke-dasharray="5 3" stroke-linejoin="round"/>')
    if curve is not None:
        pts = " ".join(f"{sx(a):.1f},{sy(v):.1f}" for a, v in zip(ages, curve.level))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{BLUE}" stroke-width="2" stroke-linejoin="round"/>')
    return out


def render(curves: dict, *, caption: str = "") -> str:
    """The whole figure as an SVG string, from `age_curves.all_curves`."""
    cols = len(ac.MEASURES)
    width = cols * PANEL_W + (cols - 1) * GAP_X
    height = HEADER + len(ac.POSITIONS) * PANEL_H + (len(ac.POSITIONS) - 1) * GAP_Y // 2 + FOOTER
    scales = {m: _scale_for(curves, m) for m in ac.MEASURES}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
             f'height="{height}" font-family="Helvetica, Arial, sans-serif" role="img" '
             f'aria-label="Age curves for professional players by position group">',
             f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
             f'<text x="{LEFT}" y="22" font-size="15" font-weight="600" fill="{INK}">'
             f'How playing time and output change with age, by position group</text>',
             f'<line x1="{LEFT}" x2="{LEFT + 26}" y1="46" y2="46" stroke="{BLUE}" stroke-width="2"/>',
             f'<rect x="{LEFT}" y="41" width="26" height="10" fill="{BLUE}" fill-opacity="0.18"/>',
             f'<text x="{LEFT + 32}" y="50" font-size="11" fill="{INK}">Delta-method curve, with 80% band</text>',
             f'<line x1="{LEFT + 232}" x2="{LEFT + 258}" y1="46" y2="46" stroke="{ORANGE}" stroke-width="2" stroke-dasharray="5 3"/>',
             f'<text x="{LEFT + 264}" y="50" font-size="11" fill="{INK}">Simple average by age</text>']
    for c, measure in enumerate(ac.MEASURES):
        parts.append(f'<text x="{c * (PANEL_W + GAP_X) + LEFT}" y="{HEADER - 6}" font-size="12" fill="{MUTED}">'
                     f'{escape(ac.MEASURE_LABELS[measure])}</text>')
    row_y = lambda r: HEADER + r * (PANEL_H + GAP_Y // 2)  # noqa: E731
    for r, position in enumerate(ac.POSITIONS):
        for c, measure in enumerate(ac.MEASURES):
            if measure not in ac.measures_for(position):
                continue
            curve, simple = curves[(position, measure)]
            low, high = scales[measure]
            parts += _panel(curve, simple, measure, position, c * (PANEL_W + GAP_X), row_y(r), low, high,
                            show_x_title=r == len(ac.POSITIONS) - 1)
    y = height - FOOTER + 18
    for line in (caption or default_caption()).split("\n"):
        parts.append(f'<text x="{LEFT}" y="{y}" font-size="10.5" fill="{MUTED}">{escape(line)}</text>')
        y += 14
    parts.append("</svg>")
    return "\n".join(parts)


def default_caption() -> str:
    return (f"Premier League seasons 2018/19 to 2024/25. Per 90 measures use seasons of {ac.MIN_PER90_MINUTES}+ minutes. "
            f"Ages with fewer than {ac.MIN_PAIRS} pairs are not drawn.\n"
            "The curve adds up each age's average change for players seen in two consecutive seasons, "
            "weighted by minutes; the band resamples players "
            f"{ac.N_BOOTSTRAP} times.\n"
            "Each panel of a measure shares one vertical scale. Goalkeepers have the minutes panel only.")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="figure_age_curves", description=__doc__.splitlines()[0])
    parser.add_argument("--cache-dir", required=True, type=Path, help="a FootyStats cache outside the repository")
    parser.add_argument("--out", type=Path, default=Path("docs/figures/age-curves.svg"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    records, report = ac.load_records(args.cache_dir)
    if not report.seasons:
        raise SystemExit("no Premier League season found in the cache; see ml/run_age_curve_eval.py")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(ac.all_curves(records, seed=args.seed)), encoding="utf-8")
    print(f"wrote {args.out} from {len(report.seasons)} seasons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
