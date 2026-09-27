"""The sport modules, for ML code.

There is one validator for performance records, `apps/api/app/sports.py`, reading the module
files in `packages/shared/sports/`. The fraud detector's arithmetic rule uses it rather than
keeping its own list of football checks, so ingest validation and the detector cannot
disagree about what an impossible record is, and a new sport's rules reach the detector
without touching it.

`apps/api` is not an installed package, so it is located from the repository root, the same
way `ml/write_flags.py` and the synthetic generator do it. Importing it needs the pipelines
environment (`pip install -r data/pipelines/requirements.txt`), which the harnesses already
require to read a generated dataset.
"""

from __future__ import annotations

import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from app.sports import impossibilities, registry, validate  # noqa: E402

__all__ = ["impossibilities", "registry", "validate"]
