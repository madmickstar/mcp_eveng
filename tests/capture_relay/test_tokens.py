from __future__ import annotations

import pytest

from mcp_eveng.capture_relay.tokens import InvalidToken, decode_token_unverified, issue_token, verify_token

SECRET = "test-secret-do-not-use-in-prod"


def test_issue_then_verify_round_trips_the_container_name() -> None:
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)

    result = verify_token(token, SECRET)

    assert result.container == "Capture-2101248"


def test_verify_fails_with_wrong_secret() -> None:
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)

    with pytest.raises(InvalidToken):
        verify_token(token, "a-completely-different-secret")


def test_verify_fails_when_expired() -> None:
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)
    issued_at = verify_token(token, SECRET).issued_at

    # 61 seconds after issuance -- one second past the 60s TTL.
    with pytest.raises(InvalidToken):
        verify_token(token, SECRET, now=issued_at + 61)


def test_verify_succeeds_one_second_before_expiry() -> None:
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)
    issued_at = verify_token(token, SECRET).issued_at

    # Still valid 59 seconds in -- one second of margin before the 60s TTL.
    result = verify_token(token, SECRET, now=issued_at + 59)

    assert result.container == "Capture-2101248"


def test_verify_fails_on_expiry_boundary_itself() -> None:
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)
    issued_at = verify_token(token, SECRET).issued_at

    # Exactly at expiry -- current >= exp is treated as expired, not valid.
    with pytest.raises(InvalidToken):
        verify_token(token, SECRET, now=issued_at + 60)


def test_verify_fails_on_malformed_token_missing_separator() -> None:
    with pytest.raises(InvalidToken):
        verify_token("not-a-real-token-at-all", SECRET)


def test_verify_fails_on_tampered_payload() -> None:
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)
    payload_b64, signature_b64 = token.split(".", 1)

    # Swap in a different (validly-formed) payload without re-signing --
    # simulates an attacker trying to change which container a token
    # authorizes access to.
    other_token = issue_token("Capture-9999999", SECRET, ttl_seconds=60)
    other_payload_b64, _ = other_token.split(".", 1)
    tampered = f"{other_payload_b64}.{signature_b64}"

    with pytest.raises(InvalidToken):
        verify_token(tampered, SECRET)


def test_verify_fails_on_non_json_payload() -> None:
    # A payload segment that base64-decodes fine but isn't JSON at all --
    # signed correctly against the tampered bytes, so only the "is this
    # actually a valid payload" check should catch it.
    from mcp_eveng.capture_relay.tokens import _b64url_encode, _sign

    bogus_payload_b64 = _b64url_encode(b"not json{{{")
    signature_b64 = _sign(bogus_payload_b64, SECRET)
    token = f"{bogus_payload_b64}.{signature_b64}"

    with pytest.raises(InvalidToken):
        verify_token(token, SECRET)


def test_different_containers_produce_different_tokens() -> None:
    token_a = issue_token("Capture-1111111", SECRET, ttl_seconds=60)
    token_b = issue_token("Capture-2222222", SECRET, ttl_seconds=60)

    assert token_a != token_b
    assert verify_token(token_a, SECRET).container == "Capture-1111111"
    assert verify_token(token_b, SECRET).container == "Capture-2222222"


# ============================================================================
# decode_token_unverified -- used only when CAPTURE_RELAY_TOKEN_REQUIRED=false
# ============================================================================


def test_decode_unverified_reads_container_from_a_correctly_signed_token() -> None:
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)

    result = decode_token_unverified(token)

    assert result.container == "Capture-2101248"


def test_decode_unverified_accepts_a_token_signed_with_the_wrong_secret() -> None:
    """The whole point: unlike verify_token, this never checks the
    signature at all."""
    token = issue_token("Capture-2101248", "a-totally-different-secret", ttl_seconds=60)

    result = decode_token_unverified(token)

    assert result.container == "Capture-2101248"


def test_decode_unverified_accepts_an_expired_token() -> None:
    """The whole point: unlike verify_token, this never checks expiry
    at all."""
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=-100)  # already expired

    result = decode_token_unverified(token)

    assert result.container == "Capture-2101248"


def test_decode_unverified_still_rejects_malformed_token_shape() -> None:
    with pytest.raises(InvalidToken):
        decode_token_unverified("not-even-two-dot-separated-parts")


def test_decode_unverified_still_rejects_non_json_payload() -> None:
    from mcp_eveng.capture_relay.tokens import _b64url_encode

    bogus_payload_b64 = _b64url_encode(b"not json{{{")
    token = f"{bogus_payload_b64}.anything-here-is-never-checked"

    with pytest.raises(InvalidToken):
        decode_token_unverified(token)


def test_decode_unverified_still_rejects_payload_missing_container() -> None:
    from mcp_eveng.capture_relay.tokens import _b64url_encode

    incomplete_payload_b64 = _b64url_encode(b'{"iat":1,"exp":2}')  # no "container" key
    token = f"{incomplete_payload_b64}.anything-here-is-never-checked"

    with pytest.raises(InvalidToken):
        decode_token_unverified(token)
