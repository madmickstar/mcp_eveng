"""Standalone HTTP relay: verifies a `get_capture` token, then streams
`sudo docker exec <container> dumpcap -i eth0 -w -`'s output over SSH back to
the requesting client (the `.bat` companion's curl call) as a live,
unbounded HTTP response body.

Runs as its own systemd service (`mcp-eveng-capture-relay`), independent
of the main `mcp-eveng` process, so a crash or hang here can never take
the main MCP tool server down with it.

Built on Starlette rather than a new HTTP framework -- already a
transitive dependency via `mcp[cli]`'s own `--http` transport, so this
doesn't add anything new to the dependency graph.

Token verification can be disabled entirely via
`CAPTURE_RELAY_TOKEN_REQUIRED=false` (see `config.py`) -- an explicit
admin opt-out for a trusted network, not the default.

**The actual SSH+dumpcap streaming is unverified against a live
target** -- this project's test environment has no real SSH server or
docker host to exercise it against. What IS tested (see
`tests/capture_relay/test_server.py`): token verification/rejection in
both modes (required and disabled), the chunk-forwarding loop, EOF
handling, and disconnect handling, all against a fake process/reader
injected via `open_stream` in place of the real SSH connection. The
real `asyncssh` calls (via `ssh_client.streaming_process`) are
believed correct by inspection, matching this project's convention for
unavoidable I/O-boundary code (see `client.py`'s `_get`/`_put`), but
should be exercised live before relying on them in production.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from collections.abc import AsyncIterator, Callable
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from .config import CaptureSSHSettings
from .ssh_client import streaming_process as _default_streaming_process
from .tokens import InvalidToken, decode_token_unverified, verify_token

logger = logging.getLogger("mcp_eveng.capture_relay")

# Read buffer size per chunk -- not tied to actual traffic in any way,
# dumpcap's own writes aren't chunked to any particular size.
DEFAULT_READ_CHUNK_BYTES = 65536

# How long to wait for more data before checking whether the client's
# gone. Keeps disconnect detection responsive without polling in a
# tight loop or waiting indefinitely on a quiet capture.
DEFAULT_READ_TIMEOUT_SECONDS = 1.0

OpenStream = Callable[[CaptureSSHSettings, str], Any]  # AsyncContextManager[process]


def _dumpcap_command(container: str) -> str:
    """The exact command run inside the capture container. `eth0` is
    the interface name EVE-NG's own capture containers expose the
    mirrored traffic on -- confirmed live while reverse-engineering
    `apiCaptureInterface()` earlier in this project (the mirror
    destination port is attached into the container's netns under this
    name). `shlex.quote` on the container name is defensive -- docker
    container names are restricted to a safe character set in
    practice, but this is a command string headed over SSH, so it
    isn't skipped just because the input is expected to already be safe.

    `sudo` is required -- confirmed live (same issue as
    `docker_ps.DOCKER_PS_COMMAND`): without it, `docker exec` can't
    reach the daemon socket. Matches the sudoers rule
    `docs/capture-relay.md` sets up for this account.
    """
    return f"sudo docker exec {shlex.quote(container)} dumpcap -i eth0 -w -"


async def _stream_capture(
    settings: CaptureSSHSettings,
    container: str,
    request: Request,
    open_stream: OpenStream,
    *,
    read_chunk_bytes: int = DEFAULT_READ_CHUNK_BYTES,
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
) -> AsyncIterator[bytes]:
    """The byte-forwarding loop: reads from the SSH process's stdout
    and yields chunks, stopping promptly if the client disconnects
    (checked every `read_timeout_seconds`) rather than only noticing
    when a write eventually fails, and stopping cleanly on EOF (the
    capture process itself ended, e.g. the EVE-NG-side container was
    stopped)."""
    command = _dumpcap_command(container)
    async with open_stream(settings, command) as process:
        while True:
            if await request.is_disconnected():
                return
            try:
                chunk = await asyncio.wait_for(process.stdout.read(read_chunk_bytes), timeout=read_timeout_seconds)
            except asyncio.TimeoutError:
                continue
            if not chunk:
                return
            yield chunk


def create_relay_app(
    settings: CaptureSSHSettings,
    open_stream: OpenStream = _default_streaming_process,
    *,
    token_required: bool = True,
    read_chunk_bytes: int = DEFAULT_READ_CHUNK_BYTES,
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
) -> Starlette:
    """Build the relay's Starlette app.

    `open_stream` and the read tuning parameters are injectable so
    tests can supply a fake SSH process instead of a real one --
    production code always uses the defaults. `token_required=False`
    is `CAPTURE_RELAY_TOKEN_REQUIRED`'s effect (see config.py) -- an
    explicit admin opt-out of token verification entirely, not
    something to default away from `True` in code.
    """

    async def stream_endpoint(request: Request):
        token = request.query_params.get("token")
        if not token:
            return JSONResponse({"status": "error", "message": "missing token"}, status_code=400)

        try:
            claim = (
                verify_token(token, settings.token_secret.get_secret_value())
                if token_required
                else decode_token_unverified(token)
            )
        except InvalidToken as exc:
            # The client-facing message stays deliberately vague (see
            # tokens.py's own docstring) -- this specific reason (e.g.
            # "signature mismatch" vs "expired") is only logged
            # server-side, at DEBUG, for an admin diagnosing a rejected
            # request they expected to succeed.
            logger.debug("Rejected capture stream request: %s", exc)
            message = "invalid or expired token" if token_required else "malformed token"
            status_code = 403 if token_required else 400
            return JSONResponse({"status": "error", "message": message}, status_code=status_code)

        return StreamingResponse(
            _stream_capture(
                settings,
                claim.container,
                request,
                open_stream,
                read_chunk_bytes=read_chunk_bytes,
                read_timeout_seconds=read_timeout_seconds,
            ),
            media_type="application/vnd.tcpdump.pcap",
        )

    return Starlette(routes=[Route("/capture/stream", stream_endpoint, methods=["GET"])])
