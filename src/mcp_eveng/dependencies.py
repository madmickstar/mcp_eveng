"""Lazy, process-wide singleton for the EVENG client, plus a per-lab lock
registry for serializing multi-step operations against the same lab.

Tool functions call `get_client()` to obtain an authenticated client without
each of them managing connection/session lifecycle themselves. The
singleton is created on first use and torn down via `close_client()`,
which the server calls from its MCP lifespan shutdown hook.

Tests should not rely on this singleton: `tools.<module>.register()`
accepts an injectable `get_client` callable specifically so unit tests can
supply a fake/mocked client instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .client import EvengClient

_client: EvengClient | None = None
_lock = asyncio.Lock()


async def get_client() -> EvengClient:
    """Return a shared, authenticated `EvengClient`, creating it if needed."""
    global _client
    async with _lock:
        if _client is None:
            _client = EvengClient()
        await _client.ensure_authenticated()
        return _client


async def close_client() -> None:
    """Close and drop the shared client, if one was created."""
    global _client
    async with _lock:
        if _client is not None:
            await _client.aclose()
            _client = None


# -- per-lab locking -------------------------------------------------------
#
# An AI agent's habit of firing several tool calls at once is harmless for
# read-only tools, but several mutating tools (connect_interface, add_*,
# edit_*, wipe_node, start_node/stop_node) do a read-then-decide-then-write
# sequence against EVE-NG, with real `await` gaps in between. Two
# concurrent calls against the SAME lab can each read the same "before"
# state and then both act on it -- e.g. both pick the same free interface,
# or a concurrent stop_node/start_node call undoes the "make sure it's
# stopped first" step edit_lab_node/connect_interface already did. EVE-NG's
# own server-side per-lab file locking (see the "stale lock file" guidance
# in client.py's 500-response handler) is independent evidence that
# concurrent access to the same lab isn't something the server tolerates
# well either.
#
# This registry hands out one `asyncio.Lock` per lab_path (created on first
# use, kept for the life of the process) so a mutating tool function can
# serialize its own entire read-modify-write sequence against every other
# call touching the same lab, while calls against DIFFERENT labs still run
# fully in parallel -- the agent's parallel habit becomes harmless queueing
# instead of a race.
_lab_locks: dict[str, asyncio.Lock] = {}
_lab_locks_guard = asyncio.Lock()


@asynccontextmanager
async def lab_lock(lab_path: str) -> AsyncIterator[None]:
    """Serialize the wrapped block against every other call for this same
    `lab_path`.

    Acquire once per mutating tool call, held for its entire read-modify-
    write sequence -- not just a single client call -- so a concurrent call
    against the same lab genuinely queues behind it rather than interleaving
    partway through. Calls against a different `lab_path` are never blocked
    by this.

    Not reentrant: a function already holding this lock for a given
    `lab_path` must not call another function that acquires it again for
    that SAME `lab_path`, or it will deadlock (a plain `asyncio.Lock` has no
    concept of "the task already holding this may re-enter"). None of the
    tool functions that use this call each other directly -- they only
    share client methods, which don't take the lock themselves -- so this
    doesn't currently arise; keep it that way if adding new lab-scoped
    tools.

    The lock registry itself only ever grows (one entry per distinct
    `lab_path` ever seen, for the life of the process) -- accepted as
    negligible for any realistic number of labs.
    """
    async with _lab_locks_guard:
        lock = _lab_locks.get(lab_path)
        if lock is None:
            lock = asyncio.Lock()
            _lab_locks[lab_path] = lock
    async with lock:
        yield
