"""EVENG MCP server: wires the EVENG client into a FastMCP app.

Supports all three transports the `mcp` SDK ships:
  * stdio            -- default, used by local MCP hosts (Claude Desktop, etc.)
  * sse               -- legacy HTTP transport, kept for compatibility
  * streamable-http   -- recommended transport for networked deployments

Which transport to serve is a **CLI flag** (`--sse` / `--http`, no flag =
stdio) handled in `__main__.py` -- it is not read from the environment.
The network-only settings (bind host/port/paths, DNS-rebinding allowlist,
statefulness, log level) still come from `MCPTransportSettings`, read from
environment variables / a `.env` file -- see `config.py`.
"""

from __future__ import annotations

import logging
import sys
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .config import MCPTransportSettings, Transport, get_mcp_settings
from .dependencies import close_client, get_client
from .tool_config import load_tool_status, make_enabled_predicate
from .tools import capture, console, folders, labs, meta, networks, nodes, quality, system, users

logger = logging.getLogger("mcp_eveng")

# Hosts the MCP SDK itself treats as loopback and auto-protects against
# DNS-rebinding without any extra configuration.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# The `mcp` SDK's internal FastMCP `Settings` model has a `lifespan` field
# typed with a self-referential forward reference to `FastMCP` itself, and
# the SDK never calls `model_rebuild()` on it. pydantic-settings warns about
# this every time a FastMCP instance is constructed, regardless of whether a
# `lifespan` was supplied (nothing reads that field from the environment, so
# the warning has no functional effect) -- it's an upstream SDK quirk, not
# something we can fix from here. Silence just this one message so it
# doesn't clutter stderr on every startup.
warnings.filterwarnings(
    "ignore",
    message=r"Field 'lifespan' has an incomplete definition.*",
)


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    """Close the shared EVENG HTTP session when the MCP server shuts down."""
    try:
        yield
    finally:
        await close_client()


def _build_transport_security(
    settings: MCPTransportSettings, transport: Transport
) -> TransportSecuritySettings | None:
    """Build the Host-header allowlist that guards the sse/streamable-http listeners.

    stdio never opens a socket, so it needs none of this.

    For a loopback bind host the MCP SDK auto-enables DNS-rebinding
    protection with a loopback-only allowlist, so we leave `transport_security`
    unset and let the SDK's own default handle it. For any other bind host
    (e.g. "0.0.0.0", a LAN IP), the SDK does **not** auto-protect -- without an
    explicit allowlist, requests would be accepted with no Host-header
    validation at all. So MCP_ALLOWED_HOSTS is required in that case.
    """
    if transport == "stdio":
        return None
    if settings.allowed_hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
        )
    if settings.host in _LOOPBACK_HOSTS:
        return None
    raise RuntimeError(
        f"MCP_HOST={settings.host!r} is not a loopback address, so it needs an "
        "explicit Host-header allowlist. Set MCP_ALLOWED_HOSTS to a comma-separated "
        "list, e.g. MCP_ALLOWED_HOSTS='localhost:*,192.168.10.100:*' -- "
        "otherwise the server would be reachable with no DNS-rebinding protection."
    )


def create_server(
    settings: MCPTransportSettings | None = None, transport: Transport = "stdio"
) -> FastMCP:
    """Build a fully-configured `FastMCP` instance with every EVENG tool registered."""
    settings = settings or get_mcp_settings()
    transport_security = _build_transport_security(settings, transport)
    enabled = make_enabled_predicate(load_tool_status(settings.tools_config_path))

    mcp = FastMCP(
        "mcp-eveng",
        instructions=(
            "Tools for automating an EVENG network emulator instance: manage "
            "folders, users, labs, nodes and networks, and start/stop/wipe nodes. "
            "Call get_status first to confirm connectivity."
        ),
        host=settings.host,
        port=settings.port,
        streamable_http_path=settings.http_path,
        sse_path=settings.sse_path,
        # Stateless mode drops streamable-http session persistence so a server
        # restart never leaves a client holding a now-unrecognized session id.
        stateless_http=not settings.stateful,
        transport_security=transport_security,
        lifespan=_lifespan,
    )

    for module in (system, folders, users, labs, networks, nodes, quality, capture, meta, console):
        module.register(mcp, get_client, enabled)

    return mcp


def run(transport: Transport = "stdio") -> None:
    """Entrypoint used by both `python -m mcp_eveng` and the `mcp-eveng` console script."""
    settings = get_mcp_settings()
    # stdout is reserved for the stdio JSON-RPC stream -- logs always go to
    # stderr, regardless of transport, so they never corrupt the protocol.
    logging.basicConfig(
        level=settings.log_level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mcp = create_server(settings, transport)
    logger.info("Starting mcp-eveng with transport=%s", transport)
    try:
        mcp.run(transport=transport)
    except KeyboardInterrupt:
        # Ctrl+C is a normal way to stop the server, especially in --sse/--http
        # mode running in a foreground terminal. Exit quietly with a friendly
        # message instead of letting the KeyboardInterrupt traceback spill out.
        # Printed to stderr, never stdout -- stdout carries the stdio
        # JSON-RPC stream, and a stray line there could confuse a host that's
        # still reading it during shutdown.
        print("\nGoodbye!", file=sys.stderr)
        raise SystemExit(0) from None
