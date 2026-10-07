"""Grading the table tennis ratings against the ability the generator hid.

Two models, two baselines, the same players and the same matches for all four.

- **Glicko-2** (ml/rating/glicko2.py), the method decision 0004 chose: match results only.
- **point rating** (ml/rating/points.py), the challenger: every point, adjusted for opponents.
- **match win rate** and **point win rate**, over every row the player has, including
  matches against outsiders that neither model can use. That is what a scout sees today.

Two questions.

1. Does it put players in the right order?
   Spearman rank correlation between each method's score at the reference date and the hidden
   ability (`ground_truth.json`, `table_tennis_ability`), within each gender, because boys and
   girls never meet and their ratings are two separate scales. Every player with at least one
   rated match counts. Each model's own display rule is reported too: how many players it
   would show, and how well it orders those.

2. Does it predict results it has not seen?
   Walk-forward: every confirmed match from the seventh month on is predicted from what was
   known at the start of its month, then scored by Brier score and log loss (lower is better
   for both) and by how often the favourite won. To predict from two win rates, their
   difference goes through a logistic curve whose one slope is fitted on the tuning seeds, so
   the baselines are tuned exactly as much as the models are. A coin flip (Brier 0.25, log
   loss 0.693) is the floor.

Tuning (Glicko's tau, the point rating's prior, both display rules, the baselines' slopes) is
done on seeds 101, 202 and 303 only, and the numbers are reported on others.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from data.pipelines.synthetic import performance
from ml.rating import glicko2, points
from ml.rating.matches import _as_date, _month, collect, history

GLICKO = "Glicko-2 (match results)"
POINTS = "point rating (every point)"
WIN_RATE = "baseline: match win rate"
POINT_RATE = "baseline: point win rate"
COIN = "baseline: coin flip"

# Display rules, chosen on the tuning seeds (see ml/README.md, "Table tennis rating").
# Glicko-2: shown when the rating deviation is at or below this.
SHOW_MAX_RD = 130.0
# Point rating: shown when the range of point share against an average player (two standard
# errors either side) is at most this wide.
SHOW_MAX_POINT_RANGE = 0.07
# Logistic slopes that turn a difference in win rate or point rate into a win probability.
WIN_RATE_SLOPE = 3.0
POINT_RATE_SLOPE = 20.0
# Months of matches before the first prediction is scored, so every method has some history.
WARMUP_MONTHS = 6


# ---------------------------------------------------------------------------
# Small statistics, standard library only
# ---------------------------------------------------------------------------


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


def _logistic(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


@dataclass
class PredictionScore:
    n: int = 0
    brier: float = 0.0
    log_loss: float = 0.0
    favourite_won: float = 0.0
    # (lower edge of the favourite's predicted chance, matches, mean predicted, share that won)
    calibration: list[tuple[float, int, float, float]] = field(default_factory=list)


def score_predictions(pairs: list[tuple[float, int]]) -> PredictionScore:
    """`pairs` is (predicted chance that side A wins, 1 if side A won)."""
    if not pairs:
        return PredictionScore()
    eps = 1e-9
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    log_loss = -sum(
        y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in pairs
    ) / len(pairs)
    decided = [(p, y) for p, y in pairs if p != 0.5]
    favourite = (
        sum(1 for p, y in decided if (p > 0.5) == (y == 1)) / len(decided) if decided else 0.0
    )
    bins: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p, y in pairs:
        # Fold onto the favourite's side so each bin reads "predicted x%, happened y%".
        q, z = (p, y) if p >= 0.5 else (1 - p, 1 - y)
        bins[min(int((q - 0.5) / 0.1), 4)].append((q, z))
    calibration = [
        (0.5 + 0.1 * b, len(v), sum(q for q, _ in v) / len(v), sum(z for _, z in v) / len(v))
        for b, v in sorted(bins.items())
    ]
    return PredictionScore(len(pairs), brier, log_loss, favourite, calibration)


# ---------------------------------------------------------------------------
# The evaluation
# ---------------------------------------------------------------------------


@dataclass
class GenderRanking:
    gender: str
    players: int  # with at least one rated match
    rho: dict[str, float | None]  # method -> Spearman with hidden ability
    shown: dict[str, int]  # model -> players its display rule would show
    rho_shown: dict[str, float | None]
    # Point rating only: of the players shown, how many have their true chance of winning a
    # point against an average opponent inside the shown range.
    covered: int = 0


@dataclass
class RatingReport:
    data_dir: str
    reference: date
    players: int
    matches: int
    rated_matches: int
    unconfirmed: int
    rankings: list[GenderRanking]
    predictions: dict[str, PredictionScore]


def _load(data_dir: Path) -> tuple[list[dict], dict[str, dict], dict]:
    rows = json.loads((data_dir / "performance_entries.json").read_text(encoding="utf-8"))
    players = json.loads((data_dir / "players.json").read_text(encoding="utf-8"))
    truth = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    return rows, {str(p["id"]): p for p in players}, truth


def table_tennis_rows(rows: list[dict]) -> list[dict]:
    return [
        r
        for r in rows
        if r.get("sport") == "table_tennis" and "sets_won" in (r.get("metrics") or {})
    ]


def _rates_before(rows: list[dict], when: date | None) -> dict[str, tuple[float, float]]:
    """Each player's (match win rate, point win rate) from rows before `when`."""
    acc: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        if when is not None and _as_date(r["period_start"]) >= when:
            continue
        m = r["metrics"]
        a = acc[str(r["player_id"])]
        a[0] += m["sets_won"] > m["sets_lost"]
        a[1] += 1
        a[2] += m["points_won"]
        a[3] += m["points_won"] + m["points_lost"]
    return {p: (a[0] / a[1], a[2] / a[3] if a[3] else 0.5) for p, a in acc.items() if a[1]}


def evaluate(
    data_dir: Path,
    *,
    tau: float = glicko2.TAU,
    prior_sd: float = points.PRIOR_SD,
    show_max_rd: float = SHOW_MAX_RD,
    show_max_point_range: float = SHOW_MAX_POINT_RANGE,
    win_rate_slope: float = WIN_RATE_SLOPE,
    point_rate_slope: float = POINT_RATE_SLOPE,
    use_outsiders: bool = True,
) -> RatingReport:
    data_dir = Path(data_dir)
    rows, players, truth = _load(data_dir)
    ability: dict[str, float] = truth.get("table_tennis_ability", {})
    tt_rows = table_tennis_rows(rows)
    rows_by_id = {str(r["id"]): r for r in tt_rows}
    reference = max(_as_date(r["period_start"]) for r in rows)

    matches = collect(tt_rows)
    confirmed = [m for m in matches if m.confirmed]
    glicko_final = history(matches, until=reference, tau=tau).current
    gender_of = {pid: p["sex"] for pid, p in players.items()}

    def point_fit(before: date | None) -> dict:
        registered = [m for m in matches if before is None or m.played_on < before]
        evidence = points.point_matches(registered, rows_by_id)
        if use_outsiders:
            evidence += points.outsider_matches(tt_rows, gender_of, before=before)
        return points.fit(evidence, prior_sd)

    points_final = point_fit(None)
    rates = _rates_before(tt_rows, None)

    # 1. Ranking, within each gender, on players every method can score.
    by_gender: dict[str, list[str]] = defaultdict(list)
    for pid in ability:
        if pid in glicko_final and pid in points_final and pid in rates:
            by_gender[players[pid]["sex"]].append(pid)
    rankings = []
    for gender, pids in sorted(by_gender.items()):
        scores = {
            GLICKO: {p: glicko_final[p].rating for p in pids},
            POINTS: {p: points_final[p].theta for p in pids},
            WIN_RATE: {p: rates[p][0] for p in pids},
            POINT_RATE: {p: rates[p][1] for p in pids},
        }
        shown = {
            GLICKO: [p for p in pids if glicko_final[p].rd <= show_max_rd],
            POINTS: [
                p
                for p in pids
                if points_final[p].point_range[1] - points_final[p].point_range[0]
                <= show_max_point_range
            ],
        }

        def rho(method: str, who: list[str]) -> float | None:
            return spearman([scores[method][p] for p in who], [ability[p] for p in who])

        # The truth the range should contain: the generator's own chance of winning a point
        # against a player of this gender's average ability.
        average = sum(ability[p] for p in pids) / len(pids)
        covered = 0
        for p in shown[POINTS]:
            low, high = points_final[p].point_range
            covered += low <= performance._point_chance(ability[p], average) <= high

        rankings.append(
            GenderRanking(
                gender=gender,
                players=len(pids),
                rho={m: rho(m, pids) for m in scores},
                shown={m: len(v) for m, v in shown.items()},
                rho_shown={m: rho(m, v) for m, v in shown.items()},
                covered=covered,
            )
        )

    # 2. Walk-forward prediction of confirmed matches.
    hist = history(matches, until=reference, tau=tau)
    start = hist.first_month
    pairs: dict[str, list[tuple[float, int]]] = defaultdict(list)
    per_month: dict[date, tuple[dict, dict]] = {}
    for m in confirmed:
        month = _month(m.played_on)
        if (month.year - start.year) * 12 + month.month - start.month < WARMUP_MONTHS:
            continue
        if month not in per_month:
            per_month[month] = (point_fit(month), _rates_before(tt_rows, month))
        strengths, before = per_month[month]
        # Side A is the lower id, so which side won is not given away by the order.
        a, b = sorted((m.winner, m.loser))
        y = 1 if a == m.winner else 0
        ra = hist.before(a, m.played_on) or glicko2.Rating()
        rb = hist.before(b, m.played_on) or glicko2.Rating()
        pairs[GLICKO].append((glicko2.win_probability(ra, rb), y))
        pairs[POINTS].append(
            (points.win_probability(strengths.get(a), strengths.get(b), m.best_of), y)
        )
        wa, pa = before.get(a, (0.5, 0.5))
        wb, pb = before.get(b, (0.5, 0.5))
        pairs[WIN_RATE].append((_logistic(win_rate_slope * (wa - wb)), y))
        pairs[POINT_RATE].append((_logistic(point_rate_slope * (pa - pb)), y))
        pairs[COIN].append((0.5, y))

    return RatingReport(
        data_dir=str(data_dir),
        reference=reference,
        players=len(ability),
        matches=len(matches),
        rated_matches=len(confirmed),
        unconfirmed=len(matches) - len(confirmed),
        rankings=rankings,
        predictions={k: score_predictions(v) for k, v in pairs.items()},
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

RANKED = [GLICKO, POINTS, WIN_RATE, POINT_RATE]
MODELS = [GLICKO, POINTS]


def _f(x: float | None) -> str:
    return "  n/a" if x is None else f"{x:5.3f}"


def render(report: RatingReport) -> str:
    out = [
        f"Table tennis rating, {report.data_dir}",
        f"{report.players} players; {report.matches} matches between registered players, "
        f"{report.rated_matches} confirmed and rated, {report.unconfirmed} self-submitted and "
        "unconfirmed (not rated)",
        "",
        "Ranking: Spearman correlation with hidden ability, within gender",
        f"{'method':30}" + "".join(f"{g.gender + f' ({g.players})':>16}" for g in report.rankings),
    ]
    for method in RANKED:
        out.append(f"{method:30}" + "".join(f"{_f(g.rho[method]):>16}" for g in report.rankings))
    out.append("")
    out.append("Display rule: players shown, and Spearman among them")
    for method in MODELS:
        out.append(
            f"{method:30}"
            + "".join(
                f"{f'{g.shown[method]} at {_f(g.rho_shown[method]).strip()}':>16}"
                for g in report.rankings
            )
        )
    out.append(
        f"{'point rating, range holds truth':30}"
        + "".join(f"{f'{g.covered} of {g.shown[POINTS]}':>16}" for g in report.rankings)
    )
    out += [
        "",
        f"Prediction: walk-forward, confirmed matches after a {WARMUP_MONTHS}-month warm-up",
        f"{'method':30}{'matches':>9}{'Brier':>8}{'log loss':>10}{'favourite won':>15}",
    ]
    for name, s in report.predictions.items():
        out.append(
            f"{name:30}{s.n:>9}{s.brier:>8.4f}{s.log_loss:>10.4f}{s.favourite_won:>15.3f}"
        )
    for name in MODELS:
        s = report.predictions.get(name)
        if s and s.calibration:
            out += ["", f"Calibration, {name}: favourite's predicted chance vs how often it won"]
            for lo, n, pred, real in s.calibration:
                out.append(
                    f"  {lo:.0%} to {lo + 0.1:.0%}  {n:>5} matches  predicted {pred:.3f}  won {real:.3f}"
                )
    return "\n".join(out)
