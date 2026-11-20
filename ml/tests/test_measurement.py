"""ml/decisions/measurement.py: the measuring schedules and the optimiser, on invented squads;
and the simulator in ml/run_measurement_eval.py on a small generated world."""

from __future__ import annotations

from datetime import date, timedelta

from ml.decisions import measurement as m

TODAY = date(2030, 3, 1)


def _player(pid, *, age, readings=(), heights=None, sex="male", joined_days=400, leaves_in=400):
    dob = TODAY - timedelta(days=int(age * 365.25))
    p = m.Player(pid, sex, dob, TODAY - timedelta(days=joined_days), TODAY + timedelta(days=leaves_in))
    # Oldest first, as the simulator records them.
    values = heights or [150.0] * len(readings)
    for days_ago, height in sorted(zip(readings, values), reverse=True):
        p.readings.append((TODAY - timedelta(days=days_ago), height))
    return p


def test_value_follows_age_window_size_and_need():
    young = _player("a", age=13)
    old = _player("b", age=19)
    assert m.value(young, TODAY, 0.0) > m.value(old, TODAY, 0.0)
    assert m.value(young, TODAY, -1.5) > m.value(young, TODAY, 1.5)  # smaller matters more
    well_measured = _player("c", age=13, readings=[30, 60, 90, 120, 150])
    assert m.value(young, TODAY, 0.0) > m.value(well_measured, TODAY, 0.0)


def test_version_2_values_span_not_count():
    # Two 13-year-olds with three recent readings each: one bunched in the last two months,
    # one spread over the last ten. Another reading now stretches the first one's window from
    # 2 months to 9 (a big gain) but the second's only from 10 months to 10 and a bit.
    bunched = _player("bunched", age=13, readings=[270, 240, 210])
    spread = _player("spread", age=13, readings=[300, 150, 30])
    assert m.value_span(bunched, TODAY, 0.0) > m.value_span(spread, TODAY, 0.0)
    # A reading a month after the last one adds little span, unlike version 1's count.
    just_after = _player("just_after", age=13, readings=[60, 30])
    later = _player("later", age=13, readings=[200, 170])
    assert m.value_span(later, TODAY, 0.0) > m.value_span(just_after, TODAY, 0.0)


def test_nudge_takes_never_measured_then_longest_waiting():
    squad = [_player("never", age=13), _player("old", age=13, readings=[170]),
             _player("recent", age=13, readings=[40])]
    assert m.choose_nudge(squad, TODAY, 2, {}) == ["never", "old"]


def test_rota_goes_round_the_whole_squad():
    squad = [_player(f"p{i}", age=13) for i in range(5)]
    state: dict = {}
    seen = m.choose_rota(squad, TODAY, 2, state) + m.choose_rota(squad, TODAY, 2, state) \
        + m.choose_rota(squad, TODAY, 2, state)
    assert set(seen) == {f"p{i}" for i in range(5)}


def test_nobody_absent_or_just_measured_is_chosen():
    gone = _player("gone", age=13, joined_days=400, leaves_in=-10)
    not_yet = _player("not_yet", age=13, joined_days=-10)
    just = _player("just", age=13, readings=[5])
    here = _player("here", age=13)
    for choose in m.CHOOSERS.values():
        picked = choose([gone, not_yet, just, here], TODAY, 3, {"seed": 1})
        assert picked == ["here"]


def test_optimiser_fills_the_session_and_picks_the_most_valuable():
    squad = [_player(f"adult{i}", age=20, readings=[60, 120, 200, 260]) for i in range(6)]
    squad += [_player("small13", age=13, readings=[100], heights=[140.0]),
              _player("new12", age=12)]
    picked = m.choose_optimised(squad, TODAY, 3, {}, zs={"small13": -1.5})
    assert len(picked) == 3
    assert "small13" in picked and "new12" in picked


def test_optimiser_keeps_the_six_month_rule_when_it_can():
    # A well-measured adult is worth little, but has not been measured for 170 days: by the next
    # session he would pass six months, so the plan must measure him in this one or the next,
    # even though the kids (measured a month ago, so not overdue) are each worth more.
    adult = _player("adult", age=22, readings=[170, 300, 400, 500])
    kids = [_player(f"kid{i}", age=13, readings=[30]) for i in range(4)]
    state: dict = {}
    first = m.choose_optimised([adult] + kids, TODAY, 2, state, zs={})
    second_day = TODAY + timedelta(days=m.SESSION_DAYS)
    for pid in first:
        next(p for p in [adult] + kids if p.id == pid).readings.append((TODAY, 150.0))
    second = m.choose_optimised([adult] + kids, second_day, 2, state, zs={})
    assert "adult" in first + second
    assert state.get("overdue_breaks", 0) == 0


def test_height_z_needs_a_group_of_five():
    group = [_player(f"g{i}", age=13.5, readings=[10], heights=[140.0 + 2 * i]) for i in range(5)]
    alone = _player("alone", age=15.5, readings=[10], heights=[170.0])
    zs = m.height_z(group + [alone], TODAY)
    assert set(zs) == {f"g{i}" for i in range(5)}
    assert zs["g0"] < 0 < zs["g4"]


def test_noise_is_fixed_by_who_when_and_what():
    a = m.noise(7, "p1", TODAY, "height", 0.5)
    assert a == m.noise(7, "p1", TODAY, "height", 0.5)
    assert a != m.noise(7, "p1", TODAY + timedelta(days=1), "height", 0.5)
    assert a != m.noise(7, "p2", TODAY, "height", 0.5)


def test_every_schedule_spends_the_same_budget_on_a_generated_world():
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from ml import run_measurement_eval as ev

    config = GeneratorConfig(seed=101).scaled(60)
    ds = build_dataset(config)
    counts = {}
    for policy in m.POLICIES:
        rows, info = ev.simulate(ds, config, policy, 1.0)
        counts[policy] = info["readings"]
        assert len(rows) == 3 * info["readings"]  # height, weight and sprint per reading
    # The same capacity for everyone; the optimiser uses every place it is given.
    assert len(set(counts.values())) == 1
    generated, _ = ev.simulate(ds, config, "as generated", 1.0)
    assert abs(counts["optimised"] - len(generated) / 3) / (len(generated) / 3) < 0.02
