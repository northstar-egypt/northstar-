"""Run the detectors against the answer key and report.

This is the file that produces the numbers the project is graded on for the
detector deliverable. It loads a generated dataset, runs each detector, scores it
against `ground_truth.json`, and prints every score next to the baselines from
`ml/detectors/baselines.py` so no number is read without its context.

Three things it does on purpose:

  It reports subtype breakdowns. The fraud label covers two unrelated problems,
  one statistical and one arithmetic, and a single F1 over both is close to
  meaningless. The same applies to duplicates, where half the clusters have
  already been resolved by a human.

  It lists the misses. `false_negatives` on every score carries the ids that got
  away, and the report prints what the answer key says about them. "We miss the
  fraud cases understated by under two years" is a finding. "F1 was 0.74" is not.

  It can run over several seeds. One dataset gives one number, and with 14
  positives that number moves several points on the strength of a single case.
  `--seed-sweep` runs the same detectors over several generated datasets and
  reports the spread, which is the honest version of the headline figure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ml.detectors import baselines, duplicate, fraud, late_bloomer
from ml.detectors.features import FeatureSet
from ml.evaluation.metrics import Score, ScoreSet, score_ids


def load_ground_truth(data_dir: str | Path) -> dict:
    path = Path(data_dir) / "ground_truth.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No ground_truth.json in {data_dir}. Generate a dataset first:\n"
            f"  python -m data.pipelines.synthetic.generate --out {data_dir}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Report:
    data_dir: str
    seed: int
    population: int
    sections: list[ScoreSet] = field(default_factory=list)
    # Headline score per detector, pulled out so a sweep can aggregate them.
    headline: dict[str, Score] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "data_dir": self.data_dir,
            "seed": self.seed,
            "population": self.population,
            "headline": {k: v.as_dict() for k, v in self.headline.items()},
            "sections": [s.as_dict() for s in self.sections],
            "notes": self.notes,
        }


def evaluate(data_dir: str | Path) -> Report:
    """Run every detector and baseline against one generated dataset."""
    features = FeatureSet(data_dir)
    gt = load_ground_truth(data_dir)
    population = set(gt["population"]["player_ids"])
    labels = gt["labels"]
    cases = gt["cases"]

    report = Report(
        data_dir=str(data_dir), seed=gt.get("seed", -1), population=len(population)
    )

    if set(features.players) != population:
        report.notes.append(
            f"Population mismatch: {len(features.players)} players loaded, "
            f"{len(population)} in the answer key. Scores use the answer key."
        )

    # ------------------------------------------------------------------
    # Late bloomer
    # ------------------------------------------------------------------
    truth = set(labels["late_bloomer"])
    section = ScoreSet("Late bloomer")
    predicted = late_bloomer.detect(features)
    report.headline["late_bloomer"] = section.add(
        score_ids("late_bloomer v1", predicted, truth, population)
    )
    section.add(
        score_ids(
            "baseline: shortest for age",
            baselines.shortest_for_age(features, len(truth)),
            truth,
            population,
            note="the same number of players, picked by height alone",
        )
    )
    section.add(
        score_ids(
            "baseline: random at prevalence",
            baselines.random_at_prevalence(features, len(truth)),
            truth,
            population,
        )
    )
    section.add(
        score_ids(
            "baseline: flag everyone",
            baselines.all_positive(features),
            truth,
            population,
        )
    )
    report.sections.append(section)

    # ------------------------------------------------------------------
    # Fraud, combined and split by subtype
    # ------------------------------------------------------------------
    truth = set(labels["fraud"])
    section = ScoreSet("Fraud")
    predicted = fraud.detect(features)
    report.headline["fraud"] = section.add(
        score_ids("fraud v1 (both rules)", predicted, truth, population)
    )

    age_truth = {
        c["player_id"] for c in cases["fraud"] if c["fraud_type"] == "age_misrepresentation"
    }
    metric_truth = {
        c["player_id"]
        for c in cases["fraud"]
        if c["fraud_type"] == "implausible_self_reported_performance"
    }
    # Each subtype is scored on a population with the *other* subtype's cases
    # removed. Leaving them in would count a metric-fraud player that the age rule
    # correctly ignored as a false negative for age fraud, which it is not.
    section.add(
        score_ids(
            "  rule: age misrepresentation",
            fraud.detect_age_misrepresentation(features),
            age_truth,
            population - metric_truth,
            note=f"the hard subtype, {len(age_truth)} cases",
        )
    )
    section.add(
        score_ids(
            "  rule: impossible metrics",
            fraud.detect_impossible_metrics(features),
            metric_truth,
            population - age_truth,
            note=f"arithmetic, not a model, {len(metric_truth)} cases",
        )
    )
    section.add(
        score_ids(
            "baseline: any self-submitted row",
            baselines.any_self_submitted(features),
            truth,
            population,
        )
    )
    section.add(
        score_ids(
            "baseline: random at prevalence",
            baselines.random_at_prevalence(features, len(truth)),
            truth,
            population,
        )
    )
    report.sections.append(section)

    # Row-level score for the arithmetic rule, against the ids of the injected rows.
    flagged_rows = fraud.flagged_entry_ids(features)
    truth_rows = set(gt["flagged_performance_entry_ids"])
    all_rows = {
        e["id"] for e in features.raw["performance_entries"] if e.get("id")
    }
    row_section = ScoreSet("Fraud, scored per performance row")
    row_section.add(
        score_ids(
            "impossible-metric rows",
            flagged_rows,
            truth_rows,
            all_rows,
            note=f"{len(truth_rows)} injected rows among {len(all_rows)}",
        )
    )
    report.sections.append(row_section)

    # ------------------------------------------------------------------
    # Duplicate
    # ------------------------------------------------------------------
    truth = set(labels["duplicate"])
    section = ScoreSet("Duplicate identity")
    predicted = duplicate.detect(features)
    report.headline["duplicate"] = section.add(
        score_ids("duplicate v1", predicted, truth, population)
    )

    unresolved = {
        pid
        for cluster in cases["duplicates"]
        if not cluster["resolved"]
        for pid in cluster["player_ids"]
    }
    resolved = truth - unresolved
    # The clusters a human has not already merged are the ones worth finding.
    # Resolved cluster members are removed from the population as well as the
    # labels, so they cannot count as false positives here either.
    section.add(
        score_ids(
            "  unresolved clusters only",
            set(predicted) - resolved,
            unresolved,
            population - resolved,
            note=f"{len(unresolved)} records a human has not already merged",
        )
    )
    section.add(
        score_ids(
            "baseline: exact name match",
            baselines.exact_name_match(features),
            truth,
            population,
            note="no Arabic normalisation",
        )
    )
    section.add(
        score_ids(
            "control: read merged_into (cheating)",
            baselines.leakage_merged_into(features),
            truth,
            population,
            note="not a detector, see baselines.leakage_merged_into",
        )
    )
    section.add(
        score_ids(
            "baseline: random at prevalence",
            baselines.random_at_prevalence(features, len(truth)),
            truth,
            population,
        )
    )
    report.sections.append(section)

    return report


# ---------------------------------------------------------------------------
# Error analysis
# ---------------------------------------------------------------------------


def describe_misses(data_dir: str | Path, report: Report) -> list[str]:
    """What the answer key says about the cases each detector missed."""
    gt = load_ground_truth(data_dir)
    cases = gt["cases"]
    lines: list[str] = []

    lb_by_id = {c["player_id"]: c for c in cases["late_bloomers"]}
    misses = report.headline["late_bloomer"].false_negatives
    if misses:
        lines.append(f"Late bloomers missed ({len(misses)}):")
        for pid in misses:
            c = lb_by_id.get(pid, {})
            lines.append(
                f"  {pid[:8]}  offset {c.get('maturity_offset_years', '?')}y, "
                f"deficit {c.get('height_deficit_cm_at_14', '?')}cm at 14"
            )

    fraud_by_id = {c["player_id"]: c for c in cases["fraud"]}
    misses = report.headline["fraud"].false_negatives
    if misses:
        lines.append(f"Fraud cases missed ({len(misses)}):")
        for pid in misses:
            c = fraud_by_id.get(pid, {})
            detail = c.get("detail", {})
            understated = detail.get("years_understated")
            lines.append(
                f"  {pid[:8]}  {c.get('fraud_type', '?')}"
                + (f", understated by {understated}y" if understated else "")
            )

    dup_by_id = {
        pid: c for c in cases["duplicates"] for pid in c["player_ids"]
    }
    misses = report.headline["duplicate"].false_negatives
    if misses:
        lines.append(f"Duplicate records missed ({len(misses)}):")
        for pid in misses:
            c = dup_by_id.get(pid, {})
            lines.append(
                f"  {pid[:8]}  cluster {c.get('cluster_id', '?')}, "
                f"resolved={c.get('resolved', '?')}, "
                f"variations: {', '.join(c.get('variations', []))}"
            )

    return lines


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_HEADER = (
    f"{'':44} {'TP':>4} {'FP':>4} {'FN':>4} "
    f"{'prec':>7} {'recall':>7} {'F1':>7}  {'recall 95% CI':>16}"
)


def render(report: Report, *, misses: list[str] | None = None) -> str:
    out: list[str] = []
    out.append("=" * 104)
    out.append(
        f"Detector evaluation, seed {report.seed}, {report.population} players"
    )
    out.append(f"dataset: {report.data_dir}")
    out.append("=" * 104)

    for section in report.sections:
        support = section.scores[0].support if section.scores else 0
        population = section.scores[0].population if section.scores else 0
        out.append("")
        out.append(
            f"{section.title}  ({support} positives in {population}, "
            f"prevalence {support / population:.1%})"
            if population
            else section.title
        )
        out.append("-" * 104)
        out.append(_HEADER)
        for s in section.scores:
            lo, hi = s.recall_ci
            label = s.detector[:43]
            out.append(
                f"{label:44} {s.tp:>4} {s.fp:>4} {s.fn:>4} "
                f"{s.precision:>7.3f} {s.recall:>7.3f} {s.f1:>7.3f}  "
                f"{f'{lo:.2f} to {hi:.2f}':>16}"
            )
            if s.note:
                out.append(f"{'':44} {s.note}")

    if report.notes:
        out.append("")
        for note in report.notes:
            out.append(f"NOTE: {note}")

    if misses:
        out.append("")
        out.append("Error analysis")
        out.append("-" * 104)
        out.extend(misses)

    return "\n".join(out)


def render_sweep(reports: list[Report]) -> str:
    """Headline F1 per detector across several seeds, with the spread."""
    out: list[str] = []
    out.append("")
    out.append("=" * 104)
    out.append(f"Seed sweep over {len(reports)} datasets")
    out.append("=" * 104)
    out.append(
        f"{'detector':24} {'seeds':>8}  "
        + "  ".join(f"{r.seed:>8}" for r in reports)
        + f"  {'mean':>8} {'min':>8} {'max':>8}"
    )
    out.append("-" * 104)
    for name in ("late_bloomer", "fraud", "duplicate"):
        f1s = [r.headline[name].f1 for r in reports if name in r.headline]
        if not f1s:
            continue
        out.append(
            f"{name:24} {'F1':>8}  "
            + "  ".join(f"{v:>8.3f}" for v in f1s)
            + f"  {sum(f1s) / len(f1s):>8.3f} {min(f1s):>8.3f} {max(f1s):>8.3f}"
        )
    return "\n".join(out)
