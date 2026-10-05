"""Canvas `left`/`top` accept integers as well as strings.

AI agents routinely send integer coordinates; the tool schemas used to
declare `str` only, so pydantic rejected the call before any tool code
ran. These tests cover the normalizer itself and, importantly, calling the
*registered* MCP tools (the layer where the real failure happened).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_eveng.coordinates import normalize_coordinate
from mcp_eveng.tools import networks, nodes


def test_normalize_none_stays_none() -> None:
    assert normalize_coordinate(None) is None


@pytest.mark.parametrize(("value", "expected"), [(77, "77"), (0, "0"), (-5, "-5"), (1642, "1642")])
def test_normalize_int_becomes_string(value: int, expected: str) -> None:
    assert normalize_coordinate(value) == expected


@pytest.mark.parametrize("value", ["380", "0", "35%", ""])
def test_normalize_string_passes_through_unchanged(value: str) -> None:
    assert normalize_coordinate(value) == value


def test_normalize_rejects_bool() -> None:
    with pytest.raises(ValueError, match="boolean"):
        normalize_coordinate(True)


async def test_add_lab_network_function_converts_int_coordinates() -> None:
    client = AsyncMock()
    client.add_lab_network.return_value = {"status": "success"}

    await networks.add_lab_network(client, "/lab.unl", "bridge", name="OOB2", left=77, top=816)

    client.add_lab_network.assert_awaited_once_with("/lab.unl", "bridge", name="OOB2", left="77", top="816")


async def test_add_lab_network_zero_int_is_kept_not_defaulted() -> None:
    client = AsyncMock()
    client.add_lab_network.return_value = {"status": "success"}

    await networks.add_lab_network(client, "/lab.unl", "bridge", left=0, top=0)

    kwargs = client.add_lab_network.await_args.kwargs
    assert (kwargs["left"], kwargs["top"]) == ("0", "0")


async def test_edit_lab_network_function_converts_int_coordinates() -> None:
    client = AsyncMock()
    client.edit_lab_network.return_value = {"status": "success"}

    await networks.edit_lab_network(client, "/lab.unl", 3, left=10, top=0)

    client.edit_lab_network.assert_awaited_once_with("/lab.unl", 3, left="10", top="0")


async def test_add_lab_node_function_converts_int_coordinates() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = {"status": "success", "data": {"c8000v": "Cisco Catalyst 8000v"}}
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/lab.unl", template="c8000v", left=1123, top=1642)

    kwargs = client.add_lab_node.await_args.kwargs
    assert (kwargs["left"], kwargs["top"]) == ("1123", "1642")
    client.list_lab_nodes.assert_not_awaited()  # explicit position -> no auto-placement


async def test_add_lab_node_int_left_with_omitted_top_auto_places_only_top() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = {"status": "success", "data": {"c8000v": "Cisco Catalyst 8000v"}}
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/lab.unl", template="c8000v", left=500)

    kwargs = client.add_lab_node.await_args.kwargs
    assert kwargs["left"] == "500"
    assert isinstance(kwargs["top"], str)


async def test_edit_lab_node_function_converts_int_coordinates() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"name": "R1", "status": 0}}
    client.edit_lab_node.return_value = {"status": "success"}

    await nodes.edit_lab_node(client, "/lab.unl", 1, left=20, top=30)

    fields = client.edit_lab_node.await_args.args[2:] or client.edit_lab_node.await_args.kwargs
    flat = {**client.edit_lab_node.await_args.kwargs}
    assert fields is not None
    assert flat.get("left") == "20"
    assert flat.get("top") == "30"


def _server_with(module: Any, client: AsyncMock) -> FastMCP:
    mcp = FastMCP("coordinates-test")

    async def get_client() -> AsyncMock:
        return client

    module.register(mcp, get_client, lambda _name: True)
    return mcp


async def test_registered_add_lab_network_accepts_int_coordinates() -> None:
    # Exact call from the production log that failed with
    # "Input should be a valid string [type=string_type, input_value=77, input_type=int]".
    client = AsyncMock()
    client.add_lab_network.return_value = {"status": "success"}
    mcp = _server_with(networks, client)

    await mcp.call_tool(
        "add_lab_network",
        {"lab_path": "/strata-unsloth-testing.unl", "left": 77, "name": "OOB2", "network_type": "pnet0", "top": 816},
    )

    kwargs = client.add_lab_network.await_args.kwargs
    assert (kwargs["left"], kwargs["top"]) == ("77", "816")


async def test_registered_add_lab_network_still_accepts_string_coordinates() -> None:
    client = AsyncMock()
    client.add_lab_network.return_value = {"status": "success"}
    mcp = _server_with(networks, client)

    await mcp.call_tool("add_lab_network", {"lab_path": "/l.unl", "network_type": "pnet0", "left": "77", "top": "816"})

    kwargs = client.add_lab_network.await_args.kwargs
    assert (kwargs["left"], kwargs["top"]) == ("77", "816")


async def test_registered_edit_lab_network_accepts_int_coordinates() -> None:
    client = AsyncMock()
    client.edit_lab_network.return_value = {"status": "success"}
    mcp = _server_with(networks, client)

    await mcp.call_tool("edit_lab_network", {"lab_path": "/l.unl", "network_id": 1, "left": 5, "top": 6})

    client.edit_lab_network.assert_awaited_once_with("/l.unl", 1, left="5", top="6")


async def test_registered_add_lab_node_accepts_int_coordinates() -> None:
    # Exact call from the production log: add_lab_node with int left/top.
    client = AsyncMock()
    client.list_node_templates.return_value = {"status": "success", "data": {"c8000v": "Cisco Catalyst 8000v"}}
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.add_lab_node.return_value = {"status": "success"}
    mcp = _server_with(nodes, client)

    await mcp.call_tool(
        "add_lab_node",
        {"lab_path": "/strata-unsloth-testing.unl", "left": 1123, "name": "RTR-202", "template": "c8000v", "top": 1642},
    )

    kwargs = client.add_lab_node.await_args.kwargs
    assert (kwargs["left"], kwargs["top"]) == ("1123", "1642")


async def test_registered_edit_lab_node_accepts_int_coordinates() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"name": "R1", "status": 0}}
    client.edit_lab_node.return_value = {"status": "success"}
    mcp = _server_with(nodes, client)

    await mcp.call_tool("edit_lab_node", {"lab_path": "/l.unl", "node_id": 1, "left": 20, "top": 30})

    kwargs = client.edit_lab_node.await_args.kwargs
    assert (kwargs["left"], kwargs["top"]) == ("20", "30")
