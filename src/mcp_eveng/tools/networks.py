"""MCP tools for managing networks (clouds/bridges) inside an EVENG lab."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..confirmation import format_numbered, run_delete_flow
from ..coordinates import normalize_coordinate
from ..dependencies import lab_lock
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


async def list_lab_networks(client: EvengClient, lab_path: str, network_id: int | None = None) -> dict[str, Any]:
    """List all networks in a lab, or get a single network by id."""
    return await client.list_lab_networks(lab_path, network_id)


async def add_lab_network(
    client: EvengClient,
    lab_path: str,
    network_type: str = "",
    name: str | None = None,
    left: str | int | None = None,
    top: str | int | None = None,
    hideme: int | None = None,
    icon: str | None = None,
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

    Caveat on `hideme`: a Community server tested live (2026-10-05) never
    stored it -- the saved network had no `hideme` attribute and still
    rendered visibly. It is sent regardless (it may persist on other
    versions), but don't rely on it having taken effect.

    `icon` is the icon filename shown for the network. Valid names are the
    `icons` list returned by `list_network_types` (a different catalogue
    from node icons). Omit it to keep EVE-NG's default cloud icon.
    """
    async with lab_lock(lab_path):
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
                    'its number from this list, or "cloud"/"cloud0"-"cloud9" (resolved to '
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

        norm_left = normalize_coordinate(left)
        norm_top = normalize_coordinate(top)
        resolved_left = norm_left if norm_left is not None else "0"
        resolved_top = norm_top if norm_top is not None else "0"
        kwargs: dict[str, Any] = {"name": name, "left": resolved_left, "top": resolved_top}
        if hideme is not None:
            kwargs["hideme"] = hideme
        if icon is not None:
            kwargs["icon"] = icon
        return await client.add_lab_network(lab_path, resolved_network_type, **kwargs)


# -- EVE-NG bug workaround: a network edit that flips nothing returns 500 -----
# -- and strands the lab lock --------------------------------------------------
#
# Confirmed live (2026-10-05, Community server, raw <network> XML checked on
# the host): EVE-NG's network-edit handler only treats `name`, `left`, `top`
# (and `visibility`) as changes. A PUT containing ONLY `icon`, `style`,
# `color`, `label` and/or `hideme` changes nothing as far as EVE-NG is
# concerned, so it ends in an unhandled path: HTTP 500 with no JSON body,
# and EVE-NG's server-side lab lock file is never released (every later
# write to that lab then fails until the `.lock` file is removed by hand on
# the EVE-NG host). Same mechanism as the node `delay` workaround in
# tools/nodes.py (`_with_delay_workaround`).
#
# Workaround: when the payload holds only such fields, pad it with the
# network's own current `name` (value-blind -- resending the same name
# counts as a change). Applied to the raw API payload only.

_NETWORK_NO_FLAG_FIELDS = {"icon", "style", "color", "label", "hideme"}
_NETWORK_FLAG_FIELDS = {"name", "left", "top"}


def _network_edit_needs_padding(fields: dict[str, Any]) -> bool:
    return bool(_NETWORK_NO_FLAG_FIELDS & fields.keys()) and not (_NETWORK_FLAG_FIELDS & fields.keys())


def _extract_network_record(data: Any, network_id: int) -> dict[str, Any] | None:
    """Pull one network's record out of a `list_lab_networks` response.

    A single-id GET returns the record itself; a full listing is keyed by
    id. Handle both rather than assume which one EVE-NG sends.
    """
    if not isinstance(data, dict):
        return None
    keyed = data.get(str(network_id))
    if isinstance(keyed, dict):
        return keyed
    if "name" in data:
        return data
    return None


# -- EVE-NG bug: hiding an unwired network silently DELETES it -----------------
#
# Confirmed live (2026-10-06, Community server, reproduced 3x): setting
# `visibility=0` on a network with nothing attached (`count` 0) makes EVE-NG
# remove the network from the lab during the save, yet it still answers
# 201 "Lab has been saved" -- silent data loss. Padding with `name` does not
# prevent it. A network with at least one attached endpoint keeps
# `visibility=0` correctly. `connect_interface` is unaffected: it wires
# both endpoints first and calls the client directly, bypassing this tool.
# So the public `edit_lab_network` refuses the call up front.


def _is_hide_request(fields: dict[str, Any]) -> bool:
    value = fields.get("visibility")
    return value is not None and str(value).strip() == "0"


def _attached_endpoints(record: dict[str, Any]) -> int | None:
    """The network's `count` of attached endpoints, or None if unknown."""
    try:
        return int(record["count"])
    except (KeyError, TypeError, ValueError):
        return None


async def edit_lab_network(
    client: EvengClient,
    lab_path: str,
    network_id: int,
    name: str | None = None,
    left: str | int | None = None,
    top: str | int | None = None,
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

    `style`, `color`, `label` and `hideme` are sent but were not stored by
    a Community server tested live (2026-10-05); `name`, `left`, `top`,
    `visibility` and `icon` were. A payload holding only icon/style/color/
    label/hideme is padded with the network's current `name` (see
    `_network_edit_needs_padding`); if the network can't be found, nothing
    is sent.

    `visibility=0` is refused unless the network has at least one attached
    endpoint (`count` >= 1): EVE-NG silently deletes a network that is
    hidden while nothing is attached, while reporting success.
    """
    async with lab_lock(lab_path):
        fields = {
            k: v
            for k, v in {
                "name": name,
                "left": normalize_coordinate(left),
                "top": normalize_coordinate(top),
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
        api_fields = fields
        hiding = _is_hide_request(fields)
        needs_padding = _network_edit_needs_padding(fields)
        if hiding or needs_padding:
            current = await client.list_lab_networks(lab_path, network_id)
            record = _extract_network_record(current.get("data"), network_id)
            if hiding:
                if record is None:
                    return {
                        "status": "error",
                        "message": (
                            f"Network {network_id} was not found in {lab_path}, so nothing was sent. "
                            "Check the id with list_lab_networks."
                        ),
                    }
                attached = _attached_endpoints(record)
                if attached is None or attached < 1:
                    state = "has nothing attached" if attached == 0 else "has no readable endpoint count"
                    return {
                        "status": "error",
                        "message": (
                            f"Refusing visibility=0 on network {network_id} ({record.get('name', '?')}): it {state}, "
                            "and EVE-NG silently DELETES a network that is set invisible while nothing is "
                            "attached to it (while still reporting success). Nothing was sent. Wire at least "
                            "one node interface to it first (see connect_interface), then hide it; or leave "
                            "it visible (visibility=1)."
                        ),
                    }
            if needs_padding and (record is None or "name" not in record):
                # Never send the unpadded edit: it would 500 and strand the
                # lab's server-side lock. Never pad with a guessed/empty
                # name either -- that would rename the network.
                return {
                    "status": "error",
                    "message": (
                        f"Network {network_id} was not found in {lab_path} (or has no name), "
                        "so nothing was sent. Check the id with list_lab_networks."
                    ),
                }
            if needs_padding and record is not None:
                api_fields = {**fields, "name": str(record["name"])}
        return await client.edit_lab_network(lab_path, network_id, **api_fields)


def _network_id(network: dict[str, Any]) -> int:
    raw_id = network.get("id", network.get("_key"))
    if raw_id is None:
        raise ValueError(f"network record has neither 'id' nor '_key': {network!r}")
    return int(raw_id)


def _network_name(network: dict[str, Any]) -> str:
    return str(network.get("name", network.get("_key", "?")))


def _network_label(network: dict[str, Any]) -> str:
    return f"{_network_name(network)} (id {network.get('id', network.get('_key', '?'))})"


async def _find_networks_by_name(client: EvengClient, lab_path: str, name: str) -> list[dict[str, Any]]:
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
    async with lab_lock(lab_path):
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


def register(mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]) -> None:
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
            left: str | int | None = None,
            top: str | int | None = None,
            hideme: int | None = None,
            icon: str | None = None,
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
                left: Canvas position from the left. Integer or numeric string, e.g. 380 or "380".
                top: Canvas position from the top. Integer or numeric string, e.g. 153 or "153".
                hideme: 0 (default) renders as its own icon; 1 hides it.
                    Sent to EVE-NG, but a Community server tested live did
                    not store it (network stayed visible) -- don't rely on
                    it. Not what makes a node-to-node connect_interface
                    bridge render as a direct line -- that's `visibility`,
                    set separately after wiring, not something you set here.
                icon: Icon filename for the network, from the `icons` list
                    in `list_network_types` (network icons are a different
                    set from node icons). Omit for the default cloud icon.
            """
            return await add_lab_network(
                await get_client(),
                lab_path,
                network_type,
                name=name,
                left=left,
                top=top,
                hideme=hideme,
                icon=icon,
            )

    if enabled("edit_lab_network"):

        @mcp.tool(name="edit_lab_network")
        async def _edit_lab_network(
            lab_path: str,
            network_id: int,
            name: str | None = None,
            left: str | int | None = None,
            top: str | int | None = None,
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
                left: New canvas position from the left (integer or numeric string), if changing.
                top: New canvas position from the top (integer or numeric string), if changing.
                visibility: 0/1, if changing. This is what actually makes
                    a node-to-node bridge render as a direct line, but
                    only when set *after* the network is created and wired
                    -- not at creation time. 0 is REFUSED while the network
                    has nothing attached: EVE-NG would silently delete it.
                hideme: 0/1, if changing. NOT PERSISTED on the Community
                    server tested live -- accepted, but silently ignored.
                icon: Icon filename, if changing. Must be one of the
                    `icons` returned by `list_network_types` (network icons
                    differ from node icons). Persists and renders.
                style: Line style, if changing. NOT PERSISTED on the
                    Community server tested live -- silently ignored.
                color: Line color, if changing. NOT PERSISTED on the
                    Community server tested live -- silently ignored.
                label: Text label, if changing. NOT PERSISTED on the
                    Community server tested live -- silently ignored.

            Only `name`, `left`, `top`, `visibility` and `icon` were
            confirmed to actually be saved. If you send only
            icon/style/color/label/hideme, the current `name` is added to
            the request automatically (EVE-NG otherwise fails with a 500
            and leaves the lab locked). To verify a change took effect,
            re-read it with `list_lab_networks`.
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
