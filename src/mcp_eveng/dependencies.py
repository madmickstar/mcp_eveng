"""Lazy, process-wide singleton for the EVENG client.

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
