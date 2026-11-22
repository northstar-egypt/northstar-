"""Find the next <pro> (ml/next_pro.py).

What is pinned: style is judged within each side's own peers, so a child who stands out the
way a professional does matches them even at a far lower level; goalkeepers and small pools give
nothing rather than a guess; and the match is a percentage from 0 to 100.
"""

from __future__ import annotations

from ml import next_pro as N


def _metrics(shots, assists, tackles=10, minutes=900):
    return {"minutes_played": minutes, "goals": shots // 4, "assists": assists, "shots": shots,
            "shots_on_target": shots // 2, "key_passes": assists * 2, "passes_attempted": 300,
            "passes_completed": 240, "tackles": tackles}


def _pool(prefix, position, scale, peers, n=10):
    return [N.Player(f"{prefix}{i}", position, peers, N.rates(_metrics(scale * (2 + i), 1 + i % 3)))
            for i in range(n)]


def test_a_child_who_stands_out_the_same_way_matches_at_a_lower_level():
    pros = _pool("pro", "ST", 10, ("api",))
    star = N.Player("star", "ST", ("api",), N.rates(_metrics(200, 2, tackles=2)))
    pros.append(star)
    kids = _pool("kid", "ST", 2, ("male", "2012"))
    twin = N.Player("twin", "ST", ("male", "2012"), N.rates(_metrics(40, 2, tackles=2)))
    kids.append(twin)
    out = N.matches(star, pros, kids)
    assert out[0].player_id == "twin"
    assert all(0 <= m.percent <= 100 for m in out)
    assert "shots" in out[0].alike


def test_goalkeepers_and_small_pools_give_nothing():
    pros = _pool("pro", "GK", 1, ("api",))
    assert N.matches(pros[0], pros, _pool("kid", "GK", 1, ("male", "2012"))) == []
    pros = _pool("pro", "ST", 10, ("api",))
    assert N.matches(pros[0], pros, _pool("kid", "ST", 2, ("male", "2012"), n=3)) == []


def test_pros_from_another_source_are_not_peers():
    pros = _pool("pro", "ST", 10, ("api",), n=5) + _pool("real", "ST", 10, ("footystats",), n=10)
    assert N.matches(pros[0], pros, _pool("kid", "ST", 2, ("male", "2012"))) == []


def test_a_small_age_year_is_widened_to_all_ages():
    kids = _pool("a", "ST", 2, ("male", "2012"), n=3) + _pool("b", "ST", 2, ("male", "2010"), n=9)
    widened = {p.player_id: p.peers for p in N.youth_peers(kids)}
    assert widened["a0"] == ("male", "any age") and widened["b0"] == ("male", "2010")


def test_a_missing_statistic_is_not_taken_as_zero():
    metrics = _metrics(10, 1)
    del metrics["tackles"]
    assert N.rates(metrics) is None
