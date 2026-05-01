"""FastAPI dependencies for resolving the current user from a session cookie.

`current_user` raises `HTTPException(401)` for any unauthenticated state —
no cookie, garbage cookie, no matching session row, or expired session.
Route handlers wanting redirect-on-missing must catch this themselves;
the dependency is deliberately strict.

`optional_user` returns `None` for the same set of failure modes — for
public routes that *might* personalize when a session is present.

Both filter by `Session.expires_at > now()` at the SQL level so an
expired row is invalid even if it still exists in the database; we
deliberately do NOT mutate session state in the dependency (no sliding
expiration in v1 — see ticket #5 guardrails).
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from app.config import Settings
from app.db import get_session
from app.models.session import Session as UserSession
from app.models.user import User

DBSessionDep = Annotated[DBSession, Depends(get_session)]


def _resolve_user(request: Request, db: DBSession) -> User | None:
    """Pure resolution: cookie → User instance, or None for any failure."""
    raw_cookie = request.cookies.get(Settings.SESSION_COOKIE_NAME)
    if not raw_cookie:
        return None

    try:
        session_id = UUID(raw_cookie)
    except ValueError:
        return None

    statement = (
        select(User)
        .join(UserSession, col(UserSession.user_id) == col(User.id))
        .where(
            col(UserSession.id) == session_id,
            col(UserSession.expires_at) > datetime.now(UTC),
        )
    )
    return db.exec(statement).first()


def current_user(request: Request, db: DBSessionDep) -> User:
    """Require an authenticated user, or raise 401."""
    user = _resolve_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Session"},
        )
    return user


def optional_user(request: Request, db: DBSessionDep) -> User | None:
    """Return the authenticated user if any, else None — never raises."""
    return _resolve_user(request, db)
