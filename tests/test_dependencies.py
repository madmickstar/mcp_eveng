from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import mcp_eveng.dependencies as deps


@pytest.fixture(autouse=True)
async def _reset_singleton():
    """Ensure each test starts and ends with a clean singleton and lab-lock registry."""
    await deps.close_client()
    deps._lab_locks.clear()
    yield
    await deps.close_client()
    deps._lab_locks.clear()


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


# -- lab_lock ---------------------------------------------------------------
#
# The scenario these guard against: an AI agent fires several tool calls at
# once against the same lab. Without serialization, two concurrent
# read-modify-write sequences (e.g. connect_interface picking a "free"
# interface, or edit_lab_node's stop-then-edit) can interleave and race.


async def test_lab_lock_serializes_calls_for_the_same_lab_path() -> None:
    events: list[str] = []

    async def worker(label: str, delay: float) -> None:
        async with deps.lab_lock("/same.unl"):
            events.append(f"{label}-start")
            await asyncio.sleep(delay)
            events.append(f"{label}-end")

    # "a" is slower than "b" -- if unlocked, a naive interleaving would put
    # b's start (and often its end) between a's start and end. Serialized,
    # one worker's start+end must appear as a contiguous pair before the
    # other's start appears at all, regardless of which one runs first.
    await asyncio.gather(worker("a", 0.05), worker("b", 0.01))

    assert events in (
        ["a-start", "a-end", "b-start", "b-end"],
        ["b-start", "b-end", "a-start", "a-end"],
    )


async def test_lab_lock_does_not_serialize_different_lab_paths() -> None:
    events: list[str] = []

    async def worker(label: str, lab_path: str) -> None:
        async with deps.lab_lock(lab_path):
            events.append(f"{label}-start")
            await asyncio.sleep(0.05)
            events.append(f"{label}-end")

    await asyncio.gather(worker("a", "/a.unl"), worker("b", "/b.unl"))

    # Unlocked/parallel: both start before either finishes -- the direct
    # opposite of the same-lab_path test above.
    assert set(events[:2]) == {"a-start", "b-start"}


async def test_lab_lock_releases_on_exception() -> None:
    with pytest.raises(ValueError, match="boom"):
        async with deps.lab_lock("/x.unl"):
            raise ValueError("boom")

    # A failed call must not leave the lock permanently held -- acquiring it
    # again for the same lab_path has to succeed promptly, not hang.
    async def reacquire() -> None:
        async with deps.lab_lock("/x.unl"):
            pass

    await asyncio.wait_for(reacquire(), timeout=1)


async def test_lab_lock_reuses_the_same_lock_object_for_the_same_path() -> None:
    async with deps.lab_lock("/reuse.unl"):
        pass
    first_lock = deps._lab_locks["/reuse.unl"]
    async with deps.lab_lock("/reuse.unl"):
        pass
    assert deps._lab_locks["/reuse.unl"] is first_lock


# -- closing from a different event loop than the connections were opened on ---------


def _client_with_pooled_connection_on_a_dead_loop():
    """An EvengClient whose pool holds a live keep-alive connection bound to an event loop that has since closed."""
    import asyncio

    import httpx

    from mcp_eveng.client import EvengClient

    async def handler(reader, writer) -> None:  # noqa: ANN001
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n{}")
        await writer.drain()
        await asyncio.sleep(30)  # keep the connection open (keep-alive)

    async def open_connection() -> httpx.AsyncClient:
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        http = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}")
        await http.get("/x")
        return http

    http = asyncio.run(open_connection())  # that loop is now closed, like after Ctrl+C
    assert len(http._transport._pool.connections) == 1  # type: ignore[attr-defined]
    return EvengClient.__new__(EvengClient), http


def test_close_client_from_a_new_loop_does_not_raise_event_loop_is_closed(monkeypatch) -> None:
    """Regression: `anyio.run(close_client)` after Ctrl+C raised `RuntimeError: Event loop is closed`."""
    import anyio

    shell, http = _client_with_pooled_connection_on_a_dead_loop()

    async def real_aclose() -> None:
        await http.aclose()

    shell.aclose = real_aclose  # type: ignore[method-assign]
    monkeypatch.setattr(deps, "_client", shell)

    anyio.run(deps.close_client)  # must not raise

    assert deps._client is None


async def test_close_client_still_raises_unrelated_runtime_errors(monkeypatch) -> None:
    class FakeClient:
        async def aclose(self) -> None:
            raise RuntimeError("something else broke")

    monkeypatch.setattr(deps, "_client", FakeClient())

    with pytest.raises(RuntimeError, match="something else broke"):
        await deps.close_client()

    assert deps._client is None  # dropped regardless, so shutdown is never retried forever
