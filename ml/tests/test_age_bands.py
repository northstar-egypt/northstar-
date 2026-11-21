"""ml/run_age_bands: the bands, and the pooling, on invented counts."""

from ml import run_age_bands as ab


def test_bands_follow_the_stated_age_and_take_the_youngest_into_the_first():
    assert ab.band(10.6) == "11 to 13"   # the rare planted cheat stated under 11
    assert ab.band(12.99) == "11 to 13"
    assert ab.band(13.0) == "13 to 15"
    assert ab.band(16.5) == "15 to 17"
    assert ab.band(17.0) == "17+"


def test_pooling_adds_counts_and_bands_across_datasets():
    from ml.evaluation import fairness

    def one(tp, fp, caught):
        bands = {b: {"planted": 2, "caught": 0, "false": 0} for b in ab.BANDS}
        bands["13 to 15"]["caught"] = caught
        audit = fairness.audit("x", set(), set(), set(), {})
        return {"tp": tp, "fp": fp, "fn": 1, "bands": bands, "quarters": audit}

    results = [{"v1": one(1, 3, 1), "v2": one(2, 1, 2)}, {"v1": one(2, 4, 0), "v2": one(1, 0, 1)}]
    total = ab.pool(results)
    assert (total["v1"]["tp"], total["v1"]["fp"], total["v1"]["fn"]) == (3, 7, 2)
    assert total["v2"]["bands"]["13 to 15"]["caught"] == 3
    assert total["v2"]["bands"]["17+"]["planted"] == 4
