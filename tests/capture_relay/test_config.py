from __future__ import annotations

import pytest

from mcp_eveng.capture_relay.config import CaptureSSHSettings, CaptureURLSettings, RelayListenSettings


def test_capture_ssh_settings_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("CAPTURE_SSH_HOST", "172.16.130.14")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")

    settings = CaptureSSHSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.ssh_host == "172.16.130.14"
    assert settings.ssh_username == "capture-svc"
    assert settings.ssh_key_path == "/etc/mcp-eveng/capture-relay.key"
    assert settings.token_secret.get_secret_value() == "s3cret"


def test_capture_ssh_settings_defaults() -> None:
    settings = CaptureSSHSettings(
        ssh_host="172.16.130.14",
        ssh_username="capture-svc",
        ssh_key_path="/etc/mcp-eveng/capture-relay.key",
        token_secret="s3cret",
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.ssh_port == 22
    assert settings.ssh_known_hosts is None
    assert settings.token_ttl_seconds == 60
    assert settings.ssh_timeout_seconds == 15.0


def test_capture_ssh_settings_requires_host_username_key_and_secret() -> None:
    with pytest.raises(Exception):  # pydantic ValidationError
        CaptureSSHSettings(_env_file=None)  # type: ignore[call-arg]


def test_relay_listen_settings_defaults() -> None:
    settings = RelayListenSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.listen_host == "0.0.0.0"
    assert settings.listen_port == 8001


def test_relay_listen_settings_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("CAPTURE_RELAY_LISTEN_HOST", "10.0.0.5")
    monkeypatch.setenv("CAPTURE_RELAY_LISTEN_PORT", "9001")

    settings = RelayListenSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.listen_host == "10.0.0.5"
    assert settings.listen_port == 9001


def test_capture_ssh_env_prefix_does_not_leak_into_relay_listen_settings(monkeypatch) -> None:
    # CAPTURE_ vs CAPTURE_RELAY_ prefixes must not cross-contaminate --
    # e.g. CAPTURE_SSH_HOST should never be readable as a RelayListenSettings field.
    monkeypatch.setenv("CAPTURE_SSH_HOST", "172.16.130.14")

    settings = RelayListenSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.listen_host == "0.0.0.0"


def test_capture_url_settings_defaults_advertise_port_to_8001() -> None:
    settings = CaptureURLSettings(advertise_host="172.16.130.14", _env_file=None)  # type: ignore[call-arg]

    assert settings.advertise_port == 8001


def test_capture_url_settings_and_relay_listen_settings_share_prefix_without_collision(monkeypatch) -> None:
    monkeypatch.setenv("CAPTURE_RELAY_ADVERTISE_HOST", "172.16.130.14")
    monkeypatch.setenv("CAPTURE_RELAY_LISTEN_HOST", "0.0.0.0")

    url_settings = CaptureURLSettings(_env_file=None)  # type: ignore[call-arg]
    listen_settings = RelayListenSettings(_env_file=None)  # type: ignore[call-arg]

    assert url_settings.advertise_host == "172.16.130.14"
    assert listen_settings.listen_host == "0.0.0.0"
