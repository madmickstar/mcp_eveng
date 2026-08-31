from __future__ import annotations

from mcp_eveng.capture_relay.config import CaptureSSHSettings
from mcp_eveng.capture_relay.ssh_client import _connect_kwargs, streaming_process

# NOTE: run_command and the actual SSH round-trip inside streaming_process
# are NOT tested here -- they require a live SSH server, which this
# project's test environment doesn't have. What CAN be tested without one,
# and now is (see below): that streaming_process calls asyncssh with the
# right *arguments* -- confirmed live that getting this wrong is a real,
# silent-until-you-stream-real-data class of bug (encoding=None was
# missing, and asyncssh's default UTF-8 text mode broke on real binary
# dumpcap output with a ProtocolError only a live capture would trigger).


def _settings(**overrides) -> CaptureSSHSettings:
    defaults = dict(
        ssh_host="192.168.1.50",
        ssh_username="capture-svc",
        ssh_key_path="/etc/mcp-eveng/capture-relay.key",
        token_secret="s3cret",
    )
    defaults.update(overrides)
    return CaptureSSHSettings(_env_file=None, **defaults)  # type: ignore[call-arg]


def test_connect_kwargs_includes_host_port_username_and_key() -> None:
    kwargs = _connect_kwargs(_settings())

    assert kwargs["host"] == "192.168.1.50"
    assert kwargs["port"] == 22
    assert kwargs["username"] == "capture-svc"
    assert kwargs["client_keys"] == ["/etc/mcp-eveng/capture-relay.key"]


def test_connect_kwargs_disables_host_key_checking_when_known_hosts_unset() -> None:
    kwargs = _connect_kwargs(_settings())

    assert kwargs["known_hosts"] is None


def test_connect_kwargs_uses_known_hosts_file_when_configured() -> None:
    kwargs = _connect_kwargs(_settings(ssh_known_hosts="/etc/mcp-eveng/known_hosts"))

    assert kwargs["known_hosts"] == "/etc/mcp-eveng/known_hosts"


def test_connect_kwargs_respects_custom_port() -> None:
    kwargs = _connect_kwargs(_settings(ssh_port=2222))

    assert kwargs["port"] == 2222


# -- streaming_process: verify the asyncssh call shape, mocked ---------------


class _FakeAsyncCM:
    """A bare async context manager wrapping a fixed value -- stands in
    for both `asyncssh.connect(...)` and `conn.create_process(...)`,
    which asyncssh itself makes usable directly as `async with X() as y`
    without a separate `await`."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc_info):
        return False


class _FakeConnection:
    def __init__(self):
        self.create_process_calls: list[tuple[str, dict]] = []

    def create_process(self, command, **kwargs):
        self.create_process_calls.append((command, kwargs))
        return _FakeAsyncCM("fake-process-handle")


async def test_streaming_process_requests_raw_bytes_not_text(monkeypatch) -> None:
    """Regression test for a real, live-confirmed bug: asyncssh defaults
    to UTF-8 text mode, which broke on real (binary) dumpcap output --
    `ProtocolError: 'utf-8' codec can't decode byte ... invalid
    continuation byte`. `encoding=None` (asyncssh's own documented way
    to request raw bytes -- verified directly against the installed
    library's docstring, not just assumed) must actually be passed to
    `create_process`."""
    import asyncssh

    fake_conn = _FakeConnection()
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeAsyncCM(fake_conn))

    async with streaming_process(_settings(), "sudo docker exec x dumpcap -i eth0 -w -") as process:
        assert process == "fake-process-handle"

    assert len(fake_conn.create_process_calls) == 1
    command, kwargs = fake_conn.create_process_calls[0]
    assert command == "sudo docker exec x dumpcap -i eth0 -w -"
    assert "encoding" in kwargs
    assert kwargs["encoding"] is None


async def test_streaming_process_passes_connect_kwargs_through(monkeypatch) -> None:
    import asyncssh

    captured_connect_kwargs = {}

    def fake_connect(**kwargs):
        captured_connect_kwargs.update(kwargs)
        return _FakeAsyncCM(_FakeConnection())

    monkeypatch.setattr(asyncssh, "connect", fake_connect)

    settings = _settings(ssh_host="192.168.1.50", ssh_port=2222)
    async with streaming_process(settings, "some command"):
        pass

    assert captured_connect_kwargs["host"] == "192.168.1.50"
    assert captured_connect_kwargs["port"] == 2222
