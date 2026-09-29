"""Relative-age audit: does a model treat players differently by birth quarter?

Why this exists
---------------
The relative age effect is the best documented bias in youth talent selection. Players born
early in the selection year are older, bigger and more mature than team-mates born late in
the same year, and selection follows that advantage rather than lasting ability (Cobley et
al. 2009, Romann et al. 2021). It turns up inside the prediction studies too, and the most
recent review of machine learning for talent identification asks that every model be
audited by birth quarter as a minimum fairness check (Tang et al. 2026). This module is that
audit for the NorthStar detectors and forecasts.

Birth quarter is taken from the calendar month of the **stated** date of birth, because
youth age groups here run on the calendar year, the same cutoff FIFA youth competitions
use, and the stated date is all a deployment has. Q1 is January to March, the oldest
quarter of any age group; Q4 is October to December, the youngest.

What it can and cannot say
--------------------------
The synthetic generator draws birth dates uniformly, so the population carries no planted
relative age effect of its own. That is the right setting for this question: any difference
between quarters in who gets flagged, or how well a player is forecast, comes from the model
and not from the data. It does not test how the models would behave on a real academy,
where Q1 players are over-represented to begin with.

A single dataset has a few positives per quarter, so per-quarter recall from one seed is
close to noise. The false-positive rate among players who are *not* positive is the better
measure, because there are about fifty of them per quarter, and it is also the fairness
question that matters: is a player without the condition more likely to be flagged because
of when in the year they were born? The seed sweep pools counts across datasets, and the
chi-square test below is run on those pooled counts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from ml.evaluation.metrics import Score, score_ids, wilson_interval

QUARTERS = ("Q1", "Q2", "Q3", "Q4")
QUARTER_LABELS = {
    "Q1": "Q1 Jan-Mar, oldest",
    "Q2": "Q2 Apr-Jun",
    "Q3": "Q3 Jul-Sep",
    "Q4": "Q4 Oct-Dec, youngest",
}


def birth_quarter(dob: date | str | None) -> str | None:
    if dob is None:
        return None
    month = dob.month if isinstance(dob, date) else int(str(dob)[5:7])
    return QUARTERS[(month - 1) // 3]


def quarters_of(players: list[dict]) -> dict[str, str]:
    """{player_id: quarter} for every player with a stated date of birth."""
    out = {}
    for p in players:
        quarter = birth_quarter(p.get("date_of_birth"))
        if quarter is not None:
            out[p["id"]] = quarter
    return out


def chi_square_3df_p(statistic: float) -> float:
    """Upper tail of a chi-square with 3 degrees of freedom, in closed form.

    Four quarters against flagged or not is a 2 by 4 table, so 3 degrees of freedom, and for
    an odd number of degrees of freedom the tail has an exact expression. It keeps the module
    on the standard library like the rest of `ml/evaluation`.
    """
    if statistic <= 0:
        return 1.0
    root = math.sqrt(statistic)
    return math.erfc(root / math.sqrt(2)) + math.sqrt(2 * statistic / math.pi) * math.exp(
        -statistic / 2
    )


def chi_square_independence(flagged: list[int], totals: list[int]) -> tuple[float, float]:
    """Chi-square test that the flag rate is the same in every group. Returns (statistic, p).

    Groups with no members are left out. With fewer than two groups left, or nobody flagged
    or everybody flagged, there is nothing to compare and the result is (0, 1).
    """
    pairs = [(f, t) for f, t in zip(flagged, totals) if t > 0]
    grand_flagged = sum(f for f, _ in pairs)
    grand_total = sum(t for _, t in pairs)
    if len(pairs) < 2 or grand_flagged in (0, grand_total):
        return 0.0, 1.0
    rate = grand_flagged / grand_total
    statistic = 0.0
    for f, t in pairs:
        expected_yes = t * rate
        expected_no = t * (1 - rate)
        statistic += (f - expected_yes) ** 2 / expected_yes
        statistic += ((t - f) - expected_no) ** 2 / expected_no
    if len(pairs) != 4:
        # The closed form is for 3 degrees of freedom only, so an empty quarter gets no
        # p-value rather than a wrong one. With ~50 players per quarter it does not happen.
        return statistic, float("nan")
    return statistic, chi_square_3df_p(statistic)


@dataclass
class QuarterAudit:
    """One detector's confusion counts split by birth quarter."""

    detector: str
    by_quarter: dict[str, Score] = field(default_factory=dict)
    note: str = ""

    @property
    def false_positive_test(self) -> tuple[float, float]:
        """Is a negative player's chance of being flagged the same in every quarter?"""
        scores = [self.by_quarter[q] for q in QUARTERS]
        return chi_square_independence([s.fp for s in scores], [s.fp + s.tn for s in scores])

    def as_dict(self) -> dict:
        statistic, p = self.false_positive_test
        return {
            "detector": self.detector,
            "note": self.note,
            "by_quarter": {
                q: {
                    "population": s.population,
                    "positives": s.support,
                    "flagged": s.predicted,
                    "tp": s.tp,
                    "fp": s.fp,
                    "fn": s.fn,
                    "tn": s.tn,
                    "recall": round(s.recall, 4),
                    "recall_ci95": [round(v, 4) for v in s.recall_ci],
                    "false_positive_rate": round(false_positive_rate(s), 4),
                    "false_positive_rate_ci95": [
                        round(v, 4) for v in wilson_interval(s.fp, s.fp + s.tn)
                    ],
                }
                for q, s in self.by_quarter.items()
            },
            "false_positive_chi_square": round(statistic, 4),
            "false_positive_p_value": None if math.isnan(p) else round(p, 4),
        }


def false_positive_rate(score: Score) -> float:
    negatives = score.fp + score.tn
    return score.fp / negatives if negatives else 0.0


def audit(
    detector: str,
    predicted: set[str] | list[str],
    truth: set[str] | list[str],
    population: set[str] | list[str],
    quarters: dict[str, str],
    *,
    note: str = "",
) -> QuarterAudit:
    """Score one detector separately inside each birth quarter.

    Players in the population without a stated date of birth belong to no quarter and are
    left out, which is why the four quarters can sum to slightly less than the population.
    """
    population = set(population)
    result = QuarterAudit(detector=detector, note=note)
    for quarter in QUARTERS:
        members = {pid for pid in population if quarters.get(pid) == quarter}
        result.by_quarter[quarter] = score_ids(detector, predicted, truth, members)
    return result


def pool(audits: list[QuarterAudit]) -> QuarterAudit:
    """Add the counts of the same detector over several datasets.

    Summing counts, rather than averaging per-seed rates, weights each player equally and
    gives the chi-square test enough players per cell to mean something.
    """
    first = audits[0]
    pooled = QuarterAudit(detector=first.detector, note=first.note)
    for quarter in QUARTERS:
        scores = [a.by_quarter[quarter] for a in audits]
        pooled.by_quarter[quarter] = Score(
            detector=first.detector,
            tp=sum(s.tp for s in scores),
            fp=sum(s.fp for s in scores),
            fn=sum(s.fn for s in scores),
            tn=sum(s.tn for s in scores),
        )
    return pooled


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_WIDTH = 104
SIGNIFICANCE = 0.05


def render(audits: list[QuarterAudit], title: str) -> str:
    out = ["", title, "-" * _WIDTH]
    out.append(
        f"{'':24} {'players':>8} {'pos':>5} {'flagged':>8} {'recall':>7} "
        f"{'recall 95% CI':>15} {'false pos rate':>15} {'FPR 95% CI':>15}"
    )
    for item in audits:
        out.append(f"{item.detector}" + (f"   ({item.note})" if item.note else ""))
        for quarter in QUARTERS:
            s = item.by_quarter[quarter]
            r_lo, r_hi = s.recall_ci
            f_lo, f_hi = wilson_interval(s.fp, s.fp + s.tn)
            recall = f"{s.recall:>7.2f}" if s.support else f"{'-':>7}"
            recall_ci = f"{r_lo:.2f} to {r_hi:.2f}" if s.support else "-"
            out.append(
                f"  {QUARTER_LABELS[quarter]:22} {s.population:>8} {s.support:>5} "
                f"{s.predicted:>8} {recall} {recall_ci:>15} "
                f"{false_positive_rate(s):>15.3f} {f'{f_lo:.3f} to {f_hi:.3f}':>15}"
            )
        statistic, p = item.false_positive_test
        if math.isnan(p):
            out.append("  false positive rate: not tested, a quarter has no negative players")
            continue
        verdict = (
            "differs by quarter" if p < SIGNIFICANCE else "no detectable difference by quarter"
        )
        out.append(
            f"  false positive rate: chi-square {statistic:.2f}, 3 df, p = {p:.3f}, {verdict}"
        )
    return "\n".join(out)
