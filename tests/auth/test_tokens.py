"""Magic-link token tests.

The five DoD assertions from issue #4:

  1. Round-trip: verify(sign(...)) returns the original (email, nonce)
  2. A token mutated by one byte raises MagicLinkInvalid
  3. A token signed with a different secret raises MagicLinkInvalid
  4. A token older than the 15-minute TTL raises MagicLinkExpired
  5. With no MAGIC_LINK_SECRET set, sign_magic_link raises a config error

Plus a few small belt-and-suspenders cases (different salt, malformed
payload) that fall out of the same machinery.
"""

import time

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.auth.tokens import (
    MagicLinkConfigError,
    MagicLinkExpired,
    MagicLinkInvalid,
    sign_magic_link,
    verify_magic_link,
)
from app.config import get_settings

# 32-byte hex used by every test that needs a non-empty secret.
_TEST_SECRET = "0" * 64


@pytest.fixture(autouse=True)
def _set_test_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to a non-empty secret. Tests that need it empty override."""
    monkeypatch.setenv("MAGIC_LINK_SECRET", _TEST_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_sign_then_verify_round_trips_email_and_nonce() -> None:
    token = sign_magic_link("alice@example.com", "n-abc123")
    email, nonce = verify_magic_link(token)
    assert email == "alice@example.com"
    assert nonce == "n-abc123"


def test_token_mutated_by_one_byte_raises_invalid() -> None:
    token = sign_magic_link("a@b.com", "n1")
    # Flip a single character somewhere in the middle of the payload.
    mutated = token[:-3] + ("A" if token[-3] != "A" else "B") + token[-2:]
    with pytest.raises(MagicLinkInvalid):
        verify_magic_link(mutated)


def test_token_signed_with_different_secret_raises_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sign under a different secret using itsdangerous directly. Then
    # verify under the test secret — signature must not match.
    foreign_serializer = URLSafeTimedSerializer("a-different-secret", salt="magic-link")
    foreign_token = foreign_serializer.dumps({"email": "a@b.com", "nonce": "n1"})

    with pytest.raises(MagicLinkInvalid):
        verify_magic_link(foreign_token)


def test_token_older_than_ttl_raises_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    # Jump time forward past the 15-minute TTL between sign and verify.
    real_time = time.time
    fake_now = real_time()

    def fake_time() -> float:
        return fake_now

    # Sign at "now"
    monkeypatch.setattr(time, "time", fake_time)
    token = sign_magic_link("a@b.com", "n1")

    # Verify "16 minutes later" — past the 900s TTL
    later = fake_now + (60 * 16)
    monkeypatch.setattr(time, "time", lambda: later)
    with pytest.raises(MagicLinkExpired):
        verify_magic_link(token)


def test_sign_with_unset_secret_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAGIC_LINK_SECRET", "")
    get_settings.cache_clear()
    with pytest.raises(MagicLinkConfigError):
        sign_magic_link("a@b.com", "n1")


def test_verify_with_unset_secret_also_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First sign a valid token with a real secret
    token = sign_magic_link("a@b.com", "n1")
    # Then unset the secret and try to verify — should fail loud, not
    # silently succeed or return None.
    monkeypatch.setenv("MAGIC_LINK_SECRET", "")
    get_settings.cache_clear()
    with pytest.raises(MagicLinkConfigError):
        verify_magic_link(token)


def test_token_with_wrong_salt_raises_invalid() -> None:
    # The auth module signs with salt="magic-link". A token signed with
    # a different salt under the same secret must NOT be accepted —
    # this is the salt's whole job.
    secret = _TEST_SECRET
    other_serializer = URLSafeTimedSerializer(secret, salt="some-other-purpose")
    foreign_token = other_serializer.dumps({"email": "a@b.com", "nonce": "n1"})

    with pytest.raises(MagicLinkInvalid):
        verify_magic_link(foreign_token)


def test_malformed_payload_raises_invalid() -> None:
    # A correctly signed payload that doesn't look like {email, nonce}
    # must raise — we don't want None-return surprises in callers.
    secret = _TEST_SECRET
    serializer = URLSafeTimedSerializer(secret, salt="magic-link")
    bad_payload_token = serializer.dumps("just a string, not a dict")
    with pytest.raises(MagicLinkInvalid):
        verify_magic_link(bad_payload_token)

    missing_field_token = serializer.dumps({"email": "a@b.com"})  # no nonce
    with pytest.raises(MagicLinkInvalid):
        verify_magic_link(missing_field_token)


def test_two_tokens_with_different_nonces_decode_to_their_own_nonces() -> None:
    # Sanity check that nonce isn't a constant baked in somewhere.
    t1 = sign_magic_link("a@b.com", "first")
    t2 = sign_magic_link("a@b.com", "second")
    assert t1 != t2
    assert verify_magic_link(t1)[1] == "first"
    assert verify_magic_link(t2)[1] == "second"
