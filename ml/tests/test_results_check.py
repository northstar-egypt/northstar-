"""Tests for the results check (ml/run_results_check.py).

Two kinds. The mechanics, on small invented README text and outputs: a number is compared at the
README's own precision, a pattern that finds nothing or two different values is reported as
broken and never as passed, an anchor picks the table meant, a row label never matches a heading
on the line above. And the registry itself, against today's ml/README.md: every check names a
module that exists, and every README pattern still finds exactly one published value, so an edit
to the README that moves a table is caught here, in seconds, instead of when someone next runs
the evaluations.
"""

from __future__ import annotations

import importlib.util

import pytest

from ml import run_results_check as rc
from ml.run_results_check import Check, Number, compare, find, md, out, parse

# ---------------------------------------------------------------------------
# Parsing and finding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, value, decimals",
    [("0.94", 0.94, 2), ("12,550", 12550.0, 0), ("79.0%", 79.0, 1), ("-0.07", -0.07, 2),
     ("−0.07", -0.07, 2), ("+1.5", 1.5, 1), ("41%", 41.0, 0)],
)
def test_parse_reads_a_number_as_written(text, value, decimals):
    assert parse(text) == (pytest.approx(value), decimals)


@pytest.mark.parametrize("text", ["abc", "", "0.9.4", "1 2"])
def test_parse_refuses_what_is_not_a_number(text):
    with pytest.raises(ValueError):
        parse(text)


def test_a_number_quoted_twice_is_fine_two_different_ones_are_not():
    assert find(r"F1 ([\d.]+)", "F1 0.5\nagain F1 0.5") == ("0.5", "")
    value, why = find(r"F1 ([\d.]+)", "F1 0.5\nF1 0.6")
    assert value is None and "different values" in why
    value, why = find(r"F1 ([\d.]+)", "nothing here")
    assert value is None and "found nothing" in why


def test_an_anchor_picks_the_first_match_after_it():
    text = "table A\nrow 1.0\ntable B\nrow 2.0\nrow 3.0"
    assert find(r"^row ([\d.]+)", text, after="table B") == ("2.0", "")
    value, why = find(r"^row ([\d.]+)", text, after="table C")
    assert value is None and "anchor not found" in why


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------

README_TEXT = "| model | 0.94 | **0.86** |\n| rate | 2.3% | 5 |\n"


def _number(readme_cell: int, output: str = r"^value ([\d.]+)", scale: float = 1.0) -> Number:
    return Number("x", md("model", readme_cell), output, scale=scale)


def test_today_is_rounded_to_the_readme_precision():
    assert compare("c", _number(1), README_TEXT, "value 0.9412").status == "same"
    assert compare("c", _number(1), README_TEXT, "value 0.9461").status == "differs"
    assert compare("c", _number(2), README_TEXT, "value 0.864").status == "same"  # bold cell


def test_a_half_is_rounded_up_as_a_person_would():
    """0.285 is stored as 0.28499999... in a float, so round() gives 0.28; the README says 0.29."""
    number = Number("p", r"p = ([\d.]+)", r"^value ([\d.]+)")
    assert compare("c", number, "p = 0.29", "value 0.285").status == "same"
    assert compare("c", number, "p = 0.28", "value 0.285").status == "differs"
    assert compare("c", number, "p = 0.28", "value 0.2849").status == "same"


def test_a_rate_printed_as_a_fraction_is_scaled_to_the_readme_percent():
    number = Number("rate", md("rate", 1), r"^value ([\d.]+)", scale=100)
    outcome = compare("c", number, README_TEXT, "value 0.023")
    assert outcome.status == "same"
    assert compare("c", number, README_TEXT, "value 0.021").status == "differs"


def test_a_pattern_that_finds_nothing_is_broken_never_passed():
    missing_readme = Number("x", md("no such row", 1), r"^value ([\d.]+)")
    assert compare("c", missing_readme, README_TEXT, "value 0.94").status == "broken"
    assert compare("c", _number(1), README_TEXT, "the output changed shape").status == "broken"


def test_a_row_label_never_matches_a_heading_on_the_line_above():
    """The bug this guards: 'fraud, age: isolation forest' is both a summary row and the
    heading of a birth-quarter block, and a field pattern must not read into the block."""
    output = "fraud, age: forest\n  Q1 Jan-Mar 38 0 2\nfraud, age: forest    0.446    95   147\n"
    assert find(out("fraud, age: forest", 2), output) == ("147", "")


def test_md_reads_the_start_of_the_cell_it_is_asked_for():
    text = "| v1 | 81 | 0.643 [0.56, 0.72] | **41%**, 35 of 86 |"
    assert find(md("v1", 1), text) == ("81", "")
    assert find(md("v1", 2), text) == ("0.643", "")
    assert find(md("v1", 3), text) == ("41%", "")
    assert find(md("v", 1), text)[0] is None  # a label is the whole first cell, not a prefix


# ---------------------------------------------------------------------------
# The whole run
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_registry(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text("| model | 0.94 |\n", encoding="utf-8")
    check = Check("tiny", "Tiny", ("ml.run_eval",), (Number("model", md("model", 1), r"^value ([\d.]+)"),))
    monkeypatch.setattr(rc, "README", readme)
    monkeypatch.setattr(rc, "CHECKS", (check,))
    saved = tmp_path / "saved"
    saved.mkdir()
    return saved


def test_exit_code_is_zero_only_when_every_number_is_as_published(tiny_registry, capsys):
    (tiny_registry / "tiny.txt").write_text("value 0.941\n", encoding="utf-8")
    assert rc.main(["--from-output", str(tiny_registry)]) == 0
    (tiny_registry / "tiny.txt").write_text("value 0.951\n", encoding="utf-8")
    assert rc.main(["--from-output", str(tiny_registry)]) == 1
    assert "DIFFERS  model: README 0.94, today 0.951" in capsys.readouterr().out


def test_a_missing_output_fails_the_run(tiny_registry):
    assert rc.main(["--from-output", str(tiny_registry)]) == 1


def test_an_unknown_check_name_is_refused(tiny_registry):
    assert rc.main(["--only", "nope", "--from-output", str(tiny_registry)]) == 2


def test_list_names_what_is_not_checked(capsys):
    assert rc.main(["--list"]) == 0
    printed = capsys.readouterr().out
    for name in rc.NOT_CHECKED:
        assert name in printed


# ---------------------------------------------------------------------------
# The registry, against today's README
# ---------------------------------------------------------------------------


def test_check_names_and_labels_are_unique():
    names = [c.name for c in rc.CHECKS]
    assert len(names) == len(set(names))
    for check in rc.CHECKS:
        labels = [n.label for n in check.numbers]
        assert len(labels) == len(set(labels)), check.name


@pytest.mark.parametrize("check", rc.CHECKS, ids=lambda c: c.name)
def test_every_command_names_a_module_that_exists(check):
    assert importlib.util.find_spec(check.command[0]) is not None


@pytest.mark.parametrize("check", rc.CHECKS, ids=lambda c: c.name)
def test_every_readme_pattern_finds_exactly_one_published_value(check):
    readme = rc.README.read_text(encoding="utf-8")
    for number in check.numbers:
        value, why = find(number.readme, readme, number.readme_after)
        assert value is not None, f"{check.name}, {number.label}: {why}"
        parse(value)  # and it is a number
