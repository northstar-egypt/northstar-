"""Tests for the late-bloomer backtest and the database export guard.

The backtest makes a claim about the past, so the test that matters is again the lookahead
one: what the system "said" on a cutoff date must not change when everything after that date
is rewritten. Only the outcome, which is judged afterwards on purpose, may move.
"""

from __future__ import annotations

import json
import shutil
from datetime import date

import pytest

from ml import backtest
from ml.export_db import REPO_ROOT, tracked_by_git


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    out_dir = tmp_path_factory.mktemp("backtest_dataset")
    ds = build_dataset(GeneratorConfig(seed=4242).scaled(160))
    write_ground_truth(ds.ground_truth, out_dir / "ground_truth.json")
    export_json(ds, out_dir)
    return out_dir


def test_as_of_drops_everything_after_the_cutoff(dataset):
    tables, _ = backtest.load_tables(dataset)
    cutoff = backtest.cutoffs_for(tables)[0]
    then = backtest.as_of(tables, cutoff)
    assert then["measurements"]
    assert all(date.fromisoformat(m["measured_at"][:10]) <= cutoff for m in then["measurements"])
    assert all(
        date.fromisoformat(e["period_start"][:10]) <= cutoff for e in then["performance_entries"]
    )


def test_what_the_system_said_cannot_depend_on_the_future(dataset, tmp_path):
    report = backtest.run(dataset)
    assert report.decisions
    cutoff = report.cutoffs[len(report.cutoffs) // 2]

    rewritten = tmp_path / "rewritten"
    shutil.copytree(dataset, rewritten)
    path = rewritten / "measurements.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        if date.fromisoformat(row["measured_at"][:10]) > cutoff and row["metric"] == "height_cm":
            row["value"] = float(row["value"]) + 30.0
    path.write_text(json.dumps(rows), encoding="utf-8")

    after = backtest.run(rewritten)
    said = lambda r: {  # noqa: E731
        d.player_id: (d.cutoff, d.flagged, round(d.height_z, 6), d.readings)
        for d in r.decisions
        if d.cutoff <= cutoff
    }
    assert said(report), "no decisions on or before the chosen cutoff"
    assert said(report) == said(after)


def test_decision_is_the_first_cutoff_in_the_size_cut(dataset):
    report = backtest.run(dataset)
    ids = [d.player_id for d in report.decisions]
    assert len(ids) == len(set(ids)), "a player can only be cut once"


def test_runs_without_an_answer_key(dataset, tmp_path):
    """Real data has no ground_truth.json. Nothing may assume one."""
    bare = tmp_path / "bare"
    shutil.copytree(dataset, bare)
    (bare / "ground_truth.json").unlink()
    report = backtest.run(bare)
    assert not report.has_answer_key
    assert all(d.planted_late_bloomer is None for d in report.decisions)
    text = backtest.render([report], "no key")
    assert "against the answer key" not in text
    assert "without an answer key" in text


def test_flagged_players_are_scored_against_the_detector_as_it_stood(dataset):
    report = backtest.run(dataset)
    for d in report.decisions:
        assert d.flagged == (d.not_flagged_because == "")


# ---------------------------------------------------------------------------
# The export guard. Real data must never be writable into a tracked path.
# ---------------------------------------------------------------------------


def test_export_refuses_tracked_paths_inside_the_repo():
    assert tracked_by_git(REPO_ROOT / "ml" / "real_export")
    assert tracked_by_git(REPO_ROOT / "docs")


def test_export_allows_the_ignored_out_directory():
    assert not tracked_by_git(REPO_ROOT / "out" / "db_export")


def test_export_allows_paths_outside_the_repo(tmp_path):
    assert not tracked_by_git(tmp_path / "export")
