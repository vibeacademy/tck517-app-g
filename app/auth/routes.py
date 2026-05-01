"""Magic-link auth routes.

Three endpoints — login (form + submit), verify, logout. Self-referential
URL construction reads `X-Forwarded-Host` / `X-Forwarded-Proto` so the
emailed link works behind Cloud Run's load balancer (see
docs/PATTERN-LIBRARY.md pattern #4).

Sessions live in the `sessions` table and identify the browser via the
`session_id` cookie set on /auth/verify success.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from app.auth.email import EmailSender, get_email_sender
from app.auth.tokens import (
    MagicLinkExpired,
    MagicLinkInvalid,
    sign_magic_link,
    verify_magic_link,
)
from app.config import Settings
from app.db import get_session
from app.models.session import Session as UserSession
from app.models.user import User
from app.templates import templates

router = APIRouter()

DBSessionDep = Annotated[DBSession, Depends(get_session)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]


def _generate_nonce() -> str:
    """Cryptographically random opaque token used to single-use a magic link."""
    return secrets.token_urlsafe(16)


def _build_verify_url(request: Request, token: str) -> str:
    """Construct an absolute URL to /auth/verify, honoring forwarded headers.

    Cloud Run terminates TLS at the load balancer and forwards the
    original host via X-Forwarded-Host. Hard-coding APP_URL would break
    PR preview environments where the host is generated per-deploy.
    """
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    host = forwarded_host or request.headers.get("host", "localhost:8080")
    proto = forwarded_proto or request.url.scheme
    return f"{proto}://{host}/auth/verify?token={token}"


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request", "").lower() == "true"


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=Settings.SESSION_COOKIE_NAME,
        value=session_id,
        max_age=Settings.SESSION_TTL_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.get("/auth/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    """Render the login form. Returns a fragment for HTMX, full page otherwise."""
    template = "auth/_login_form.html" if _is_htmx(request) else "auth/login.html"
    return templates.TemplateResponse(request, template, {"error": None})


@router.post("/auth/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    db: DBSessionDep,
    sender: EmailSenderDep,
    email: Annotated[str, Form()],
) -> HTMLResponse:
    """Issue a magic-link email and render the 'check your inbox' page."""
    normalized = email.strip().lower()
    if "@" not in normalized or len(normalized) < 3:
        template = "auth/_login_form.html" if _is_htmx(request) else "auth/login.html"
        return templates.TemplateResponse(
            request,
            template,
            {"error": "Please enter a valid email address."},
            status_code=422,
        )

    user = db.exec(select(User).where(col(User.email) == normalized)).first()
    if user is None:
        user = User(email=normalized)
        db.add(user)

    user.magic_link_nonce = _generate_nonce()
    user.magic_link_sent_at = datetime.now(UTC)
    db.add(user)
    db.commit()
    db.refresh(user)

    token = sign_magic_link(normalized, user.magic_link_nonce)
    sender.send_magic_link(normalized, _build_verify_url(request, token))

    template = "auth/check_email.html"
    return templates.TemplateResponse(request, template, {"email": normalized})


@router.get("/auth/verify")
def verify(request: Request, db: DBSessionDep, token: str) -> Response:
    """Consume a magic link: rotate nonce, create session, set cookie, redirect."""
    try:
        email, nonce = verify_magic_link(token)
    except (MagicLinkExpired, MagicLinkInvalid) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Magic link is invalid or expired.",
        ) from exc

    normalized = email.strip().lower()
    user = db.exec(select(User).where(col(User.email) == normalized)).first()
    if user is None or user.magic_link_nonce != nonce:
        # nonce mismatch covers both "already consumed" and "newer link
        # was issued in the meantime" — both invalid.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Magic link is invalid or expired.",
        )

    user.magic_link_nonce = _generate_nonce()  # rotate; the consumed link is now dead
    user.last_login_at = datetime.now(UTC)
    db.add(user)

    session_row = UserSession(
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=Settings.SESSION_TTL_DAYS),
    )
    db.add(session_row)
    db.commit()
    db.refresh(session_row)

    response = RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, str(session_row.id))
    return response


@router.post("/auth/logout")
def logout(request: Request, db: DBSessionDep) -> Response:
    """Delete the session row, clear the cookie, redirect to /."""
    raw_cookie = request.cookies.get(Settings.SESSION_COOKIE_NAME)
    if raw_cookie:
        try:
            from uuid import UUID

            session_id = UUID(raw_cookie)
            row = db.exec(
                select(UserSession).where(col(UserSession.id) == session_id)
            ).first()
            if row is not None:
                db.delete(row)
                db.commit()
        except ValueError:
            # Garbage cookie — nothing to delete; just clear it below.
            pass

    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key=Settings.SESSION_COOKIE_NAME, path="/")
    return response
