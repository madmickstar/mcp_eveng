from __future__ import annotations

from mcp_eveng.capture_relay.config import CaptureSSHSettings
from mcp_eveng.capture_relay.ssh_client import _connect_kwargs

# NOTE: run_command and streaming_process themselves are NOT tested here --
# they require a live SSH server, which this project's test environment
# doesn't have. See ssh_client.py's module docstring.


def _settings(**overrides) -> CaptureSSHSettings:
    defaults = dict(
        ssh_host="172.16.130.14",
        ssh_username="capture-svc",
        ssh_key_path="/etc/mcp-eveng/capture-relay.key",
        token_secret="s3cret",
    )
    defaults.update(overrides)
    return CaptureSSHSettings(_env_file=None, **defaults)  # type: ignore[call-arg]


def test_connect_kwargs_includes_host_port_username_and_key() -> None:
    kwargs = _connect_kwargs(_settings())

    assert kwargs["host"] == "172.16.130.14"
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
