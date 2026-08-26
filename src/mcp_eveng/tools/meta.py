"""MCP tool for self-introspection: what this server currently advertises.

Separate from `system.py` (which covers the EVE-NG *server's* own status/
catalog endpoints) -- this is about the MCP server itself, not EVE-NG.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient

GetClient = Callable[[], Awaitable[EvengClient]]


async def list_tools(mcp: FastMCP) -> dict[str, Any]:
    """List every tool this MCP server currently advertises.

    Reflects `tools.env`: a tool disabled there never appears here, since
    it was never registered with the server at all -- not just hidden
    behind an error if called. Useful as a single authoritative answer to
    "what's actually available right now", instead of piecing it together
    from several unrelated tool searches.
    """
    tools = await mcp.list_tools()
    entries = sorted(
        (
            {"name": t.name, "description": (t.description or "").split("\n", 1)[0].strip()}
            for t in tools
        ),
        key=lambda entry: entry["name"],
    )
    return {
        "status": "success",
        "message": f"{len(entries)} tool(s) currently advertised.",
        "data": {"tools": entries, "count": len(entries)},
    }


def register(mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]) -> None:
    if enabled("list_tools"):

        @mcp.tool(name="list_tools")
        async def _list_tools() -> dict[str, Any]:
            """List every tool this MCP server currently advertises.

            Reflects tools.env -- a disabled tool never appears here, since
            it was never registered with the server at all, not just
            hidden behind an error if called. Useful as a single
            authoritative check of what's actually available right now.
            """
            return await list_tools(mcp)
