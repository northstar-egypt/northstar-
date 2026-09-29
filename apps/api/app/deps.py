"""Request dependencies, chiefly "who is calling".

A caller is whoever holds a valid session token (see `app.security`). The browser sends it as
an HttpOnly cookie; tests, scripts and the `/docs` page send it as `Authorization: Bearer`.
Either way the token only names a user id. The user is loaded from the database on every
request, so an account that has been deactivated, or had its role changed, is treated that
way immediately.

Cross-site request forgery
--------------------------
A cookie is sent by the browser automatically, which is what makes a cookie session safer
against script injection and also what makes forgery possible: another website could try to
make a signed-in user's browser send a request here. Two layers stop that:

1. The cookie is `SameSite=Lax`, so browsers do not attach it to a POST coming from another
   site at all.
2. `check_origin` refuses any state-changing request whose `Origin` header names a site
   that is not one of the configured web origins. Browsers always set `Origin` on such
   requests and a web page cannot forge it.

A request with no `Origin` header at all comes from a non-browser client (curl, a test, a
script). Such a client cannot borrow somebody else's cookie, so it is not a forgery risk.

Everything downstream takes a `Caller` from `app.services.access` and does not care how the
caller was identified.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.user import User
from app.security import SESSION_COOKIE, read_token
from app.services.access import Caller, load_caller

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# `auto_error=False` because a missing bearer token is normal: the browser uses the cookie.
# Declaring it here is also what puts the "Authorize" button on the /docs page.
_bearer = HTTPBearer(auto_error=False, description="A session token, for non-browser clients.")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def check_origin(request: Request) -> None:
    """Refuse a state-changing request sent by a page on another site. See the module doc."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in get_settings().cors_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This request came from a site that is not allowed to act on NorthStar.",
        )


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Caller:
    """Resolve the caller from the session token, or refuse with 401."""
    if bearer is not None:
        token = bearer.credentials
    else:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            check_origin(request)

    if not token:
        raise _unauthorized("Not signed in.")

    user_id = read_token(token)
    if user_id is None:
        raise _unauthorized("Your session has expired or is not valid. Sign in again.")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        # The same message for both, so a stolen token cannot be used to learn whether the
        # account still exists.
        raise _unauthorized("Your session has expired or is not valid. Sign in again.")

    return load_caller(db, user)
