"""Import table tennis match results from a spreadsheet (CSV), for results copied by hand from
the official ITTF and WTT sites.

Why by hand, and not a scraper: results.ittf.link and ittf.com answer automated requests with
403 Forbidden, and results.ittf.link's robots.txt shuts out its /api/ path; worldtabletennis.com
offers no public API. A scraper would have to get round that, so there is none. A person reads
the results in a browser and copies them into the template (docs/results-import.md). The
file stays on their machine: real results are never committed (CLAUDE.md).

One row is one match, as results are published: the date, the event, the two players and the
game scores ("11-7, 9-11, 11-5, 11-8"). Everything else is worked out from the scores, never
guessed: best of (from the winner's number of games), sets won and lost, points won and lost.
Service winners and unforced errors are not published and are left out; the sport module does
not require them.

Two steps, as the player import (services/imports.py): a preview that saves nothing, then an
import that checks the file again from scratch and saves the ready rows in one transaction.

- **Who.** Federation staff and admins: results cover players of every club, which is the
  national body's work. A coach would be matching opponents from clubs they cannot see.
- **Players.** Each name is matched to a registered table tennis player by sound, in Arabic or
  Latin spelling (app/names.py), so "ELSAYED Ahmed" finds "أحمد السيد"; a name typed exactly
  wins over ones that only sound alike. A name that matches several players is refused unless
  the row gives the id (`player_a_id`, `player_b_id`).
- **Records.** When both players are registered, each gets a match record naming the other,
  as the generator writes them (decision 0004), so the match counts toward both ratings. When
  only one is, they get a record and nothing at all is stored about the other player, who may
  be a child with no consent form. When neither is, the row is refused.
- **Checks.** Every game must be a finished game (to 11, by two), the match must stop when one
  player wins, and each record passes the sport module's rules (`sports.validate`). A match
  already on record (same players, date and score) is skipped, so importing a file twice
  is safe. Men and women are never matched against each other.
- One audit record per import: who, how many rows of each kind, and the events named.

TODO: the event name is shown and audited but not stored with the match; the match record has
no field for it, and adding one is a schema change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import names, sports
from app.models.audit_log import AuditLog
from app.models.enums import PerformanceSource, PlayerStatus
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.services.imports import _looks_like_formula, _read

SCHEMA_REF = "table_tennis.match.v1"
MAX_ROWS = 500

COLUMNS: dict[str, str] = {
    "date": "Date of the match, YYYY-MM-DD (required)",
    "event": "The event, e.g. WTT Youth Contender Cairo 2026",
    "player_a": "One player's name as published (required)",
    "player_b": "The other player's name (required)",
    "games": "Game scores from player A's side, e.g. 11-7, 9-11, 11-5, 11-8 (required)",
    "best_of": "3, 5 or 7; worked out from the scores when left empty",
    "player_a_id": "Player A's NorthStar id, when the name matches more than one player",
    "player_b_id": "Player B's NorthStar id",
}
REQUIRED = ("date", "player_a", "player_b", "games")

_GAME = re.compile(r"(\d{1,2})\s*[-:]\s*(\d{1,2})")


@dataclass
class Row:
    line: int
    name: str
    event: str = ""
    status: str = "ready"  # ready | rejected | duplicate
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # What would be written: (player, opponent or None, metrics), one per registered player.
    records: list[tuple[Player, Player | None, dict]] = field(default_factory=list)
    played_on: date | None = None


@dataclass
class Preview:
    file_problems: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            s: sum(r.status == s for r in self.rows) for s in ("ready", "duplicate", "rejected")
        }


def parse_games(text: str) -> tuple[list[tuple[int, int]], list[str]]:
    """Game scores from player A's side, and every problem with them."""
    games = [(int(a), int(b)) for a, b in _GAME.findall(text)]
    leftover = _GAME.sub("", text).replace(",", " ").replace(";", " ").replace("(", " ").replace(")", " ")
    problems = []
    if leftover.strip():
        problems.append(f"Could not read the scores \"{text}\"; write them like 11-7, 9-11, 11-5.")
    if not games:
        problems.append("No game scores.")
    for i, (a, b) in enumerate(games, start=1):
        high, low = max(a, b), min(a, b)
        finished = (high == 11 and low <= 9) or (high > 11 and high - low == 2)
        if not finished:
            problems.append(f"Game {i} ({a}-{b}) is not a finished game: to 11, by two.")
    return games, problems


def match_metrics(games: list[tuple[int, int]], best_of: int | None) -> tuple[dict | None, list[str]]:
    """Player A's match record from the game scores, or the reasons there is none."""
    sets_a = sum(a > b for a, b in games)
    sets_b = len(games) - sets_a
    winner = max(sets_a, sets_b)
    if best_of is None and (sets_a == sets_b or winner < 2):
        return None, [f"Not a finished match: the scores give {sets_a}-{sets_b}."]
    best_of = best_of or 2 * winner - 1
    problems = []
    if best_of not in (3, 5, 7):
        problems.append(f"A match is best of 3, 5 or 7, not {best_of}.")
    elif winner != best_of // 2 + 1:
        problems.append(
            f"Not a finished best of {best_of}: the winner needs {best_of // 2 + 1} games, "
            f"the scores give {sets_a}-{sets_b}."
        )
    else:
        # The match ends when one player has won: no game may follow the deciding one.
        need, a, b = best_of // 2 + 1, 0, 0
        for i, (x, y) in enumerate(games, start=1):
            a, b = a + (x > y), b + (y > x)
            if (a == need or b == need) and i < len(games):
                problems.append(f"The match was decided in game {i}, but more games follow.")
                break
    if problems:
        return None, problems
    return {
        "best_of": best_of,
        "sets_won": sets_a,
        "sets_lost": sets_b,
        "points_won": sum(a for a, _ in games),
        "points_lost": sum(b for _, b in games),
    }, []


def mirrored(metrics: dict) -> dict:
    return {
        "best_of": metrics["best_of"],
        "sets_won": metrics["sets_lost"],
        "sets_lost": metrics["sets_won"],
        "points_won": metrics["points_lost"],
        "points_lost": metrics["points_won"],
    }


def _normal(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def _resolve(name: str, given_id: str, players: list[Player]) -> tuple[Player | None, str | None]:
    """The registered player a name means; None and a reason when it is unclear; (None, None)
    when nobody matches, which means the player is not on the platform."""
    if given_id:
        found = next((p for p in players if str(p.id) == given_id), None)
        if found is None:
            return None, f"No registered table tennis player has the id {given_id}."
        return found, None
    exact = [p for p in players if _normal(name) in (_normal(p.full_name), _normal(p.known_as))]
    found = exact or [p for p in players if names.matches(name, p.full_name, p.known_as)]
    if len(found) > 1:
        return None, (
            f"\"{name}\" matches {len(found)} registered players; give the right one's id in "
            "the id column."
        )
    return (found[0], None) if found else (None, None)


def _on_record(db: Session, player: Player, opponent: Player | None, played_on: date, metrics: dict) -> bool:
    stmt = (
        select(PerformanceEntry.metrics)
        .where(PerformanceEntry.player_id == player.id)
        .where(PerformanceEntry.schema_ref == SCHEMA_REF)
        .where(PerformanceEntry.period_start == played_on)
    )
    stmt = stmt.where(
        PerformanceEntry.opponent_player_id == opponent.id if opponent
        else PerformanceEntry.opponent_player_id.is_(None)
    )
    keys = ("sets_won", "sets_lost", "points_won", "points_lost")
    return any(
        all(m.get(k) == metrics[k] for k in keys) for m in db.execute(stmt).scalars()
    )


def preview(db: Session, text: str, today: date | None = None) -> Preview:
    """Every row's verdict. Saves nothing."""
    today = today or date.today()
    problems, raw = _read(text, COLUMNS, REQUIRED, noun="matches")
    if problems:
        return Preview(file_problems=problems)
    if len(raw) > MAX_ROWS:
        return Preview(file_problems=[f"More than {MAX_ROWS} matches in one file. Split it."])

    players = list(
        db.execute(
            select(Player)
            .where(Player.primary_sport == "table_tennis")
            .where(Player.status != PlayerStatus.MERGED)
        ).scalars()
    )
    modules = sports.registry()
    seen: set = set()
    out = Preview()
    for line, cells in raw:
        row = Row(line=line, name=f"{cells.get('player_a', '')} v {cells.get('player_b', '')}",
                  event=cells.get("event", ""))
        out.rows.append(row)
        if cells.get("__extra__"):
            row.problems.append("The row has more cells than there are columns.")
        if any(_looks_like_formula(v) for k, v in cells.items() if k != "games"):
            row.problems.append("A cell starts like a spreadsheet formula (= + - @).")

        try:
            row.played_on = date.fromisoformat(cells.get("date", ""))
            if row.played_on > today:
                row.problems.append("The date is in the future.")
        except ValueError:
            row.problems.append("The date must be written YYYY-MM-DD.")

        games, game_problems = parse_games(cells.get("games", ""))
        row.problems += game_problems
        best_of = None
        if cells.get("best_of"):
            try:
                best_of = int(cells["best_of"])
            except ValueError:
                row.problems.append("best_of must be 3, 5 or 7.")
        metrics = None
        if games and not game_problems:
            metrics, match_problems = match_metrics(games, best_of)
            row.problems += match_problems

        a, a_problem = _resolve(cells.get("player_a", ""), cells.get("player_a_id", ""), players)
        b, b_problem = _resolve(cells.get("player_b", ""), cells.get("player_b_id", ""), players)
        row.problems += [p for p in (a_problem, b_problem) if p]
        if not a_problem and not b_problem:
            if a is None and b is None:
                row.problems.append("Neither player is registered on NorthStar; add them first.")
            elif a is not None and b is not None and a.id == b.id:
                row.problems.append("Both names are the same player.")
            elif a is not None and b is not None and a.sex != b.sex:
                row.problems.append("Men and women are not compared; check the names.")
            for side, who, name in (("A", a, cells.get("player_a")), ("B", b, cells.get("player_b"))):
                if who is None:
                    row.warnings.append(
                        f"Player {side}, {name}, is not on NorthStar: nothing about them is stored."
                    )
                elif row.played_on and who.date_of_birth and row.played_on < who.date_of_birth:
                    row.problems.append(f"The date is before player {side} was born.")

        if row.problems:
            row.status = "rejected"
            continue

        for player, opponent, record in ((a, b, metrics), (b, a, mirrored(metrics))):
            if player is None:
                continue
            invalid = sports.validate(record, SCHEMA_REF, modules)
            if invalid:
                row.problems += invalid
            row.records.append((player, opponent, record))
        if row.problems:
            row.status = "rejected"
            continue

        key = frozenset(str(p.id) for p, _, _ in row.records), row.played_on, tuple(sorted(
            (m["points_won"], m["points_lost"]) for _, _, m in row.records))
        if key in seen or all(
            _on_record(db, p, o, row.played_on, m) for p, o, m in row.records
        ):
            row.status = "duplicate"
            row.warnings.append("Already on record, or earlier in this file; it will be skipped.")
        seen.add(key)
    return out


def _club(db: Session, player: Player):
    return db.execute(
        select(PlayerOrganization.organization_id)
        .where(PlayerOrganization.player_id == player.id)
        .where(PlayerOrganization.end_date.is_(None))
        .limit(1)
    ).scalar_one_or_none()


def commit(db: Session, *, text: str, actor_user_id, today: date | None = None) -> tuple[Preview, int]:
    """Check the file again and save every ready row. Returns the verdicts and how many match
    records were written. Writes nothing when the file itself has a problem."""
    result = preview(db, text, today)
    if result.file_problems:
        return result, 0
    written = 0
    for row in result.rows:
        if row.status != "ready":
            continue
        for player, opponent, metrics in row.records:
            db.add(PerformanceEntry(
                player_id=player.id,
                sport="table_tennis",
                period_type="match",
                period_start=row.played_on,
                organization_id=_club(db, player),
                opponent_player_id=opponent.id if opponent else None,
                metrics=metrics,
                schema_ref=SCHEMA_REF,
                source=PerformanceSource.IMPORT.value,
                # From the official results, copied by a federation account.
                is_validated=True,
            ))
            written += 1
        row.status = "imported"
    db.add(AuditLog(
        actor_user_id=actor_user_id,
        action="results.import",
        entity_type="performance_entry",
        entity_id=None,
        event_metadata={
            "records_written": written,
            "rows": {s: sum(r.status == s for r in result.rows)
                     for s in ("imported", "duplicate", "rejected")},
            "events": sorted({r.event for r in result.rows if r.event})[:50],
        },
    ))
    db.flush()
    return result, written
