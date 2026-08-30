from __future__ import annotations

from unittest.mock import patch

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
    monkeypatch.setenv("CAPTURE_SSH_HOST", "172.16.130.14")
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
