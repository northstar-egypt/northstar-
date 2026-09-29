"""Signing in and out, and "who am I".

How the pieces fit is described in `app.security` (passwords and tokens) and `app.deps`
(reading the session and refusing forged requests). This file is the three endpoints.

What each one writes to the audit log:
  auth.login          a successful sign-in, by that user
  auth.login_failed   a failed one, with the email that was tried (never the password)
  auth.logout         a sign-out that carried a valid session
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import check_origin, current_user
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.core import CamelModel, SessionUserOut
from app.security import (
    SESSION_COOKIE,
    hash_password,
    issue_token,
    needs_rehash,
    read_token,
    spend_equal_time,
    verify_password,
)
from app.services.access import Caller, load_caller

router = APIRouter(tags=["auth"])

# One message for a wrong email, a wrong password and a deactivated account, so the form
# cannot be used to find out which accounts exist.
BAD_CREDENTIALS = "Email or password is incorrect."


class LoginIn(CamelModel):
    email: str = Field(max_length=320)
    # Bounded so a megabyte "password" cannot be used to make the hashing expensive.
    password: str = Field(max_length=1024)


def session_user(caller: Caller) -> SessionUserOut:
    return SessionUserOut(
        id=caller.user_id,
        full_name=caller.full_name,
        email=caller.email,
        role=caller.role,
        organization_id=caller.organization_id,
        organization_name=caller.organization_name,
        linked_player_id=caller.linked_player_id,
    )


def _ip(request: Request) -> str | None:
    """The client address, only if it is one. The column is Postgres `inet`, and some
    transports report a name here instead (the test client says "testclient"), which would
    fail the insert and with it the sign-in."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


@router.post("/auth/login", response_model=SessionUserOut)
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> SessionUserOut:
    """Check an email and password and start a session.

    The session token is set as an HttpOnly cookie and is not in the response body: the page's
    JavaScript never sees it, which is the point of using a cookie. The body is who signed in.
    """
    # A forged sign-in (logging a victim into the attacker's account) is refused like any
    # other cross-site write.
    check_origin(request)

    email = payload.email.strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()

    if user is None:
        spend_equal_time(payload.password)
        ok = False
    else:
        ok = verify_password(user.password_hash, payload.password) and user.is_active

    if not ok:
        db.add(
            AuditLog(
                actor_user_id=user.id if user is not None else None,
                action="auth.login_failed",
                entity_type="user",
                entity_id=user.id if user is not None else None,
                event_metadata={"email": email},
                ip_address=_ip(request),
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=BAD_CREDENTIALS)

    # Hashes made with weaker settings (the synthetic accounts' cheap ones, or an older
    # default) are upgraded now, while the plain password is briefly in hand.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="auth.login",
            entity_type="user",
            entity_id=user.id,
            event_metadata={"role": user.role},
            ip_address=_ip(request),
        )
    )
    db.commit()

    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        issue_token(user.id),
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return session_user(load_caller(db, user))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    """End the session in this browser. Safe to call when already signed out."""
    check_origin(request)
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_token(token) if token else None
    if user_id is not None and db.get(User, user_id) is not None:
        db.add(
            AuditLog(
                actor_user_id=user_id,
                action="auth.logout",
                entity_type="user",
                entity_id=user_id,
                ip_address=_ip(request),
            )
        )
        db.commit()

    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=SessionUserOut)
def me(caller: Caller = Depends(current_user)) -> SessionUserOut:
    """Who the current session belongs to. 401 when signed out."""
    return session_user(caller)
