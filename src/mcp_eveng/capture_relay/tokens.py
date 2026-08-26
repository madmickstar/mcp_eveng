"""Self-contained, HMAC-signed tokens for the capture relay.

The relay (`mcp-eveng-capture-relay`) runs as its own systemd service,
independent of the main `mcp-eveng` process -- deliberately, so a crash
in one can't take the other down. That separation means the two
processes share no runtime state (no database, no shared memory, no RPC
between them) -- so a token minted by `get_capture` (in the main
process) has to be verifiable by the relay (a different process,
possibly on a different restart cycle) without either one calling the
other or consulting shared storage.

The scheme: a token is `<base64url(payload json)>.<base64url(HMAC-SHA256
signature)>`, signed with a secret both processes read from their own
`.env` (`CAPTURE_RELAY_TOKEN_SECRET` -- same shared-secret pattern this
project already uses for `EVENG_PASSWORD` etc.). Verifying a token means
recomputing the HMAC over the payload and comparing (constant-time) --
no lookup, no state, no network call. This is the same self-contained
approach a JWT takes, without pulling in a JWT library for one narrow
use.

A token is scoped to exactly one container and carries its own
expiry -- there's no revocation list; letting it expire is the only way
to invalidate one early. Short TTLs (`get_capture`'s default is 60
seconds -- long enough for the `.bat` to act on it, short enough that a
leaked URL stops being useful quickly) are the entire mitigation for
that.
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


class InvalidToken(Exception):
    """Raised by `verify_token` for any reason a token can't be trusted:
    malformed, signature mismatch, or expired. Deliberately one
    exception type for all three -- the relay's response to a bad token
    doesn't need to (and shouldn't) reveal which of those it was."""


@dataclass(frozen=True)
class CaptureToken:
    """A verified token's payload. Only ever constructed by
    `verify_token` after the signature and expiry have already checked
    out -- there's no public constructor that skips verification."""

    container: str
    issued_at: int
    expires_at: int


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload_b64: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), sha256).digest()
    return _b64url_encode(digest)


def issue_token(container: str, secret: str, ttl_seconds: int = 60) -> str:
    """Mint a token scoped to `container`, valid for `ttl_seconds` from
    now. Called by `get_capture` in the main MCP process -- never by the
    relay, which only ever verifies.

    Args:
        container: The exact container name this token authorizes
            streaming from (e.g. "Capture-2101248").
        secret: The shared HMAC secret (`CAPTURE_RELAY_TOKEN_SECRET`).
        ttl_seconds: How long the token stays valid. Keep this short --
            it's the only revocation mechanism there is.
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "container": container,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_b64 = _sign(payload_b64, secret)
    return f"{payload_b64}.{signature_b64}"


def verify_token(token: str, secret: str, *, now: int | None = None) -> CaptureToken:
    """Verify a token's signature and expiry, returning its payload.
    Called by the relay for every incoming stream request -- never by
    the main MCP process, which only ever issues.

    Args:
        token: The token as produced by `issue_token`.
        secret: The shared HMAC secret -- must match the one used to
            issue it, or verification fails.
        now: Unix timestamp to check expiry against. Defaults to the
            real current time; only overridden in tests.

    Raises:
        InvalidToken: if the token is malformed, the signature doesn't
            match, or it's expired. Callers shouldn't try to distinguish
            these -- see the module docstring.
    """
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError:
        raise InvalidToken("malformed token") from None

    expected_signature_b64 = _sign(payload_b64, secret)
    if not hmac.compare_digest(signature_b64, expected_signature_b64):
        raise InvalidToken("signature mismatch")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidToken("malformed payload") from exc

    if not isinstance(payload, dict):
        raise InvalidToken("malformed payload")

    container = payload.get("container")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not isinstance(container, str) or not isinstance(issued_at, int) or not isinstance(expires_at, int):
        raise InvalidToken("malformed payload")

    current_time = int(time.time()) if now is None else now
    if current_time >= expires_at:
        raise InvalidToken("expired")

    return CaptureToken(container=container, issued_at=issued_at, expires_at=expires_at)
