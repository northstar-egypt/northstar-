"""Request dependencies, chiefly "who is calling".

There is no authentication in this repo yet. The auth approach is an open decision on the
board and picking it unilaterally would be exactly the kind of choice CLAUDE.md says to stop
and ask about, so this file resolves a caller from a request header instead, and does it in a
way that cannot quietly survive into a deployment.

How it fails closed
-------------------
The header is honoured only when `settings.environment == "development"`. Anywhere else the
API returns 401 for every endpoint that needs a caller, because `_dev_identity` refuses to
run and no other identity source exists yet. That ordering matters: the safe path is the
default and the convenient one is the exception, rather than the other way round.

It is still a development affordance and not a weak form of auth. Anyone who can reach the
API in development can act as any user, including an admin. That is acceptable for a local
stack holding synthetic data and is not acceptable for anything else, which is why it is
scoped to one environment value and shouted about in the OpenAPI description.

When the security track lands real sessions, `current_user` is the only function that
changes. Everything downstream takes a `Caller` from `app.services.access` and does not care
where it came from.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.user import User
from app.services.access import Caller, load_caller

DEV_IDENTITY_HEADER = "X-NorthStar-User"


def _development_mode() -> bool:
    return get_settings().environment == "development"


def current_user(
    db: Session = Depends(get_db),
    x_northstar_user: str | None = Header(
        default=None,
        alias=DEV_IDENTITY_HEADER,
        description=(
            "DEVELOPMENT ONLY. A user id or email to act as. Ignored outside the "
            "development environment, where every authenticated endpoint returns 401 "
            "until real authentication lands."
        ),
    ),
) -> Caller:
    """Resolve the caller, or refuse.

    Accepts a user id or an email so a human poking at `/docs` can type something they can
    remember rather than copying a UUID.
    """
    if not _development_mode():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authentication is not implemented. The development identity header is "
                "only honoured when environment=development."
            ),
        )

    if not x_northstar_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"No caller. Send the {DEV_IDENTITY_HEADER} header with a user id or "
                f"email. This is a development stand-in for real authentication."
            ),
        )

    stmt = select(User).where(User.is_active.is_(True))
    try:
        user_id = uuid.UUID(x_northstar_user)
        stmt = stmt.where(or_(User.id == user_id, User.email == x_northstar_user))
    except ValueError:
        stmt = stmt.where(User.email == x_northstar_user)

    user = db.execute(stmt.limit(1)).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"No active user matching {x_northstar_user!r}.",
        )

    return load_caller(db, user)
