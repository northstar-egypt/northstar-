"""Bulk import of players from a spreadsheet (CSV), for an academy that already keeps records.

Two steps, and nothing is saved by the first:

1. **Preview** (`preview`): every row of the file gets a verdict. *ready*, *confirm* (it would
   save, but something looks unusual and a person should say yes: a reading outside the usual
   range, or a player who may already be on the platform), or *rejected*, with every reason.
2. **Import** (`commit`): the same file is checked again from scratch (the preview is never
   trusted), then every ready row and every confirm row the coach confirmed is saved, in one
   transaction, through the same `writes.create_player` the add player screen uses. Rejected
   rows are skipped and listed, to fix and upload again.

One row is one player: what the add player screen collects, including the signed consent form
and, optionally, one visit's readings. Measurement history is not imported yet.

Care
----
This is the most likely route for real data about real children to enter the system, so:

- Every row passes the same checks as a player typed in by hand (`writes.check_player`,
  `writes.check_measurements`, `writes.plausibility_warnings`), including the consent rule:
  no player without a signed form, and a named guardian for a minor.
- The file is read in memory and never stored. Only the players it creates are.
- Limits: `MAX_CHARS` and `MAX_ROWS`. A cell that starts like a spreadsheet formula (= + @, or
  - followed by a letter) is refused, because a name like that, exported to Excel later, would
  run as a formula on a staff member's machine.
- One audit record for the import (who, which organization, how many rows of each kind), plus
  the usual player.create and consent.grant records for each player it creates.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import names
from app.models.audit_log import AuditLog
from app.models.enums import PlayerStatus
from app.models.player import Player
from app.schemas.writes import PlayerCreateIn
from app.services import writes

MAX_CHARS = 1_000_000
MAX_ROWS = 500

# Column name -> what it means. Names are matched ignoring case, spaces and dashes.
COLUMNS: dict[str, str] = {
    "full_name": "Full name (required)",
    "known_as": "Name used day to day",
    "date_of_birth": "Date of birth, YYYY-MM-DD (required)",
    "gender": "male or female; required for sports open to both",
    "sport": "football or table_tennis (required)",
    "position": "As the sport module names it, e.g. ST, CB",
    "tier": "Football only: pro, youth or diaspora",
    "nationality": "Two-letter country codes, several separated by ; (e.g. EG;FR)",
    "egypt_eligible": "yes or no",
    "consent_signed": "yes: the sign-up consent form is signed (required)",
    "guardian_name": "Required for a player under 18",
    "measured_on": "Date of the readings below, YYYY-MM-DD",
    "height_cm": "Height in cm",
    "weight_kg": "Weight in kg",
    "sprint_10m_s": "10 m sprint in seconds",
    "confidence": "measured or estimated (default measured)",
}
REQUIRED = ("full_name", "date_of_birth", "sport", "consent_signed")
READINGS = ("height_cm", "weight_kg", "sprint_10m_s")
_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0", ""}


@dataclass
class Row:
    line: int  # line number in the file, counting the header as 1
    name: str
    status: str = "ready"  # ready | confirm | rejected
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    payload: PlayerCreateIn | None = None


@dataclass
class Preview:
    file_problems: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {s: sum(r.status == s for r in self.rows) for s in ("ready", "confirm", "rejected")}


def _key(header: str) -> str:
    return header.strip().lower().replace(" ", "_").replace("-", "_")


def _looks_like_formula(cell: str) -> bool:
    if not cell:
        return False
    if cell[0] in "=+@\t\r":
        return True
    return cell[0] == "-" and len(cell) > 1 and not (cell[1].isdigit() or cell[1] == ".")


def _read(
    text: str,
    columns: dict[str, str] = COLUMNS,
    required: tuple[str, ...] = REQUIRED,
    noun: str = "players",
) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """The file's problems, and its rows as (line, {column: cell}). Shared with the results
    import (services/results_import.py), which passes its own columns."""
    if len(text) > MAX_CHARS:
        return [f"The file is larger than {MAX_CHARS // 1000} KB. Split it into smaller files."], []
    text = text.lstrip("﻿")
    if not text.strip():
        return ["The file is empty."], []
    first = text.splitlines()[0]
    # Excel writes ; instead of , where the decimal separator is a comma.
    delimiter = ";" if first.count(";") > first.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except (StopIteration, csv.Error) as exc:
        return [f"The first line could not be read as column names ({exc})."], []
    keys = [_key(h) for h in header]
    problems = []
    unknown = [h for h, k in zip(header, keys) if k and k not in columns]
    if unknown:
        problems.append(
            "Unknown column(s): " + ", ".join(unknown) + ". Use the template's column names."
        )
    missing = [c for c in required if c not in keys]
    if missing:
        problems.append("Missing required column(s): " + ", ".join(missing) + ".")
    if len(set(k for k in keys if k)) != len([k for k in keys if k]):
        problems.append("A column appears twice.")
    if problems:
        return problems, []

    rows = []
    try:
        for record in reader:
            if not any(cell.strip() for cell in record):
                continue  # a blank line
            line = reader.line_num
            if len(rows) >= MAX_ROWS:
                return [f"More than {MAX_ROWS} {noun} in one file. Split it."], []
            cells = {k: (record[i].strip() if i < len(record) else "") for i, k in enumerate(keys) if k}
            if len(record) > len(keys):
                cells["__extra__"] = "yes"
            rows.append((line, cells))
    except csv.Error as exc:
        return [f"The file could not be read as CSV ({exc})."], []
    if not rows:
        return [f"The file has column names but no {noun}."], []
    return [], rows


def _readable(error: ValidationError) -> list[str]:
    fields = {
        "fullName": "full_name", "dateOfBirth": "date_of_birth", "sex": "gender",
        "primarySport": "sport", "nationality": "nationality", "position": "position",
        "tier": "tier", "knownAs": "known_as", "guardianName": "guardian_name",
        "measuredAt": "measured_on", "value": "reading", "confidence": "confidence",
    }
    out = []
    for e in error.errors():
        where = next((fields[str(p)] for p in reversed(e["loc"]) if str(p) in fields), None)
        message = e["msg"].removeprefix("Value error, ")
        out.append(f"{where}: {message}" if where else message)
    return out


def _to_payload(cells: dict[str, str], row: Row) -> PlayerCreateIn | None:
    for column, cell in cells.items():
        if _looks_like_formula(cell):
            row.problems.append(
                f"{column} starts like a spreadsheet formula ({cell[:12]!r}). Remove the leading "
                f"character."
            )
    if cells.get("__extra__"):
        row.problems.append("This row has more cells than there are columns.")

    consent = cells.get("consent_signed", "").lower()
    if consent not in _YES | _NO:
        row.problems.append("consent_signed must be yes or no.")
    eligible = cells.get("egypt_eligible", "").lower()
    if eligible not in _YES | _NO:
        row.problems.append("egypt_eligible must be yes or no.")

    readings = []
    for column in READINGS:
        raw = cells.get(column, "")
        if not raw:
            continue
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            row.problems.append(f"{column} is not a number ({raw!r}).")
            continue
        spec = writes.METRICS[column]
        readings.append(
            {
                "metric": column,
                "value": value,
                "unit": spec.unit,
                "confidence": cells.get("confidence", "").lower() or "measured",
            }
        )
    measured_on = cells.get("measured_on", "")
    if readings and not measured_on:
        row.problems.append("measured_on is required when there are readings.")
    if measured_on and not readings:
        row.problems.append("measured_on is given but there are no readings.")
    if row.problems:
        return None

    try:
        return PlayerCreateIn.model_validate(
            {
                "fullName": cells.get("full_name", ""),
                "knownAs": cells.get("known_as") or None,
                "dateOfBirth": cells.get("date_of_birth", ""),
                "sex": cells.get("gender", "").lower() or None,
                "nationality": [c.strip().upper() for c in cells.get("nationality", "").split(";") if c.strip()],
                "isEgyptEligible": eligible in _YES,
                "primarySport": cells.get("sport", "").lower(),
                "tier": cells.get("tier", "").lower() or None,
                "position": cells.get("position") or None,
                "consent": {"signed": consent in _YES, "guardianName": cells.get("guardian_name") or None},
                "measurements": (
                    {"measuredAt": measured_on, "metrics": readings} if readings else None
                ),
            }
        )
    except ValidationError as exc:
        row.problems.extend(_readable(exc))
        return None


def preview(db: Session, text: str, today: date | None = None) -> Preview:
    """Every row's verdict. Saves nothing."""
    today = today or date.today()
    result = Preview()
    result.file_problems, records = _read(text)
    if result.file_problems:
        return result

    existing = db.execute(
        select(Player.id, Player.full_name, Player.date_of_birth).where(
            Player.status != PlayerStatus.MERGED
        )
    ).all()
    by_birth: dict[date, list[tuple[uuid.UUID, str]]] = {}
    for pid, full_name, dob in existing:
        if dob is not None:
            by_birth.setdefault(dob, []).append((pid, full_name))
    seen_in_file: dict[tuple[date, str], int] = {}

    for line, cells in records:
        row = Row(line=line, name=cells.get("full_name", ""))
        payload = _to_payload(cells, row)
        if payload is not None:
            row.problems += writes.check_player(payload, today)
            if payload.measurements is not None:
                row.problems += writes.check_measurements(
                    payload.measurements, payload.date_of_birth, today
                )
        if row.problems or payload is None:
            row.status = "rejected"
            result.rows.append(row)
            continue

        row.payload = payload
        if payload.measurements is not None:
            for w in writes.plausibility_warnings(db, None, payload.measurements):
                row.warnings.append(w.get("message") or str(w))
        for pid, full_name in by_birth.get(payload.date_of_birth, []):
            if names.matches(payload.full_name, full_name):
                row.warnings.append(
                    f"May already be on the platform: {full_name}, same date of birth."
                )
        key = (payload.date_of_birth, payload.full_name.lower())
        if key in seen_in_file:
            row.warnings.append(f"Same name and date of birth as line {seen_in_file[key]}.")
        seen_in_file.setdefault(key, line)
        if row.warnings:
            row.status = "confirm"
        result.rows.append(row)
    return result


def commit(
    db: Session,
    *,
    text: str,
    confirmed_lines: set[int],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    today: date | None = None,
) -> tuple[Preview, list[tuple[int, Player]]]:
    """Check the file again and save what may be saved, in one transaction. The caller commits."""
    result = preview(db, text, today)
    created: list[tuple[int, Player]] = []
    if result.file_problems:
        return result, created
    for row in result.rows:
        if row.status == "rejected" or row.payload is None:
            continue
        if row.status == "confirm" and row.line not in confirmed_lines:
            continue
        payload = row.payload
        if payload.measurements is not None and row.status == "confirm":
            payload.measurements.acknowledge_warnings = True
        player, _, _ = writes.create_player(
            db,
            payload=payload,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            today=today,
        )
        created.append((row.line, player))
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="players.import",
            entity_type="organization",
            entity_id=organization_id,
            event_metadata={
                "rows": len(result.rows),
                "created": len(created),
                "confirmed_lines": sorted(confirmed_lines & {r.line for r in result.rows}),
                "rejected_lines": [r.line for r in result.rows if r.status == "rejected"],
                "skipped_unconfirmed_lines": [
                    r.line
                    for r in result.rows
                    if r.status == "confirm" and r.line not in confirmed_lines
                ],
            },
        )
    )
    db.flush()
    return result, created
