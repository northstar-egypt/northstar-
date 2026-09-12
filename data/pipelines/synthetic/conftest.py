"""Put the repository root on sys.path for the test run.

`data/` and `data/pipelines/` are namespace packages with no `__init__.py`, so
pytest's default import mode inserts `data/pipelines` rather than the repo root,
and the tests' `from data.pipelines.synthetic import ...` would not resolve. This
makes `pytest data/pipelines/synthetic` work the same way from anywhere, and with
either `pytest` or `python -m pytest`.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
