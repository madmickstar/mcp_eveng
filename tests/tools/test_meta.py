from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from mcp_eveng.tools import meta


def _tool(name: str, description) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=description)


async def test_list_tools_returns_sorted_names_and_first_line_of_description() -> None:
    mcp = AsyncMock()
    mcp.list_tools.return_value = [
        _tool(
            "delete_lab",
            "Delete exactly one lab, matched by path OR name.\n\nMore details here.",
        ),
        _tool("add_lab_node", "Add a node to a lab's canvas."),
    ]

    result = await meta.list_tools(mcp)

    assert result["status"] == "success"
    assert result["data"]["count"] == 2
    names = [t["name"] for t in result["data"]["tools"]]
    assert names == ["add_lab_node", "delete_lab"]  # sorted alphabetically

    descriptions = {t["name"]: t["description"] for t in result["data"]["tools"]}
    assert descriptions["delete_lab"] == "Delete exactly one lab, matched by path OR name."
    assert "More details" not in descriptions["delete_lab"]
    assert descriptions["add_lab_node"] == "Add a node to a lab's canvas."


async def test_list_tools_handles_empty_description() -> None:
    mcp = AsyncMock()
    mcp.list_tools.return_value = [_tool("get_status", "")]

    result = await meta.list_tools(mcp)

    assert result["data"]["tools"][0]["description"] == ""


async def test_list_tools_handles_none_description() -> None:
    mcp = AsyncMock()
    mcp.list_tools.return_value = [_tool("get_status", None)]

    result = await meta.list_tools(mcp)

    assert result["data"]["tools"][0]["description"] == ""


async def test_list_tools_no_tools_registered() -> None:
    mcp = AsyncMock()
    mcp.list_tools.return_value = []

    result = await meta.list_tools(mcp)

    assert result["data"]["count"] == 0
    assert result["data"]["tools"] == []


async def test_list_tools_message_states_the_count() -> None:
    mcp = AsyncMock()
    mcp.list_tools.return_value = [_tool("a", "..."), _tool("b", "...")]

    result = await meta.list_tools(mcp)

    assert "2" in result["message"]
