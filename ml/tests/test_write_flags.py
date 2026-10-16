"""ml/write_flags.py: which flags the batch job may write.

The job applies the API's own rule (flags.TALENT_TYPES, access.consent_subquery); this checks
the decision it makes with them. The end-to-end run against a database is in the PR that added
it, since the job opens its own connection and commits.
"""

from __future__ import annotations

from ml.write_flags import withheld_for_consent

TALENT = ("late_bloomer", "breakout")


def test_a_talent_flag_needs_analytics_consent():
    assert withheld_for_consent("late_bloomer", "p1", analytics=set(), talent_types=TALENT)
    assert withheld_for_consent("breakout", "p1", analytics={"p2"}, talent_types=TALENT)
    assert not withheld_for_consent("late_bloomer", "p1", analytics={"p1"}, talent_types=TALENT)


def test_an_integrity_flag_is_written_without_it():
    """Withdrawing analytics consent must not hide a falsified record from review."""
    for flag_type in ("fraud", "duplicate", "anomaly"):
        assert not withheld_for_consent(flag_type, "p1", analytics=set(), talent_types=TALENT)
