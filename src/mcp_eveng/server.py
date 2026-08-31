"""EVENG MCP server: wires the EVENG client into a FastMCP app.

Supports all three transports the `mcp` SDK ships:
  * stdio            -- default, used by local MCP hosts (Claude Desktop, etc.)
  * sse               -- legacy HTTP transport, kept for compatibility
  * streamable-http   -- recommended transport for networked deployments

Which transport to serve is a **CLI flag** (`--sse` / `--http`, no flag =
stdio) handled in `__main__.py` -- it is not read from the environment.
The network-only settings (bind host/port/paths, DNS-rebinding allowlist,
statefulness, log level, optional API key, optional TLS) still come from
`MCPTransportSettings`, read from environment variables / a `.env` file --
see `config.py`.

`--sse`/`--http` are served with our own `uvicorn.Config`, not
`FastMCP.run()`'s -- the SDK's own `run_sse_async`/`run_streamable_http_async`
hardcode a plain-HTTP `uvicorn.Config` with no hook for either an API-key
check or TLS, so this module builds the same Starlette app the SDK would
(via the SDK's own public `sse_app()`/`streamable_http_app()`), optionally
wraps it with `_APIKeyMiddleware`, and serves it with `uvicorn.Config`
ourselves, adding `ssl_certfile`/`ssl_keyfile` when configured.
"""

from __future__ import annotations

import logging
import secrets
import sys
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

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


def _build_transport_security(settings: MCPTransportSettings, transport: Transport) -> TransportSecuritySettings | None:
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


def create_server(settings: MCPTransportSettings | None = None, transport: Transport = "stdio") -> FastMCP:
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


class _APIKeyMiddleware:
    """Raw ASGI middleware -- rejects any HTTP request that doesn't present
    `Authorization: Bearer <api_key>` with a 401, before it ever reaches the
    real MCP handler. Only installed when `MCP_API_KEY` is set -- see
    `_run_networked`.

    Uses `secrets.compare_digest` for the comparison, not `==` -- a plain
    string comparison short-circuits on the first mismatched byte, which
    leaks (via response timing) how many leading characters of a guessed
    key were correct. That would partially defeat the point of an API key
    check, so this is not a stylistic choice.
    """

    def __init__(self, app: ASGIApp, api_key: str) -> None:
        self._app = app
        self._expected = f"Bearer {api_key}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        presented = headers.get(b"authorization", b"")
        # compare_digest requires equal-length inputs to stay constant-time;
        # a length mismatch is itself a safe, non-sensitive thing to leak
        # (it doesn't narrow down the key's actual content at all).
        if len(presented) != len(self._expected) or not secrets.compare_digest(presented, self._expected):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


def _check_tls_files_readable(cert_path: str | None, key_path: str | None) -> None:
    """Raise a clear, actionable error before uvicorn ever gets a chance
    to try. Confirmed live (against the relay's identical check -- see
    `capture_relay/__main__.py`): a bad path (a typo, a missing file,
    wrong permissions) passed to OpenSSL's `load_cert_chain()` surfaces
    as an utterly unhelpful `OSError: [Errno 22] Invalid argument`, with
    nothing indicating which of the two files is the problem or what's
    actually wrong with it -- opening each file ourselves catches the
    same underlying OS errors (missing, wrong type, unreadable) with a
    message that actually says which variable and which path.
    """
    for path, var_name in (
        (cert_path, "MCP_TLS_CERT_PATH"),
        (key_path, "MCP_TLS_KEY_PATH"),
    ):
        if path is None:
            continue
        try:
            with open(path, "rb") as f:
                f.read(1)
        except OSError as e:
            print(f"{var_name} could not be read ({e.strerror or e}): {path!r}", file=sys.stderr)
            raise SystemExit(1) from None


def _run_networked(mcp: FastMCP, settings: MCPTransportSettings, transport: Transport) -> None:
    """Serve `--sse`/`--http` ourselves, not via `FastMCP.run()` -- see this
    module's docstring for why."""
    import uvicorn

    app: ASGIApp = mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()

    if settings.api_key is not None:
        app = _APIKeyMiddleware(app, settings.api_key.get_secret_value())
        logger.info("API key required for every request (MCP_API_KEY is set).")
    else:
        logger.info("No API key configured (MCP_API_KEY unset) -- relying on the Host-header allowlist alone.")

    if settings.tls_cert_path and settings.tls_key_path:
        logger.info("Serving over HTTPS (MCP_TLS_CERT_PATH/MCP_TLS_KEY_PATH are set).")
    else:
        logger.info("Serving over plain HTTP (MCP_TLS_CERT_PATH/MCP_TLS_KEY_PATH unset).")

    _check_tls_files_readable(settings.tls_cert_path, settings.tls_key_path)

    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        ssl_certfile=settings.tls_cert_path,
        ssl_keyfile=settings.tls_key_path,
        ssl_keyfile_password=(settings.tls_key_password.get_secret_value() if settings.tls_key_password else None),
    )
    server = uvicorn.Server(config)
    anyio.run(server.serve)


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
        if transport == "stdio":
            mcp.run(transport="stdio")
        else:
            _run_networked(mcp, settings, transport)
    except KeyboardInterrupt:
        # Ctrl+C is a normal way to stop the server, especially in --sse/--http
        # mode running in a foreground terminal. Exit quietly with a friendly
        # message instead of letting the KeyboardInterrupt traceback spill out.
        # Printed to stderr, never stdout -- stdout carries the stdio
        # JSON-RPC stream, and a stray line there could confuse a host that's
        # still reading it during shutdown.
        print("\nGoodbye!", file=sys.stderr)
        raise SystemExit(0) from None
