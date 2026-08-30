from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from starlette.testclient import TestClient

from mcp_eveng.capture_relay.config import CaptureSSHSettings
from mcp_eveng.capture_relay.server import _dumpcap_command, _stream_capture, create_relay_app
from mcp_eveng.capture_relay.tokens import issue_token

SECRET = "test-secret-do-not-use-in-prod"


def ssh_settings(**overrides) -> CaptureSSHSettings:
    defaults = dict(
        ssh_host="172.16.130.14",
        ssh_username="capture-svc",
        ssh_key_path="/etc/mcp-eveng/capture-relay.key",
        token_secret=SECRET,
    )
    defaults.update(overrides)
    return CaptureSSHSettings(_env_file=None, **defaults)  # type: ignore[call-arg]


class FakeStdout:
    """Hands back chunks from a list in order, then b"" (EOF). An
    optional per-read delay lets tests force the wait_for timeout
    branch in _stream_capture without needing a slow real SSH read."""

    def __init__(self, chunks: list[bytes], delay: float = 0.0) -> None:
        self._chunks = list(chunks)
        self._delay = delay

    async def read(self, _n: int) -> bytes:
        if self._delay:
            await asyncio.sleep(self._delay)
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class FakeProcess:
    def __init__(self, chunks: list[bytes], delay: float = 0.0) -> None:
        self.stdout = FakeStdout(chunks, delay)


def fake_open_stream(chunks: list[bytes], delay: float = 0.0):
    @asynccontextmanager
    async def _open(settings, command):
        yield FakeProcess(chunks, delay)

    return _open


class _TrackedOpenStream:
    """Like fake_open_stream, but records whether the context manager's
    cleanup actually ran -- used to confirm cancellation propagates
    through it correctly (see test_stream_capture_cleans_up_on_task_cancellation)."""

    def __init__(self, chunks: list[bytes], delay: float = 0.0) -> None:
        self.chunks = chunks
        self.delay = delay
        self.exited = False

    @asynccontextmanager
    async def __call__(self, settings, command):
        try:
            yield FakeProcess(self.chunks, self.delay)
        finally:
            self.exited = True


class FakeRequest:
    """Controls is_disconnected() via a sequence of return values,
    consumed in order; once exhausted, always reports connected."""

    def __init__(self, disconnected_sequence: list[bool]) -> None:
        self._sequence = list(disconnected_sequence)

    async def is_disconnected(self) -> bool:
        if self._sequence:
            return self._sequence.pop(0)
        return False


# -- _stream_capture: the chunk-forwarding loop, tested directly --------------


async def test_stream_capture_yields_chunks_in_order() -> None:
    request = FakeRequest([])

    chunks = [
        chunk
        async for chunk in _stream_capture(
            ssh_settings(), "Capture-2101248", request, fake_open_stream([b"abc", b"def"])
        )
    ]

    assert chunks == [b"abc", b"def"]


async def test_stream_capture_stops_on_eof() -> None:
    request = FakeRequest([])

    chunks = [
        chunk async for chunk in _stream_capture(ssh_settings(), "Capture-2101248", request, fake_open_stream([]))
    ]

    assert chunks == []


async def test_stream_capture_stops_immediately_if_already_disconnected() -> None:
    request = FakeRequest([True])

    chunks = [
        chunk
        async for chunk in _stream_capture(
            ssh_settings(), "Capture-2101248", request, fake_open_stream([b"should-not-be-read"])
        )
    ]

    assert chunks == []


async def test_stream_capture_stops_after_timeout_detects_disconnect() -> None:
    # First disconnect check: still connected. The read then blocks
    # longer than read_timeout_seconds, forcing the TimeoutError/continue
    # branch. Second disconnect check (after the timeout): disconnected.
    request = FakeRequest([False, True])

    chunks = [
        chunk
        async for chunk in _stream_capture(
            ssh_settings(),
            "Capture-2101248",
            request,
            fake_open_stream([b"never-arrives"], delay=0.05),
            read_timeout_seconds=0.01,
        )
    ]

    assert chunks == []


async def test_stream_capture_yields_data_that_arrives_within_timeout() -> None:
    request = FakeRequest([])

    chunks = [
        chunk
        async for chunk in _stream_capture(
            ssh_settings(),
            "Capture-2101248",
            request,
            fake_open_stream([b"fast-chunk"], delay=0.0),
            read_timeout_seconds=1.0,
        )
    ]

    assert chunks == [b"fast-chunk"]


async def test_stream_capture_cleans_up_on_task_cancellation() -> None:
    """Regression test for a real, confirmed gap: without an explicit
    `timeout_graceful_shutdown`, uvicorn's own default (`None`) means
    `systemctl stop` on the relay would hang indefinitely (a capture
    stream never finishes on its own) until systemd's own much longer
    default `TimeoutStopSec` gives up and SIGKILLs the whole process --
    bypassing this cleanup entirely and orphaning the remote `dumpcap`
    process on the EVE-NG host. Confirms OUR side of that fix: that
    cancelling the task actually iterating this generator does run
    `open_stream`'s cleanup, per Python's normal
    cancellation-through-`async with` semantics. The other half --
    something actually calling `.cancel()` in time -- is uvicorn's own
    `timeout_graceful_shutdown`, set explicitly in `__main__.py`.
    """
    tracked = _TrackedOpenStream([b"chunk-1"], delay=10.0)  # never arrives on its own
    request = FakeRequest([])

    async def consume() -> None:
        async for _ in _stream_capture(ssh_settings(), "Capture-x", request, tracked):
            pass

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0.05)  # let it start and reach the (slow) read
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert tracked.exited is True


# -- create_relay_app: HTTP routing + token layer, via TestClient -------------


def test_missing_token_returns_400() -> None:
    app = create_relay_app(ssh_settings(), open_stream=fake_open_stream([]))
    client = TestClient(app)

    response = client.get("/capture/stream")

    assert response.status_code == 400


def test_invalid_token_returns_403() -> None:
    app = create_relay_app(ssh_settings(), open_stream=fake_open_stream([]))
    client = TestClient(app)

    response = client.get("/capture/stream?token=not-a-real-token")

    assert response.status_code == 403


def test_expired_token_returns_403() -> None:
    settings = ssh_settings()
    expired_token = issue_token("Capture-2101248", SECRET, ttl_seconds=-1)
    app = create_relay_app(settings, open_stream=fake_open_stream([]))
    client = TestClient(app)

    response = client.get(f"/capture/stream?token={expired_token}")

    assert response.status_code == 403


def test_valid_token_streams_the_fake_process_output() -> None:
    settings = ssh_settings()
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)
    app = create_relay_app(settings, open_stream=fake_open_stream([b"pcap-bytes-1", b"pcap-bytes-2"]))
    client = TestClient(app)

    response = client.get(f"/capture/stream?token={token}")

    assert response.status_code == 200
    assert response.content == b"pcap-bytes-1pcap-bytes-2"


def test_valid_token_sets_pcap_content_type() -> None:
    settings = ssh_settings()
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)
    app = create_relay_app(settings, open_stream=fake_open_stream([b"data"]))
    client = TestClient(app)

    response = client.get(f"/capture/stream?token={token}")

    assert response.headers["content-type"] == "application/vnd.tcpdump.pcap"


def test_token_for_wrong_secret_is_rejected() -> None:
    settings = ssh_settings(token_secret="a-different-secret")
    token = issue_token("Capture-2101248", SECRET, ttl_seconds=60)  # signed with SECRET, not settings' secret
    app = create_relay_app(settings, open_stream=fake_open_stream([b"data"]))
    client = TestClient(app)

    response = client.get(f"/capture/stream?token={token}")

    assert response.status_code == 403


def test_dumpcap_command_is_prefixed_with_sudo() -> None:
    # Regression test: confirmed live that without sudo, docker exec
    # can't reach the daemon socket -- same underlying issue as
    # docker_ps.DOCKER_PS_COMMAND, matches the sudoers rule
    # docs/capture-relay.md sets up.
    command = _dumpcap_command("Capture-2101248")

    assert command.startswith("sudo docker exec ")
    assert "Capture-2101248" in command
    assert command.endswith("dumpcap -i eth0 -w -")
