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


def main() -> None:
    ssh_settings = get_capture_ssh_settings()
    listen_settings = get_relay_listen_settings()
    app = create_relay_app(ssh_settings)

    try:
        uvicorn.run(app, host=listen_settings.listen_host, port=listen_settings.listen_port)
    except KeyboardInterrupt:
        print("\nGoodbye!", file=sys.stderr)
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
