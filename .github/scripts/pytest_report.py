"""Summarise a pytest JUnit report for CI, and fail when a suite only looked green.

    python .github/scripts/pytest_report.py REPORT.xml --title "API tests"
        [--fail-on-skip "No database at"] [--min-tests 1]

Writes a table (passed, failed, errors, skipped, and why each test skipped) to the job summary
($GITHUB_STEP_SUMMARY) so it shows on the pull request without opening the log, and exits 1 if:

- any test was skipped with a reason that contains a --fail-on-skip text. The API suite skips,
  rather than fails, when no database is reachable (apps/api/tests/conftest.py), so a run with
  a broken database would otherwise finish green having tested nothing; or
- fewer than --min-tests tests ran (passed + failed + errors), which also catches a collection
  that silently found nothing.

pytest's own exit code still decides failures and errors; this script only adds the two checks
pytest cannot make. Standard library only, so it runs before or after any pip install.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--title", required=True)
    ap.add_argument("--fail-on-skip", action="append", default=[],
                    help="fail if a skip reason contains this text (repeatable)")
    ap.add_argument("--min-tests", type=int, default=1)
    args = ap.parse_args()

    try:
        root = ET.parse(args.report).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"::error::{args.title}: no readable pytest report at {args.report} ({exc})")
        return 1

    counts = Counter()
    skip_reasons = Counter()
    for case in root.iter("testcase"):
        outcome = "passed"
        for child in case:
            if child.tag in ("failure", "error", "skipped"):
                outcome = {"failure": "failed", "error": "errors", "skipped": "skipped"}[child.tag]
                if child.tag == "skipped":
                    reason = (child.get("message") or child.text or "no reason given").strip()
                    skip_reasons[reason.splitlines()[0][:200]] += 1
                break
        counts[outcome] += 1

    ran = counts["passed"] + counts["failed"] + counts["errors"]
    problems = []
    for needle in args.fail_on_skip:
        hit = sum(n for reason, n in skip_reasons.items() if needle in reason)
        if hit:
            problems.append(f"{hit} test(s) skipped with a reason containing {needle!r}. "
                            "They did not run, so a green check would mean nothing.")
    if ran < args.min_tests:
        problems.append(f"only {ran} test(s) ran; at least {args.min_tests} expected.")

    lines = [f"### {args.title}", "",
             "| passed | failed | errors | skipped |", "|---:|---:|---:|---:|",
             f"| {counts['passed']} | {counts['failed']} | {counts['errors']} | {counts['skipped']} |", ""]
    if skip_reasons:
        lines += ["| skipped | reason |", "|---:|---|"]
        lines += [f"| {n} | {reason.replace('|', '/')} |" for reason, n in skip_reasons.most_common()]
        lines.append("")
    if problems:
        lines += [f"**Failed the guard:** {p}" for p in problems]
    summary = "\n".join(lines) + "\n"

    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(summary)
    for p in problems:
        print(f"::error title={args.title}::{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
