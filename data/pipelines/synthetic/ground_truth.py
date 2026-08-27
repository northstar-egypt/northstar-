"""The answer key.

`ground_truth.json` is the deliverable the ML track's evaluation harness reads.
It is not documentation: it is the labelled set that turns the generated data
into something precision, recall and F1 can be computed against.

Two shapes are provided deliberately:

- the nested case records, which carry *why* a case is a case (how many years an
  age was understated, how large a late bloomer's deficit was at 14, which
  variations a duplicate cluster differs by). Useful for error analysis: "we miss
  the fraud cases understated by under two years" is a far more useful finding
  than a single F1 number.
- flat label sets keyed by player id, which is what a scoring function actually
  wants. `label_vectors()` turns those into aligned y_true arrays for any list of
  player ids.

Everything not listed is a true negative. That is stated explicitly in the file
rather than left as an assumption, because the difference between "not a
positive" and "unlabelled" is the difference between a real recall number and a
meaningless one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .planted import PlantedCases

GROUND_TRUTH_VERSION = "1.0.0"

DETECTORS = ("late_bloomer", "fraud", "duplicate")


def build(
    cases: PlantedCases,
    *,
    seed: int,
    counts: dict,
    all_player_ids: list[str],
) -> dict:
    late_bloomer_ids = sorted({c.player_id for c in cases.late_bloomers})
    fraud_ids = sorted({c.player_id for c in cases.fraud})
    duplicate_ids = sorted(
        {pid for cluster in cases.duplicates for pid in cluster.player_ids}
    )

    return {
        "version": GROUND_TRUTH_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": seed,
        "counts": counts,
        "labelling": {
            "closed_world": True,
            "note": (
                "Every player id in the dataset that does not appear in a label "
                "set below is a true negative for that detector. The label sets "
                "are complete, not a sample."
            ),
            "detectors": list(DETECTORS),
        },
        "population": {"player_ids": sorted(all_player_ids)},
        "labels": {
            "late_bloomer": late_bloomer_ids,
            "fraud": fraud_ids,
            "duplicate": duplicate_ids,
        },
        "flagged_performance_entry_ids": sorted(
            {
                eid
                for c in cases.fraud
                for eid in c.detail.get("performance_entry_ids", [])
            }
        ),
        "cases": {
            "late_bloomers": [c.to_dict() for c in cases.late_bloomers],
            "fraud": [c.to_dict() for c in cases.fraud],
            "duplicates": [c.to_dict() for c in cases.duplicates],
        },
    }


def write(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def label_vectors(payload: dict, player_ids: list[str]) -> dict[str, list[int]]:
    """Aligned y_true vectors, one per detector.

        gt = ground_truth.load("data/pipelines/synthetic/out/ground_truth.json")
        y_true = label_vectors(gt, player_ids)["fraud"]
        precision_recall_fscore_support(y_true, y_pred, average="binary")

    Kept here rather than in ml/ so there is exactly one definition of what the
    labels mean, owned by the code that created them.
    """
    labels = payload["labels"]
    return {
        detector: [1 if pid in set(labels[detector]) else 0 for pid in player_ids]
        for detector in DETECTORS
    }


def duplicate_pairs(payload: dict) -> list[tuple[str, str]]:
    """Positive pairs for a duplicate detector scored pairwise rather than per player."""
    pairs = []
    for cluster in payload["cases"]["duplicates"]:
        ids = cluster["player_ids"]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.append((ids[i], ids[j]))
    return pairs
