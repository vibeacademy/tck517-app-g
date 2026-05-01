"""Tests for the current_user / optional_user FastAPI dependencies.

The five DoD assertions from issue #5:

  1. Route protected with `Depends(current_user)` returns 401 when no
     cookie is present.
  2. Same returns 401 when the cookie value doesn't match any Session.
  3. Same returns 401 when the Session row exists but expires_at < now().
  4. Same returns the correct User to the handler when the cookie maps
     to a valid, unexpired Session.
  5. `optional_user` returns None (not raises) when no cookie is present.

Extra coverage: WWW-Authenticate header on 401, garbage-UUID cookie,
and optional_user happy path.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.auth.deps import current_user, optional_user
from app.db import get_session
from app.models.session import Session as UserSession
from app.models.user import User


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


@pytest.fixture(name="client")
def client_fixture(db_session: Session) -> Generator[TestClient, None, None]:
    """A throwaway FastAPI app with two routes that exercise the deps.

    /whoami     — Depends(current_user); 401 on auth failure
    /maybe      — Depends(optional_user); always 200 with user-or-null
    """
    test_app = FastAPI()

    def get_session_override() -> Generator[Session, None, None]:
        yield db_session

    test_app.dependency_overrides[get_session] = get_session_override

    @test_app.get("/whoami")
    def whoami(user: Annotated[User, Depends(current_user)]) -> dict[str, str]:
        return {"id": str(user.id), "email": user.email}

    @test_app.get("/maybe")
    def maybe(
        user: Annotated[User | None, Depends(optional_user)],
    ) -> dict[str, str | None]:
        return {"id": str(user.id) if user else None}

    with TestClient(test_app) as c:
        yield c


def _make_user_with_session(
    db_session: Session,
    *,
    email: str = "alice@example.com",
    expires_in: timedelta = timedelta(days=30),
) -> tuple[User, UserSession]:
    user = User(email=email)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    sess = UserSession(
        user_id=user.id,
        expires_at=datetime.now(UTC) + expires_in,
    )
    db_session.add(sess)
    db_session.commit()
    db_session.refresh(sess)
    return user, sess


def test_current_user_returns_401_when_no_cookie(client: TestClient) -> None:
    response = client.get("/whoami")
    assert response.status_code == 401
    # Project guardrail: 401s must carry WWW-Authenticate so clients know
    # which auth scheme is in play.
    assert response.headers.get("www-authenticate") == "Session"


def test_current_user_returns_401_when_cookie_does_not_match_any_session(
    client: TestClient,
) -> None:
    bogus_id = uuid4()
    client.cookies.set("session_id", str(bogus_id))
    response = client.get("/whoami")
    assert response.status_code == 401


def test_current_user_returns_401_when_session_is_expired(
    client: TestClient, db_session: Session
) -> None:
    _user, sess = _make_user_with_session(
        db_session,
        email="expired@example.com",
        # Negative delta — already expired
        expires_in=timedelta(seconds=-1),
    )
    client.cookies.set("session_id", str(sess.id))
    response = client.get("/whoami")
    assert response.status_code == 401


def test_current_user_returns_the_user_for_a_valid_session(
    client: TestClient, db_session: Session
) -> None:
    user, sess = _make_user_with_session(db_session, email="valid@example.com")
    client.cookies.set("session_id", str(sess.id))
    response = client.get("/whoami")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "valid@example.com"
    assert UUID(body["id"]) == user.id


def test_optional_user_returns_none_when_no_cookie(client: TestClient) -> None:
    response = client.get("/maybe")
    assert response.status_code == 200
    assert response.json() == {"id": None}


def test_optional_user_returns_user_when_session_is_valid(
    client: TestClient, db_session: Session
) -> None:
    user, sess = _make_user_with_session(db_session, email="opt@example.com")
    client.cookies.set("session_id", str(sess.id))
    response = client.get("/maybe")
    assert response.status_code == 200
    assert response.json() == {"id": str(user.id)}


def test_optional_user_returns_none_for_expired_session(
    client: TestClient, db_session: Session
) -> None:
    _user, sess = _make_user_with_session(
        db_session, email="opt-exp@example.com", expires_in=timedelta(seconds=-1)
    )
    client.cookies.set("session_id", str(sess.id))
    response = client.get("/maybe")
    assert response.status_code == 200
    assert response.json() == {"id": None}


def test_garbage_uuid_in_cookie_is_treated_as_unauthenticated(
    client: TestClient,
) -> None:
    # The UUID parse failure must not leak as a 500 — same 401 path as
    # any other unauthenticated state.
    client.cookies.set("session_id", "not-a-uuid")
    response = client.get("/whoami")
    assert response.status_code == 401

    response = client.get("/maybe")
    assert response.status_code == 200
    assert response.json() == {"id": None}


def test_session_lookup_does_not_modify_session_row(
    client: TestClient, db_session: Session
) -> None:
    """No sliding expiration in v1 — verifying expires_at is unchanged after lookup."""
    _user, sess = _make_user_with_session(db_session, email="static@example.com")
    original_expires_at = sess.expires_at

    client.cookies.set("session_id", str(sess.id))
    client.get("/whoami")

    db_session.refresh(sess)
    assert sess.expires_at == original_expires_at
