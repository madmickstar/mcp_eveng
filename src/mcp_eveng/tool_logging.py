"""Tool-call visibility: logs which MCP tool a client invoked as structured
key=value fields -- timestamp, status, tool name, client address, and the
JSON arguments passed (with sensitive-looking values redacted) -- plus
(optional) rotating-file log output.

Answers the "can we even see this?" question first: `FastMCP.call_tool(name,
arguments)` (see the `mcp` SDK's `mcp/server/fastmcp/server.py`) is the single
choke point every tool call passes through on every transport -- stdio, sse,
and streamable-http alike. `FastMCP._setup_handlers()` registers exactly this
bound method as the low-level `mcp.server.lowlevel.Server`'s `call_tool`
request handler. Subclassing `FastMCP` and overriding `call_tool` here means
one call site captures every tool invocation, without touching any of the
~47 individual `@mcp.tool` registrations spread across `tools/*.py`.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock

logger = logging.getLogger("mcp_eveng.tool_calls")

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_FILENAME = "mcp-eveng.log"

_REDACTED_PLACEHOLDER = "***REDACTED***"

# Argument-name suffixes (case-insensitive) treated as sensitive and never
# written to the log in full -- matched as an exact name (e.g. "password")
# or as "..._<suffix>" (e.g. "rdp_password", which add_lab_node/change of
# an rdp/rdp-tls console node's password takes as an argument). Extend this
# tuple if a future tool adds another argument that shouldn't be logged
# verbatim -- e.g. add_user/edit_user's own "password" argument, or a
# future SSH/API-key-carrying argument.
_SENSITIVE_ARGUMENT_SUFFIXES = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
)


def _format_timestamp(dt: datetime) -> str:
    """ISO-8601 with milliseconds: `2026-09-11T19:31:00.000Z` for UTC, or
    `2026-09-11T19:31:00.000+10:00` for any other offset.

    `datetime.isoformat()` already produces that exact `+HH:MM` form for a
    non-zero offset -- the only adjustment needed is swapping a zero
    offset's `+00:00` for the more conventional `Z`.
    """
    text = dt.isoformat(timespec="milliseconds")
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def _now() -> str:
    """Current time in the format above, in the local timezone -- so a
    server running with `TZ=UTC` naturally logs `Z`, and one running in
    another timezone naturally logs its own `+HH:MM` offset."""
    return _format_timestamp(datetime.now().astimezone())


class _Iso8601Formatter(logging.Formatter):
    """`logging.Formatter` whose `%(asctime)s` renders in the same
    ISO-8601 style as `_now()` above (`Z` for UTC, `+HH:MM`/`-HH:MM`
    otherwise), instead of the default `2026-09-11 19:31:00,001`.

    Used for every handler `build_log_handlers()` builds below, so this
    applies to every log line written through this project -- not just
    tool-call lines -- since it's the formatter itself that changed.
    """

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return _format_timestamp(datetime.fromtimestamp(record.created).astimezone())


def _is_sensitive_argument_name(name: str) -> bool:
    lowered = name.lower()
    return any(lowered == suffix or lowered.endswith(f"_{suffix}") for suffix in _SENSITIVE_ARGUMENT_SUFFIXES)


def _redact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Replace any sensitive-looking argument value with a fixed placeholder
    before logging -- the key name is still logged (useful for seeing *that*
    a password was being changed), just not the value itself."""
    return {
        key: (_REDACTED_PLACEHOLDER if _is_sensitive_argument_name(key) else value) for key, value in arguments.items()
    }


def _safe_json(value: Any) -> str:
    """Best-effort JSON serialization for logging.

    Tool arguments are normally plain JSON-compatible types already (that's
    the whole point of MCP tool call arguments), but `default=str` means a
    logging call itself can never raise over something unexpected.
    """
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _client_address(context: Any) -> str:
    """Best-effort "host:port" of the connected client, for the sse/
    streamable-http transports -- both hand the low-level server the real
    Starlette `Request` for each call (see `mcp.server.streamable_http`/
    `mcp.server.sse`), which carries `.client` from the ASGI connection.

    stdio has no such thing -- it's a local subprocess talking over stdin/
    stdout pipes, not a network connection -- so this returns "stdio" in
    that case rather than a misleading blank/n-a value.
    """
    try:
        request_context = context.request_context
    except (LookupError, ValueError):
        return "unknown"
    request = getattr(request_context, "request", None)
    if request is None:
        return "stdio"
    client = getattr(request, "client", None)
    if client is None:
        return "unknown"
    host = getattr(client, "host", None)
    port = getattr(client, "port", None)
    if host is None:
        return "unknown"
    return f"{host}:{port}" if port is not None else host


class ToolCallLoggingFastMCP(FastMCP):
    """`FastMCP` that logs every tool call as key=value fields: status
    (`call`/`finished`/`error`), tool name, client address, arguments
    (JSON, with sensitive values redacted) on the initial line, and
    duration_ms on the follow-up line. The timestamp isn't repeated in the
    message body -- the line's own leading timestamp (see
    `_Iso8601Formatter` above) already covers it.

    Logged at INFO so it's visible with the project's default log level with
    no extra configuration. A failing call is logged at ERROR alongside the
    exception, then re-raised unchanged -- this class only observes calls,
    it never changes their outcome.
    """

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        start = time.monotonic()
        client = _client_address(self.get_context())
        logger.info(
            "status=call tool=%s client=%s arguments=%s",
            name,
            client,
            _safe_json(_redact_arguments(arguments)),
        )
        try:
            result = await super().call_tool(name, arguments)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error(
                "status=error tool=%s client=%s duration_ms=%.1f error=%s",
                name,
                client,
                elapsed_ms,
                _safe_json(str(exc)),
            )
            raise
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "status=finished tool=%s client=%s duration_ms=%.1f",
            name,
            client,
            elapsed_ms,
        )
        return result


def build_log_handlers(
    *,
    file_enabled: bool,
    log_dir: str,
    max_mb: float,
    backup_count: int,
    stderr_stream: IO[str],
) -> list[logging.Handler]:
    """Build the handler list passed to `logging.basicConfig()` in `server.py`.

    A stderr handler is always included -- never stdout, since stdout carries
    the stdio JSON-RPC stream and nothing else may ever print to it. A
    rotating file handler is added on top when `file_enabled` is true;
    `log_dir` is created (including parents) if it doesn't already exist.
    """
    formatter = _Iso8601Formatter(_LOG_FORMAT)

    stderr_handler = logging.StreamHandler(stderr_stream)
    stderr_handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [stderr_handler]

    if file_enabled:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            directory / _LOG_FILENAME,
            maxBytes=int(max_mb * 1024 * 1024),
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    return handlers
