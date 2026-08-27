"""Thin async SSH wrapper for the capture-relay feature.

Deliberately minimal: asyncssh already handles connection setup and the
run/process primitives -- this module just supplies the connection
kwargs (from `CaptureSSHSettings`) in one place, so `tools/capture.py`
and the relay's `server.py` don't each reconstruct them slightly
differently.

**`asyncssh` is imported lazily, inside `run_command`/
`streaming_process`, not at module top level.** `tools/capture.py`
imports this module, and `server.py` unconditionally imports every
tools module regardless of whether `list_captures`/`get_capture` are
even enabled -- a top-level `import asyncssh` here would mean the
*entire* `mcp-eveng` server fails to start whenever the optional
`capture-relay` extra isn't installed, for every user, not just people
touching this feature. (Confirmed the hard way: exactly this happened
on a real test install.) `is_available()` below lets callers check
first and give a clear, actionable error instead of a raw
`ModuleNotFoundError` surfacing from inside an MCP tool call.

**Not unit-tested beyond `_connect_kwargs`.** Actually opening an SSH
connection requires a live SSH server, which this project's test
environment doesn't have. `_connect_kwargs` is factored out separately
so at least that part is directly testable; `run_command` and
`streaming_process` are thin enough to be correct by inspection,
matching this project's own convention for I/O-boundary code (see
`client.py`'s `_get`/`_put`) -- but they're genuinely unverified against
a real target and should be exercised live before relying on them.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from .config import CaptureSSHSettings


def is_available() -> bool:
    """Whether `asyncssh` is importable in the current environment.
    Used by `tools/capture.py` to give a clear, actionable error before
    attempting any SSH work, rather than a raw `ModuleNotFoundError`
    bubbling out of an MCP tool call."""
    try:
        import asyncssh  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def _connect_kwargs(settings: CaptureSSHSettings) -> dict:
    """Connection kwargs for `asyncssh.connect()`, built once from
    settings so every caller applies the same host-key policy.

    `known_hosts=None` (when `settings.ssh_known_hosts` is unset)
    disables host-key checking entirely -- see the warning on
    `CaptureSSHSettings.ssh_known_hosts`.
    """
    return {
        "host": settings.ssh_host,
        "port": settings.ssh_port,
        "username": settings.ssh_username,
        "client_keys": [settings.ssh_key_path],
        "known_hosts": settings.ssh_known_hosts or None,
    }


async def run_command(settings: CaptureSSHSettings, command: str) -> str:
    """Run one command to completion over SSH and return its stdout.

    For bounded, fast output only (e.g. `docker ps`) -- NOT for
    `dumpcap` streaming, which never completes on its own. Use
    `streaming_process` for that instead.
    """
    import asyncssh

    async with asyncssh.connect(**_connect_kwargs(settings)) as conn:
        result = await conn.run(command, check=False, timeout=settings.ssh_timeout_seconds)
        stdout = result.stdout
        return stdout if isinstance(stdout, str) else (stdout or b"").decode("utf-8", "replace")


@asynccontextmanager
async def streaming_process(settings: CaptureSSHSettings, command: str) -> AsyncIterator[Any]:
    """Run `command` over SSH and yield the live process so its stdout
    can be read as it arrives, for as long as the caller keeps the
    context open (i.e. for as long as the relay's HTTP client stays
    connected). Both the process and the underlying SSH connection are
    torn down on exit, including on an exception -- the caller doesn't
    need to manage that separately.
    """
    import asyncssh

    async with asyncssh.connect(**_connect_kwargs(settings)) as conn:
        async with conn.create_process(command) as process:
            yield process
