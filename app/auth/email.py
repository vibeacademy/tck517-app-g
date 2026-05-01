"""Email delivery for magic-link auth.

Defines an `EmailSender` Protocol so route handlers depend on a tiny
interface, not the Resend SDK. Production wires `ResendEmailSender`;
tests inject a `FakeEmailSender` via `app.dependency_overrides`.

The `resend` SDK is imported ONLY in this module. Future tickets that
need other transports (SES, Postmark) replace `ResendEmailSender` here
without touching routes.
"""

from typing import Protocol

import resend

from app.config import get_settings


class EmailConfigError(Exception):
    """`RESEND_API_KEY` is unset or empty."""


class EmailSender(Protocol):
    def send_magic_link(self, email: str, link: str) -> None:
        """Deliver a magic-link email. Implementations may raise on failure."""
        ...


class ResendEmailSender:
    """Production sender that calls the Resend HTTP API."""

    def __init__(self, api_key: str, from_address: str) -> None:
        self._from_address = from_address
        # The resend SDK reads its API key from a module-level attribute.
        # Setting it here keeps the configuration localized to this class.
        resend.api_key = api_key

    def send_magic_link(self, email: str, link: str) -> None:
        resend.Emails.send(
            {
                "from": self._from_address,
                "to": [email],
                "subject": "Your sign-in link",
                "html": (
                    "<p>Click the link below to sign in. The link expires in "
                    "15 minutes and works once.</p>"
                    f'<p><a href="{link}">{link}</a></p>'
                ),
            }
        )


def get_email_sender() -> EmailSender:
    """FastAPI dependency that returns the configured sender.

    Raises `EmailConfigError` if `RESEND_API_KEY` is unset — same
    fail-loud-at-first-use pattern as `app/auth/tokens.py`.
    """
    settings = get_settings()
    api_key = settings.resend_api_key.get_secret_value()
    if not api_key:
        raise EmailConfigError(
            "RESEND_API_KEY env var is not set. Magic-link emails cannot "
            "be sent. In production, set this on the Cloud Run revision "
            "via Secret Manager. In tests, override `get_email_sender` "
            "with a fake via `app.dependency_overrides`."
        )
    return ResendEmailSender(api_key, settings.resend_from_address)
