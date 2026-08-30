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

**Unit-tested beyond `_connect_kwargs` too now, via mocking
`asyncssh.connect`/`create_process` directly** -- confirmed live that
"thin enough to be correct by inspection" was wrong at least once: this
module shipped without `encoding=None` on `create_process`, and
asyncssh's default UTF-8 text mode broke the moment real (binary)
`dumpcap` output reached it. `run_command`'s actual round-trip over a
real SSH connection is still untested (needs a live server this
project's test environment doesn't have), but the *shape* of both
calls -- which arguments actually reach `asyncssh`, which was exactly
where the bug was -- is now covered without needing one.
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

    `encoding=None` is required here, not optional -- confirmed live:
    `asyncssh.create_process()` defaults to text mode (UTF-8-decoding
    every byte of channel data) unless told otherwise, but `dumpcap`'s
    output (`-w -`) is raw binary pcap/pcapng, not text at all. Without
    this, asyncssh raised `ProtocolError: 'utf-8' codec can't decode
    byte ... invalid continuation byte` on the very first non-UTF-8 byte
    of real capture data. `run_command` (used only for `docker ps`,
    genuinely textual output) is correctly left in the default text mode
    -- this fix is specific to the binary streaming path.
    """
    import asyncssh

    async with asyncssh.connect(**_connect_kwargs(settings)) as conn:
        async with conn.create_process(command, encoding=None) as process:
            yield process
