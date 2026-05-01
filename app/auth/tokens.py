"""Magic-link token sign + verify.

Pure functions. No DB, no HTTP, no logging of token contents.

The token encodes `(email, nonce)` and is signed with
`itsdangerous.URLSafeTimedSerializer` against `Settings.magic_link_secret`.
TTL is hard-coded at 15 minutes; `nonce` is the row-level single-use
guarantee, rotated by the auth route on consumption (a later ticket).
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

_TTL_SECONDS = 60 * 15  # 15 minutes
_SALT = "magic-link"


class MagicLinkInvalid(Exception):
    """Token signature does not match — tampered, wrong secret, or garbage."""


class MagicLinkExpired(Exception):
    """Token is correctly signed but older than the 15-minute TTL."""


class MagicLinkConfigError(Exception):
    """`MAGIC_LINK_SECRET` env var is unset or empty."""


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().magic_link_secret.get_secret_value()
    if not secret:
        raise MagicLinkConfigError(
            "MAGIC_LINK_SECRET env var is not set. Magic-link auth cannot "
            "function. In production, this comes from Google Secret Manager; "
            "for local dev set it in .env (any random hex string is fine)."
        )
    return URLSafeTimedSerializer(secret, salt=_SALT)


def sign_magic_link(email: str, nonce: str) -> str:
    """Return a URL-safe signed token encoding `(email, nonce)`.

    The token is opaque to callers — no parsing or guessing.
    """
    return _serializer().dumps({"email": email, "nonce": nonce})


def verify_magic_link(token: str) -> tuple[str, str]:
    """Verify a token and return `(email, nonce)`.

    Raises `MagicLinkExpired` if the token is correctly signed but older
    than the 15-minute TTL. Raises `MagicLinkInvalid` for any other
    failure mode (tampered, signed with a different secret, wrong salt,
    malformed payload).
    """
    try:
        payload = _serializer().loads(token, max_age=_TTL_SECONDS)
    except SignatureExpired as exc:
        raise MagicLinkExpired() from exc
    except BadSignature as exc:
        raise MagicLinkInvalid() from exc

    if not isinstance(payload, dict) or "email" not in payload or "nonce" not in payload:
        raise MagicLinkInvalid()
    return payload["email"], payload["nonce"]
