"""The governorate of synthetic clubs (data/pipelines/synthetic/regions.py).

It must never draw from the generator's random stream, so it is a pure function of the name.
"""

from __future__ import annotations

from data.pipelines.synthetic import regions


def test_a_name_that_says_where_gets_that_governorate():
    assert regions.region_for("المصري", "club", "EG") == "EG-PTS"
    assert regions.region_for("أكاديمية أسوان", "academy", "EG") == "EG-ASN"


def test_any_other_name_gets_the_same_governorate_every_time():
    first = regions.region_for("أكاديمية النيل", "academy", "EG")
    assert first is not None and first.startswith("EG-")
    assert all(regions.region_for("أكاديمية النيل", "academy", "EG") == first for _ in range(5))


def test_abroad_and_national_bodies_have_none():
    assert regions.region_for("Some FC", "club", "FR") is None
    assert regions.region_for("منتخب مصر", "national_team", "EG") is None
    assert regions.region_for("اتحاد", "federation", "EG") is None


def test_every_known_home_is_a_real_governorate_code():
    from app.regions import GOVERNORATES

    assert set(regions.HOME.values()) <= set(GOVERNORATES)
    assert len(GOVERNORATES) == 27
