from __future__ import annotations

import io
import logging

import pytest

from mcp_eveng.config import MCPTransportSettings
from mcp_eveng.server import create_server
from mcp_eveng.tool_logging import ToolCallLoggingFastMCP, build_log_handlers


def _make_server() -> ToolCallLoggingFastMCP:
    settings = MCPTransportSettings(
        tools_config_path="/nonexistent-path-for-tests/tools.env",
        _env_file=None,  # type: ignore[call-arg]
    )
    return create_server(settings, "stdio")


async def test_create_server_returns_tool_call_logging_instance() -> None:
    # create_server must build the logging subclass, not plain FastMCP,
    # or every tool call silently goes back to being invisible.
    mcp = _make_server()
    assert isinstance(mcp, ToolCallLoggingFastMCP)


async def test_call_tool_logs_status_call_and_tool_and_arguments(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # No real EVE-NG server is reachable in tests, so get_status errors out --
    # but the pre-call log line must still have been written first.
    mcp = _make_server()
    with caplog.at_level(logging.INFO, logger="mcp_eveng.tool_calls"):
        try:
            await mcp.call_tool("get_status", {})
        except Exception:
            pass

    messages = [r.message for r in caplog.records]
    assert any("status=call" in m and "tool=get_status" in m and "arguments={}" in m for m in messages)


async def test_call_tool_logs_client(caplog: pytest.LogCaptureFixture) -> None:
    mcp = _make_server()
    with caplog.at_level(logging.INFO, logger="mcp_eveng.tool_calls"):
        try:
            await mcp.call_tool("get_status", {})
        except Exception:
            pass

    messages = [r.message for r in caplog.records]
    pre_call = next(m for m in messages if "status=call" in m and "tool=get_status" in m)
    # No timestamp= field in the message body -- the line's own leading
    # timestamp (see test_build_log_handlers_leading_timestamp_matches_
    # requested_format) already covers it, so it isn't duplicated here.
    assert "timestamp=" not in pre_call
    # Called outside any real MCP request (no transport session live), so
    # there's genuinely no client to report -- see test_client_address_*
    # below for the sse/streamable-http and stdio cases themselves.
    assert "client=unknown" in pre_call


def test_call_tool_timestamp_matches_requested_format() -> None:
    import re

    from mcp_eveng.tool_logging import _now

    # Z for UTC, or +HH:MM/-HH:MM (no seconds) for any other offset --
    # exercised directly here; test_call_tool_logs_timestamp_and_client
    # above checks a timestamp is actually present on a real log line.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|[+-]\d{2}:\d{2})", _now())


async def test_call_tool_logs_finish_on_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import mcp_eveng.server as server_module

    async def _fake_get_client():
        class _FakeClient:
            async def get_status(self):
                return {"status": "ok"}

        return _FakeClient()

    monkeypatch.setattr(server_module, "get_client", _fake_get_client)
    mcp = _make_server()

    with caplog.at_level(logging.INFO, logger="mcp_eveng.tool_calls"):
        await mcp.call_tool("get_status", {})

    messages = [r.message for r in caplog.records]
    finished = next(m for m in messages if "status=finished" in m and "tool=get_status" in m)
    assert "duration_ms=" in finished


async def test_call_tool_logs_arguments_as_json(caplog: pytest.LogCaptureFixture) -> None:
    mcp = _make_server()
    with caplog.at_level(logging.INFO, logger="mcp_eveng.tool_calls"):
        # get_node_template requires a `template` arg -- it'll fail against a
        # non-existent client/server, but the pre-call log line is written
        # before that happens, which is what this test checks.
        try:
            await mcp.call_tool("get_node_template", {"template": "iol"})
        except Exception:
            pass

    messages = [r.message for r in caplog.records]
    assert any('arguments={"template": "iol"}' in m for m in messages)


async def test_call_tool_redacts_password_argument(caplog: pytest.LogCaptureFixture) -> None:
    mcp = _make_server()
    with caplog.at_level(logging.INFO, logger="mcp_eveng.tool_calls"):
        try:
            await mcp.call_tool("add_user", {"username": "bob", "password": "hunter2"})
        except Exception:
            pass

    messages = [r.message for r in caplog.records]
    pre_call = next(m for m in messages if "status=call" in m and "tool=add_user" in m)
    assert "hunter2" not in pre_call
    assert '"password": "***REDACTED***"' in pre_call
    # The non-sensitive argument is unaffected.
    assert '"username": "bob"' in pre_call


async def test_call_tool_redacts_rdp_password_argument(caplog: pytest.LogCaptureFixture) -> None:
    mcp = _make_server()
    with caplog.at_level(logging.INFO, logger="mcp_eveng.tool_calls"):
        try:
            await mcp.call_tool(
                "change_node_delay",
                {"lab_path": "/x.unl", "node_id": 1, "rdp_password": "s3cr3t"},
            )
        except Exception:
            pass

    messages = [r.message for r in caplog.records]
    pre_call = next(m for m in messages if "status=call" in m and "tool=change_node_delay" in m)
    assert "s3cr3t" not in pre_call
    assert '"rdp_password": "***REDACTED***"' in pre_call


async def test_call_tool_logs_failure_and_reraises(caplog: pytest.LogCaptureFixture) -> None:
    mcp = _make_server()
    with caplog.at_level(logging.INFO, logger="mcp_eveng.tool_calls"), pytest.raises(Exception):  # noqa: B017
        await mcp.call_tool("nonexistent_tool_xyz", {})

    messages = [r.message for r in caplog.records]
    error_line = next(m for m in messages if "status=error" in m and "tool=nonexistent_tool_xyz" in m)
    assert "duration_ms=" in error_line
    assert 'error="Unknown tool: nonexistent_tool_xyz"' in error_line


# -- _redact_arguments / _is_sensitive_argument_name -------------------


def test_redact_arguments_masks_known_sensitive_names() -> None:
    from mcp_eveng.tool_logging import _redact_arguments

    redacted = _redact_arguments(
        {
            "username": "bob",
            "password": "hunter2",
            "rdp_password": "s3cr3t",
            "api_key": "abcd1234",
            "note": "nothing sensitive here",
        }
    )
    assert redacted["username"] == "bob"
    assert redacted["note"] == "nothing sensitive here"
    assert redacted["password"] == "***REDACTED***"
    assert redacted["rdp_password"] == "***REDACTED***"
    assert redacted["api_key"] == "***REDACTED***"


def test_redact_arguments_is_case_insensitive() -> None:
    from mcp_eveng.tool_logging import _redact_arguments

    redacted = _redact_arguments({"PASSWORD": "hunter2", "Api_Key": "abcd1234"})
    assert redacted["PASSWORD"] == "***REDACTED***"
    assert redacted["Api_Key"] == "***REDACTED***"


def test_redact_arguments_leaves_non_sensitive_names_alone() -> None:
    from mcp_eveng.tool_logging import _redact_arguments

    original = {"path": "/my-lab.unl", "template": "iol", "count": 3}
    assert _redact_arguments(original) == original


# -- _client_address ------------------------------------------------------


def test_client_address_unknown_when_context_unavailable() -> None:
    from mcp_eveng.tool_logging import _client_address

    class _NoContext:
        @property
        def request_context(self):
            raise ValueError("Context is not available outside of a request")

    assert _client_address(_NoContext()) == "unknown"


def test_client_address_stdio_when_request_context_has_no_request() -> None:
    from mcp_eveng.tool_logging import _client_address

    class _RequestContext:
        request = None

    class _Context:
        request_context = _RequestContext()

    assert _client_address(_Context()) == "stdio"


def test_client_address_reports_host_and_port_for_http_transports() -> None:
    from mcp_eveng.tool_logging import _client_address

    class _Client:
        host = "192.168.1.50"
        port = 54321

    class _Request:
        client = _Client()

    class _RequestContext:
        request = _Request()

    class _Context:
        request_context = _RequestContext()

    assert _client_address(_Context()) == "192.168.1.50:54321"


def test_build_log_handlers_stderr_only_by_default() -> None:
    stream = io.StringIO()
    handlers = build_log_handlers(
        file_enabled=False,
        log_dir="log",
        max_mb=10,
        backup_count=5,
        stderr_stream=stream,
    )
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)


def test_build_log_handlers_leading_timestamp_matches_requested_format() -> None:
    """The line's own leading timestamp (not just the timestamp= field in
    the message) must be in the same format -- this is what distinguishes
    this test from test_call_tool_timestamp_matches_requested_format."""
    import re

    stream = io.StringIO()
    handlers = build_log_handlers(
        file_enabled=False,
        log_dir="log",
        max_mb=10,
        backup_count=5,
        stderr_stream=stream,
    )
    test_logger = logging.getLogger("mcp_eveng.test_format_check")
    test_logger.setLevel(logging.INFO)
    test_logger.handlers = handlers
    test_logger.propagate = False

    test_logger.info("hello")
    for h in handlers:
        h.flush()

    line = stream.getvalue().strip()
    leading_timestamp = line.split(" ", 1)[0]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|[+-]\d{2}:\d{2})", leading_timestamp)

    for h in handlers:
        h.close()


def test_build_log_handlers_creates_log_dir_and_rotating_file(tmp_path) -> None:
    log_dir = tmp_path / "log"
    assert not log_dir.exists()

    handlers = build_log_handlers(
        file_enabled=True,
        log_dir=str(log_dir),
        max_mb=1,
        backup_count=3,
        stderr_stream=io.StringIO(),
    )

    assert log_dir.is_dir()
    assert len(handlers) == 2
    file_handler = handlers[1]
    from logging.handlers import RotatingFileHandler

    assert isinstance(file_handler, RotatingFileHandler)
    assert file_handler.maxBytes == 1 * 1024 * 1024
    assert file_handler.backupCount == 3
    assert file_handler.baseFilename == str(log_dir / "mcp-eveng.log")

    for h in handlers:
        h.close()


def test_build_log_handlers_writes_and_rolls_over(tmp_path) -> None:
    """End-to-end: a small maxBytes actually produces a rolled-over backup
    file once enough is logged, confirming the wiring (not just the
    constructor args) works."""
    log_dir = tmp_path / "log"
    handlers = build_log_handlers(
        file_enabled=True,
        log_dir=str(log_dir),
        max_mb=1 / 1024 / 1024 * 200,  # ~200 bytes, so a handful of records roll it over
        backup_count=2,
        stderr_stream=io.StringIO(),
    )
    logger = logging.getLogger("mcp_eveng.test_rollover")
    logger.setLevel(logging.INFO)
    logger.handlers = handlers
    logger.propagate = False

    for i in range(50):
        logger.info("padding log line number %d to force rollover", i)

    for h in handlers:
        h.flush()
        h.close()

    files = sorted(p.name for p in log_dir.iterdir())
    assert "mcp-eveng.log" in files
    assert any(name.startswith("mcp-eveng.log.") for name in files)
    # Never more than backup_count rolled-over files, on top of the live one.
    assert len(files) <= 3
