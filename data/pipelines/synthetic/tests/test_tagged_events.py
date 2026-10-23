"""Synthetic tagged events (data/pipelines/synthetic/tagged_events.py).

The rule that matters: a match's events add up to its logged totals, by the sport module's own
`counts`, so the tagging screen's "tagged against logged" agrees on seeded matches.
"""

from __future__ import annotations

from collections import Counter

import pytest

from data.pipelines.synthetic import tagged_events

MATCH = {
    "minutes_played": 90, "shots": 4, "shots_on_target": 2, "goals": 1, "assists": 1,
    "key_passes": 3, "passes_attempted": 38, "passes_completed": 31, "tackles": 3,
    "distance_km": 10.1, "yellow_cards": 0, "red_cards": 0,
}


def _tallies(events: list[dict]) -> Counter:
    from app import sports

    kinds = sports.registry()["football"].events
    out: Counter = Counter()
    for e in events:
        for total in kinds[e["event_type"]].outcomes[e["outcome"]].counts:
            out[total] += 1
    return out


def test_events_add_up_to_the_logged_totals():
    events = tagged_events.events_for("entry-1", MATCH, "CM")
    tally = _tallies(events)
    for total in ("shots", "shots_on_target", "goals", "assists", "key_passes",
                  "passes_attempted", "passes_completed", "tackles"):
        assert tally[total] == MATCH[total], total


def test_the_same_record_always_gets_the_same_events():
    assert tagged_events.events_for("entry-1", MATCH, "ST") == tagged_events.events_for("entry-1", MATCH, "ST")
    assert tagged_events.events_for("entry-1", MATCH, "ST") != tagged_events.events_for("entry-2", MATCH, "ST")


def test_places_are_on_the_pitch_and_goals_come_from_close_in():
    events = tagged_events.events_for("entry-3", {**MATCH, "goals": 2, "shots_on_target": 3}, "ST")
    assert all(1 <= e["x"] <= 99 and 1 <= e["y"] <= 99 for e in events)
    assert all(e["x"] >= 83 for e in events if e["outcome"] == "goal")
    assert all(0 <= e["video_seconds"] <= 90 * 60 for e in events)
    assert [e["video_seconds"] for e in events] == sorted(e["video_seconds"] for e in events)


def test_a_match_not_played_has_no_events():
    assert tagged_events.events_for("entry-4", {**MATCH, "minutes_played": 0}, "CM") == []


@pytest.mark.parametrize("position, low, high", [("CB", 8, 60), ("ST", 45, 92)])
def test_ordinary_passes_sit_in_the_roles_zone(position, low, high):
    events = tagged_events.events_for("entry-5", MATCH, position)
    plain = [e for e in events if e["event_type"] == "pass" and e["outcome"] in ("complete", "incomplete")]
    assert plain and all(low <= e["x"] <= high for e in plain)
