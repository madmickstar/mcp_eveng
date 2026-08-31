"""CLI entrypoint: `mcp-eveng-capture-relay` / `python -m mcp_eveng.capture_relay`.

Runs as its own systemd service, independent of the main `mcp-eveng`
process -- see `docs/capture-relay.md`. No CLI flags: everything comes
from `.env` (`CAPTURE_SSH_*`, `CAPTURE_TOKEN_SECRET`,
`CAPTURE_RELAY_LISTEN_*` -- see `config.py`).
"""

from __future__ import annotations

import sys

import uvicorn

from .config import get_capture_ssh_settings, get_relay_listen_settings
from .server import create_relay_app

# How long uvicorn waits, on shutdown (SIGTERM -- e.g. `systemctl stop`),
# for in-flight requests to finish naturally before cancelling them
# itself. Confirmed against uvicorn's own source: the default is `None`,
# which means `asyncio.wait_for(..., timeout=None)` -- wait FOREVER, and
# the code path that cancels remaining tasks is never reached at all.
# A capture stream never finishes on its own (that's the whole point --
# it runs until the client disconnects or the process ends), so with the
# default, stopping this service while a capture is running would hang
# until systemd's own (much longer, default 90s) TimeoutStopSec gives up
# and SIGKILLs the whole process -- which bypasses Python's own cleanup
# entirely (the `async with` chain in `streaming_process` that closes the
# SSH channel, which is what actually terminates the remote `dumpcap`
# process), leaving it orphaned on the EVE-NG host. Setting an explicit,
# short value here means uvicorn cancels any still-running capture
# streams itself after this many seconds, which DOES let that cleanup
# chain run (Python's task cancellation raises CancelledError at the
# suspended await point, which propagates out through the `async with`
# blocks normally) -- see docs/capture-relay.md's systemd unit for the
# matching `TimeoutStopSec` safety net on top of this.
_SHUTDOWN_TIMEOUT_SECONDS = 5


def main() -> None:
    ssh_settings = get_capture_ssh_settings()
    listen_settings = get_relay_listen_settings()
    app = create_relay_app(ssh_settings)

    try:
        uvicorn.run(
            app,
            host=listen_settings.listen_host,
            port=listen_settings.listen_port,
            timeout_graceful_shutdown=_SHUTDOWN_TIMEOUT_SECONDS,
            ssl_certfile=listen_settings.tls_cert_path,
            ssl_keyfile=listen_settings.tls_key_path,
            ssl_keyfile_password=(
                listen_settings.tls_key_password.get_secret_value() if listen_settings.tls_key_password else None
            ),
        )
    except KeyboardInterrupt:
        print("\nGoodbye!", file=sys.stderr)
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
