"""Argument-validation failures reach AI agents as short, direct messages.

Production log (2026-10-09): an agent called add_lab_node without `lab_path`
and got pydantic's raw "1 validation error for _add_lab_nodeArguments ...
Field required [type=missing, input_value=..., input_type=dict] For further
information visit https://errors.pydantic.dev/..." text. The server now
rewrites that (and only that) into a message naming the argument.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from mcp_eveng.tool_logging import ToolCallLoggingFastMCP
from mcp_eveng.tools import networks, nodes


def _server_with(module: Any, client: AsyncMock) -> ToolCallLoggingFastMCP:
    mcp = ToolCallLoggingFastMCP("validation-test")

    async def get_client() -> AsyncMock:
        return client

    module.register(mcp, get_client, lambda _n: True)
    return mcp


async def test_production_call_missing_lab_path_gets_a_direct_message() -> None:
    client = AsyncMock()
    mcp = _server_with(nodes, client)

    with pytest.raises(ToolError) as caught:
        await mcp.call_tool(
            "add_lab_node",
            {"ethernet": 2, "image": "vtmgmt-20.15.3", "left": 939, "name": "VMANAGE01", "top": 243},
        )

    message = str(caught.value)
    assert message.startswith("Invalid arguments for add_lab_node:")
    assert "`lab_path` is required but was not provided" in message
    assert "Nothing was sent to EVE-NG." in message
    assert "every required argument: lab_path" in message
    # none of pydantic's noise
    for noise in ("validation error for", "pydantic.dev", "input_type=", "[type=missing"):
        assert noise not in message
    client.add_lab_node.assert_not_awaited()


async def test_wrong_type_names_the_argument_and_echoes_what_was_received() -> None:
    mcp = _server_with(nodes, AsyncMock())

    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("add_lab_node", {"lab_path": 5})

    message = str(caught.value)
    assert "`lab_path` is invalid (received 5): Input should be a valid string" in message


async def test_union_argument_reports_one_entry_not_one_per_branch() -> None:
    mcp = _server_with(networks, AsyncMock())

    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("add_lab_network", {"lab_path": "/l.unl", "network_type": "bridge", "left": [1, 2]})

    message = str(caught.value)
    assert message.count("`left`") == 1
    assert "(received [1, 2])" in message


async def test_every_bad_argument_is_listed_in_one_message() -> None:
    mcp = _server_with(networks, AsyncMock())

    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("add_lab_network", {"left": [1], "unknown_arg": 1, "icon": 7})

    message = str(caught.value)
    for expected in ("`lab_path` is required", "`left` is invalid", "`icon` is invalid"):
        assert expected in message


async def test_sensitive_argument_values_are_never_echoed() -> None:
    mcp = ToolCallLoggingFastMCP("sensitive-test")

    @mcp.tool()
    async def set_secret(lab_path: str, rdp_password: str = "") -> dict[str, Any]:
        return {}

    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("set_secret", {"lab_path": "/l.unl", "rdp_password": 123456})

    message = str(caught.value)
    assert "`rdp_password` is invalid" in message
    assert "123456" not in message


async def test_long_received_values_are_truncated() -> None:
    mcp = ToolCallLoggingFastMCP("long-test")

    @mcp.tool()
    async def count_things(count: int) -> dict[str, Any]:
        return {}

    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("count_things", {"count": "x" * 500})

    message = str(caught.value)
    assert "..." in message
    assert "x" * 200 not in message


async def test_the_rewritten_text_is_what_gets_logged(caplog: pytest.LogCaptureFixture) -> None:
    mcp = _server_with(nodes, AsyncMock())

    with caplog.at_level(logging.INFO, logger="mcp_eveng.tool_calls"), pytest.raises(ToolError):
        await mcp.call_tool("add_lab_node", {"name": "VMANAGE01"})

    error_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_lines) == 1
    assert "status=error tool=add_lab_node" in error_lines[0]
    assert "`lab_path` is required" in error_lines[0]
    assert "pydantic.dev" not in error_lines[0]


async def test_valid_call_is_untouched() -> None:
    client = AsyncMock()
    client.add_lab_network.return_value = {"status": "success"}
    mcp = _server_with(networks, client)

    await mcp.call_tool("add_lab_network", {"lab_path": "/l.unl", "network_type": "bridge", "left": 7})

    client.add_lab_network.assert_awaited_once()


async def test_errors_raised_inside_a_tool_are_not_rewritten() -> None:
    mcp = ToolCallLoggingFastMCP("inner-test")

    @mcp.tool()
    async def explode(lab_path: str) -> dict[str, Any]:
        raise RuntimeError("boom from EVE-NG")

    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("explode", {"lab_path": "/l.unl"})

    assert str(caught.value) == "Error executing tool explode: boom from EVE-NG"


async def test_a_validation_error_raised_inside_tool_code_is_not_mistaken_for_bad_arguments() -> None:
    class Model(BaseModel):
        n: int

    mcp = ToolCallLoggingFastMCP("inner-validation-test")

    @mcp.tool()
    async def parse_something(lab_path: str) -> dict[str, Any]:
        Model(n="not-an-int")  # type: ignore[arg-type]
        return {}

    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("parse_something", {"lab_path": "/l.unl"})

    message = str(caught.value)
    assert message.startswith("Error executing tool parse_something:")
    assert "Invalid arguments for" not in message
    assert isinstance(caught.value.__cause__, ValidationError)


async def test_unknown_tool_error_is_unchanged() -> None:
    mcp = ToolCallLoggingFastMCP("unknown-test")

    with pytest.raises(ToolError, match="Unknown tool: nope"):
        await mcp.call_tool("nope", {})


def test_every_lab_path_argument_doc_says_it_is_required() -> None:
    import pathlib
    import re

    for path in pathlib.Path("src/mcp_eveng/tools").glob("*.py"):
        for line in path.read_text().splitlines():
            if re.search(r"^\s+lab_path: (?!str\b)", line):
                assert "REQUIRED on every call" in line, f"{path.name}: {line.strip()}"


# -- direct wording of the tool-level errors audited alongside this change ------


async def test_delete_tools_name_the_missing_argument() -> None:
    from mcp_eveng.tools import folders, labs, users

    client = AsyncMock()
    cases = [
        (folders.delete_folder(client, ""), "`path`"),
        (labs.delete_lab(client, ""), "`name`"),
        (users.delete_user(client, ""), "`username`"),
        (networks.delete_lab_network(client, "/l.unl", ""), "`name`"),
        (nodes.delete_lab_node(client, "/l.unl", ""), "`name`"),
    ]
    for coro, argument in cases:
        result = await coro
        assert result["status"] == "error"
        assert result["message"].startswith("Missing required argument")
        assert argument in result["message"]
        assert "Nothing was deleted" in result["message"]
        assert "none was supplied" not in result["message"]


async def test_empty_edits_list_which_fields_can_be_changed() -> None:
    client = AsyncMock()

    node_result = await nodes.edit_lab_node(client, "/l.unl", 1)
    network_result = await networks.edit_lab_network(client, "/l.unl", 1)

    for result in (node_result, network_result):
        assert result["status"] == "error"
        assert result["message"].startswith("No fields to change were given.")
        assert "Provide at least one of: name, left, top" in result["message"]
