"""Health-check endpoints.

`/health` proves the API process is up. `/health/db` proves it can reach PostgreSQL. The web
app calls these on its landing page to prove the local stack is wired together correctly.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check. Returns ok if the API process is running."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness check. Runs a trivial query to confirm the database is reachable."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001  (report any failure as an unhealthy database)
        return {"status": "error", "database": "unreachable"}
    return {"status": "ok", "database": "reachable"}
