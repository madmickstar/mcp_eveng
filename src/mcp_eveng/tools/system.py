"""MCP tools for EVENG system/discovery endpoints.

Each public function below is the actual tool logic and takes an
already-authenticated `EvengClient`; that makes it directly unit-testable
with a mocked client, with no MCP/FastMCP machinery involved. `register()`
is the thin adapter that exposes each one as an MCP tool.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..vendor import extract_vendor, has_image, strip_hidden_marker

GetClient = Callable[[], Awaitable[EvengClient]]


async def get_status(client: EvengClient) -> dict[str, Any]:
    """Get EVENG server status: CPU, RAM, disk usage and version info."""
    return await client.get_status()


async def list_node_templates(
    client: EvengClient, include_without_images: bool = False
) -> dict[str, Any]:
    """List node templates EVENG knows about, with vendor context.

    By default only lists templates that have at least one image
    installed. EVE-NG marks a template with no image by suffixing its
    description with ".hided" (confirmed against a live server: every
    template actually in use by a real node lacked this suffix); this
    filters those out so you're only shown templates you could actually
    use right now. Pass `include_without_images=True` to see the full
    catalog, including templates you can't add a node with until an image
    is uploaded for them.

    EVE-NG's API has no explicit vendor field, so `vendor` on each result
    is a best-effort label extracted from the template's description text
    -- see `vendor.extract_vendor`.
    """
    result = await client.list_node_templates()
    data = result.get("data") or {}

    templates: list[dict[str, Any]] = []
    for template_id, description in data.items():
        description = str(description)
        available = has_image(description)
        if not available and not include_without_images:
            continue
        templates.append(
            {
                "id": template_id,
                "name": strip_hidden_marker(description),
                "vendor": extract_vendor(description),
                "has_image": available,
            }
        )
    templates.sort(key=lambda t: (t["vendor"], t["name"]))

    scope = "" if include_without_images else " with an image installed"
    return {
        "status": "success",
        "message": f"Found {len(templates)} template(s){scope}.",
        "data": {"templates": templates, "count": len(templates)},
    }


async def get_node_template(client: EvengClient, template: str) -> dict[str, Any]:
    """Get details (available images, default options) for one node template, with vendor context."""
    result = await client.get_node_template(template)
    data = result.get("data")
    if not isinstance(data, dict):
        return result

    description = str(data.get("description", ""))
    image_list = ((data.get("options") or {}).get("image") or {}).get("list") or {}
    enriched = {
        **data,
        "vendor": extract_vendor(description) if description else "Unknown",
        "has_image": bool(image_list),
    }
    return {**result, "data": enriched}


async def list_network_types(client: EvengClient) -> dict[str, Any]:
    """List available network/cloud types (bridge, ovs, pnetX, ...) for lab networks."""
    return await client.list_network_types()


async def list_user_roles(client: EvengClient) -> dict[str, Any]:
    """List valid EVENG user roles (admin, editor, user)."""
    return await client.list_user_roles()


def register(
    mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]
) -> None:
    if enabled("get_status"):
        @mcp.tool(name="get_status")
        async def _get_status() -> dict[str, Any]:
            """Get EVENG server status: CPU, RAM, disk usage and version info."""
            return await get_status(await get_client())

    if enabled("list_node_templates"):
        @mcp.tool(name="list_node_templates")
        async def _list_node_templates(include_without_images: bool = False) -> dict[str, Any]:
            """List node templates EVENG knows about, with vendor context.

            By default only lists templates that have an image installed (so
            you're only shown templates you could actually use). Pass
            include_without_images=true to see the full catalog. Each result
            includes a best-effort `vendor` label extracted from the
            template's description -- EVE-NG's API has no explicit vendor field.

            Args:
                include_without_images: Also list templates with no image
                    installed (these can't be used to add a node yet).
            """
            return await list_node_templates(await get_client(), include_without_images)

    if enabled("get_node_template"):
        @mcp.tool(name="get_node_template")
        async def _get_node_template(template: str) -> dict[str, Any]:
            """Get details (available images, default options) for one node template.

            Includes a best-effort `vendor` label extracted from the
            template's description -- EVE-NG's API has no explicit vendor field.

            Args:
                template: Template id, e.g. "iol", "vios", "csr1000v".
            """
            return await get_node_template(await get_client(), template)

    if enabled("list_network_types"):
        @mcp.tool(name="list_network_types")
        async def _list_network_types() -> dict[str, Any]:
            """List available network/cloud types (bridge, ovs, pnetX, ...) for lab networks."""
            return await list_network_types(await get_client())

    if enabled("list_user_roles"):
        @mcp.tool(name="list_user_roles")
        async def _list_user_roles() -> dict[str, Any]:
            """List valid EVENG user roles (admin, editor, user)."""
            return await list_user_roles(await get_client())
