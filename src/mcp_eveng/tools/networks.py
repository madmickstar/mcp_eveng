"""MCP tools for managing networks (clouds/bridges) inside an EVENG lab."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..confirmation import format_numbered, run_delete_flow
from ..search import find_by_name_case_insensitive, iter_named_records

GetClient = Callable[[], Awaitable[EvengClient]]

# EVE-NG creates exactly 10 "pnet" bridges (pnet0-pnet9) during
# installation -- a fixed architectural limit, confirmed against EVE-NG's
# own official Community Cookbook and multiple independent technical
# writeups, not something that scales further or varies by server. The
# GUI displays these as "Cloud0" through "Cloud9"; the API's own
# `network_type` value is always the bare `pnetN` form, `cloud`/`cloudN`
# is purely a display-only convention EVE-NG's API itself doesn't accept
# -- confirmed live (list_network_types never returns a `cloud` key, only
# `pnetN`). Aliased here so either form works as input.
_CLOUD_ALIASES = {"cloud": "pnet0", **{f"cloud{i}": f"pnet{i}" for i in range(10)}}


async def list_lab_networks(
    client: EvengClient, lab_path: str, network_id: int | None = None
) -> dict[str, Any]:
    """List all networks in a lab, or get a single network by id."""
    return await client.list_lab_networks(lab_path, network_id)


async def add_lab_network(
    client: EvengClient,
    lab_path: str,
    network_type: str = "",
    name: str | None = None,
    left: str | None = None,
    top: str | None = None,
    hideme: int | None = None,
) -> dict[str, Any]:
    """Add a network (bridge/cloud/ovs/pnetX) to a lab's canvas.

    If `network_type` isn't given, this doesn't guess or error -- it fetches
    the current list of valid types and prompts for one (status
    "selection_required"). Reply with the exact type name, or its number
    from that list (a plain digit is resolved as a 1-based index into the
    freshly-refetched, alphabetically-sorted list).

    `"cloud"`/`"cloud0"` through `"cloud9"` (case-insensitive) are also
    accepted and resolved to `"pnet0"` through `"pnet9"` -- EVE-NG's own
    API only ever accepts the bare `pnetN` form (confirmed live:
    `list_network_types` never returns a `cloud` key), `CloudN` is purely
    how the GUI displays it. EVE-NG creates exactly 10 of these (a fixed
    limit, confirmed against EVE-NG's own documentation), so `cloud`/
    `cloud0` through `cloud9` are the only recognized aliases.

    EVE-NG's network-creation endpoint requires "left"/"top" to always be
    present in the payload -- confirmed live, the same class of bug as
    add_lab_node's (missing "left" causes a silent failure here: EVE-NG
    reports success with an id, but the network never actually persists,
    unlike add_lab_node's version of this bug, which crashes with a clean
    500). Never forward a bare None here, or it overrides
    EvengClient.add_lab_network's own "0"/"0" default with an explicit null.

    `hideme` (0/1) controls whether the network renders as its own icon
    (0, the default) or is hidden from view (1). Note this is NOT what
    makes a node-to-node bridge render as a direct line between two nodes
    -- that's `visibility`, set to 0 via a separate call *after* both
    interfaces are wired, which is what `connect_interface` actually does
    (confirmed against a working reference implementation, after setting
    `hideme` at creation time was tried first and confirmed live not to
    produce a direct line -- no cable rendered at all instead).
    """
    if not network_type.strip():
        types_result = await client.list_network_types()
        types_data = types_result.get("data") or {}
        type_names = sorted(types_data) if isinstance(types_data, dict) else []
        if not type_names:
            return {
                "status": "error",
                "message": "Could not retrieve the list of network types from the server.",
            }
        return {
            "status": "selection_required",
            "message": (
                f"{len(type_names)} network type(s) available:\n{format_numbered(type_names)}\n\n"
                "Call add_lab_network again with `network_type` set to the exact name, "
                "its number from this list, or \"cloud\"/\"cloud0\"-\"cloud9\" (resolved to "
                "pnet0-pnet9 -- what the GUI calls Cloud0-Cloud9)."
            ),
            "data": {"types": type_names},
        }

    resolved_network_type = network_type.strip()
    cloud_alias = _CLOUD_ALIASES.get(resolved_network_type.lower())
    if cloud_alias is not None:
        resolved_network_type = cloud_alias
    elif resolved_network_type.isdigit():
        types_result = await client.list_network_types()
        types_data = types_result.get("data") or {}
        type_names = sorted(types_data) if isinstance(types_data, dict) else []
        idx = int(resolved_network_type)
        if 1 <= idx <= len(type_names):
            resolved_network_type = type_names[idx - 1]
        else:
            return {
                "status": "error",
                "message": (
                    f"{resolved_network_type!r} is out of range for the current "
                    f"{len(type_names)} network type(s):\n{format_numbered(type_names)}"
                ),
                "data": {"types": type_names},
            }

    resolved_left = left if left is not None else "0"
    resolved_top = top if top is not None else "0"
    kwargs: dict[str, Any] = {"name": name, "left": resolved_left, "top": resolved_top}
    if hideme is not None:
        kwargs["hideme"] = hideme
    return await client.add_lab_network(lab_path, resolved_network_type, **kwargs)



async def edit_lab_network(
    client: EvengClient,
    lab_path: str,
    network_id: int,
    name: str | None = None,
    left: str | None = None,
    top: str | None = None,
    visibility: int | None = None,
    hideme: int | None = None,
    style: str | None = None,
    icon: str | None = None,
    color: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Edit an existing network by id. Only supplied fields are changed.

    Same partial-update pattern as `edit_lab`/`edit_lab_node`. This is what
    `connect_interface` uses internally to set `visibility=0` on a
    node-to-node bridge after wiring it -- confirmed (against a working
    reference implementation) to be a required separate step after
    creation and wiring, not something set at creation time.
    """
    fields = {
        k: v
        for k, v in {
            "name": name,
            "left": left,
            "top": top,
            "visibility": visibility,
            "hideme": hideme,
            "style": style,
            "icon": icon,
            "color": color,
            "label": label,
        }.items()
        if v is not None
    }
    if not fields:
        return {
            "status": "error",
            "message": "At least one field to change is required; none was supplied.",
        }
    return await client.edit_lab_network(lab_path, network_id, **fields)


def _network_id(network: dict[str, Any]) -> int:
    return int(network.get("id", network.get("_key")))


def _network_name(network: dict[str, Any]) -> str:
    return str(network.get("name", network.get("_key", "?")))


def _network_label(network: dict[str, Any]) -> str:
    return f"{_network_name(network)} (id {network.get('id', network.get('_key', '?'))})"


async def _find_networks_by_name(
    client: EvengClient, lab_path: str, name: str
) -> list[dict[str, Any]]:
    result = await client.list_lab_networks(lab_path)
    data = result.get("data") or {}
    return find_by_name_case_insensitive(iter_named_records(data, "name"), name)


async def delete_lab_network(
    client: EvengClient,
    lab_path: str,
    name: str,
    selection: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete network(s) from a lab, matched by name substring (case-insensitive).

    Matches on name only, never on id. Search -> select -> confirm, no
    special MCP host capability required:
      1. Call with just `name`. Nothing is deleted -- if exactly one
         network matches, the response says to call again with
         confirm=true; if more than one match, it lists them and asks you
         to reply with `selection` (numbers and/or exact names, separated
         by spaces or commas -- more than one is allowed here).
      2. If there were multiple matches, call again with `selection` set;
         the response reports back exactly the resolved network(s) and
         asks you to call again with confirm=true.
      3. Call again with confirm=true to actually delete.
    """
    if not name or not name.strip():
        return {
            "status": "error",
            "message": "A network name is required to delete a network; none was supplied.",
        }

    candidates = await _find_networks_by_name(client, lab_path, name)

    async def _perform_delete(network: dict[str, Any]) -> str | None:
        await client.delete_lab_network(lab_path, _network_id(network))
        return None

    return await run_delete_flow(
        candidates,
        matches_exact=lambda n, needle: _network_name(n).strip().lower() == needle,
        describe=_network_label,
        noun="network",
        selection=selection,
        confirm=confirm,
        allow_multiple=True,
        perform_delete=_perform_delete,
    )


def register(
    mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]
) -> None:
    if enabled("list_lab_networks"):
        @mcp.tool(name="list_lab_networks")
        async def _list_lab_networks(lab_path: str, network_id: int | None = None) -> dict[str, Any]:
            """List all networks in a lab, or get a single network by id.

            Args:
                lab_path: Full path to the .unl lab file.
                network_id: Specific network id, or omit to list all.
            """
            return await list_lab_networks(await get_client(), lab_path, network_id)

    if enabled("add_lab_network"):
        @mcp.tool(name="add_lab_network")
        async def _add_lab_network(
            lab_path: str,
            network_type: str = "",
            name: str | None = None,
            left: str | None = None,
            top: str | None = None,
            hideme: int | None = None,
        ) -> dict[str, Any]:
            """Add a network (bridge/cloud/ovs/pnetX) to a lab's canvas.

            If `network_type` isn't given, fetches the current list of
            valid types and prompts for one instead of guessing or
            erroring -- reply with the exact name, or its number from
            that list. "cloud"/"cloud0" through "cloud9"
            (case-insensitive) are also accepted, resolved to "pnet0"
            through "pnet9" -- what EVE-NG's GUI calls Cloud0-Cloud9, a
            fixed set of exactly 10 (confirmed against EVE-NG's own
            documentation); the API itself only ever accepts the bare
            pnetN form.

            Args:
                lab_path: Full path to the .unl lab file.
                network_type: See `list_network_types` for valid values,
                    "cloud"/"cloud0"-"cloud9" for pnet0-pnet9, or omit to
                    be shown the list.
                name: Network display name, default "NetX".
                left: Canvas position from the left. Numeric string, e.g. "380".
                top: Canvas position from the top. Numeric string, e.g. "153".
                hideme: 0 (default) renders as its own icon; 1 hides it.
                    Note: not what makes a node-to-node connect_interface
                    bridge render as a direct line -- that's `visibility`,
                    set separately after wiring, not something you set here.
            """
            return await add_lab_network(
                await get_client(), lab_path, network_type, name=name, left=left, top=top, hideme=hideme
            )

    if enabled("edit_lab_network"):
        @mcp.tool(name="edit_lab_network")
        async def _edit_lab_network(
            lab_path: str,
            network_id: int,
            name: str | None = None,
            left: str | None = None,
            top: str | None = None,
            visibility: int | None = None,
            hideme: int | None = None,
            style: str | None = None,
            icon: str | None = None,
            color: str | None = None,
            label: str | None = None,
        ) -> dict[str, Any]:
            """Edit an existing network by id. Only supplied fields are changed.

            Same partial-update pattern as `edit_lab`/`edit_lab_node`. This
            is what `connect_interface` uses internally to set
            `visibility=0` on a node-to-node bridge after wiring it --
            confirmed (against a working reference implementation) to be
            a required separate step after creation and wiring, not
            something set at creation time.

            Args:
                lab_path: Full path to the .unl lab file.
                network_id: Id of the network to edit (see list_lab_networks).
                name: New name, if changing.
                left: New canvas position from the left, if changing.
                top: New canvas position from the top, if changing.
                visibility: 0/1, if changing. This is what actually makes
                    a node-to-node bridge render as a direct line, but
                    only when set *after* the network is created and wired
                    -- not at creation time.
                hideme: 0/1, if changing -- whether the network shows its
                    own icon at all.
                style: Line style, if changing (e.g. "Solid").
                icon: Icon filename, if changing.
                color: Line color, if changing.
                label: Text label, if changing.
            """
            return await edit_lab_network(
                await get_client(),
                lab_path,
                network_id,
                name=name,
                left=left,
                top=top,
                visibility=visibility,
                hideme=hideme,
                style=style,
                icon=icon,
                color=color,
                label=label,
            )

    if enabled("delete_lab_network"):
        @mcp.tool(name="delete_lab_network")
        async def _delete_lab_network(
            lab_path: str, name: str = "", selection: str = "", confirm: bool = False
        ) -> dict[str, Any]:
            """Delete network(s) from a lab, matched by name substring (case-insensitive).

            Matches on name only, never id. Search -> select -> confirm flow
            (see module docs). More than one network can be selected/deleted
            per call here.

            Args:
                lab_path: Full path to the .unl lab file.
                name: Network name or a fragment of one to delete. Required.
                selection: When multiple networks matched, the number(s) and/or
                    exact name(s) of the one(s) to delete, space/comma separated.
                confirm: Set true on the final call to actually delete.
            """
            return await delete_lab_network(await get_client(), lab_path, name, selection, confirm)
