"""Persisting the dataset.

The primary target is the database, through the ORM models. That is the point of
building model instances rather than dictionaries: the insert is the same code
path the API uses, so a column renamed in `apps/api` breaks this pipeline
immediately instead of producing a JSON file that fails to load weeks later.

A JSON export is still available, because the ML track needs data before anyone
has Postgres running. It is derived from the ORM instances by walking the
mapper's column attributes, so the keys in the file are the model's attribute
names by construction. There is no second, hand-maintained list of field names to
drift out of sync — which is exactly how `audit_logs.json` ended up with a
`metadata` key that `AuditLog(**row)` could not accept.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect

from .dataset import Dataset


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def row_to_dict(instance) -> dict:
    """Serialise an ORM instance by its mapped attribute names.

    Attribute names, not column names: `AuditLog.event_metadata` maps to the
    `metadata` column, and the attribute name is the one that round-trips through
    `AuditLog(**row)`.
    """
    mapper = inspect(instance).mapper
    return {attr.key: getattr(instance, attr.key) for attr in mapper.column_attrs}


def export_json(dataset: Dataset, out_dir: Path) -> list[Path]:
    """Write one file per table plus ground_truth.json."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name, rows in dataset.in_insert_order():
        path = out_dir / f"{name}.json"
        payload = [row_to_dict(r) for r in rows]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
            encoding="utf-8",
        )
        written.append(path)

    return written


def verify_round_trip(dataset: Dataset) -> None:
    """Rebuild every row from its serialised form and re-instantiate the model.

    This is the check that would have caught the `metadata` / `event_metadata`
    mismatch at generation time. It is cheap, so it runs on every export rather
    than living only in the test suite.
    """
    for name, rows in dataset.in_insert_order():
        if not rows:
            continue
        sample = rows[0]
        model = type(sample)
        payload = row_to_dict(sample)
        try:
            model(**payload)
        except TypeError as exc:  # pragma: no cover - defensive
            raise AssertionError(
                f"{model.__name__} cannot be rebuilt from its own serialised row "
                f"({name}): {exc}"
            ) from exc


def write_to_database(dataset: Dataset, database_url: str, *, truncate: bool = False) -> dict:
    """Insert the dataset through a SQLAlchemy session.

    Requires a live Postgres: the models use JSONB, ARRAY, INET and
    `gen_random_uuid()`, none of which SQLite provides. `docker compose up db`
    from the repo root is enough.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from .orm import Base

    engine = create_engine(database_url, future=True)
    counts: dict = {}

    with Session(engine) as session:
        if truncate:
            for name, rows in reversed(dataset.in_insert_order()):
                if rows:
                    session.execute(
                        Base.metadata.tables[type(rows[0]).__tablename__].delete()
                    )
            session.flush()

        for name, rows in dataset.in_insert_order():
            session.add_all(rows)
            session.flush()
            counts[name] = len(rows)
        session.commit()

    return counts
