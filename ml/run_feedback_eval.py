"""Do reviewers' decisions make the next flags better? (ml/feedback.py)

    python -m ml.run_feedback_eval

Generates the calibration seeds (101, 202, 303) and the reported seeds (20260827, 7, 99, 404,
555), simulates reviewers deciding the candidates raised on the calibration seeds, fits the
learner on those decisions, and scores it on the reported seeds against the v1 rules. Every
setting was fixed before the first run; the net level is chosen on the calibration seeds by
leaving one out in turn. Takes a few minutes, most of it generating the datasets.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ml import feedback
from ml.detectors.features import FeatureSet
from ml.evaluation.harness import load_ground_truth
from ml.run_eval import _generate

CALIBRATION = (101, 202, 303)
REPORTED = (20260827, 7, 99, 404, 555)
WRONG_SHARE = 0.10
NOISE_DRAWS = 5
SHARES = (0.25, 0.5, 1.0)


@dataclass
class Seed:
    seed: int
    features: FeatureSet
    truth: dict[str, set[str]] = field(default_factory=dict)
    population: dict[str, set[str]] = field(default_factory=dict)


def load(seed: int, out_dir: Path) -> Seed:
    _generate(seed, out_dir)
    features = FeatureSet(out_dir)
    gt = load_ground_truth(out_dir)
    population = set(gt["population"]["player_ids"])
    cases = gt["cases"]["fraud"]
    by_type = {}
    for case in cases:
        by_type.setdefault(case["fraud_type"], set()).add(case["player_id"])
    age = by_type.get("age_misrepresentation", set())
    others = set().union(*(ids for kind, ids in by_type.items() if kind != "age_misrepresentation"))
    return Seed(
        seed, features,
        truth={"late_bloomer": set(gt["labels"]["late_bloomer"]), "age_fraud": age},
        # As in ml/evaluation/harness.py: age fraud is scored without the other fraud subtypes'
        # cases, which the age rule is right to ignore.
        population={"late_bloomer": population, "age_fraud": population - others},
    )


def raised(s: Seed, detector: str, level: int) -> set[str]:
    return feedback.candidates(s.features, detector, level) & s.population[detector]


@dataclass
class Tally:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    reviewed: int = 0
    f1s: list[float] = field(default_factory=list)

    def add(self, predicted: set[str], truth: set[str], reviewed: int) -> None:
        tp, fp, fn = len(predicted & truth), len(predicted - truth), len(truth - predicted)
        self.tp, self.fp, self.fn, self.reviewed = (
            self.tp + tp, self.fp + fp, self.fn + fn, self.reviewed + reviewed)
        self.f1s.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)

    def row(self, label: str, seeds: int) -> str:
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0
        return (
            f"{label:46} {np.mean(self.f1s):6.3f}  {precision:6.3f}  {recall:6.3f}  "
            f"{self.tp:4}  {self.fp:4}  {self.fn:4}  {self.reviewed / seeds:7.1f}"
        )


def decisions_on(seeds: list[Seed], detector: str, level: int, *, wrong: float = 0.0,
                 share: float = 1.0, rng_seed: int = 0) -> feedback.Decisions:
    rng = np.random.default_rng(rng_seed)
    out = feedback.Decisions([], [])
    for s in seeds:
        ids = sorted(raised(s, detector, level))
        if share < 1.0:
            ids = [i for i in ids if rng.random() < share]
        out = out + feedback.decide(s.features, set(ids), s.truth[detector], wrong=wrong, rng=rng)
    return out


def choose_level(calibration: list[Seed], detector: str) -> tuple[int, list[str]]:
    """The net level with the best mean F1 when each calibration seed is scored by a learner
    fitted on the other two. Ties go to the narrower net, which means less to review."""
    lines, best = [], (-1.0, 0)
    for level in range(len(feedback.NET_LEVELS[detector])):
        f1s = []
        for held in calibration:
            rest = [s for s in calibration if s is not held]
            learner = feedback.Learner(decisions_on(rest, detector, level))
            kept = learner.keep(held.features, raised(held, detector, level))
            truth = held.truth[detector]
            tp, fp, fn = len(kept & truth), len(kept - truth), len(truth - kept)
            f1s.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
        mean = float(np.mean(f1s))
        lines.append(f"  level {level}: leave-one-out F1 {mean:.3f} ({', '.join(f'{f:.3f}' for f in f1s)})")
        if mean > best[0] + 1e-9:
            best = (mean, level)
    return best[1], lines


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="northstar-feedback-") as tmp:
        seeds = {}
        for seed in (*CALIBRATION, *REPORTED):
            print(f"generating seed {seed} ...", file=sys.stderr)
            seeds[seed] = load(seed, Path(tmp) / str(seed))
    calibration = [seeds[s] for s in CALIBRATION]
    reported = [seeds[s] for s in REPORTED]
    n = len(reported)

    for detector in feedback.DETECTORS:
        level, lines = choose_level(calibration, detector)
        print(f"\n=== {detector} ===")
        print("net level, chosen on the calibration seeds only:")
        print("\n".join(lines))
        print(f"  chosen: level {level}")
        decided = {lv: len(decisions_on(calibration, detector, lv)) for lv in {0, level}}
        print("decisions the learner is fitted on (3 calibration seeds): "
              + ", ".join(f"level {lv}: {k}" for lv, k in sorted(decided.items())))

        print(f"\nreported seeds {', '.join(map(str, REPORTED))}")
        print(f"{'':46} {'F1':>6}  {'prec':>6}  {'recall':>6}  {'TP':>4}  {'FP':>4}  {'FN':>4}  "
              f"{'review/seed':>7}")

        def run(label, lvl, learner=None, detector=detector):
            tally = Tally()
            for s in reported:
                ids = raised(s, detector, lvl)
                kept = learner.keep(s.features, ids) if learner else ids
                tally.add(kept, s.truth[detector], len(ids))
            print(tally.row(label, n))

        run("v1 rule (level 0), no learner", 0)
        if level:
            run(f"wider net (level {level}), no learner", level)
        for lvl, name in ((0, "filter on v1 flags"), (level, f"wider net (level {level})")):
            if name.startswith("wider") and level == 0:
                continue
            learner = feedback.Learner(decisions_on(calibration, detector, lvl))
            run(f"{name} + learner, perfect reviewer", lvl, learner)
            # Which decisions go wrong is random, and with a few dozen decisions it moves the
            # result, so the reviewer who errs is drawn NOISE_DRAWS times. Added after the first
            # run, which showed one draw beating the perfect reviewer; nothing else changed.
            f1s = []
            for draw in range(NOISE_DRAWS):
                learner = feedback.Learner(
                    decisions_on(calibration, detector, lvl, wrong=WRONG_SHARE, rng_seed=draw))
                tally = Tally()
                for s in reported:
                    ids = raised(s, detector, lvl)
                    tally.add(learner.keep(s.features, ids), s.truth[detector], len(ids))
                f1s.append(float(np.mean(tally.f1s)))
            print(f"{name + f' + learner, {WRONG_SHARE:.0%} wrong':46} {np.mean(f1s):6.3f}  "
                  f"mean of {NOISE_DRAWS} draws, range {min(f1s):.3f} to {max(f1s):.3f}")

        print("\nhow many decisions it takes (perfect reviewer, chosen level):")
        for share in SHARES:
            learner = feedback.Learner(decisions_on(calibration, detector, level, share=share))
            run(f"  {share:.0%} of calibration decisions ({learner.n})", level, learner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
