"""Results check: re-run every published evaluation and compare its numbers with ml/README.md.

    python -m ml.run_results_check               # every check that runs on synthetic data
    python -m ml.run_results_check --list        # what is checked, and what is not
    python -m ml.run_results_check --only detectors-5 forecast --verbose
    python -m ml.run_results_check --keep-output DIR   # also save each evaluation's output
    python -m ml.run_results_check --from-output DIR   # compare saved outputs, run nothing

Run from the repository root; the whole run takes about 20 minutes with three evaluations at a
time, most of it the three measurement evaluations (the paired one alone takes about 15). Save
outputs outside the repository.

Published numbers must not move silently (CLAUDE.md, "The quality bar"). This runs each
evaluation the README publishes, with the same command the README gives, reads the published
value from the README and today's value from the command's output, and prints every number
that differs. Exit code 0 when every number matches, 1 otherwise.

How a number is compared
------------------------
Each `Number` has two patterns, each with one group around the number: one finds the published
value in ml/README.md, the other finds the same value in the command's output. Today's value
is rounded half up to the README's own number of decimals and must then be equal: a README
that says 0.94 matches an output of 0.9412 and not one of 0.9461, and 0.29 matches 0.285.
Percent signs and thousands commas are ignored. A pattern that matches nothing, or matches two different values, is reported as
broken rather than passed, because a check that silently finds nothing would be worse than
no check: it means the README or the evaluation's output changed shape and the check needs
updating.

The README is read for the published values, never this file, so the two cannot drift
apart: this file only says where each number is.

What is not checked
-------------------
Evaluations that need data outside the repository (the FootyStats download, StatsBomb's open
data, a database export) are listed in `NOT_CHECKED` with the reason, and `--list` prints them.
Tuning runs (`--tune`, the calibration seeds) are not checked either: they choose settings and
publish no graded number. Each check covers the headline numbers of its README section, not
every cell; adding one is a `Number(...)` line below.

Evaluated by its own tests, ml/tests/test_results_check.py, which also check that every
README pattern below still finds exactly one value in today's ml/README.md.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT =Path(__file__).resolve().parents[1]
README = ROOT / "ml" / "README.md"

FIVE = ("20260827", "7", "99", "404", "555")
TWENTY = FIVE + tuple(str(s) for s in range(1000, 1015))


@dataclass(frozen=True)
class Number:
    """One published number: where it is in the README, and where it is in the output.

    `readme_after` and `after` narrow the search to the text after the first occurrence of an
    anchor (a table's heading, a summary's title), for a row label that appears in more than one
    table; the first match after the anchor is the one meant. `scale` multiplies today's value
    before comparing, for a rate the output prints as 0.023 and the README as 2.3%.
    """

    label: str
    readme: str
    output: str
    readme_after: str = ""
    after: str = ""
    scale: float = 1.0


@dataclass(frozen=True)
class Check:
    """One published evaluation command and the numbers it produces."""

    name: str
    section: str
    command: tuple[str, ...]
    numbers: tuple[Number, ...]


@dataclass
class Outcome:
    """The result for one number."""

    check: str
    label: str
    status: str  # "same", "differs", "broken"
    published: str = ""
    today: str = ""
    note: str = ""


@dataclass
class Result:
    check: Check
    seconds: float = 0.0
    outcomes: list[Outcome] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"^[+-]?\d(?:[\d,]*\d)?(\.\d+)?%?$")


def parse(text: str) -> tuple[float, int]:
    """A number as written, and how many decimals it was written with."""
    cleaned = text.strip().replace("−", "-")
    if not _NUMBER.match(cleaned):
        raise ValueError(f"not a number: {text!r}")
    cleaned = cleaned.rstrip("%").replace(",", "")
    decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
    return float(cleaned), decimals


def find(pattern: str, text: str, after: str = "") -> tuple[str | None, str]:
    """The one value a pattern finds, or None and why not.

    Without an anchor, several matches are fine when they all agree (a number quoted twice);
    disagreeing matches are not, because then the pattern does not say which number it means.
    With an anchor, the first match after the anchor's first occurrence is the one meant.
    """
    if after:
        start = text.find(after)
        if start < 0:
            return None, f"anchor not found: {after!r}"
        match = re.search(pattern, text[start:], flags=re.MULTILINE)
        if match is None:
            return None, f"pattern found nothing after {after!r}"
        return match.group(1), ""
    values = {m.group(1) for m in re.finditer(pattern, text, flags=re.MULTILINE)}
    if not values:
        return None, "pattern found nothing"
    if len(values) > 1:
        return None, f"pattern found different values: {', '.join(sorted(values))}"
    return values.pop(), ""


def compare(check_name: str, number: Number, readme_text: str, output: str) -> Outcome:
    published, why = find(number.readme, readme_text, number.readme_after)
    if published is None:
        return Outcome(check_name, number.label, "broken", note=f"in ml/README.md: {why}")
    today, why = find(number.output, output, number.after)
    if today is None:
        return Outcome(check_name, number.label, "broken", published, note=f"in the output: {why}")
    expected, decimals = parse(published)
    parse(today)  # refuse what is not a number
    found = _decimal(today) * Decimal(str(number.scale))
    # Rounded half up, as a person rounds the printed value: an output of 0.285 is published as
    # 0.29. Floats would round it to 0.28, because 0.285 is stored as 0.28499999...
    rounded = found.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    shown = today if number.scale == 1.0 else f"{rounded} ({today})"
    status = "same" if rounded == _decimal(published) else "differs"
    return Outcome(check_name, number.label, status, published, shown)


def _decimal(text: str) -> Decimal:
    return Decimal(text.strip().replace("−", "-").rstrip("%").replace(",", ""))


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def from_saved(check: Check, readme_text: str, directory: Path) -> Result:
    """Compare an output saved earlier (`--keep-output`) instead of running the command."""
    result = Result(check)
    path = directory / f"{check.name}.txt"
    if not path.exists():
        result.error = f"no saved output at {path}"
        result.outcomes = [
            Outcome(check.name, n.label, "broken", note="no saved output") for n in check.numbers
        ]
        return result
    output = path.read_text(encoding="utf-8")
    result.outcomes = [compare(check.name, n, readme_text, output) for n in check.numbers]
    return result


def run(check: Check, readme_text: str, *, keep: Path | None = None) -> Result:
    """Run the check's command from the repository root and compare its output."""
    result = Result(check)
    started = time.monotonic()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
    completed = subprocess.run(
        [sys.executable, "-m", *check.command],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    result.seconds = time.monotonic() - started
    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        (keep / f"{check.name}.txt").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        tail = "\n".join(completed.stderr.strip().splitlines()[-5:])
        result.error = f"exit code {completed.returncode}: {tail}"
        result.outcomes = [
            Outcome(check.name, n.label, "broken", note="the command failed") for n in check.numbers
        ]
        return result
    result.outcomes = [compare(check.name, n, readme_text, completed.stdout) for n in check.numbers]
    return result


def render(results: list[Result], *, verbose: bool = False) -> str:
    """One line per evaluation, then every number that moved; with `verbose`, every number."""
    lines = []
    for result in results:
        same = sum(o.status == "same" for o in result.outcomes)
        lines.append(
            f"{result.check.name}: {same} of {len(result.outcomes)} numbers as published "
            f"({result.seconds:.0f} s)  [{result.check.section}]"
        )
        if result.error:
            lines.append(f"    command failed, {result.error}")
        for o in result.outcomes:
            if o.status == "differs":
                lines.append(f"    DIFFERS  {o.label}: README {o.published}, today {o.today}")
            elif o.status == "broken":
                lines.append(f"    BROKEN   {o.label}: {o.note}")
            elif verbose:
                lines.append(f"    same     {o.label}: README {o.published}, today {o.today}")
    outcomes = [o for r in results for o in r.outcomes]
    differ = sum(o.status == "differs" for o in outcomes)
    broken = sum(o.status == "broken" for o in outcomes)
    lines += [
        "",
        f"{len(outcomes)} numbers in {len(results)} evaluations: "
        f"{len(outcomes) - differ - broken} as published, {differ} differ, {broken} could not be checked.",
    ]
    if NOT_CHECKED:
        lines.append(f"Not checked (see --list): {'; '.join(sorted(NOT_CHECKED))}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The published evaluations
# ---------------------------------------------------------------------------

NUM = r"([+-]?\d(?:[\d,]*\d)?(?:\.\d+)?%?)"


def md(label: str, column: int) -> str:
    """A README table row whose first cell is `label` (a regex, bold marks included), and the
    number at the start of its `column`th cell after the label (1 is the first)."""
    return rf"^\| {label} \|" + r"[^|\n]*\|" * (column - 1) + rf" *\**{NUM}"


def out(label: str, index: int) -> str:
    """An output line starting with `label` (a regex), and its `index`th whitespace-separated
    field after the label (0 is the first). Never reads past the end of that line: a label that
    is also a heading (a detector's name above its birth-quarter rows) must not match there."""
    return rf"^{label}[ \t]+(?:\S+[ \t]+){{{index}}}{NUM}(?!\S)"


def fraction(label: str, index: int) -> str:
    """Like `out`, for a field written "caught/planted": the number before the slash."""
    return rf"^{label}[ \t]+(?:\S+[ \t]+){{{index}}}(\d+)/\d+(?!\S)"


def quarter_rate(header: str, quarter: int) -> str:
    """The false-positive rate in a birth-quarter block of the relative age audit's output."""
    return (
        rf"^{header}[^\n]*\n(?:  Q[^\n]*\n){{{quarter - 1}}}  Q{quarter}[^\n]*\s{NUM}"
        rf"\s+[\d.]+ to [\d.]+[ \t]*$"
    )


def quarter_test(header: str, what: str) -> str:
    """The chi-square (`what="chi-square"`) or its p value (`what="p"`) under a birth-quarter block."""
    lead = r"chi-square " if what == "chi-square" else r"chi-square [\d.]+, 3 df, p = "
    return rf"^{header}[^\n]*\n(?:  Q[^\n]*\n){{4}}  false positive rate: {lead}{NUM}"


def _quarters(name: str, readme_label: str, output_header: str, after: str) -> list[Number]:
    """False-positive rate by birth quarter (README in %, output as a fraction), and the chi-square."""
    numbers = [
        Number(f"{name}, false positive rate, Q{q}", md(readme_label, q), quarter_rate(output_header, q),
               after=after, scale=100)
        for q in (1, 2, 3, 4)
    ]
    numbers.append(
        Number(f"{name}, chi-square", md(readme_label, 5), quarter_test(output_header, "chi-square"), after=after)
    )
    return numbers


_POOLED_AGE_BANDS = "Relative age, counts pooled over 20 datasets"
_BANDS = ("11 to 13", "13 to 15", "15 to 17", "17+")


def _by_stated_age() -> tuple[Number, ...]:
    """The "By stated age" table: catches (before the slash) and false accusations, v1 and v2."""
    return tuple(
        Number(f"by stated age, {rule} {what}, {band}", md(readme, column), pattern(rf"  {rule} {what}", column - 1))
        for rule, what, readme, pattern in (
            ("v1", "caught", "v1 caught", fraction),
            ("v2", "caught", r"\*\*v2 caught\*\*", fraction),
            ("v1", "false accusations", "v1 false accusations", out),
            ("v2", "false accusations", "v2 false accusations", out),
        )
        for column, band in enumerate(_BANDS, start=1)
    )


_POOLED_20 = "Relative age audit, counts pooled over 20 datasets"

_GAP_TEAM_ROWS = (
    ("Chances made", r"Chances made \(xG per game\)", r"Chances made \(xG per game\)"),
    ("Chances allowed", r"Chances allowed \(xG against per game\)", r"Chances allowed \(xG against per game\)"),
    ("Shots allowed", r"Shots allowed per game", r"Shots allowed per game"),
    ("Possession", r"Possession", r"Possession"),
    ("Points per game", r"Points per game", r"Points per game"),
    ("Goals above xG", r"Goals above xG per game", r"Goals above xG per game"),
    ("Goals conceded above xG", r"Goals conceded above xG per game", r"Goals conceded above xG per game"),
    ("Set piece goals", r"Set piece goals per game", r"Set piece goals per game"),
    ("Set piece goals conceded", r"Set piece goals conceded per game", r"Set piece goals conceded per game"),
    ("Late goals conceded", r"Goals conceded in the last 15 minutes", r"Goals conceded in the last 15 minutes per game"),
)

_SCHEDULES = (
    ("as generated", "as generated"),
    ("rota", "rota"),
    ("nudge", "nudge"),
    ("random", "random"),
    ("optimised", r"\*\*optimised\*\*"),
)


def _measurement(seeds: str, readme_after: str) -> tuple[Number, ...]:
    """The table at today's budget (1.0): late bloomers flagged, too few readings, other small
    players flagged, per schedule. In the output these are the 1st, 3rd and 4th percentages of
    the schedule's 1.0 row."""
    return tuple(
        Number(
            f"{seeds}, {schedule}, {what}",
            md(readme, col),
            rf"^  {schedule}\s+1\.0\s+\d+\s+(?:[\d.]+% \([^)]*\)\s*){{{skip}}}{NUM}",
            readme_after=readme_after,
        )
        for schedule, readme in _SCHEDULES
        for what, col, skip in (
            ("late bloomers flagged", 1, 0), ("too few readings", 2, 2), ("other small players flagged", 3, 3),
        )
    )


def _paired(budget: str) -> tuple[Number, ...]:
    """One budget's row of the paired comparison: against nudge (mean, interval, seeds won),
    the means against rota and random, and the extra false alarms."""
    row = re.escape(budget)
    cell = r"\S+ \([^)]*\), \d+ won, \d+ tied\s+"  # one comparison in the output row
    return (
        Number(f"paired, budget {budget}, against nudge", md(row, 1), rf"^\s+{row}\s+{NUM} \("),
        Number(f"paired, budget {budget}, against nudge, interval low",
               rf"^\| {row} \| [^(|]*\(([+-][\d.]+) to", rf"^\s+{row}\s+\S+ \({NUM} to"),
        Number(f"paired, budget {budget}, against nudge, interval high",
               rf"^\| {row} \| [^(|]*\([+-][\d.]+ to ([+-][\d.]+)\)", rf"^\s+{row}\s+\S+ \(\S+ to {NUM}\)"),
        Number(f"paired, budget {budget}, against nudge, seeds won",
               rf"^\| {row} \|[^|]*\), (\d+) won", rf"^\s+{row}\s+\S+ \([^)]*\), {NUM} won"),
        Number(f"paired, budget {budget}, against rota", md(row, 2), rf"^\s+{row}\s+(?:{cell}){{1}}{NUM} \("),
        Number(f"paired, budget {budget}, against random", md(row, 3), rf"^\s+{row}\s+(?:{cell}){{2}}{NUM} \("),
        Number(f"paired, budget {budget}, extra false alarms", md(row, 4), rf"^\s+{row}\s+(?:{cell}){{3}}{NUM}"),
    )


_REPORT_GROUPS = (
    ("Centre backs", "centre_backs"),
    ("Full backs", "full_backs"),
    ("Holding midfielders", "holding_midfielders"),
    ("Central midfielders", "central_midfielders"),
    ("Wingers", "wingers"),
    ("Strikers", "strikers"),
)

CHECKS: tuple[Check, ...] = (
    Check(
        "detectors-5",
        "Results, v1",
        ("ml.run_eval", "--seed-sweep", *FIVE),
        tuple(
            Number(f"{name} F1, mean of 5 datasets", md(name, 6), out(rf"{name}\s+F1", 5))
            for name in ("late_bloomer", "fraud", "duplicate")
        ),
    ),
    Check(
        "detectors-20",
        "Age misrepresentation, v2; isolation forest; relative age audit",
        ("ml.run_eval", "--seed-sweep", *TWENTY),
        (
            Number(
                "late bloomer F1, mean of 20 datasets",
                r"^\| late-bloomer F1, 5 seeds / 20 seeds \|[^|\n]*\| \*\*[\d.]+ / ([\d.]+)\*\*",
                out(r"late_bloomer\s+F1", 20),
            ),
            *(
                Number(f"age rule v2, {what}", md(r"\*\*v2, growth and performance\*\*", col), out("fraud, age: rule", idx))
                for what, col, idx in (
                    ("caught", 1, 1), ("false accusations", 2, 2), ("precision", 3, 4), ("recall", 4, 5), ("F1", 5, 6),
                )
            ),
            *(
                Number(f"isolation forest, {what}", md("isolation forest", col), out("fraud, age: isolation forest", idx))
                for what, col, idx in (
                    ("caught", 1, 1), ("false accusations", 2, 2), ("precision", 3, 4), ("recall", 4, 5), ("F1", 5, 6),
                )
            ),
            *_quarters("relative age, late bloomer v1", "late_bloomer v1", "late_bloomer v1", _POOLED_20),
            *_quarters(
                "relative age, age rule v2",
                r"fraud: age misrepresentation \(v2, with performance\)",
                "fraud: age misrepresentation",
                _POOLED_20,
            ),
            *_quarters(
                "relative age, birth-year control",
                r"\*\*control: birth-year cohort\*\*",
                "control: birth-year cohort",
                _POOLED_20,
            )[4:],
            # "false positive rate 3.2% to 4.7% across quarters, p = 0.29": lowest in Q2, highest in Q1.
            Number("isolation forest, lowest quarter false positive rate (Q2)",
                   r"positive rate ([\d.]+)% to [\d.]+% across quarters, p = [\d.]+;",
                   quarter_rate("fraud, age: isolation forest", 2), after=_POOLED_20, scale=100),
            Number("isolation forest, highest quarter false positive rate (Q1)",
                   r"positive rate [\d.]+% to ([\d.]+)% across quarters, p = [\d.]+;",
                   quarter_rate("fraud, age: isolation forest", 1), after=_POOLED_20, scale=100),
            Number("isolation forest, birth-quarter p",
                   r"% across quarters, p = ([\d.]+);",
                   quarter_test("fraud, age: isolation forest", "p"), after=_POOLED_20),
        ),
    ),
    Check(
        "age-bands",
        "Age misrepresentation, v2: v1 against v2, by stated age; relative age audit",
        ("ml.run_age_bands",),
        (
            *(
                Number(f"age rule v1, {what}", md("v1, growth only", col), out("  v1, growth only", idx))
                for what, col, idx in (
                    ("caught", 1, 0), ("false accusations", 2, 1), ("precision", 3, 2), ("recall", 4, 3), ("F1", 5, 4),
                )
            ),
            *_by_stated_age(),
            *_quarters(
                "relative age, age rule v1",
                r"fraud: age misrepresentation \(v1, growth only\)",
                "age rule v1",
                _POOLED_AGE_BANDS,
            ),
        ),
    ),
    Check(
        "age-bands-whatif",
        "Age misrepresentation, v2: the what-if, by stated age and birth quarter",
        ("ml.run_age_bands", "--performance-follows-maturity"),
        (
            # "v2 then catches 95 with 82 false accusations: still fewer than v1's 112"
            Number("what-if, v1 false accusations quoted beside v2",
                   r"still fewer than v1's (\d+)", out("  v1, growth only", 1)),
            # "(19 against 15, and 25 against 22), and lower above 15 (35 against 69, 6 against 8)"
            *(
                Number(f"what-if, by stated age, {rule} false accusations, {band}", readme,
                       out(rf"  {rule} false accusations", idx))
                for rule, band, readme, idx in (
                    ("v2", "11 to 13", r"higher than v1's\*\* \((\d+) against", 0),
                    ("v1", "11 to 13", r"higher than v1's\*\* \(\d+ against (\d+),", 0),
                    ("v2", "13 to 15", r"higher than v1's\*\* \(\d+ against \d+, and (\d+) against", 1),
                    ("v1", "13 to 15", r"higher than v1's\*\* \(\d+ against \d+, and \d+ against (\d+)\)", 1),
                    ("v2", "15 to 17", r"lower above 15\s+\((\d+) against", 2),
                    ("v1", "15 to 17", r"lower above 15\s+\(\d+ against (\d+),", 2),
                    ("v2", "17+", r"lower above 15\s+\(\d+ against \d+, (\d+) against", 3),
                    ("v1", "17+", r"lower above 15\s+\(\d+ against \d+, \d+ against (\d+)\)", 3),
                )
            ),
            # "In the what-if ... it is 2.2%, 1.6%, 2.3%, 2.4%, p = 0.53" (the age rule v2)
            *(
                Number(f"what-if, relative age, age rule v2, false positive rate, Q{q}",
                       r"it is " + r"[\d.]+%, " * (q - 1) + r"([\d.]+)%,",
                       quarter_rate("age rule v2", q), after=_POOLED_AGE_BANDS, scale=100)
                for q in (1, 2, 3, 4)
            ),
            Number("what-if, relative age, age rule v2, p",
                   r"it is [\d.]+%, [\d.]+%, [\d.]+%, [\d.]+%,\s+p = ([\d.]+)\.",
                   quarter_test("age rule v2", "p"), after=_POOLED_AGE_BANDS),
        ),
    ),
    Check(
        "detectors-20-whatif",
        "Age misrepresentation, v2: the what-if",
        ("ml.run_eval", "--seed-sweep", *TWENTY, "--performance-follows-maturity"),
        tuple(
            Number(f"age rule v2 in the what-if, {what}", md("v2 in the what-if below", col), out("fraud, age: rule", idx))
            for what, col, idx in (
                ("caught", 1, 1), ("false accusations", 2, 2), ("precision", 3, 4), ("recall", 4, 5), ("F1", 5, 6),
            )
        ),
    ),
    Check(
        "forecast",
        "Height forecasts, v1; Challenger models",
        ("ml.run_forecast_eval", "--seed-sweep", *FIVE),
        (
            *(
                Number(f"{label} MAE, mean of 5", md(readme, 6), out(output, 5), after="Seed sweep over 5 datasets")
                for label, readme, output in (
                    ("last value", "baseline: last value", "baseline: last value"),
                    ("population average", "baseline: population average", "baseline: population average"),
                    ("cohort velocity", r"\*\*cohort velocity\*\*", "cohort velocity"),
                    ("centile tracking", "centile tracking", "centile tracking"),
                )
            ),
            Number(
                "XGBoost MAE under 18, mean of 5",
                md(r"\*\*under 18 \(headline\)\*\*", 1),
                out(r"challenger: xgboost", 5),
                after="Seed sweep over 5 datasets",
            ),
            *(
                Number(
                    f"{label} band, {gender}, {what}",
                    md(readme, col),
                    rf"^{output}\s+{sex}\s+observed " + (NUM if what == "inside" else rf"[^\n]*mean width {NUM}"),
                    after="Band learned per gender, pooled",
                )
                for label, readme, output in (
                    ("cohort velocity", "cohort velocity", "cohort velocity"),
                    ("XGBoost", r"\*\*XGBoost\*\*", r"challenger: xgboost"),
                )
                for gender, sex, inside_col in (("boys", "male", 1), ("girls", "female", 3))
                for what, col in (("inside", inside_col), ("width", inside_col + 1))
            ),
        ),
    ),
    Check(
        "tempo-fit",
        "Late bloomers by growth timing",
        ("ml.challengers.tempo_fit", "--seed-sweep", *FIVE),
        (
            Number("timing fit, mean F1", md("timing fit", 1), rf"^timing fit, tau >= 0\.8\s+mean F1 {NUM}"),
            Number("timing fit, caught", md("timing fit", 2), rf"^timing fit, tau[^\n]*TP {NUM}"),
            Number("timing fit, false alarms", md("timing fit", 3), rf"^timing fit, tau[^\n]*FP {NUM}"),
            Number("v1 rule, mean F1", md(r"\*\*v1 rule\*\*", 1), rf"^v1 rule\s+mean F1 {NUM}",
                   readme_after="| reported seeds, settings frozen |"),
        ),
    ),
    Check(
        "sitar",
        "Late bloomers by growth timing: SITAR",
        ("ml.challengers.sitar", "--seed-sweep", *FIVE),
        (
            Number("v1 or SITAR 1.4+, mean F1", md(r"v1 or a SITAR timing flag of 1\.4\+ years \(2026-10-25\)", 1),
                   rf"^v1 or SITAR tau >= 1\.4\s+mean F1 {NUM}"),
            Number("v1 or SITAR 1.4+, false alarms", md(r"v1 or a SITAR timing flag of 1\.4\+ years \(2026-10-25\)", 3),
                   rf"^v1 or SITAR tau >= 1\.4[^\n]*FP {NUM}"),
            Number("SITAR alone, mean F1", md(r"SITAR timing fit alone, 1\.4\+ years", 1),
                   rf"^SITAR, tau >= 1\.4\s+mean F1 {NUM}"),
        ),
    ),
    Check(
        "feedback",
        "Reviewers' decisions as training data",
        ("ml.run_feedback_eval",),
        (
            *(
                Number(f"late bloomer, {label}, F1", md(readme, 1), out(output, 0),
                       readme_after="| late bloomer, reported seeds |", after="=== late_bloomer ===")
                for label, readme, output in (
                    ("v1 rule", r"\*\*v1 rule\*\*", r"v1 rule \(level 0\), no learner"),
                    ("filter, perfect reviewer", r"filter, perfect reviewer \(43 decisions\)",
                     r"filter on v1 flags \+ learner, perfect reviewer"),
                    ("filter, 1 in 10 wrong", r"filter, 1 decision in 10 wrong", r"filter on v1 flags \+ learner, 10% wrong"),
                    ("wider net, perfect reviewer", r"wider net, perfect reviewer \(67 decisions\)",
                     r"wider net \(level 1\) \+ learner, perfect reviewer"),
                    ("wider net, 1 in 10 wrong", r"wider net, 1 decision in 10 wrong", r"wider net \(level 1\) \+ learner, 10% wrong"),
                )
            ),
            *(
                Number(f"age, {label}, F1", md(readme, 1), out(output, 0),
                       readme_after="| age misrepresentation, reported seeds |", after="=== age_fraud ===")
                for label, readme, output in (
                    ("v1 rule", r"\*\*v1 rule\*\*", r"v1 rule \(level 0\), no learner"),
                    ("filter, perfect reviewer", r"filter, perfect reviewer \(17 decisions\)",
                     r"filter on v1 flags \+ learner, perfect reviewer"),
                    ("filter, 1 in 10 wrong", r"filter, 1 decision in 10 wrong", r"filter on v1 flags \+ learner, 10% wrong"),
                )
            ),
        ),
    ),
    Check(
        "rating",
        "Table tennis rating",
        ("ml.run_rating_eval",),
        (
            *(
                Number(f"Spearman, {label}, {gender}", md(readme, col), out(output, idx),
                       readme_after="Ranking, Spearman correlation", after="Across 5 seeds")
                for label, readme, output in (
                    ("point rating", r"\*\*point rating\*\*", r"point rating \(every point\)"),
                    ("Glicko-2", "Glicko-2", r"Glicko-2 \(match results\)"),
                    ("point win rate", "point win rate", r"baseline: point win rate"),
                    ("match win rate", "match win rate", r"baseline: match win rate"),
                )
                for gender, col, idx in (("girls", 1, 0), ("boys", 2, 1))
            ),
            *(
                Number(f"prediction, {label}, {what}", md(readme, col),
                       rf"^{output}\s+(?:\d\.\d{{4}}\s+){{{col - 1}}}(\d\.\d{{4}})(?!\S)",
                       readme_after="Predicting matches it has not seen", after="Across 5 seeds")
                for label, readme, output in (
                    ("point rating", r"\*\*point rating\*\*", r"point rating \(every point\)"),
                    ("Glicko-2", "Glicko-2", r"Glicko-2 \(match results\)"),
                    ("point win rate", "point win rate", r"baseline: point win rate"),
                    ("match win rate", "match win rate", r"baseline: match win rate"),
                )
                for what, col in (("Brier", 1), ("log loss", 2))
            ),
        ),
    ),
    Check(
        "rating-by-level",
        "Table tennis rating: what if strong players mostly met strong fields?",
        ("ml.run_rating_eval", "--schedule", "by-level"),
        tuple(
            Number(f"Spearman by level, {label}, {gender}", md(readme, col), out(output, idx),
                   readme_after="| Spearman, by-level schedule |", after="Across 5 seeds")
            for label, readme, output in (
                ("point rating", r"\*\*point rating\*\*", r"point rating \(every point\)"),
                ("Glicko-2", "Glicko-2", r"Glicko-2 \(match results\)"),
                ("point win rate", "point win rate", r"baseline: point win rate"),
                ("match win rate", "match win rate", r"baseline: match win rate"),
            )
            for gender, col, idx in (("girls", 1, 0), ("boys", 2, 1))
        ),
    ),
    Check(
        "pro",
        "Pro tier: breakouts and finishing",
        ("ml.run_pro_eval",),
        (
            *(
                Number(f"breakouts, {label}, {what}", md(readme, col), out(output, idx))
                for label, readme, output in (
                    ("v1", r"\*\*v1\*\*", "v1, all seeds"),
                    ("v1 without the age window", "v1 without the age window", "v1, no age window, all seeds"),
                    ("per 90 rate", "first version, per 90 rate", "per 90 rate, all seeds"),
                    ("minutes only", "minutes only", "minutes only, all seeds"),
                )
                for what, col, idx in (("TP", 1, 0), ("FP", 2, 1), ("FN", 3, 2), ("F1", 6, 9))
            ),
            Number('one season called "above"', md(r'one season called "above"', 1), rf"^  one season 'above':\s+{NUM}"),
            Number('one season "above", truly better', md(r'one season called "above"', 2),
                   rf"^  one season 'above':[^\n]*finishers {NUM}"),
            Number('all seasons called "above"', md(r'all seasons pooled, called "above"', 1), rf"^  all seasons 'above':\s+{NUM}"),
            Number('all seasons "above", truly better', md(r'all seasons pooled, called "above"', 2),
                   rf"^  all seasons 'above':[^\n]*finishers {NUM}"),
            Number("next season's goals, MAE from npxG per 90", md(r"\*\*npxG per 90\*\*", 1),
                   rf"predicted by this season's npxG per 90\s+{NUM}"),
            Number("next season's goals, MAE from position average", md("position average", 1),
                   rf"predicted by this season's position average\s+{NUM}"),
            Number("next season's goals, MAE from goals per 90", md("goals per 90", 1),
                   rf"predicted by this season's goals per 90\s+{NUM}"),
        ),
    ),
    Check(
        "gap",
        "Team gap analysis",
        ("ml.run_gap_eval",),
        (
            *(
                Number(f"team statistic, {label}, {what}", md(readme, col), out(output, idx))
                for label, readme, output in _GAP_TEAM_ROWS
                for what, col, idx in (("reporting r", 2, 0), ("bottom third kept", 3, 1))
            ),
            *(
                Number(f"player statistics, median reliability at {minutes} minutes", md(r"\*\*median\*\*", col),
                       out("median", idx))
                for minutes, col, idx in (("300", 1, 0), ("450", 2, 1), ("900", 3, 3), ("1800", 4, 6))
            ),
        ),
    ),
    Check(
        "report",
        "Scouting report",
        ("ml.run_report_eval",),
        (
            *(
                Number(f"level against true quality, {label}", md(label, 1), out(output, 5),
                       after="Scouting report level against true quality")
                for label, output in _REPORT_GROUPS
            ),
            *(
                Number(f"baseline, minutes played, {label}", md(label, 2), out(output, 5),
                       after="Baseline: minutes played")
                for label, output in _REPORT_GROUPS
            ),
            Number("level, all groups", md(r"\*\*All groups, mean\*\*", 1), out(r"all groups \(mean\)", 0),
                   after="Scouting report level against true quality"),
            Number("baseline, all groups", md(r"\*\*All groups, mean\*\*", 2), out(r"all groups \(mean\)", 0),
                   after="Baseline: minutes played"),
            Number("shortlist, players", md("Shortlist", 1), rf"^  Shortlist\s+{NUM} players"),
            Number("shortlist, in the top third", md("Shortlist", 2), rf"^  Shortlist[^\n]*players, {NUM} in the top"),
            Number("not now, players", md("Not now", 1), rf"^  Not now\s+{NUM} players"),
            Number("not now, in the bottom third", md("Not now", 2), rf"^  Not now[^\n]*players, {NUM} in the bottom"),
        ),
    ),
    Check(
        "similarity-20",
        "Player similarity",
        ("ml.run_similarity_eval", "--seed-sweep", *TWENTY),
        (
            Number("football, same kind of position", md(r"football, same kind of position \(never read\)", 1),
                   rf"^  role \(position group\): {NUM} of the 5"),
            Number("football, same kind of position, chance", md(r"football, same kind of position \(never read\)", 2),
                   rf"^  role \(position group\):[^\n]*chance {NUM}"),
            Number("football, level", md("football, level: share of the gap from random to best", 1),
                   rf"^  level, [^\n]*similarity [\d.]+ \({NUM} of the way", after="football:"),
            Number("football, level, shots per 90 alone", md("football, level: share of the gap from random to best", 3),
                   rf"^  level, [^\n]*shots per 90 alone [\d.]+ \({NUM}\)", after="football:"),
            Number("table tennis, level", md("table tennis, level", 1),
                   rf"^  level, [^\n]*similarity [\d.]+ \({NUM} of the way", after="table_tennis:"),
            Number("table tennis, level, points share alone", md("table tennis, level", 3),
                   rf"^  level, [^\n]*share of points won alone [\d.]+ \({NUM}\)", after="table_tennis:"),
            Number("table tennis, same playing style", md(r"table tennis, same playing style \(not used by the generator\)", 1),
                   rf"^  playing style [^\n]*: {NUM} of the 5"),
        ),
    ),
    Check(
        "identity",
        "Player identity",
        ("ml.run_identity_eval",),
        (
            *(
                Number(f"{world}, {label}, {what}", md(readme, col), out(output, idx),
                       readme_after=readme_after, after=after)
                for world, readme_after, after in (
                    ("as generated", "| *as generated* |", "as generated:"),
                    ("hard", "| *hard* |", "hard:"),
                )
                # "engine, now" is the engine as it runs: the output's `measured-tf` row (#119).
                # The output's plain `measured` row is a method the README does not publish.
                for label, readme, output in (
                    ("duplicate v1", "duplicate v1", "  duplicate v1"),
                    ("engine, no labels", "engine, no labels", "  engine, em"),
                    ("engine, now", r"\*\*engine, now\*\*", "  engine, measured-tf"),
                )
                for what, col, idx in (
                    ("pairs found", 1, 0), ("wrong", 2, 1), ("missed", 3, 2), ("F1", 6, 5), ("B-cubed F1", 7, 7),
                )
            ),
            *(
                # The output prints v1, em, measured and measured-tf; the README's columns are
                # v1, no labels (em) and now (measured-tf), so "now" is the fourth percentage.
                Number(f"hard, recall when {label}, {method}", md(label, col),
                       rf"^    {key}\s+\(\s*\d+ pairs\)\s+(?:[\d.]+%\s+){{{skip}}}{NUM}")
                for label, key in (
                    ("nothing", "none"), ("spelled in Latin", "latin"),
                    ("no date of birth", "no_dob"), ("at another club", "other_club"),
                )
                for method, col, skip in (("v1", 2, 0), ("no labels", 3, 1), ("now", 4, 3))
            ),
        ),
    ),
    Check(
        "measurement",
        "Who to measure next: reported seeds",
        ("ml.run_measurement_eval",),
        _measurement("reported seeds", "| *reported seeds (20260827, 7, 99, 404, 555)"),
    ),
    Check(
        "measurement-fresh",
        "Who to measure next: fresh seeds",
        ("ml.run_measurement_eval", "--fresh"),
        _measurement("fresh seeds", "| *fresh seeds (3001 to 3005)"),
    ),
    Check(
        "measurement-paired",
        "Who to measure next: the paired comparison over ten seeds",
        ("ml.run_measurement_eval", "--paired"),
        (*_paired("0.5"), *_paired("1.0"), *_paired("1.5")),
    ),
    Check(
        "backtest",
        "The late-bloomer backtest, 212 players",
        ("ml.run_backtest", "--seed-sweep", *FIVE),
        (
            Number("late bloomers measured 3+ times, flagged",
                   r"^\| late bloomers the system had measured 3\+ times \|[^|\n]*\(\d+%, (\d+) of",
                   rf"^  with 3\+ height readings at the cut: late bloomers flagged {NUM} of"),
            Number("other small players measured 3+ times, flagged",
                   r"^\| other small players measured 3\+ times \|[^|\n]*\(\d+%, (\d+) of",
                   rf"^  with 3\+ height readings[^\n]*others flagged {NUM} of"),
        ),
    ),
    Check(
        "backtest-1000",
        "The late-bloomer backtest, 1,000 players",
        ("ml.run_backtest", "--seed-sweep", *FIVE, "--players", "1000"),
        (
            Number("late bloomers measured 3+ times, flagged",
                   r"^\| late bloomers the system had measured 3\+ times \|[^|\n]*\*\*, (\d+) of",
                   rf"^  with 3\+ height readings at the cut: late bloomers flagged {NUM} of"),
            Number("late bloomers measured 3+ times, of",
                   r"^\| late bloomers the system had measured 3\+ times \|[^|\n]*\*\*, \d+ of (\d+)",
                   rf"^  with 3\+ height readings at the cut: late bloomers flagged \d+ of {NUM}"),
            Number("other small players measured 3+ times, flagged",
                   r"^\| other small players measured 3\+ times \|[^|\n]*\*\*, (\d+) of",
                   rf"^  with 3\+ height readings[^\n]*others flagged {NUM} of"),
            Number("other small players measured 3+ times, of",
                   r"^\| other small players measured 3\+ times \|[^|\n]*\*\*, \d+ of (\d+)",
                   rf"^  with 3\+ height readings[^\n]*others flagged \d+ of {NUM}"),
            Number("late bloomers measured fewer than 3 times, of",
                   r"^\| late bloomers measured fewer than 3 times \|[^|\n]*\*\*, \d+ of (\d+)",
                   rf"^  with fewer, the detector cannot fire at all: late bloomers flagged \d+ of {NUM}"),
            Number("median follow-up, years", md("median follow-up from the cut", 1),
                   rf"^median follow-up from the cut to the outcome\s+{NUM}"),
            Number("late bloomers the label finds", r"^\| late bloomers the label finds \|[^|\n]*, (\d+) of",
                   rf"^'caught up' vs the planted truth: recall {NUM} of"),
            Number("players the label finds who are late bloomers",
                   r"^\| players the label finds who are late bloomers \|[^|\n]*, \d+ of (\d+)",
                   rf"^'caught up' vs the planted truth:[^\n]*precision \d+ of {NUM}"),
            Number("small players with an outcome", md("small players with an outcome", 1),
                   rf"^players with an outcome a year or more later\s+\d+ of \d+ \({NUM}"),
            Number("recall scored on everyone", md("late bloomer recall, scored on everyone", 1),
                   rf"^late bloomers caught, scored on everyone\s+\d+ of \d+ \({NUM}"),
            Number("recall scored on stayers", md("late bloomer recall, scored on stayers only", 1),
                   rf"^late bloomers caught, scored on stayers only\s+\d+ of \d+ \({NUM}"),
            Number("players observed to catch up", md("players observed to catch up", 1),
                   rf"^of those who caught up, flagged at the time\s+\d+ of {NUM}"),
        ),
    ),
    Check(
        "backtest-1000-release",
        "The late-bloomer backtest: players who disappear",
        ("ml.run_backtest", "--seed-sweep", *FIVE, "--players", "1000", "--attrition"),
        (
            Number("small players with an outcome, with release", md("small players with an outcome", 2),
                   rf"^players with an outcome a year or more later\s+\d+ of \d+ \({NUM}"),
            Number("recall scored on everyone, with release", md("late bloomer recall, scored on everyone", 2),
                   rf"^late bloomers caught, scored on everyone\s+\d+ of \d+ \({NUM}"),
            Number("recall scored on stayers, with release", md("late bloomer recall, scored on stayers only", 2),
                   rf"^late bloomers caught, scored on stayers only\s+\d+ of \d+ \({NUM}"),
            Number("players observed to catch up, with release", md("players observed to catch up", 2),
                   rf"^of those who caught up, flagged at the time\s+\d+ of {NUM}"),
        ),
    ),
)

# Published evaluations this cannot run, and why. Shown by --list and at the end of every run.
NOT_CHECKED: dict[str, str] = {
    "talent estimates": "needs the FootyStats download (python -m ml.run_estimate_eval --cache-dir ...)",
    "expected goals": "needs StatsBomb's open data (python -m ml.run_xg_eval --data-dir ...)",
    "plays most like": "needs StatsBomb's open data (python -m ml.run_style_eval --data-dir ...)",
    "identity, real data": "needs a database export (python -m ml.run_identity_eval --real-export DIR)",
    "assistant": "needs the local Ollama model (apps/api/eval)",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_results_check", description=__doc__.split("\n")[0])
    parser.add_argument("--only", nargs="+", metavar="NAME", help="run only these checks")
    parser.add_argument("--list", action="store_true", help="list the checks and what is not checked")
    parser.add_argument("--jobs", type=int, default=3, help="evaluations run at once (default 3)")
    parser.add_argument("--keep-output", type=Path, default=None, metavar="DIR",
                        help="also save each evaluation's output here, as NAME.txt")
    parser.add_argument("--from-output", type=Path, default=None, metavar="DIR",
                        help="compare outputs saved by --keep-output instead of running anything")
    parser.add_argument("--verbose", action="store_true",
                        help="print every number with both values, not only the ones that differ")
    args = parser.parse_args(argv)

    if args.list:
        for check in CHECKS:
            print(f"{check.name:24} {len(check.numbers):3} numbers  python -m {' '.join(check.command)}")
        for name, why in sorted(NOT_CHECKED.items()):
            print(f"{name:24} not checked: {why}")
        return 0

    known = {c.name for c in CHECKS}
    unknown = set(args.only or ()) - known
    if unknown:
        print(f"No such check: {', '.join(sorted(unknown))}. Known: {', '.join(sorted(known))}",
              file=sys.stderr)
        return 2
    chosen = [c for c in CHECKS if not args.only or c.name in args.only]
    readme_text = README.read_text(encoding="utf-8")
    if args.from_output is not None:
        results = [from_saved(c, readme_text, args.from_output) for c in chosen]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            results = list(pool.map(lambda c: run(c, readme_text, keep=args.keep_output), chosen))
    print(render(results, verbose=args.verbose))
    ok = all(o.status == "same" for r in results for o in r.outcomes)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
