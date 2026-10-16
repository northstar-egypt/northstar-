"""Performance evidence in the age-fraud rule (features.output_z, fraud.detect_age_misrepresentation).

What these pin, because a reviewer cannot check it by eye:

- Output is read against the role first. A striker shoots more than a centre back for reasons
  that have nothing to do with age, so a typical striker is not "dominant".
- Rows that cannot be true, and players with too little playing time, contribute nothing.
- An accusation needs two lines of evidence. An early maturer, big and finished growing but
  playing like his age group, is not accused; that is the false accusation this change exists
  to remove. A small child who outplays his age group is never accused either: being small
  and good is a late bloomer or a talent, not a cheat.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from ml.detectors import fraud
from ml.detectors.features import FeatureSet, PlayerFeatures

TODAY = date(2026, 6, 1)


def _player(pid, position, sport="football", age=14.0):
    return {
        "id": pid,
        "primary_sport": sport,
        "position": position,
        "sex": "male",
        "date_of_birth": (TODAY - timedelta(days=int(age * 365.25))).isoformat(),
    }


def _football_rows(pid, shots_per_90, key_passes_per_90, matches=10, minutes=90):
    share = minutes / 90
    return [
        {
            "id": f"{pid}-{i}",
            "player_id": pid,
            "sport": "football",
            "schema_ref": "football.match.v1",
            "period_start": TODAY.isoformat(),
            "metrics": {
                "minutes_played": minutes,
                "shots": round(shots_per_90 * share),
                "shots_on_target": 0,
                "goals": 0,
                "key_passes": round(key_passes_per_90 * share),
                "passes_attempted": 30,
                "passes_completed": 20,
            },
        }
        for i in range(matches)
    ]


def _population(extra_players=(), extra_rows=()):
    """Six ordinary centre backs and six ordinary strikers, all recorded as 14."""
    players, rows = [], []
    for i in range(6):
        players.append(_player(f"cb{i}", "CB"))
        rows += _football_rows(f"cb{i}", shots_per_90=1 + i % 2, key_passes_per_90=1)
        players.append(_player(f"st{i}", "ST"))
        rows += _football_rows(f"st{i}", shots_per_90=3 + i % 2, key_passes_per_90=1)
    players += list(extra_players)
    rows += list(extra_rows)
    return FeatureSet(
        ".",
        raw={
            "players": players,
            "measurements": [],
            "performance_entries": rows,
            "organizations": [],
            "affiliations": [],
        },
    )


def test_a_typical_striker_is_typical_for_his_role():
    fs = _population()
    for pid in ("cb0", "st0"):
        assert abs(fs.players[pid].output_index) < 0.3


def test_a_striker_doing_twice_the_work_stands_out_against_his_age_group():
    fs = _population(
        [_player("star", "ST")], _football_rows("star", shots_per_90=7, key_passes_per_90=3)
    )
    assert fs.players["star"].output_z > 2.0


def test_rows_that_cannot_be_true_do_not_count_toward_output():
    impossible = _football_rows("cheat", shots_per_90=3, key_passes_per_90=1)
    for row in impossible[:3]:
        row["metrics"].update(goals=9, shots=1, shots_on_target=1, key_passes=20)
    with_rows = _population([_player("cheat", "ST")], impossible)
    clean = _population(
        [_player("cheat", "ST")], _football_rows("cheat", shots_per_90=3, key_passes_per_90=1)[3:]
    )
    assert with_rows.players["cheat"].output_index == clean.players["cheat"].output_index


def test_too_little_playing_time_gives_no_output():
    fs = _population(
        [_player("sub", "ST")],
        _football_rows("sub", shots_per_90=9, key_passes_per_90=3, matches=4, minutes=20),
    )
    assert fs.players["sub"].output_index is None
    assert fs.players["sub"].output_z is None


def test_table_tennis_output_is_read_per_set_with_errors_counting_against():
    def rows(pid, service_winners, unforced_errors):
        return [
            {
                "id": f"{pid}-{i}",
                "player_id": pid,
                "sport": "table_tennis",
                "schema_ref": "table_tennis.match.v1",
                "period_start": TODAY.isoformat(),
                "metrics": {
                    "best_of": 5,
                    "sets_won": 3,
                    "sets_lost": 1,
                    "points_won": 44,
                    "points_lost": 30,
                    "service_winners": service_winners,
                    "unforced_errors": unforced_errors,
                },
            }
            for i in range(8)
        ]

    players = [_player(f"tt{i}", "attacker", sport="table_tennis") for i in range(6)]
    entries = [r for i in range(6) for r in rows(f"tt{i}", 2 + i % 2, 8)]
    players.append(_player("clean", "attacker", sport="table_tennis"))
    entries += rows("clean", 2, 2)  # same service, far fewer errors
    fs = FeatureSet(
        ".",
        raw={
            "players": players,
            "measurements": [],
            "performance_entries": entries,
            "organizations": [],
            "affiliations": [],
        },
    )
    assert fs.players["clean"].output_z > 2.0


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def _judge(*, mismatch, height_z, output_z, age=13.5):
    pf = PlayerFeatures(player_id="p", player={"id": "p"})
    pf.heights = [(TODAY, 160.0)] * 4
    pf.stated_age = age
    pf.height_z_mean = height_z
    pf.maturity_mismatch = mismatch
    pf.velocity_z = None if mismatch is None else height_z - mismatch
    pf.output_z = output_z
    return fraud.detect_age_misrepresentation(SimpleNamespace(players={"p": pf})).get("p")


def test_an_early_maturer_who_plays_like_his_age_group_is_not_accused():
    """The growth rule alone would accuse him. This is the false accusation being removed."""
    assert _judge(mismatch=2.6, height_z=1.6, output_z=1.6) is not None
    assert _judge(mismatch=2.6, height_z=1.6, output_z=0.0) is None


def test_growth_backed_by_output_is_flagged_and_says_both():
    reason = _judge(mismatch=2.6, height_z=1.6, output_z=0.8)
    assert reason is not None
    assert "no longer growing" in reason and "outproduces" in reason


def test_output_and_size_together_flag_a_boy_whose_growth_does_not_give_him_away():
    """A boy claiming 12 who is really 14 has barely started his spurt; growth misses him."""
    reason = _judge(mismatch=0.3, height_z=1.2, output_z=2.0, age=12.2)
    assert reason is not None
    assert reason.startswith("Dominates the age group")


def test_a_small_child_who_outplays_his_age_group_is_never_accused():
    assert _judge(mismatch=-1.5, height_z=-1.2, output_z=4.0) is None
    assert _judge(mismatch=0.0, height_z=0.5, output_z=4.0) is None


def test_without_output_growth_decides_alone_and_the_sentence_says_so():
    reason = _judge(mismatch=2.6, height_z=1.6, output_z=None)
    assert reason is not None
    assert "not enough playing time" in reason
    assert _judge(mismatch=1.0, height_z=1.6, output_z=None) is None
