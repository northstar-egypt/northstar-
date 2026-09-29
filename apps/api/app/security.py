"""Passwords and session tokens. Everything cryptographic in the API is in this file.

How a session works
-------------------
1. `POST /auth/login` checks the email and password. The password is compared against an
   argon2id hash, never stored or logged in plain text.
2. On success the API signs a short token (a JWT) that says only "user <id>, issued at, expires
   at", and sets it as a cookie the browser's JavaScript cannot read (HttpOnly). A script
   injected into the page therefore cannot steal the session.
3. Every later request carries the cookie. `app.deps.current_user` checks the signature and
   the expiry, then loads the user **from the database**. The role, the organization and
   whether the account is active come from there, not from the token, so deactivating an
   account or changing a role takes effect on the very next request.

Non-browser clients (tests, scripts, the interactive `/docs` page) send the same token as
`Authorization: Bearer <token>` instead of a cookie.

Choices, and what they cost
---------------------------
- **argon2id** with the library's defaults (RFC 9106's second recommended profile: 64 MiB,
  3 passes). It is the current OWASP first choice for password storage.
- **HS256** with one server secret. There is one API, so there is no need for public-key
  signatures. The secret is refused outside development unless it is set and long
  (`app.config`).
- **Stateless tokens cannot be revoked early.** Signing out deletes the cookie, but a stolen
  token stays valid until it expires. The lifetime is short (8 hours by default), and
  deactivating the account stops it at once because the account is re-checked on every
  request. A server-side session table would remove the gap; it is recorded as future work
  in `docs/threat-model.md`.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type, hash_secret

from app.config import get_settings

SESSION_COOKIE = "northstar_session"
ALGORITHM = "HS256"
ISSUER = "northstar"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """True only for the right password. A malformed or placeholder hash is a plain no."""
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when a hash was made with weaker settings than the current ones."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False


# A real hash of a random string, checked against when the email does not exist. Without it a
# wrong email answers faster than a wrong password, and the timing tells an attacker which
# accounts exist, which the identical error message is there to hide.
_TIMING_DUMMY = _hasher.hash(uuid.uuid4().hex)


def spend_equal_time(password: str) -> None:
    verify_password(_TIMING_DUMMY, password)


def issue_token(user_id: uuid.UUID, *, now: datetime | None = None) -> str:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=settings.session_hours),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def read_token(token: str) -> uuid.UUID | None:
    """The user id a valid token names, or None for anything forged, altered or expired.

    The algorithm is pinned: a token claiming `alg: none`, or any algorithm but HS256, is
    rejected rather than trusted.
    """
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Synthetic demo accounts
# ---------------------------------------------------------------------------

# The password of every account the synthetic generator creates. It is published on purpose:
# the accounts exist only in a local stack holding synthetic data, and the login screen shows
# it so a reviewer can sign in as any role. Never seed these accounts anywhere real.
DEMO_PASSWORD = "northstar-demo"


def demo_password_hash(user_id: uuid.UUID) -> str:
    """A valid argon2id hash of `DEMO_PASSWORD`, the same every time for the same user.

    Two things differ from `hash_password`, both on purpose:

    - The salt comes from the user id rather than from a random source, so the generator's
      output stays byte-identical run to run (its tests check that).
    - The cost is deliberately low, so generating hundreds of accounts takes milliseconds.
      `needs_rehash` is then true for these hashes, and the first real login upgrades the
      stored hash to full strength. That upgrade path is what a real system needs anyway when
      it raises its hashing cost, so the demo exercises it.
    """
    salt = hashlib.sha256(user_id.bytes).digest()[:16]
    return hash_secret(
        DEMO_PASSWORD.encode(),
        salt,
        time_cost=1,
        memory_cost=1024,
        parallelism=1,
        hash_len=32,
        type=Type.ID,
    ).decode()
