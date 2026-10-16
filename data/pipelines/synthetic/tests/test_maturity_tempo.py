"""Maturity timing (players.draw_maturity_tempo).

Two properties the evaluation depends on:

- Isolation. Timing draws from its own stream, so switching it on changes growth timing and
  nothing else. Every before/after comparison in ml/README.md leans on this.
- A complete answer key. No child who was not planted is as late as a planted late bloomer,
  so a detector that finds a late maturer is never scored as wrong for it.
"""

from __future__ import annotations

import statistics
from dataclasses import replace

import pytest

from data.pipelines.synthetic.config import GeneratorConfig
from data.pipelines.synthetic.dataset import build_dataset


@pytest.fixture(scope="module")
def pair():
    on = GeneratorConfig(seed=4711)
    off = replace(on, measurements=replace(on.measurements, maturity_tempo_sd_years=0.0))
    return build_dataset(on), build_dataset(off), on


def test_timing_changes_nothing_but_timing(pair):
    on, off, _ = pair

    def identity(ds):
        return [
            (str(p.id), p.player.full_name, p.player.date_of_birth, round(p.adult_height_cm, 6))
            for p in ds.profiles
        ]

    assert identity(on) == identity(off)
    assert on.ground_truth["cases"] == off.ground_truth["cases"]
    # ...but the growth itself moved.
    assert [round(m.value, 3) for m in on.measurements] != [round(m.value, 3) for m in off.measurements]


def test_off_is_the_old_population(pair):
    _, off, _ = pair
    unplanted = [p for p in off.profiles if not p.is_planted_late_bloomer]
    assert all(p.maturity_offset_years == 0.0 for p in unplanted)


def test_no_unplanted_child_is_as_late_as_a_planted_late_bloomer(pair):
    on, _, config = pair
    late = config.planted.late_bloomer_offset_years[0]
    unplanted = [p.maturity_offset_years for p in on.profiles if not p.is_planted_late_bloomer]
    planted = [p.maturity_offset_years for p in on.profiles if p.is_planted_late_bloomer]
    assert max(unplanted) < late <= min(planted)
    # Early and late both occur, at about the configured spread (the late tail is cut at the
    # planted bound, which narrows it a little).
    assert min(unplanted) < -1.0 and max(unplanted) > 0.8
    assert 0.7 < statistics.pstdev(unplanted) < 1.0
