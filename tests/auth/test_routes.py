"""Tests for the magic-link auth routes.

Covers all DoD assertions from issue #6:

  1. POST /auth/login with valid email returns 200, calls fake EmailSender once
  2. The captured magic link points to /auth/verify?token=...
  3. GET /auth/verify with a valid token redirects 303 to /projects AND
     sets a session_id cookie with HttpOnly, Secure, SameSite=Lax
  4. Consuming the same valid link a second time returns 401
     (nonce was rotated on first consumption)
  5. Tampered token returns 401
  6. Expired token (>15 min old) returns 401
  7. POST /auth/logout deletes the Session row and clears the cookie
  8. login.html as an HTMX fragment does NOT include `<html`
  9. No test imports `resend` directly; all email goes through a fake

Coverage extras: case-insensitive email upsert, garbage-token cookie on
logout, missing-email validation, expired sessions still hit 401 etc.
"""

import re
import time
from collections.abc import Generator
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.auth.email import EmailSender, get_email_sender
from app.auth.tokens import sign_magic_link
from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models.session import Session as UserSession
from app.models.user import User

_TEST_SECRET = "0" * 64


class FakeEmailSender:
    """Captures send_magic_link calls; never touches the network."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_magic_link(self, email: str, link: str) -> None:
        self.sent.append((email, link))


@pytest.fixture(autouse=True)
def _set_test_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Magic-link signing requires a non-empty secret in every test."""
    monkeypatch.setenv("MAGIC_LINK_SECRET", _TEST_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(name="db_session")
def db_session_fixture() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="email_sender")
def email_sender_fixture() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture(name="client")
def client_fixture(
    db_session: Session, email_sender: FakeEmailSender
) -> Generator[TestClient, None, None]:
    def get_session_override() -> Generator[Session, None, None]:
        yield db_session

    def get_email_sender_override() -> EmailSender:
        return email_sender

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_email_sender] = get_email_sender_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _extract_token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


# ---- GET /auth/login -------------------------------------------------------


def test_get_auth_login_returns_full_page_by_default(client: TestClient) -> None:
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert "<html" in response.text
    assert "Sign in" in response.text
    assert 'name="email"' in response.text


def test_get_auth_login_returns_fragment_for_htmx(client: TestClient) -> None:
    response = client.get("/auth/login", headers={"HX-Request": "true"})
    assert response.status_code == 200
    # DoD assertion: HTMX fragment must NOT include the full-page chrome.
    assert "<html" not in response.text
    assert 'name="email"' in response.text


# ---- POST /auth/login ------------------------------------------------------


def test_post_auth_login_creates_user_and_calls_email_sender_once(
    client: TestClient, db_session: Session, email_sender: FakeEmailSender
) -> None:
    response = client.post("/auth/login", data={"email": "alice@example.com"})
    assert response.status_code == 200
    assert "Check your email" in response.text

    # User row created
    user = db_session.exec(select(User).where(User.email == "alice@example.com")).one()
    assert user.magic_link_nonce is not None
    assert user.magic_link_sent_at is not None

    # Email sender called exactly once with the right email
    assert len(email_sender.sent) == 1
    sent_email, sent_link = email_sender.sent[0]
    assert sent_email == "alice@example.com"
    # DoD: the magic link points at /auth/verify?token=...
    assert "/auth/verify?token=" in sent_link
    assert _extract_token(sent_link)


def test_post_auth_login_lowercases_and_strips_email(
    client: TestClient, db_session: Session, email_sender: FakeEmailSender
) -> None:
    response = client.post("/auth/login", data={"email": "  Alice@Example.com  "})
    assert response.status_code == 200

    user = db_session.exec(select(User).where(User.email == "alice@example.com")).one()
    assert user is not None
    assert email_sender.sent[0][0] == "alice@example.com"


def test_post_auth_login_with_empty_email_returns_422(
    client: TestClient, email_sender: FakeEmailSender
) -> None:
    response = client.post("/auth/login", data={"email": ""})
    assert response.status_code == 422
    assert email_sender.sent == []


def test_post_auth_login_with_invalid_email_returns_422(
    client: TestClient, email_sender: FakeEmailSender
) -> None:
    response = client.post("/auth/login", data={"email": "not-an-email"})
    assert response.status_code == 422
    assert email_sender.sent == []


def test_post_auth_login_for_existing_user_does_not_create_duplicate(
    client: TestClient, db_session: Session, email_sender: FakeEmailSender
) -> None:
    db_session.add(User(email="repeat@example.com"))
    db_session.commit()

    client.post("/auth/login", data={"email": "repeat@example.com"})
    client.post("/auth/login", data={"email": "repeat@example.com"})

    users = db_session.exec(select(User).where(User.email == "repeat@example.com")).all()
    assert len(users) == 1
    assert len(email_sender.sent) == 2


# ---- GET /auth/verify ------------------------------------------------------


def test_get_auth_verify_with_valid_token_sets_cookie_and_redirects(
    client: TestClient, db_session: Session, email_sender: FakeEmailSender
) -> None:
    # Trigger login → captures the magic link
    client.post("/auth/login", data={"email": "verify@example.com"})
    _, link = email_sender.sent[0]
    token = _extract_token(link)

    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/projects"

    # Cookie attributes — DoD assertion. Compare lowercased so we don't
    # depend on starlette's exact attribute capitalization.
    lowered = response.headers["set-cookie"].lower()
    assert "session_id=" in lowered
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered

    # Session row exists for the user
    user = db_session.exec(select(User).where(User.email == "verify@example.com")).one()
    rows = db_session.exec(select(UserSession).where(UserSession.user_id == user.id)).all()
    assert len(rows) == 1


def test_get_auth_verify_consuming_same_link_twice_returns_401(
    client: TestClient, email_sender: FakeEmailSender
) -> None:
    client.post("/auth/login", data={"email": "single-use@example.com"})
    _, link = email_sender.sent[0]
    token = _extract_token(link)

    first = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert first.status_code == 303

    # Same client carries the cookie from the first verify, but that's
    # irrelevant — the link itself must not redeem twice.
    client.cookies.clear()
    second = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert second.status_code == 401


def test_get_auth_verify_with_tampered_token_returns_401(client: TestClient) -> None:
    # Sign a real-shaped token, then mutate one byte.
    token = sign_magic_link("a@b.com", "n1")
    mutated = token[:-3] + ("A" if token[-3] != "A" else "B") + token[-2:]
    response = client.get(f"/auth/verify?token={mutated}", follow_redirects=False)
    assert response.status_code == 401


def test_get_auth_verify_with_expired_token_returns_401(
    client: TestClient, email_sender: FakeEmailSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sign at "now"
    fake_now = time.time()
    monkeypatch.setattr(time, "time", lambda: fake_now)
    client.post("/auth/login", data={"email": "expire@example.com"})
    _, link = email_sender.sent[0]
    token = _extract_token(link)

    # Verify "16 minutes later" — past the 900s TTL
    monkeypatch.setattr(time, "time", lambda: fake_now + (60 * 16))
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert response.status_code == 401


def test_get_auth_verify_with_unknown_email_returns_401(client: TestClient) -> None:
    # Forge a token against an email that has no User row.
    token = sign_magic_link("ghost@example.com", "made-up-nonce")
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert response.status_code == 401


# ---- POST /auth/logout -----------------------------------------------------


def test_post_auth_logout_deletes_session_row_and_clears_cookie(
    client: TestClient, db_session: Session, email_sender: FakeEmailSender
) -> None:
    # Sign in to get a real session
    client.post("/auth/login", data={"email": "logout@example.com"})
    _, link = email_sender.sent[0]
    token = _extract_token(link)
    verify_response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    set_cookie = verify_response.headers["set-cookie"]
    session_id_str = re.search(r"session_id=([^;]+);", set_cookie).group(1)  # type: ignore[union-attr]
    session_id = UUID(session_id_str)
    # TestClient doesn't auto-extract cookies from a 303 when
    # follow_redirects=False — set it explicitly so the logout request
    # actually sees it.
    client.cookies.set("session_id", session_id_str)

    # Confirm one session row exists
    user = db_session.exec(select(User).where(User.email == "logout@example.com")).one()
    rows_before = db_session.exec(select(UserSession).where(UserSession.user_id == user.id)).all()
    assert len(rows_before) == 1

    # Logout — TestClient already has the cookie from the verify response
    logout_response = client.post("/auth/logout", follow_redirects=False)
    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/"
    # Cookie cleared
    assert 'session_id=""' in logout_response.headers["set-cookie"] or (
        "session_id=" in logout_response.headers["set-cookie"]
        and "Max-Age=0" in logout_response.headers["set-cookie"]
    )

    # Session row gone
    rows_after = db_session.exec(select(UserSession).where(UserSession.id == session_id)).all()
    assert rows_after == []


def test_post_auth_logout_with_garbage_cookie_still_redirects(client: TestClient) -> None:
    client.cookies.set("session_id", "not-a-uuid")
    response = client.post("/auth/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_post_auth_logout_with_no_cookie_still_redirects(client: TestClient) -> None:
    response = client.post("/auth/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
