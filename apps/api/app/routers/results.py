"""Table tennis results imported from a spreadsheet (app/services/results_import.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.schemas.core import CamelModel
from app.services import results_import
from app.services.access import Caller

router = APIRouter(tags=["results"])


class ResultsImportIn(CamelModel):
    """Results as CSV text. The browser reads the file and sends its text; nothing is stored
    but the match records it creates."""

    csv: str = Field(max_length=1_000_000)


class ResultRowOut(CamelModel):
    line: int
    # "Player A v Player B", as written in the file.
    name: str
    event: str = ""
    # ready | duplicate | rejected; after an import, imported instead of ready.
    status: str
    problems: list[str] = []
    warnings: list[str] = []
    # Worked out from the scores, from player A's side: "3-1 (44-35 points), best of 5".
    score: str | None = None


class ResultsImportOut(CamelModel):
    file_problems: list[str] = []
    rows: list[ResultRowOut] = []
    counts: dict[str, int] = {}
    saved: bool = False
    records_written: int = 0


def _may_import(caller: Caller) -> None:
    if not (caller.is_federation or caller.is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Results are imported by federation staff.",
        )


def _rows(result: results_import.Preview) -> list[ResultRowOut]:
    out = []
    for row in result.rows:
        score = None
        if row.records:
            # The first record is player A's when A is registered, else B's; it names whose.
            player, _, m = row.records[0]
            score = (
                f"{m['sets_won']}-{m['sets_lost']} ({m['points_won']}-{m['points_lost']} points), "
                f"best of {m['best_of']}, for {player.full_name}"
            )
        out.append(ResultRowOut(
            line=row.line, name=row.name, event=row.event, status=row.status,
            problems=row.problems, warnings=row.warnings, score=score,
        ))
    return out


@router.post("/results/import/preview", response_model=ResultsImportOut)
def preview(
    payload: ResultsImportIn,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> ResultsImportOut:
    """What importing this file would do, row by row. Nothing is saved."""
    _may_import(caller)
    result = results_import.preview(db, payload.csv)
    return ResultsImportOut(
        file_problems=result.file_problems, rows=_rows(result), counts=result.counts()
    )


@router.post("/results/import", response_model=ResultsImportOut)
def import_results(
    payload: ResultsImportIn,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> ResultsImportOut:
    """Save every ready row, in one transaction, after checking the file again."""
    _may_import(caller)
    result, written = results_import.commit(db, text=payload.csv, actor_user_id=caller.user_id)
    if result.file_problems:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Nothing was saved.", "problems": result.file_problems},
        )
    db.commit()
    counts = {s: sum(r.status == s for r in result.rows) for s in ("imported", "duplicate", "rejected")}
    return ResultsImportOut(rows=_rows(result), counts=counts, saved=True, records_written=written)
