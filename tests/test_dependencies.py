from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import mcp_eveng.dependencies as deps


@pytest.fixture(autouse=True)
async def _reset_singleton():
    """Ensure each test starts and ends with a clean singleton."""
    await deps.close_client()
    yield
    await deps.close_client()


async def test_get_client_creates_and_reuses_singleton(monkeypatch) -> None:
    created = []

    class FakeClient:
        def __init__(self):
            created.append(self)
            self.ensure_authenticated = AsyncMock()
            self.aclose = AsyncMock()

    monkeypatch.setattr(deps, "EvengClient", FakeClient)

    first = await deps.get_client()
    second = await deps.get_client()

    assert first is second
    assert len(created) == 1
    assert first.ensure_authenticated.await_count == 2


async def test_close_client_drops_singleton(monkeypatch) -> None:
    class FakeClient:
        def __init__(self):
            self.ensure_authenticated = AsyncMock()
            self.aclose = AsyncMock()

    monkeypatch.setattr(deps, "EvengClient", FakeClient)

    first = await deps.get_client()
    await deps.close_client()
    second = await deps.get_client()

    assert first is not second
    first.aclose.assert_awaited_once()
