"""Signing in and out, and the session that results.

What is tested hard here, because each is a way sign-in could fail quietly:

  Credentials. A wrong password, an unknown email and a deactivated account all get the same
  401 and the same words, so the form cannot be used to find out who has an account.

  The cookie. HttpOnly (a script cannot read it), SameSite=Lax, and the token never appears
  in a response body.

  The token. A forged, altered, expired or unsigned token is refused, and so is a genuine one
  for an account that has since been deactivated. The role comes from the database on every
  request, never from the token.

  Forgery. A state-changing request carrying the cookie but sent from another site is
  refused, and nothing is saved.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app.security import DEMO_PASSWORD, SESSION_COOKIE, issue_token

EVIL = "https://evil.example"
ALLOWED = "http://localhost:3000"


def login(client, user, password=DEMO_PASSWORD, **kwargs):
    return client.post("/auth/login", json={"email": user.email, "password": password}, **kwargs)


def audit_rows(db, action: str) -> list:
    from app.models.audit_log import AuditLog

    return list(db.execute(select(AuditLog).where(AuditLog.action == action)).scalars())


def set_cookie_header(response) -> str:
    return response.headers.get("set-cookie", "")


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------


def test_sign_in_sets_an_httponly_lax_cookie_and_returns_the_user(client, world):
    coach = world["users"]["coach_a"]
    response = login(client, coach)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["id"] == str(coach.id)
    assert body["role"] == "coach"

    cookie = set_cookie_header(response).lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "max-age=28800" in cookie
    # The token lives only in the cookie. A body a script can read must not carry it.
    token = client.cookies.get(SESSION_COOKIE)
    assert token and token not in response.text


def test_the_cookie_is_the_session(client, world):
    login(client, world["users"]["coach_a"])
    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["email"] == world["users"]["coach_a"].email
    assert client.get("/players").status_code == 200


def test_email_is_matched_without_case_or_spaces(client, world):
    coach = world["users"]["coach_a"]
    response = client.post(
        "/auth/login", json={"email": f"  {coach.email.upper()} ", "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200


@pytest.mark.parametrize("case", ["wrong password", "unknown email", "deactivated account"])
def test_every_failed_sign_in_looks_the_same(client, world, case):
    if case == "wrong password":
        response = login(client, world["users"]["coach_a"], password="not-the-password")
    elif case == "unknown email":
        response = client.post(
            "/auth/login", json={"email": "nobody@test.invalid", "password": DEMO_PASSWORD}
        )
    else:
        response = login(client, world["users"]["inactive"])

    assert response.status_code == 401
    assert response.json()["detail"] == "Email or password is incorrect."
    assert SESSION_COOKIE not in set_cookie_header(response)
    assert client.get("/me").status_code == 401


def test_a_placeholder_hash_cannot_be_signed_in_to(client, world, db):
    """Accounts from before real passwords carry a non-hash. That is a no, not a crash."""
    coach = world["users"]["coach_a"]
    coach.password_hash = "$synthetic$not-a-real-hash$do-not-use"
    db.flush()
    assert login(client, coach).status_code == 401


def test_sign_ins_are_audited_and_the_password_never_is(client, world, db):
    coach = world["users"]["coach_a"]
    login(client, coach, password="a-wrong-guess-123")
    login(client, coach)

    (failed,) = [r for r in audit_rows(db, "auth.login_failed") if r.entity_id == coach.id]
    assert failed.event_metadata["email"] == coach.email.lower()
    assert "a-wrong-guess-123" not in str(failed.event_metadata)

    (ok,) = [r for r in audit_rows(db, "auth.login") if r.actor_user_id == coach.id]
    assert ok.event_metadata == {"role": "coach"}
    db.refresh(coach)
    assert coach.last_login_at is not None


def test_a_cheap_hash_is_upgraded_at_sign_in(client, world, db):
    from app.security import needs_rehash, verify_password

    coach = world["users"]["coach_a"]
    assert needs_rehash(coach.password_hash)
    login(client, coach)
    db.refresh(coach)
    assert not needs_rehash(coach.password_hash)
    assert coach.password_hash.startswith("$argon2id$")
    assert verify_password(coach.password_hash, DEMO_PASSWORD)


def test_an_oversized_password_is_refused_before_hashing(client, world):
    response = client.post(
        "/auth/login", json={"email": world["users"]["coach_a"].email, "password": "x" * 5000}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Signing out
# ---------------------------------------------------------------------------


def test_sign_out_clears_the_cookie_and_is_audited(client, world, db):
    coach = world["users"]["coach_a"]
    login(client, coach)
    response = client.post("/auth/logout")
    assert response.status_code == 204
    cookie = set_cookie_header(response).lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "max-age=0" in cookie
    assert client.get("/me").status_code == 401
    assert [r for r in audit_rows(db, "auth.logout") if r.actor_user_id == coach.id]


def test_sign_out_when_signed_out_is_harmless(client, world):
    assert client.post("/auth/logout").status_code == 204


# ---------------------------------------------------------------------------
# The token
# ---------------------------------------------------------------------------


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_an_altered_token_is_refused(client, world):
    token = issue_token(world["users"]["admin"].id)
    head, body, signature = token.split(".")
    forged = f"{head}.{body}.{signature[:-2]}{'AA' if signature[-2:] != 'AA' else 'BB'}"
    assert client.get("/me", headers=_bearer(forged)).status_code == 401


def test_a_token_naming_another_user_cannot_be_made_without_the_key(client, world):
    claims = {
        "sub": str(world["users"]["admin"].id),
        "iss": "northstar",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    forged = jwt.encode(claims, "a-guessed-key-that-is-long-enough-to-pass", algorithm="HS256")
    assert client.get("/me", headers=_bearer(forged)).status_code == 401


def test_an_unsigned_token_is_refused(client, world):
    """`alg: none` is the classic JWT hole: a token that claims to need no signature."""
    claims = {
        "sub": str(world["users"]["admin"].id),
        "iss": "northstar",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }
    unsigned = jwt.encode(claims, key=None, algorithm="none")
    assert client.get("/me", headers=_bearer(unsigned)).status_code == 401


def test_an_expired_token_is_refused(client, world):
    long_ago = datetime.now(timezone.utc) - timedelta(days=2)
    token = issue_token(world["users"]["admin"].id, now=long_ago)
    assert client.get("/me", headers=_bearer(token)).status_code == 401


def test_deactivating_an_account_ends_its_session_at_once(client, world, db):
    coach = world["users"]["coach_a"]
    login(client, coach)
    assert client.get("/me").status_code == 200
    coach.is_active = False
    db.flush()
    assert client.get("/me").status_code == 401


def test_the_role_comes_from_the_database_not_the_token(client, world, db):
    coach = world["users"]["coach_a"]
    login(client, coach)
    coach.role = "scout"
    db.flush()
    assert client.get("/me").json()["role"] == "scout"


def test_no_session_at_all_is_401(client, world):
    assert client.get("/me").status_code == 401


# ---------------------------------------------------------------------------
# Cross-site request forgery
# ---------------------------------------------------------------------------


def _new_player(name: str) -> dict:
    from tests.test_writes import new_player

    return new_player(fullName=name)


def test_a_cross_site_write_with_the_cookie_is_refused(client, world, db):
    from app.models.player import Player

    login(client, world["users"]["coach_a"])
    name = f"Forged {uuid.uuid4().hex[:6]}"
    response = client.post("/players", json=_new_player(name), headers={"Origin": EVIL})
    assert response.status_code == 403
    assert db.execute(select(Player).where(Player.full_name == name)).first() is None


def test_the_same_write_from_the_web_app_goes_through(client, world):
    login(client, world["users"]["coach_a"])
    response = client.post(
        "/players", json=_new_player(f"Allowed {uuid.uuid4().hex[:6]}"), headers={"Origin": ALLOWED}
    )
    assert response.status_code == 201, response.text


def test_reads_are_not_blocked_by_origin(client, world):
    """A cross-site GET changes nothing, and SameSite=Lax already keeps the cookie off it."""
    login(client, world["users"]["coach_a"])
    assert client.get("/me", headers={"Origin": EVIL}).status_code == 200


def test_a_cross_site_sign_in_is_refused(client, world):
    response = login(client, world["users"]["coach_a"], headers={"Origin": EVIL})
    assert response.status_code == 403
    assert client.get("/me").status_code == 401


# ---------------------------------------------------------------------------
# Configuration and hashing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("secret", [None, "short"])
def test_outside_development_a_weak_signing_key_stops_startup(monkeypatch, secret):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    if secret is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None)


def test_outside_development_the_cookie_is_https_only(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    assert Settings(_env_file=None).session_cookie_secure is True
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert Settings(_env_file=None).session_cookie_secure is False


def test_passwords_are_stored_as_argon2id():
    from app.security import hash_password, verify_password

    stored = hash_password("correct horse battery staple")
    assert stored.startswith("$argon2id$")
    assert "correct horse" not in stored
    assert verify_password(stored, "correct horse battery staple")
    assert not verify_password(stored, "correct horse battery stapler")
    assert not verify_password("not-a-hash", "anything")


def test_demo_hashes_are_deterministic_real_and_marked_for_upgrade():
    from app.security import demo_password_hash, needs_rehash, verify_password

    user_id = uuid.uuid4()
    assert demo_password_hash(user_id) == demo_password_hash(user_id)
    assert demo_password_hash(user_id) != demo_password_hash(uuid.uuid4())
    assert verify_password(demo_password_hash(user_id), DEMO_PASSWORD)
    assert needs_rehash(demo_password_hash(user_id))


def test_every_demo_account_offered_can_actually_sign_in(client, world):
    """The login screen's demo buttons go through the real sign-in, so each must work."""
    identities = client.get("/dev/identities").json()
    assert identities
    for row in identities:
        response = client.post(
            "/auth/login", json={"email": row["email"], "password": row["demoPassword"]}
        )
        assert response.status_code == 200, (row["email"], response.text)
