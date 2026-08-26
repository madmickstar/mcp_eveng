"""CLI entrypoint: `mcp-eveng` / `python -m mcp_eveng`.

Transport is chosen with a flag, not an environment variable:

    mcp-eveng              # stdio (default) -- launched by an MCP host
    mcp-eveng --sse        # legacy SSE transport, network-exposed
    mcp-eveng --http       # Streamable HTTP transport, network-exposed (recommended)

`--sse` and `--http` are mutually exclusive. With neither set, the server
runs in stdio mode and none of the MCP_* network settings are needed --
the MCP host process supplies EVENG_* connection details directly via its
own "env" block instead.
"""

from __future__ import annotations

import argparse
import sys

from .config import Transport
from .server import run


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mcp-eveng",
        description="MCP server for automating EVE-NG labs.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--sse",
        action="store_true",
        default=False,
        help="Serve over the legacy SSE transport (network-exposed). Uses MCP_* env vars.",
    )
    group.add_argument(
        "--http",
        action="store_true",
        default=False,
        help=(
            "Serve over the Streamable HTTP transport (network-exposed, recommended). "
            "Uses MCP_* env vars."
        ),
    )
    return parser.parse_args(argv)


def _resolve_transport(args: argparse.Namespace) -> Transport:
    if args.sse:
        return "sse"
    if args.http:
        return "streamable-http"
    return "stdio"


def main() -> None:
    args = _parse_args()
    try:
        run(_resolve_transport(args))
    except KeyboardInterrupt:
        # Defensive fallback: `run()` already handles Ctrl+C around the actual
        # server loop, but this also covers a Ctrl+C landing during the brief
        # setup window (e.g. while loading settings) before that starts.
        print("\nGoodbye!", file=sys.stderr)
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
