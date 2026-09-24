"""Development-only helpers.

There is exactly one endpoint here and it exists because the web app's role switcher needs
real identities to act as. Without it, "wire the web app to the real API" is blocked on
somebody pasting UUIDs out of psql.

Like the identity header in `app.deps`, this is refused unless
`settings.environment == "development"`, and it is refused by the same check so the two
cannot drift apart. It exposes the email addresses of active accounts, which in a real
deployment would be a disclosure worth having a meeting about. In a local stack holding
synthetic data it is the difference between a demo that runs and one that does not.

Everything in this file goes away with the security track's auth implementation. It is in its
own router so that removal is deleting one file and one `include_router` line.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.core import CamelModel

router = APIRouter(tags=["development"], prefix="/dev")


class DevIdentityOut(CamelModel):
    id: str
    email: str
    full_name: str
    role: str
    organization_id: str | None = None
    organization_name: str | None = None
    linked_player_id: str | None = None


@router.get("/identities", response_model=list[DevIdentityOut])
def identities(db: Session = Depends(get_db)) -> list[DevIdentityOut]:
    """One active account per role, for the development role switcher.

    Returns the value to send in the `X-NorthStar-User` header. Refused outside development.
    """
    if get_settings().environment != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not available outside development.",
        )

    out: list[DevIdentityOut] = []
    for role in UserRole:
        user = db.execute(
            select(User)
            .where(User.role == role.value)
            .where(User.is_active.is_(True))
            # A coach with no organization sees nobody, which makes a confusing demo. Prefer
            # an account that is actually attached to something.
            .order_by(User.organization_id.is_(None), User.email)
            .limit(1)
        ).scalar_one_or_none()
        if user is None:
            continue
        out.append(
            DevIdentityOut(
                id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                organization_id=str(user.organization_id) if user.organization_id else None,
                organization_name=user.organization.name if user.organization else None,
                linked_player_id=(
                    str(user.linked_player_id) if user.linked_player_id else None
                ),
            )
        )
    return out
