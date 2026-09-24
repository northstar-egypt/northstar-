"""Where flags come from, and why there are none yet.

The screens expect flags. The squad table shows them per row, the player profile has a
banner for them with the rule that "every flag carries the sentence that explains why it
fired", and the integrity board is entirely made of them. `ml/detectors` now produces exactly
those sentences.

Nothing connects the two, because **there is no Flag table**. `docs/schema.md` has no table
holding a raised flag with a type, confidence, evidence, status, reviewer, decision and
reason. `apps/web/lib/api.ts` says so too, in capital letters, on `getFlags`. There is a
board item for it.

This module is the seam that change plugs into. Today every function returns nothing, which
makes the screens render their empty states rather than fabricate a flag. That is the correct
behaviour for "the detectors have not been run against this database yet", and it is much
better than the alternative of computing flags on the fly inside a request.

Why not compute them on the fly
-------------------------------
It is tempting, since `ml/detectors` is right there. Three reasons not to:

  A flag has state. Open, confirmed, dismissed, needs_info, plus who decided and why. That
  is a row, not a function call. The integrity board cannot exist without it, and half the
  point of the board is that each decision plus its reason becomes a labelled example that
  the detectors' precision and recall are then computed from.

  The detectors read the JSON export, not the database, and the API image installs only
  `apps/api/requirements.txt`. Importing `ml` from a request handler would drag the ML
  dependency tree into the container that serves traffic.

  Running three detectors over the whole population inside a page load is the wrong shape at
  any scale. It is a batch job that writes rows.

So the sequence is: add the Flag table, have the ML track write rows into it, and make the
functions below read them. The signatures here are what those reads should look like.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session


def flags_for_player(db: Session, player_id: uuid.UUID) -> list[dict]:
    """Flags raised against one player, newest first.

    Returns `{"type", "label", "confidence"}` per flag, matching `FlagSummaryOut`.

    TODO(data): read the Flag table once it exists. See the module docstring.
    """
    return []


def flags_for_players(db: Session, player_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    """The same, batched for the squad table.

    Batched deliberately: the squad screen would otherwise do one query per row, which is the
    shape that makes a dashboard slow the moment an academy has a hundred players.

    TODO(data): read the Flag table once it exists.
    """
    return {player_id: [] for player_id in player_ids}


def flag_reason(db: Session, player_id: uuid.UUID) -> str | None:
    """The sentence shown under the flag banner on the player profile.

    `ml/detectors` already generates these, one per detector, written for a coach to read.
    They have nowhere to be stored yet.

    TODO(data): read the Flag table once it exists.
    """
    return None


def open_flag_count(db: Session, organization_id: uuid.UUID | None = None) -> int:
    """Open flags, optionally scoped to one organization. Used by the oversight screen.

    TODO(data): read the Flag table once it exists.
    """
    return 0
