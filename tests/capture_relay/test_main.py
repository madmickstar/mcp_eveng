from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp_eveng.capture_relay import __main__ as relay_main
from mcp_eveng.capture_relay.config import get_capture_ssh_settings, get_relay_listen_settings


def test_main_passes_timeout_graceful_shutdown_to_uvicorn(monkeypatch) -> None:
    """Regression test for a real, confirmed gap: uvicorn's own default
    for `timeout_graceful_shutdown` is `None`, which (confirmed against
    uvicorn's own source -- `asyncio.wait_for(..., timeout=None)`) means
    it waits FOREVER for in-flight requests, including a capture stream
    that never finishes on its own. Without an explicit value here,
    `systemctl stop` on the relay would hang until systemd's own much
    longer default `TimeoutStopSec` gives up and SIGKILLs the whole
    process, bypassing the cleanup that actually terminates the remote
    `dumpcap` process. This confirms the value is genuinely passed
    through to `uvicorn.run`, not just present somewhere in the file.

    `get_capture_ssh_settings`/`get_relay_listen_settings` are
    `@lru_cache`d -- cleared before and after so this test's env vars
    are actually read fresh, and so it can't leave a stale cached
    instance behind for any other test that happens to call these same
    getters later.
    """
    get_capture_ssh_settings.cache_clear()
    get_relay_listen_settings.cache_clear()
    monkeypatch.setenv("CAPTURE_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")

    try:
        with patch("uvicorn.run") as mock_run:
            relay_main.main()

        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert "timeout_graceful_shutdown" in kwargs
        assert isinstance(kwargs["timeout_graceful_shutdown"], (int, float))
        assert kwargs["timeout_graceful_shutdown"] > 0
    finally:
        get_capture_ssh_settings.cache_clear()
        get_relay_listen_settings.cache_clear()


def test_main_passes_no_ssl_kwargs_when_tls_unconfigured(monkeypatch) -> None:
    get_capture_ssh_settings.cache_clear()
    get_relay_listen_settings.cache_clear()
    monkeypatch.setenv("CAPTURE_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")

    try:
        with patch("uvicorn.run") as mock_run:
            relay_main.main()

        _, kwargs = mock_run.call_args
        assert kwargs["ssl_certfile"] is None
        assert kwargs["ssl_keyfile"] is None
    finally:
        get_capture_ssh_settings.cache_clear()
        get_relay_listen_settings.cache_clear()


def test_main_passes_ssl_kwargs_when_tls_configured(monkeypatch, tmp_path) -> None:
    """Confirms CAPTURE_RELAY_TLS_CERT_PATH/_KEY_PATH genuinely reach
    uvicorn.run as ssl_certfile/ssl_keyfile, not just present somewhere
    in the settings object."""
    get_capture_ssh_settings.cache_clear()
    get_relay_listen_settings.cache_clear()
    cert = tmp_path / "relay-cert.pem"
    key = tmp_path / "relay-key.pem"
    cert.write_text("fake cert content")
    key.write_text("fake key content")
    monkeypatch.setenv("CAPTURE_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("CAPTURE_RELAY_TLS_CERT_PATH", str(cert))
    monkeypatch.setenv("CAPTURE_RELAY_TLS_KEY_PATH", str(key))

    try:
        with patch("uvicorn.run") as mock_run:
            relay_main.main()

        _, kwargs = mock_run.call_args
        assert kwargs["ssl_certfile"] == str(cert)
        assert kwargs["ssl_keyfile"] == str(key)
        assert kwargs["ssl_keyfile_password"] is None
    finally:
        get_capture_ssh_settings.cache_clear()
        get_relay_listen_settings.cache_clear()


def test_main_passes_tls_key_password_when_set(monkeypatch, tmp_path) -> None:
    get_capture_ssh_settings.cache_clear()
    get_relay_listen_settings.cache_clear()
    cert = tmp_path / "relay-cert.pem"
    key = tmp_path / "relay-key.pem"
    cert.write_text("fake cert content")
    key.write_text("fake key content")
    monkeypatch.setenv("CAPTURE_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("CAPTURE_RELAY_TLS_CERT_PATH", str(cert))
    monkeypatch.setenv("CAPTURE_RELAY_TLS_KEY_PATH", str(key))
    monkeypatch.setenv("CAPTURE_RELAY_TLS_KEY_PASSWORD", "hunter2")

    try:
        with patch("uvicorn.run") as mock_run:
            relay_main.main()

        _, kwargs = mock_run.call_args
        assert kwargs["ssl_keyfile_password"] == "hunter2"
    finally:
        get_capture_ssh_settings.cache_clear()
        get_relay_listen_settings.cache_clear()


def test_main_passes_default_log_level_to_uvicorn(monkeypatch) -> None:
    get_capture_ssh_settings.cache_clear()
    get_relay_listen_settings.cache_clear()
    monkeypatch.setenv("CAPTURE_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")

    try:
        with patch("uvicorn.run") as mock_run:
            relay_main.main()

        _, kwargs = mock_run.call_args
        assert kwargs["log_level"] == "info"
    finally:
        get_capture_ssh_settings.cache_clear()
        get_relay_listen_settings.cache_clear()


def test_main_passes_configured_log_level_to_uvicorn(monkeypatch) -> None:
    """Confirms CAPTURE_RELAY_LOG_LEVEL genuinely reaches uvicorn.run as
    log_level (lowercased, matching uvicorn's own expected casing), not
    just present somewhere in the settings object."""
    get_capture_ssh_settings.cache_clear()
    get_relay_listen_settings.cache_clear()
    monkeypatch.setenv("CAPTURE_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("CAPTURE_RELAY_LOG_LEVEL", "DEBUG")

    try:
        with patch("uvicorn.run") as mock_run:
            relay_main.main()

        _, kwargs = mock_run.call_args
        assert kwargs["log_level"] == "debug"
    finally:
        get_capture_ssh_settings.cache_clear()
        get_relay_listen_settings.cache_clear()


def test_main_configures_python_logging_at_configured_level(monkeypatch) -> None:
    """Confirms CAPTURE_RELAY_LOG_LEVEL also drives logging.basicConfig,
    not just uvicorn's own log_level -- the two are separate mechanisms
    (Python's logging module vs. uvicorn's internal access/error logs)
    and both need wiring, matching the main mcp-eveng process's own
    pattern in server.py's run()."""
    get_capture_ssh_settings.cache_clear()
    get_relay_listen_settings.cache_clear()
    monkeypatch.setenv("CAPTURE_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("CAPTURE_RELAY_LOG_LEVEL", "WARNING")

    try:
        with patch("uvicorn.run"), patch("logging.basicConfig") as mock_basic_config:
            relay_main.main()

        _, kwargs = mock_basic_config.call_args
        assert kwargs["level"] == "WARNING"
    finally:
        get_capture_ssh_settings.cache_clear()
        get_relay_listen_settings.cache_clear()


# ============================================================================
# _check_tls_files_readable -- confirmed live: a bad TLS path (a typo, a
# missing file, wrong permissions) reaching OpenSSL's load_cert_chain()
# unchecked surfaces as an utterly unhelpful "OSError: [Errno 22] Invalid
# argument", with no indication of which file or what's wrong.
# ============================================================================


def test_check_tls_files_readable_passes_when_both_unset() -> None:
    relay_main._check_tls_files_readable(None, None)  # must not raise


def test_check_tls_files_readable_passes_for_real_readable_files(tmp_path) -> None:
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake cert content")
    key.write_text("fake key content")

    relay_main._check_tls_files_readable(str(cert), str(key))  # must not raise


def test_check_tls_files_readable_exits_clearly_on_missing_cert(tmp_path, capsys) -> None:
    key = tmp_path / "key.pem"
    key.write_text("fake key content")
    missing_cert = tmp_path / "does_not_exist.pem"

    with pytest.raises(SystemExit) as exc_info:
        relay_main._check_tls_files_readable(str(missing_cert), str(key))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "CAPTURE_RELAY_TLS_CERT_PATH" in captured.err
    assert str(missing_cert) in captured.err


def test_check_tls_files_readable_exits_clearly_on_missing_key(tmp_path, capsys) -> None:
    cert = tmp_path / "cert.pem"
    cert.write_text("fake cert content")
    missing_key = tmp_path / "does_not_exist.pem"

    with pytest.raises(SystemExit) as exc_info:
        relay_main._check_tls_files_readable(str(cert), str(missing_key))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "CAPTURE_RELAY_TLS_KEY_PATH" in captured.err
    assert str(missing_key) in captured.err


def test_check_tls_files_readable_exits_clearly_when_path_is_a_directory(tmp_path, capsys) -> None:
    key = tmp_path / "key.pem"
    key.write_text("fake key content")
    a_directory = tmp_path / "not_a_file"
    a_directory.mkdir()

    with pytest.raises(SystemExit):
        relay_main._check_tls_files_readable(str(a_directory), str(key))

    captured = capsys.readouterr()
    assert "CAPTURE_RELAY_TLS_CERT_PATH" in captured.err


def test_main_exits_cleanly_before_uvicorn_when_tls_cert_unreadable(monkeypatch, tmp_path) -> None:
    """Confirms main() actually calls the check before uvicorn.run, not
    just that the check function works in isolation."""
    get_capture_ssh_settings.cache_clear()
    get_relay_listen_settings.cache_clear()
    monkeypatch.setenv("CAPTURE_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("CAPTURE_SSH_USERNAME", "capture-svc")
    monkeypatch.setenv("CAPTURE_SSH_KEY_PATH", "/etc/mcp-eveng/capture-relay.key")
    monkeypatch.setenv("CAPTURE_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("CAPTURE_RELAY_TLS_CERT_PATH", str(tmp_path / "missing_cert.pem"))
    monkeypatch.setenv("CAPTURE_RELAY_TLS_KEY_PATH", str(tmp_path / "missing_key.pem"))

    try:
        with patch("uvicorn.run") as mock_run, pytest.raises(SystemExit):
            relay_main.main()

        mock_run.assert_not_called()
    finally:
        get_capture_ssh_settings.cache_clear()
        get_relay_listen_settings.cache_clear()
