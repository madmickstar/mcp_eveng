"""MCP tools for managing nodes (routers/switches/hosts/etc.) inside an EVENG lab."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..confirmation import format_numbered, resolve_selection, run_delete_flow
from ..edition import is_pro_edition
from ..search import find_by_name_case_insensitive, iter_named_records
from ..vendor import extract_vendor, has_image, strip_hidden_marker

GetClient = Callable[[], Awaitable[EvengClient]]


async def _template_vendor_map(client: EvengClient) -> dict[str, str]:
    """Map template id -> best-effort vendor name, for annotating nodes.

    Best-effort only: if this call fails, or the response isn't shaped as
    expected, returns an empty map rather than blocking whatever primary
    operation (listing or deleting nodes) needed it.
    """
    try:
        result = await client.list_node_templates()
    except Exception:
        return {}
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return {}
    return {template_id: extract_vendor(str(desc)) for template_id, desc in data.items()}


def _annotate_with_vendor(node: dict[str, Any], vendor_map: dict[str, str]) -> dict[str, Any]:
    vendor = vendor_map.get(str(node.get("template", "")), "Unknown")
    return {**node, "vendor": vendor}


async def list_lab_nodes(client: EvengClient, lab_path: str, node_id: int | None = None) -> dict[str, Any]:
    """List all nodes in a lab, or get a single node by id, each annotated with a vendor label.

    EVE-NG's node data has no explicit vendor field, so `vendor` here is a
    best-effort label extracted from the node's template description --
    see `vendor.extract_vendor`.
    """
    result = await client.list_lab_nodes(lab_path, node_id)
    data = result.get("data")
    if not data:
        return result

    vendor_map = await _template_vendor_map(client)

    if isinstance(data, dict) and "template" in data:
        # Single-node response (node_id was given): data IS the node itself.
        annotated: Any = _annotate_with_vendor(data, vendor_map)
    elif isinstance(data, dict):
        annotated = {
            key: (_annotate_with_vendor(node, vendor_map) if isinstance(node, dict) else node)
            for key, node in data.items()
        }
    elif isinstance(data, list):
        annotated = [(_annotate_with_vendor(node, vendor_map) if isinstance(node, dict) else node) for node in data]
    else:
        annotated = data

    return {**result, "data": annotated}


_TPL_DEFAULT_PATTERN = re.compile(r"^tpl\((.*)\)$")

# Options already handled by add_lab_node's own named parameters -- these
# are never included in the generic "everything else" passthrough, to
# avoid conflicting with a value the caller (or our own resolution logic)
# already explicitly set.
_HANDLED_OPTION_KEYS = {
    "name",
    "image",
    "icon",
    "ram",
    "cpu",
    "ethernet",
    "console",
    "config",
    "left",
    "top",
}


def _resolve_option_value(opt: dict[str, Any]) -> Any:
    """Resolve one template option's effective value.

    Usually just `opt["value"]`. Some list-type options (observed:
    `qemu_nic`) report an empty `value` with the real default only encoded
    in the corresponding list label, e.g. `{"value": "", "list": {"":
    "tpl(e1000)"}}` really means "e1000" -- unwrap that convention too.
    """
    value = opt.get("value")
    if value not in (None, ""):
        return value
    option_list = opt.get("list")
    if isinstance(option_list, dict):
        label = option_list.get(value if value is not None else "")
        if isinstance(label, str):
            match = _TPL_DEFAULT_PATTERN.match(label)
            if match:
                return match.group(1)
    return None


def _template_option_str(options: dict[str, Any], key: str) -> str | None:
    opt = options.get(key)
    if not isinstance(opt, dict):
        return None
    value = _resolve_option_value(opt)
    return str(value) if value not in (None, "") else None


def _template_option_int(options: dict[str, Any], key: str) -> int | None:
    opt = options.get(key)
    if not isinstance(opt, dict):
        return None
    try:
        return int(_resolve_option_value(opt))
    except (TypeError, ValueError):
        return None


def _template_image_names(options: dict[str, Any]) -> list[str]:
    image_list = (options.get("image") or {}).get("list")
    if isinstance(image_list, dict):
        return list(image_list.keys())
    if isinstance(image_list, list):
        return [str(item) for item in image_list]
    return []


def _template_extra_options(options: dict[str, Any]) -> dict[str, Any]:
    """Every other default the template reports, to pass straight through.

    EVE-NG's own "Add Node" UI dialog submits every configured default for
    a template, not just a fixed subset. Some templates (observed: the
    Juniper `vmx` family) crash server-side (500, no JSON body) if fields
    like `qemu_version`/`qemu_arch`/`qemu_nic`/`qemu_options` are omitted,
    even when every other field is supplied explicitly -- EVE-NG's own
    node-creation endpoint doesn't reliably fall back to the template's
    configured default for an omitted field. Passing everything the
    template reports through (for anything not already resolved by our own
    named parameters) matches what the UI actually does, instead of
    omitting fields and hoping the server fills in something sensible.
    """
    extra: dict[str, Any] = {}
    for key, opt in options.items():
        if key in _HANDLED_OPTION_KEYS or not isinstance(opt, dict):
            continue
        value = _resolve_option_value(opt)
        if value is None or value == "":
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        extra[key] = value
    return extra


# -- template search (id / name / vendor, case-insensitive substring) --------


async def _search_templates(client: EvengClient, search: str) -> list[dict[str, str]]:
    """Find templates with an image installed whose id, name, or vendor contains `search`.

    An empty `search` matches everything (every string contains ""),
    which is exactly the "no template given -- list them all" case.
    """
    result = await client.list_node_templates()
    data = result.get("data") or {}
    if not isinstance(data, dict):
        return []
    needle = search.strip().lower()
    matches: list[dict[str, str]] = []
    for template_id, description in data.items():
        description = str(description)
        if not has_image(description):
            continue
        name = strip_hidden_marker(description)
        vendor = extract_vendor(description)
        if needle in template_id.lower() or needle in name.lower() or needle in vendor.lower():
            matches.append({"id": template_id, "name": name, "vendor": vendor})
    matches.sort(key=lambda t: (t["vendor"], t["name"]))
    return matches


def _template_label(t: dict[str, str]) -> str:
    return f"{t['name']} [{t['vendor']}] (id {t['id']})"


def _template_matches_exact(t: dict[str, str], needle: str) -> bool:
    return t["id"].strip().lower() == needle or t["name"].strip().lower() == needle


# -- canvas auto-placement -----------------------------------------------------

_GRID_GAP = 100
_GRID_START = 100
_GRID_COLUMNS = 5
_OVERLAP_GAP = 50


def _grid_positions() -> Iterator[tuple[int, int]]:
    """Yield candidate (left, top) canvas positions in placement order.

    Left to right, `_GRID_COLUMNS` per row, `_GRID_GAP` apart, starting at
    (`_GRID_START`, `_GRID_START`); a new row starts `_GRID_GAP` below the
    previous one and back at `_GRID_START` on the left.
    """
    row = 0
    while True:
        top = _GRID_START + row * _GRID_GAP
        for col in range(_GRID_COLUMNS):
            left = _GRID_START + col * _GRID_GAP
            yield (left, top)
        row += 1


def _parse_position_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _position_is_free(candidate: tuple[int, int], existing: list[tuple[int, int]], gap: int = _OVERLAP_GAP) -> bool:
    """A candidate position conflicts with an existing node if both axes
    are within `gap` of it -- i.e. an existing node "claims" a `gap`-radius
    box around itself, not just an exact-match position."""
    cleft, ctop = candidate
    return all(not (abs(cleft - eleft) < gap and abs(ctop - etop) < gap) for eleft, etop in existing)


async def _next_free_position(client: EvengClient, lab_path: str) -> tuple[str, str]:
    """Compute the next left/top position for a new node, walking the grid
    in placement order and skipping any slot too close to an existing node."""
    result = await client.list_lab_nodes(lab_path)
    data = result.get("data") or {}
    if isinstance(data, dict) and "template" in data:
        nodes_iter: list[Any] = [data]
    elif isinstance(data, dict):
        nodes_iter = list(data.values())
    elif isinstance(data, list):
        nodes_iter = data
    else:
        nodes_iter = []

    existing_positions: list[tuple[int, int]] = []
    for node in nodes_iter:
        if not isinstance(node, dict):
            continue
        left = _parse_position_int(node.get("left"))
        top = _parse_position_int(node.get("top"))
        if left is not None and top is not None:
            existing_positions.append((left, top))

    for candidate in _grid_positions():
        if _position_is_free(candidate, existing_positions):
            return str(candidate[0]), str(candidate[1])
    return str(_GRID_START), str(_GRID_START)  # pragma: no cover -- grid is infinite


async def add_lab_node(
    client: EvengClient,
    lab_path: str,
    template: str = "",
    selection: str = "",
    node_type: str | None = None,
    name: str | None = None,
    image: str | None = None,
    config: str = "Unconfigured",
    left: str | None = None,
    top: str | None = None,
    ram: int | None = None,
    console: str | None = None,
    cpu: int | None = None,
    ethernet: int | None = None,
) -> dict[str, Any]:
    """Add a node to a lab's canvas, resolving the template by search and auto-placing it.

    `template` is a case-insensitive substring search against every
    template's id, name, and (best-effort) vendor -- not an exact id.
      - Empty (default): every available template matches -- lists them
        all (status "selection_required").
      - No matches: cancelled, nothing added.
      - Exactly one match: proceeds directly with it, no prompt.
      - More than one match: lists them (status "selection_required") and
        asks you to call again with `selection` set to the number or exact
        id/name of the one you want.

    Once the template is resolved, fetches its own defaults via
    `get_node_template` and uses them for anything you didn't explicitly
    specify: `node_type` (qemu/dynamips/iol), RAM, CPU, ethernet count,
    console type, and icon. This applies to every vendor/template, not
    just specific ones -- it reads whatever the template itself reports.

    Every other default the template reports is also passed straight
    through as-is (e.g. QEMU-specific fields like `qemu_version`,
    `qemu_arch`, `qemu_nic`, `qemu_options`), matching what EVE-NG's own
    "Add Node" UI dialog actually submits. This matters: some templates
    (observed live -- the Juniper `vmx` family) return a 500 with no JSON
    body if these are omitted, even when every field our own named
    parameters cover is supplied explicitly. EVE-NG's node-creation
    endpoint does not reliably fall back to a template's configured
    default for an omitted field.

    If the template has more than one image available and you didn't
    specify `image`, this does NOT guess -- it returns the list of
    available images (status "selection_required") and asks you to call
    again with `image` set to the one you want. If it has exactly one
    image (or you already specified one), it proceeds directly with no
    prompt.

    Canvas position (`left`/`top`) is auto-placed when not explicitly
    given: left to right, 5 nodes per row, 100 units apart, starting at
    (100, 100); a new row starts 100 below the previous one. Existing
    nodes already in the lab are checked, and a candidate position is
    skipped (moving to the next grid slot) if an existing node is within
    50 units on both axes -- so repeated calls (adding nodes one at a
    time, or across many separate calls) place each new node in the next
    genuinely free slot rather than piling up on top of each other.
    """
    candidates = await _search_templates(client, template)
    if not candidates:
        message = (
            f"No template found matching {template!r}."
            if template.strip()
            else "No node templates with an image installed were found."
        )
        return {"status": "cancelled", "message": message}

    if len(candidates) == 1:
        resolved_template = candidates[0]["id"]
    else:
        labels = [_template_label(t) for t in candidates]
        if selection.strip():
            resolved_list, invalid = resolve_selection(selection, candidates, _template_matches_exact)
            if invalid or not resolved_list:
                return {
                    "status": "error",
                    "message": (
                        f"Could not match {selection!r} to any current template. "
                        f"Current matches:\n{format_numbered(labels)}"
                    ),
                    "data": {"matches": labels},
                }
            if len(resolved_list) > 1:
                return {
                    "status": "error",
                    "message": f"Only one template can be chosen. Pick exactly one:\n{format_numbered(labels)}",
                    "data": {"matches": labels},
                }
            resolved_template = resolved_list[0]["id"]
        else:
            what = f"matching {template!r}" if template.strip() else "available"
            return {
                "status": "selection_required",
                "message": (
                    f"{len(candidates)} template(s) {what}:\n{format_numbered(labels)}\n\n"
                    "Call add_lab_node again with `selection` set to the number or exact "
                    "id/name of the one you want."
                ),
                "data": {"matches": labels},
            }

    template_result = await client.get_node_template(resolved_template)
    template_data = template_result.get("data") or {}
    if not isinstance(template_data, dict):
        template_data = {}
    options = template_data.get("options") or {}
    if not isinstance(options, dict):
        options = {}

    resolved_image = image
    if resolved_image is None:
        image_names = _template_image_names(options)
        if len(image_names) > 1:
            return {
                "status": "selection_required",
                "message": (
                    f"Template {resolved_template!r} has {len(image_names)} image(s) available:\n"
                    f"{format_numbered(image_names)}\n\n"
                    "Call add_lab_node again with `image` set to the one you want."
                ),
                "data": {"images": image_names},
            }
        resolved_image = image_names[0] if len(image_names) == 1 else _template_option_str(options, "image")

    resolved_node_type = node_type or str(template_data.get("type") or "qemu")
    resolved_name = name or _template_option_str(options, "name")
    resolved_console = console or _template_option_str(options, "console") or "telnet"
    resolved_icon = _template_option_str(options, "icon") or "Router.png"
    resolved_ram = ram if ram is not None else _template_option_int(options, "ram")
    resolved_cpu = cpu if cpu is not None else (_template_option_int(options, "cpu") or 1)
    resolved_ethernet = ethernet if ethernet is not None else _template_option_int(options, "ethernet")

    resolved_extra = _template_extra_options(options)

    # EVE-NG's own node-creation endpoint requires "left"/"top" to always
    # be present in the payload (see EvengClient.add_lab_node for why) --
    # never forward a bare None here, or it overrides that client-side
    # default with an explicit null. When the caller didn't give an
    # explicit position, auto-place instead of just defaulting to "0","0".
    resolved_left = left
    resolved_top = top
    if resolved_left is None or resolved_top is None:
        auto_left, auto_top = await _next_free_position(client, lab_path)
        if resolved_left is None:
            resolved_left = auto_left
        if resolved_top is None:
            resolved_top = auto_top

    return await client.add_lab_node(
        lab_path,
        node_type=resolved_node_type,
        template=resolved_template,
        name=resolved_name,
        image=resolved_image,
        config=config,
        icon=resolved_icon,
        left=resolved_left,
        top=resolved_top,
        ram=resolved_ram,
        console=resolved_console,
        cpu=resolved_cpu,
        ethernet=resolved_ethernet,
        extra=resolved_extra,
    )


def _node_id(node: dict[str, Any]) -> int:
    raw_id = node.get("id", node.get("_key"))
    if raw_id is None:
        raise ValueError(f"node record has neither 'id' nor '_key': {node!r}")
    return int(raw_id)


def _node_name(node: dict[str, Any]) -> str:
    return str(node.get("name", node.get("_key", "?")))


def _node_label(node: dict[str, Any], vendor_map: dict[str, str]) -> str:
    vendor = vendor_map.get(str(node.get("template", "")), "Unknown")
    return f"{_node_name(node)} [{vendor}] (id {node.get('id', node.get('_key', '?'))})"


async def _find_nodes_by_name(client: EvengClient, lab_path: str, name: str) -> list[dict[str, Any]]:
    result = await client.list_lab_nodes(lab_path)
    data = result.get("data") or {}
    return find_by_name_case_insensitive(iter_named_records(data, "name"), name)


async def delete_lab_node(
    client: EvengClient,
    lab_path: str,
    name: str,
    selection: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete node(s) from a lab, matched by name substring (case-insensitive).

    Matches on name only, never on id. Search -> select -> confirm, no
    special MCP host capability required:
      1. Call with just `name`. Nothing is deleted -- if exactly one node
         matches, the response says to call again with confirm=true; if
         more than one match, it lists them and asks you to reply with
         `selection` (numbers and/or exact names, separated by spaces or
         commas -- more than one is allowed here).
      2. If there were multiple matches, call again with `selection` set;
         the response reports back exactly the resolved node(s) and asks
         you to call again with confirm=true.
      3. Call again with confirm=true to actually delete.

    Each candidate is shown with a best-effort vendor label, e.g.
    "canvas-14 [Juniper] (id 21)", for context -- see `vendor.extract_vendor`.
    """
    if not name or not name.strip():
        return {
            "status": "error",
            "message": "A node name is required to delete a node; none was supplied.",
        }

    candidates = await _find_nodes_by_name(client, lab_path, name)
    vendor_map = await _template_vendor_map(client)

    async def _perform_delete(node: dict[str, Any]) -> str | None:
        await client.delete_lab_node(lab_path, _node_id(node))
        return None

    return await run_delete_flow(
        candidates,
        matches_exact=lambda n, needle: _node_name(n).strip().lower() == needle,
        describe=lambda n: _node_label(n, vendor_map),
        noun="node",
        selection=selection,
        confirm=confirm,
        allow_multiple=True,
        perform_delete=_perform_delete,
    )


# -- EVE-NG Community bug workaround: a delay-only edit is silently -----
# rejected -----------------------------------------------------------------
#
# Confirmed live against a Community server: EVE-NG's own node-edit code
# (Node::edit() in the underlying unetlab source) sets an internal
# "modified" flag for every editable field it changes -- config, icon,
# image, left, name, top -- EXCEPT `delay`. The `delay` branch updates the
# value but never flips that flag. If `delay` is the *only* field in the
# request, the server ends up thinking nothing changed and rejects the
# whole edit with its own "no attribute has been changed" error, which
# surfaces to API callers as a generic "Cannot edit node in the selected
# lab (20026)" -- indistinguishable, without this context, from a real
# failure. Not something PRO was observed to hit in this project's testing.
#
# Workaround: whenever `delay` is being changed and nothing else in the
# request already flips the flag, pad the request with the node's own
# current `name` (a value-blind field -- EVE-NG sets `modified = True` for
# `name` unconditionally, regardless of whether the resent value actually
# differs from the current one). This is transparent to callers: it's
# applied only to the raw API payload, never reported back as a changed
# field.

_MODIFIED_FLAG_FIELDS = {"config", "icon", "image", "left", "name", "top"}


def _with_delay_workaround(fields: dict[str, Any], current_data: dict[str, Any]) -> dict[str, Any]:
    """Return `fields` for the actual API call, padded with the node's
    current `name` if `delay` is present and no other field already
    guarantees EVE-NG's "modified" flag gets set (see note above)."""
    if "delay" not in fields:
        return fields
    if _MODIFIED_FLAG_FIELDS & fields.keys():
        return fields
    return {**fields, "name": str(current_data.get("name", ""))}


def _is_running(node_data: dict[str, Any]) -> bool:
    """A node's `status` field: 0 is stopped; any other value (observed: 2
    while running) counts as not-stopped. Treated conservatively -- an
    unrecognized/missing status is assumed running, so edit_lab_node still
    stops it first rather than risking an edit EVE-NG might reject."""
    status = node_data.get("status")
    if status is None:
        return True
    try:
        return int(status) != 0
    except (TypeError, ValueError):
        return True


async def _find_duplicate_name(client: EvengClient, lab_path: str, node_id: int, name: str) -> dict[str, Any] | None:
    """Find another node (not `node_id`) already using `name` (case-insensitive exact match)."""
    result = await client.list_lab_nodes(lab_path)
    data = result.get("data") or {}
    needle = name.strip().lower()
    for existing_name, record in iter_named_records(data, "name"):
        record_id = record.get("id", record.get("_key"))
        try:
            record_id_int = int(record_id)  # type: ignore[arg-type]  # deliberately unguarded -- caught below
        except (TypeError, ValueError):
            continue
        if record_id_int == node_id:
            continue
        if existing_name.strip().lower() == needle:
            return {"id": record_id_int, "name": existing_name}
    return None


async def edit_lab_node(
    client: EvengClient,
    lab_path: str,
    node_id: int,
    name: str | None = None,
    icon: str | None = None,
    image: str | None = None,
    ram: int | None = None,
    cpu: int | None = None,
    cpulimit: int | None = None,
    ethernet: int | None = None,
    console: str | None = None,
    config: str | None = None,
    left: str | None = None,
    top: str | None = None,
    delay: int | None = None,
    disable_offload: int | None = None,
    sat: str | None = None,
    eth_format: str | None = None,
    eth_name: list[str] | None = None,
    firstmac: str | None = None,
    qemu_version: str | None = None,
    qemu_arch: str | None = None,
    qemu_nic: str | None = None,
    qemu_options: str | None = None,
    rdp_user: str | None = None,
    rdp_password: str | None = None,
    confirm_duplicate_name: bool = False,
) -> dict[str, Any]:
    """Edit an existing node by id. Only supplied fields are changed.

    Covers every node field EVE-NG's own "Edit Node" dialog exposes (see
    `get_node_template`'s `options` for the full reference) -- name, icon,
    image, ram/cpu/cpulimit/ethernet, console/config, canvas position,
    delay, the QEMU-specific fields (version/arch/nic/custom options),
    disable_offload, sat, eth_format/eth_name, and rdp_user/rdp_password
    (for rdp/rdp-tls console nodes). Deliberately excludes `uuid` -- an
    identity field EVE-NG assigns itself, not something meant to be
    user-edited.

    Targets exactly one node -- for `ram`/`cpu`/`ethernet`/`icon`/`image`
    across every node sharing a template at once, see
    `edit_lab_nodes_by_template`. For `delay` specifically with bulk
    ordering/incrementing across many nodes, see `change_node_delay`.

    EVE-NG requires a node to be stopped to edit it, on **both** PRO and
    Community (unlike `connect_interface`'s wiring, which PRO allows on
    running nodes -- editing fields is different and always needs the node
    stopped either way). This checks the node's current status first and
    stops it automatically if needed, before applying the edit -- you
    don't have to stop it yourself first.

    If `name` is being changed and another node in the lab already has
    that exact name (case-insensitive), this does NOT rename it -- EVE-NG
    allows duplicate node names, but silently creating one seems worth
    avoiding by default. It returns `status: "confirmation_required"`
    naming the conflicting node; call again with either a different `name`,
    or the same `name` plus `confirm_duplicate_name=True` to use it anyway.
    """
    fields = {
        k: v
        for k, v in {
            "name": name,
            "icon": icon,
            "image": image,
            "ram": ram,
            "cpu": cpu,
            "cpulimit": cpulimit,
            "ethernet": ethernet,
            "console": console,
            "config": config,
            "left": left,
            "top": top,
            "delay": delay,
            "disable_offload": disable_offload,
            "sat": sat,
            "eth_format": eth_format,
            "eth_name": eth_name,
            "firstmac": firstmac,
            "qemu_version": qemu_version,
            "qemu_arch": qemu_arch,
            "qemu_nic": qemu_nic,
            "qemu_options": qemu_options,
            "rdp_user": rdp_user,
            "rdp_password": rdp_password,
        }.items()
        if v is not None
    }
    if not fields:
        return {
            "status": "error",
            "message": "At least one field to change is required; none was supplied.",
        }

    if name is not None and not confirm_duplicate_name:
        duplicate = await _find_duplicate_name(client, lab_path, node_id, name)
        if duplicate is not None:
            return {
                "status": "confirmation_required",
                "message": (
                    f"{name!r} is already used by node {duplicate['name']!r} "
                    f"(id {duplicate['id']}). EVE-NG allows duplicate node names, so this "
                    "isn't blocked -- call again with confirm_duplicate_name=true to use "
                    "this name anyway, or supply a different name instead."
                ),
                "data": {
                    "duplicate_node_id": duplicate["id"],
                    "duplicate_node_name": duplicate["name"],
                },
            }

    current = await client.list_lab_nodes(lab_path, node_id)
    current_data = current.get("data") or {}
    if not isinstance(current_data, dict):
        current_data = {}
    node_label = str(current_data.get("name", f"id {node_id}"))

    stopped_first = False
    if _is_running(current_data):
        await client.stop_node(lab_path, node_id)
        stopped_first = True

    api_fields = _with_delay_workaround(fields, current_data)
    await client.edit_lab_node(lab_path, node_id, **api_fields)

    changed = ", ".join(f"{k}={v!r}" for k, v in fields.items())
    note = " (it was running, so stopped it first)" if stopped_first else ""
    return {
        "status": "success",
        "message": f"Updated node {node_label!r} (id {node_id}){note}: {changed}.",
    }


# -- change_node_delay: single-node or bulk (name-matched or user-ordered) ----
#
# Three modes:
#   1. `node_id` given: single node, set to `delay` (default 10).
#   2. `bulk=True` + `names` given: every node matching any name (case-
#      insensitive substring) gets an incrementing delay, in the order the
#      names were given (and, within one name's matches, by node id).
#   3. `bulk=True`, no `names`, no `node_id`: lists every node with its
#      current delay and asks for `order` -- the numbers, in the sequence
#      the caller wants increasing delays applied.
# Every mode ends in the same confirmation step before anything is stopped
# or changed, since all three involve stopping nodes -- not just the
# explicitly-described bulk-with-no-names case -- for consistency.

_DEFAULT_DELAY = 10
_DEFAULT_DELAY_INCREMENT = 10


async def _search_nodes_by_name(client: EvengClient, lab_path: str, name: str) -> list[dict[str, Any]]:
    """Case-insensitive substring match against every node's name, sorted by id."""
    result = await client.list_lab_nodes(lab_path)
    data = result.get("data") or {}
    needle = name.strip().lower()
    matches = [
        node for _key, node in iter_named_records(data, "name") if needle in str(node.get("name", "")).strip().lower()
    ]
    matches.sort(key=lambda n: int(n.get("id", n.get("_key", 0))))
    return matches


def _delay_node_id(node: dict[str, Any]) -> int:
    raw_id = node.get("id", node.get("_key"))
    if raw_id is None:
        raise ValueError(f"node record has neither 'id' nor '_key': {node!r}")
    return int(raw_id)


def _delay_node_label(node: dict[str, Any]) -> str:
    return f"{node.get('name', '?')} (id {_delay_node_id(node)}, current delay {node.get('delay', '?')}s)"


async def change_node_delay(
    client: EvengClient,
    lab_path: str,
    node_id: int | None = None,
    delay: int | None = None,
    bulk: bool = False,
    names: str | list[str] = "",
    increment: int | None = None,
    order: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Change a node's startup delay (seconds before it auto-starts), one
    node or in bulk.

    `node_id` always means single-node mode, regardless of `bulk`: sets
    that one node's delay to `delay` (default 10).

    Otherwise `bulk=True` is required, in one of two forms:
      - `names` given (a name, or list of names -- case-insensitive
        substring match against every node's name): every match gets an
        incrementing delay (`increment`, default 10) -- the first
        matched node gets `increment` seconds, the second `increment*2`,
        and so on, in the order the names were given (and, within one
        name's multiple matches, by node id).
      - `names` omitted: lists every node in the lab with its current
        delay (status "selection_required") and asks for `order` -- the
        list numbers, in the sequence you want increasing delays applied
        (e.g. "3,1,2"); node 3 gets `increment` seconds, node 1 gets
        `increment*2`, node 2 gets `increment*3`.

    Every mode ends the same way: one more explicit confirmation
    summarizing every node and its new delay, warning that each will be
    stopped first (required regardless of PRO/Community, same as
    `edit_lab_node`). Reply "accept" or "yes" (`confirm`) to apply --
    same wording as every delete tool, kept consistent; anything else
    cancels. Nothing is stopped or changed before that.
    """
    name_list = [names] if isinstance(names, str) else list(names)
    name_list = [n for n in name_list if n.strip()]

    if node_id is not None:
        resolved_delay = delay if delay is not None else _DEFAULT_DELAY
        current = await client.list_lab_nodes(lab_path, node_id)
        current_data = current.get("data") or {}
        if not isinstance(current_data, dict):
            current_data = {}
        node_name = str(current_data.get("name", f"id {node_id}"))
        current_delay = current_data.get("delay", "?")

        if not confirm:
            return {
                "status": "confirmation_required",
                "message": (
                    f"Node {node_name!r} (id {node_id}): delay {current_delay}s -> "
                    f"{resolved_delay}s. It will be stopped first to make this change. "
                    "Reply 'accept' or 'yes' to proceed; anything else cancels."
                ),
            }

        if _is_running(current_data):
            await client.stop_node(lab_path, node_id)
        api_fields = _with_delay_workaround({"delay": resolved_delay}, current_data)
        await client.edit_lab_node(lab_path, node_id, **api_fields)
        return {
            "status": "success",
            "message": f"Set delay to {resolved_delay}s on node {node_name!r} (id {node_id}).",
        }

    if not bulk:
        return {
            "status": "error",
            "message": "Either node_id (single node) or bulk=true (multiple nodes) is required.",
        }

    resolved_increment = increment if increment is not None else _DEFAULT_DELAY_INCREMENT

    if name_list:
        ordered_targets: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        unmatched: list[str] = []
        for term in name_list:
            matches = await _search_nodes_by_name(client, lab_path, term)
            if not matches:
                unmatched.append(term)
                continue
            for node in matches:
                node_key = _delay_node_id(node)
                if node_key not in seen_ids:
                    seen_ids.add(node_key)
                    ordered_targets.append(node)

        if not ordered_targets:
            return {
                "status": "cancelled",
                "message": f"No node found matching any of: {', '.join(name_list)}.",
            }
    else:
        result = await client.list_lab_nodes(lab_path)
        data = result.get("data") or {}
        all_nodes = sorted(
            (node for _key, node in iter_named_records(data, "name")),
            key=_delay_node_id,
        )

        if not all_nodes:
            return {"status": "cancelled", "message": "No nodes found in this lab."}

        if not order.strip():
            labels = [_delay_node_label(n) for n in all_nodes]
            return {
                "status": "selection_required",
                "message": (
                    f"{len(all_nodes)} node(s) in this lab:\n{format_numbered(labels)}\n\n"
                    "Reply with `order` set to the numbers above, listed in the sequence "
                    'you want increasing delays applied (e.g. "3,1,2") -- the first '
                    f"number gets delay {resolved_increment}s, the second "
                    f"{resolved_increment * 2}s, and so on."
                ),
                "data": {"matches": labels},
            }

        tokens = [t.strip() for t in order.replace(",", " ").split() if t.strip()]
        ordered_targets = []
        for token in tokens:
            if not token.isdigit():
                return {"status": "error", "message": f"{token!r} in `order` is not a number."}
            idx = int(token)
            if not (1 <= idx <= len(all_nodes)):
                return {
                    "status": "error",
                    "message": f"{idx} in `order` is out of range (1-{len(all_nodes)}).",
                }
            ordered_targets.append(all_nodes[idx - 1])

        if not ordered_targets:
            return {"status": "error", "message": "`order` didn't resolve to any nodes."}

    assignments = [(node, resolved_increment * (position + 1)) for position, node in enumerate(ordered_targets)]

    if not confirm:
        labels = [
            f"{node.get('name', '?')} (id {_delay_node_id(node)}): {node.get('delay', '?')}s -> {new_delay}s"
            for node, new_delay in assignments
        ]
        plural = "s" if len(assignments) != 1 else ""
        return {
            "status": "confirmation_required",
            "message": (
                f"{len(assignments)} node{plural} will have their delay changed:\n"
                f"{format_numbered(labels)}\n\n"
                "Every affected node will be stopped first to make this change. "
                "Reply 'accept' or 'yes' to proceed; anything else cancels."
            ),
            "data": {"matches": labels},
        }

    updated: list[str] = []
    for node, new_delay in assignments:
        target_id = _delay_node_id(node)
        node_name = str(node.get("name", f"id {target_id}"))
        if _is_running(node):
            await client.stop_node(lab_path, target_id)
        api_fields = _with_delay_workaround({"delay": new_delay}, node)
        await client.edit_lab_node(lab_path, target_id, **api_fields)
        updated.append(f"{node_name} ({new_delay}s)")

    plural = "s" if len(updated) != 1 else ""
    return {
        "status": "success",
        "message": f"Updated delay on {len(updated)} node{plural}: {', '.join(updated)}.",
    }


# -- edit_lab_nodes_by_template: bulk interfaces/cpu/memory/icon edits, ------
# scoped to exactly one template at a time -----------------------------------
#
# Multi-stage, stateless flow (each call re-derives everything fresh from
# whatever's currently supplied -- no server-side session):
#   1. Resolve to exactly one template, searched by `vendor` and/or
#      `template` (case-insensitive substring, both required to match if
#      both given). More than one match: numbered list, narrow by replying
#      with a more specific vendor/template string, or `template_selection`
#      (number or exact template id) -- repeat until exactly one remains.
#   2. Choose which of that template's nodes: `node_selection` is "all" or
#      number(s)/exact name(s), space/comma separated.
#   3. Choose what to change: `component` (interfaces/cpu/memory/icon) and
#      `value` (a number, or for icon, `icon_search` narrowed the same way
#      as step 1 via `icon_selection`).
#   4. Final confirmation: everything resolved is summarized (nodes,
#      template, component, new value), with an explicit warning that every
#      affected node will be stopped -- reply "accept" or "yes" (`confirm`)
#      to apply, anything else cancels. Same wording as every delete tool,
#      for consistency.


_COMPONENT_ALIASES = {
    "interfaces": "ethernet",
    "interface": "ethernet",
    "ethernet": "ethernet",
    "eth": "ethernet",
    "cpu": "cpu",
    "cpus": "cpu",
    "memory": "ram",
    "ram": "ram",
    "mem": "ram",
    "icon": "icon",
    "icons": "icon",
    "image": "image",
    "images": "image",
}
_COMPONENT_CHOICES = "interfaces, cpu, memory, icon, or image"


async def _search_existing_nodes_by_vendor_template(
    client: EvengClient, lab_path: str, vendor: str, template: str
) -> dict[str, list[dict[str, Any]]]:
    """Find nodes in the lab matching `vendor` and/or `template` (each a
    case-insensitive substring, AND'd together if both are given), grouped
    by exact template id."""
    result = await client.list_lab_nodes(lab_path)
    data = result.get("data") or {}
    vendor_map = await _template_vendor_map(client)
    vendor_needle = vendor.strip().lower()
    template_needle = template.strip().lower()

    by_template: dict[str, list[dict[str, Any]]] = {}
    for _name, node in iter_named_records(data, "name"):
        template_id = str(node.get("template", ""))
        node_vendor = vendor_map.get(template_id, "Unknown")
        if vendor_needle and vendor_needle not in node_vendor.lower():
            continue
        if template_needle and template_needle not in template_id.lower():
            continue
        annotated = {**node, "vendor": node_vendor}
        by_template.setdefault(template_id, []).append(annotated)
    return by_template


def _bulk_node_label(node: dict[str, Any]) -> str:
    node_id = node.get("id", node.get("_key", "?"))
    return (
        f"{node.get('name', '?')} [{node.get('vendor', 'Unknown')}] "
        f"(id {node_id}, template {node.get('template', '?')})"
    )


def _template_choice_label(template_id: str, nodes_for_template: list[dict[str, Any]]) -> str:
    vendor = nodes_for_template[0].get("vendor", "Unknown") if nodes_for_template else "Unknown"
    plural = "s" if len(nodes_for_template) != 1 else ""
    return f"{template_id} [{vendor}] ({len(nodes_for_template)} node{plural})"


async def _search_icons(client: EvengClient, search: str) -> list[str]:
    """Find icon filenames matching `search` (case-insensitive substring).

    EVE-NG's list-network-types response carries `icons` as a top-level
    key alongside `data`, not nested inside it (confirmed live) -- unlike
    every other endpoint in this project.
    """
    result = await client.list_network_types()
    icons = result.get("icons") or {}
    if not isinstance(icons, dict):
        return []
    needle = search.strip().lower()
    return sorted(name for name in icons if needle in name.lower())


async def _search_template_images(client: EvengClient, template_id: str, search: str) -> list[str]:
    """Find image filenames matching `search` (case-insensitive substring)
    among the given template's own valid images -- unlike icons, images
    are template-scoped, not a global catalog, so this reuses
    `get_node_template` (the same source `add_lab_node` resolves images
    from) rather than searching everything on the server.
    """
    result = await client.get_node_template(template_id)
    data = result.get("data") or {}
    options = data.get("options") if isinstance(data, dict) else None
    if not isinstance(options, dict):
        return []
    image_names = _template_image_names(options)
    needle = search.strip().lower()
    return sorted(name for name in image_names if needle in name.lower())


async def edit_lab_nodes_by_template(
    client: EvengClient,
    lab_path: str,
    vendor: str = "",
    template: str = "",
    template_selection: str = "",
    node_selection: str = "",
    component: str | None = None,
    value: int | None = None,
    icon_search: str = "",
    icon_selection: str = "",
    image_search: str = "",
    image_selection: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Bulk-edit interfaces/cpu/memory/icon/image across nodes of exactly one template.

    Search by `vendor` and/or `template` (case-insensitive substring, at
    least one required) -- e.g. vendor="cisco", or template="vios". If more
    than one template matches, this never guesses: it lists every match
    (numbered) and asks you to narrow further, either by replying with a
    more specific `vendor`/`template`, or `template_selection` (the number
    or exact template id) -- repeat until exactly one template remains.
    This never targets more than one template per call.

    Once the template is resolved, `node_selection` picks which of its
    nodes to target: "all", or number(s)/exact name(s) (space/comma
    separated).

    Then `component` (one of interfaces/cpu/memory/icon/image) and `value`
    say what to change it to. For `component="icon"`, `value` isn't used --
    instead `icon_search` (case-insensitive substring against EVE-NG's
    icon catalog) narrows to exactly one icon, resolving further matches
    via `icon_selection` the same way template matches do. For
    `component="image"`, `value` also isn't used -- `image_search`
    (case-insensitive substring against *this resolved template's own*
    valid images, not a global catalog -- images are template-scoped)
    narrows the same way, via `image_selection`.

    Whatever isn't supplied yet is prompted for one piece at a time,
    re-deriving everything fresh from what's currently given -- there's no
    server-side session, so each call is a complete restatement of
    everything resolved so far, not just the new answer.

    The final step always asks for one more explicit confirmation,
    summarizing every node affected, the template, and the change --
    warning that every affected node will be stopped to make it, since
    that's required regardless of PRO/Community. Reply "accept" or "yes"
    (`confirm`) to apply; anything else cancels. Nothing is changed until
    that confirmation.
    """
    if not vendor.strip() and not template.strip():
        return {
            "status": "error",
            "message": (
                "At least a vendor or a template name/fragment is required to start "
                '(e.g. vendor="cisco" or template="vios").'
            ),
        }

    by_template = await _search_existing_nodes_by_vendor_template(client, lab_path, vendor, template)
    if not by_template:
        return {
            "status": "cancelled",
            "message": (f"No node found matching vendor={vendor!r} template={template!r}."),
        }

    template_ids = sorted(by_template)

    if len(template_ids) == 1:
        resolved_template_id = template_ids[0]
    else:
        template_candidates = [{"id": tid} for tid in template_ids]
        labels = [_template_choice_label(tid, by_template[tid]) for tid in template_ids]

        if template_selection.strip():
            resolved, invalid = resolve_selection(
                template_selection,
                template_candidates,
                lambda c, needle: c["id"].strip().lower() == needle,
            )
            if invalid or not resolved:
                return {
                    "status": "error",
                    "message": (
                        f"Could not match {template_selection!r} to any current template. "
                        f"Current matches:\n{format_numbered(labels)}"
                    ),
                    "data": {"matches": labels},
                }
            if len(resolved) > 1:
                return {
                    "status": "error",
                    "message": (
                        "Only one template can be targeted per call. Narrow further -- "
                        f"pick exactly one:\n{format_numbered(labels)}"
                    ),
                    "data": {"matches": labels},
                }
            resolved_template_id = resolved[0]["id"]
        else:
            return {
                "status": "selection_required",
                "message": (
                    f"{len(template_ids)} templates match vendor={vendor!r} "
                    f"template={template!r}:\n{format_numbered(labels)}\n\n"
                    "This only ever targets one template at a time. Narrow further by "
                    "replying with a more specific vendor/template, or "
                    "`template_selection` set to the number or exact template id of "
                    "the one you want."
                ),
                "data": {"matches": labels},
            }

    template_nodes = by_template[resolved_template_id]
    node_labels = [_bulk_node_label(n) for n in template_nodes]

    if not node_selection.strip():
        return {
            "status": "selection_required",
            "message": (
                f"Template {resolved_template_id!r} has {len(template_nodes)} node(s):\n"
                f"{format_numbered(node_labels)}\n\n"
                'Reply with `node_selection` set to "all", or the number(s)/exact '
                "name(s) (space/comma separated) of the ones you want."
            ),
            "data": {"matches": node_labels},
        }

    if node_selection.strip().lower() == "all":
        target_nodes = template_nodes
    else:
        resolved_nodes, invalid = resolve_selection(
            node_selection,
            template_nodes,
            lambda n, needle: str(n.get("name", "")).strip().lower() == needle,
        )
        if invalid or not resolved_nodes:
            return {
                "status": "error",
                "message": (
                    f"Could not match {node_selection!r} to any current node. Current "
                    f"nodes for {resolved_template_id!r}:\n{format_numbered(node_labels)}"
                ),
                "data": {"matches": node_labels},
            }
        target_nodes = resolved_nodes

    target_labels = [_bulk_node_label(n) for n in target_nodes]

    if not component:
        return {
            "status": "selection_required",
            "message": (
                f"{len(target_nodes)} node(s) selected from {resolved_template_id!r}:\n"
                f"{format_numbered(target_labels)}\n\n"
                f"What do you want to change? Reply with `component`: {_COMPONENT_CHOICES}."
            ),
            "data": {"matches": target_labels},
        }

    normalized_component = _COMPONENT_ALIASES.get(component.strip().lower())
    if normalized_component is None:
        return {
            "status": "error",
            "message": f"Unrecognized component {component!r}. Must be one of: {_COMPONENT_CHOICES}.",
        }

    resolved_icon: str | None = None
    if normalized_component == "icon":
        if not icon_search.strip():
            return {
                "status": "selection_required",
                "message": (
                    f"{len(target_nodes)} node(s) selected from {resolved_template_id!r}, "
                    "changing icon.\n\nWhat icon are you looking for? Reply with "
                    "`icon_search` -- a fragment of the icon filename is enough."
                ),
                "data": {"matches": target_labels},
            }
        icon_matches = await _search_icons(client, icon_search)
        if not icon_matches:
            return {
                "status": "cancelled",
                "message": f"No icon found matching {icon_search!r}.",
            }
        if len(icon_matches) == 1:
            resolved_icon = icon_matches[0]
        elif icon_selection.strip():
            needle = icon_selection.strip().lower()
            if icon_selection.strip().isdigit():
                idx = int(icon_selection.strip())
                if 1 <= idx <= len(icon_matches):
                    resolved_icon = icon_matches[idx - 1]
            if resolved_icon is None:
                exact = [i for i in icon_matches if i.lower() == needle]
                if len(exact) == 1:
                    resolved_icon = exact[0]
            if resolved_icon is None:
                return {
                    "status": "error",
                    "message": (
                        f"Could not match {icon_selection!r} to any current icon. Current "
                        f"matches:\n{format_numbered(icon_matches)}"
                    ),
                    "data": {"matches": icon_matches},
                }
        else:
            return {
                "status": "selection_required",
                "message": (
                    f"{len(icon_matches)} icons match {icon_search!r}:\n"
                    f"{format_numbered(icon_matches)}\n\n"
                    "Reply with `icon_selection` set to the number or exact filename of "
                    "the one you want."
                ),
                "data": {"matches": icon_matches},
            }
        change_value_label = resolved_icon
        fields: dict[str, Any] = {"icon": resolved_icon}
    elif normalized_component == "image":
        resolved_image: str | None = None
        if not image_search.strip():
            return {
                "status": "selection_required",
                "message": (
                    f"{len(target_nodes)} node(s) selected from {resolved_template_id!r}, "
                    "changing image.\n\nWhat image are you looking for? Reply with "
                    "`image_search` -- a fragment of the image filename is enough "
                    "(only images valid for this template are searched)."
                ),
                "data": {"matches": target_labels},
            }
        image_matches = await _search_template_images(client, resolved_template_id, image_search)
        if not image_matches:
            return {
                "status": "cancelled",
                "message": (f"No image found matching {image_search!r} for template {resolved_template_id!r}."),
            }
        if len(image_matches) == 1:
            resolved_image = image_matches[0]
        elif image_selection.strip():
            needle = image_selection.strip().lower()
            if image_selection.strip().isdigit():
                idx = int(image_selection.strip())
                if 1 <= idx <= len(image_matches):
                    resolved_image = image_matches[idx - 1]
            if resolved_image is None:
                exact = [i for i in image_matches if i.lower() == needle]
                if len(exact) == 1:
                    resolved_image = exact[0]
            if resolved_image is None:
                return {
                    "status": "error",
                    "message": (
                        f"Could not match {image_selection!r} to any current image. "
                        f"Current matches:\n{format_numbered(image_matches)}"
                    ),
                    "data": {"matches": image_matches},
                }
        else:
            return {
                "status": "selection_required",
                "message": (
                    f"{len(image_matches)} images match {image_search!r} for template "
                    f"{resolved_template_id!r}:\n{format_numbered(image_matches)}\n\n"
                    "Reply with `image_selection` set to the number or exact filename "
                    "of the one you want."
                ),
                "data": {"matches": image_matches},
            }
        change_value_label = resolved_image
        fields = {"image": resolved_image}
    else:
        if value is None:
            return {
                "status": "selection_required",
                "message": (
                    f"{len(target_nodes)} node(s) selected from {resolved_template_id!r}, "
                    f"changing {normalized_component}.\n\nWhat value do you want to set "
                    f"it to? Reply with `value` (a number)."
                ),
                "data": {"matches": target_labels},
            }
        change_value_label = str(value)
        fields = {normalized_component: value}

    if not confirm:
        plural = "s" if len(target_nodes) != 1 else ""
        return {
            "status": "confirmation_required",
            "message": (
                f"{len(target_nodes)} node{plural} using template {resolved_template_id!r} "
                f"will have {normalized_component} changed to {change_value_label!r}:\n"
                f"{format_numbered(target_labels)}\n\n"
                "Every affected node will be stopped first to make this change "
                "(required regardless of PRO/Community). Reply 'accept' or 'yes' to "
                "proceed; anything else cancels."
            ),
            "data": {"matches": target_labels},
        }

    updated: list[str] = []
    for node in target_nodes:
        target_id = _node_id(node)
        node_name = str(node.get("name", f"id {target_id}"))
        if _is_running(node):
            await client.stop_node(lab_path, target_id)
        await client.edit_lab_node(lab_path, target_id, **fields)
        updated.append(node_name)

    plural = "s" if len(updated) != 1 else ""
    return {
        "status": "success",
        "message": (
            f"Updated {len(updated)} node{plural} using template {resolved_template_id!r} "
            f"({normalized_component}={change_value_label!r}): {', '.join(updated)}."
        ),
    }


async def get_node_interfaces(client: EvengClient, lab_path: str, node_id: int) -> dict[str, Any]:
    """Get a node's ethernet/serial interfaces and what they're wired to."""
    return await client.get_node_interfaces(lab_path, node_id)


# -- connect_interface: wire a node to another node, or to a network ---------
#
# EVE-NG has no dedicated "connect two nodes" API endpoint. The actual
# primitive (confirmed against EVE-NG's own API docs and a real community
# cheat sheet) is `PUT /nodes/{id}/interfaces` with `{"<index>": "<network_id>"}`
# -- wiring ONE node's interface to a network. A "direct" node-to-node
# connection, the kind that renders as a plain line rather than a visible
# cloud/bridge icon in EVE-NG's own GUI, is just a regular bridge network
# wired to both nodes' interfaces -- there's no special "invisible" network
# type. It renders as a direct line purely because it has exactly two node
# endpoints and no distinguishing name a user gave it on the canvas; this
# module still gives it a descriptive name (`p2p_<node>_<if>_<node>_<if>`,
# the same convention observed being used for this purpose in the wild) for
# anyone inspecting the lab's networks later, which doesn't affect rendering.
#
# Scoped to ethernet interfaces only -- EVE-NG's interfaces API returns
# ethernet and serial as separate lists, and there's no confirmed data here
# on how (or whether) the PUT endpoint's index space covers serial too, so
# rather than guess, serial interfaces aren't supported by name/auto-pick
# here (an explicit numeric index is passed straight to the API either way).


def _available_ethernet_interfaces(interfaces_data: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """Every unconnected ethernet interface, as (0-based index, interface dict) pairs."""
    ethernet = interfaces_data.get("ethernet")
    if not isinstance(ethernet, list):
        return []
    return [
        (index, iface)
        for index, iface in enumerate(ethernet)
        if isinstance(iface, dict) and iface.get("network_id") in (0, "0", None)
    ]


def _interface_label(index: int, iface: dict[str, Any]) -> str:
    name = str(iface.get("name", f"index {index}"))
    return f"{name} (index {index})"


def _resolve_interface_selection(
    interfaces_data: dict[str, Any],
    interface: int | str | None,
    selection: str,
) -> dict[str, Any]:
    """Resolve which of a node's *available* (unconnected) ethernet
    interfaces to use for `connect_interface`.

    `interface`:
      - An `int`, or a digit-only string: a literal 0-based interface
        index, used directly regardless of whether it's currently
        connected.
      - Any other non-empty string: a case-insensitive substring search
        against every *available* interface's name -- never auto-picks
        the first available interface by default; a specific interface
        must always be named or chosen.
      - `None`/empty: matches every available interface (same as an
        empty search everywhere else in this project) -- if that's more
        than one, a numbered list is returned instead of guessing.

    Unless `interface` resolved directly to a literal index, the matched
    set (every available interface, or the substring matches) is
    narrowed further:
      - No matches: an error.
      - Exactly one match: resolved directly, no prompt.
      - More than one: needs `selection` -- the number from the shown
        list, or the exact interface name -- else returns
        `status: "selection_required"` with a numbered list of the matches.

    Returns a dict with either `{"index": int}` on success, or
    `status`/`message` (and, for `selection_required` or an unmatched
    `selection`, `data: {"matches": [...]}`) otherwise.
    """
    ethernet = interfaces_data.get("ethernet")
    if not isinstance(ethernet, list):
        ethernet = []

    if isinstance(interface, int):
        if 0 <= interface < len(ethernet):
            return {"index": interface}
        return {
            "status": "error",
            "message": f"interface index {interface} is out of range (has {len(ethernet)} ethernet interfaces)",
        }

    text = str(interface).strip() if interface is not None else ""
    if text.isdigit():
        index = int(text)
        if 0 <= index < len(ethernet):
            return {"index": index}
        return {
            "status": "error",
            "message": f"interface index {index} is out of range (has {len(ethernet)} ethernet interfaces)",
        }

    available = _available_ethernet_interfaces(interfaces_data)
    if not available:
        return {"status": "error", "message": "no available (unconnected) ethernet interfaces"}

    needle = text.lower()
    matches = [(index, iface) for index, iface in available if needle in str(iface.get("name", "")).strip().lower()]

    if not matches:
        described = f" matching {interface!r}" if text else ""
        return {"status": "error", "message": f"no available ethernet interface{described} found"}

    if len(matches) == 1:
        index, _ = matches[0]
        return {"index": index}

    labels = [_interface_label(index, iface) for index, iface in matches]

    if selection.strip():
        sel = selection.strip()
        if sel.isdigit():
            idx = int(sel)
            if 1 <= idx <= len(matches):
                chosen_index, _ = matches[idx - 1]
                return {"index": chosen_index}
        sel_lower = sel.lower()
        for index, iface in matches:
            if str(iface.get("name", "")).strip().lower() == sel_lower:
                return {"index": index}
        return {
            "status": "error",
            "message": (
                f"Could not match {selection!r} to any current interface. Current matches:\n{format_numbered(labels)}"
            ),
            "data": {"matches": labels},
        }

    described = f" matching {interface!r}" if text else ""
    return {
        "status": "selection_required",
        "message": (
            f"{len(matches)} available interface(s){described}:\n{format_numbered(labels)}\n\n"
            "Reply with the number or exact interface name of the one you want."
        ),
        "data": {"matches": labels},
    }


def _connected_network_description(interfaces_data: dict[str, Any], index: int) -> str | None:
    """If ethernet interface `index` is currently connected to something,
    a short description of what for a confirmation message; None if free."""
    ethernet = interfaces_data.get("ethernet")
    if not isinstance(ethernet, list) or not (0 <= index < len(ethernet)):
        return None
    iface = ethernet[index]
    if not isinstance(iface, dict):
        return None
    network_id = iface.get("network_id")
    if network_id in (0, "0", None):
        return None
    return f"network {network_id}"


async def _ensure_stopped_for_connection(client: EvengClient, lab_path: str, node_id: int, is_pro: bool) -> bool:
    """Stop `node_id` first if this is Community edition and it's running.

    No-op on PRO (hot interface wiring is supported there). Returns
    whether the node was actually stopped, so the caller can report it.
    """
    if is_pro:
        return False
    current = await client.list_lab_nodes(lab_path, node_id)
    current_data = current.get("data") or {}
    if not isinstance(current_data, dict):
        current_data = {}
    if _is_running(current_data):
        await client.stop_node(lab_path, node_id)
        return True
    return False


async def _wait_for_network_ready(
    client: EvengClient,
    lab_path: str,
    network_id: int,
    attempts: int = 5,
    delay_seconds: float = 0.5,
) -> bool:
    """Poll until a just-created network actually shows up in list_lab_networks.

    Defensive safety net, not a fix for a specific known cause: live
    testing traced what looked like an EVE-NG-side timing issue (a network
    reporting "created" but never appearing, or failing to wire with
    "invalid network_id") back to a real bug in this project instead --
    `add_lab_network` was omitting `left`/`top` from the request, which
    EVE-NG silently accepts (still returning a plausible id) without ever
    persisting the network. That's fixed at the source now
    (`EvengClient.add_lab_network` always sends `left`/`top`). This poll
    stays in place as a defensive check for genuine propagation delay,
    which could still exist independently, without assuming that's what
    caused any *specific* past failure.

    Returns whether the network became visible within `attempts` tries.
    """
    for attempt in range(attempts):
        result = await client.list_lab_networks(lab_path)
        data = result.get("data") or {}
        if isinstance(data, dict) and str(network_id) in data:
            return True
        if isinstance(data, list) and any(isinstance(n, dict) and n.get("id") == network_id for n in data):
            return True
        if attempt < attempts - 1:
            await asyncio.sleep(delay_seconds)
    return False


async def connect_interface(
    client: EvengClient,
    lab_path: str,
    node_id: int,
    interface: int | str | None = None,
    interface_selection: str = "",
    target_node_id: int | None = None,
    target_interface: int | str | None = None,
    target_interface_selection: str = "",
    network_id: int | None = None,
    network_name: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Connect one node's interface to another node, or to an existing network.

    Exactly one target is required:
      - `target_node_id`: connects directly to another node. Creates a new
        bridge network behind the scenes and wires both nodes' interfaces
        to it -- exactly what EVE-NG's own GUI does when you draw a line
        directly between two node icons. It renders as a plain line, not a
        separate network icon, purely because it ends up with exactly two
        node endpoints.
      - `network_id` or `network_name`: connects to a network you already
        created yourself (e.g. via `add_lab_network`) -- this one stays
        visible on the canvas as its own icon, same as wiring a cloud/
        bridge manually in the GUI. `network_name` does an exact
        (case-insensitive) match against the lab's current networks; use
        `network_id` directly if more than one network shares that name.

    `interface`/`target_interface`:
      - An interface index (int, or a digit-only string): used directly,
        even if that interface is already connected to something -- see
        `confirm` below for how that's guarded.
      - Any other string: a case-insensitive *substring* search against
        the node's *available* (unconnected) ethernet interface names --
        can never resolve to an already-connected interface, by construction.
      - Omitted entirely: matches every available interface -- also
        cannot resolve to an already-connected one.

    There is no auto-pick-the-first-available default -- a specific
    interface always has to be named or chosen. If the search (or an
    omitted `interface`) matches more than one available interface, this
    returns `status: "selection_required"` with a numbered list instead
    of guessing; reply with `interface_selection` (source node) or
    `target_interface_selection` (target node, node-to-node mode only) --
    the number from that list, or the exact interface name.

    If an explicit index (source or target) resolves to an interface
    that's already connected to something, this does **not** silently
    rewire it -- rewiring an already-connected interface disconnects it
    from whatever it was previously wired to, with no separate undo.
    Instead it returns `status: "confirmation_required"`, naming which
    interface and what it's currently connected to; call again with
    `confirm=true` to proceed with the rewire anyway, or supply a
    different interface (by search or a genuinely free index) instead.
    This only matters for explicit indices -- the search/omitted paths
    can't reach this case at all, since they only ever resolve to
    interfaces already confirmed free.

    EVE-NG PRO allows wiring interfaces on running nodes; Community
    requires every node involved to be stopped first. Everything that can
    be validated without side effects (interface resolution, the
    already-connected check above, target network resolution) happens
    before any node is touched; only once the connection is confirmed
    workable does this check the server's edition (via `get_status`) and,
    on Community only, stop whichever node(s) are running -- same
    automatic stop-if-needed behavior as `edit_lab_node`. This ordering
    matters: a node is never stopped as a side effect of an operation that
    was going to fail anyway (e.g. the *other* node having no free
    interface, or needing confirmation for an already-connected one).
    """
    node_to_node = target_node_id is not None
    node_to_network = network_id is not None or network_name is not None
    if node_to_node == node_to_network:
        return {
            "status": "error",
            "message": (
                "Exactly one target is required: target_node_id (connect to another "
                "node) or network_id/network_name (connect to an existing network) -- "
                "not both, not neither."
            ),
        }

    src_result = await client.get_node_interfaces(lab_path, node_id)
    src_data = src_result.get("data") or {}
    if not isinstance(src_data, dict):
        src_data = {}
    src_resolved = _resolve_interface_selection(src_data, interface, interface_selection)
    if "index" not in src_resolved:
        src_resolved = dict(src_resolved)
        src_resolved["message"] = f"Node {node_id}: {src_resolved['message']}"
        return src_resolved
    src_index = src_resolved["index"]

    src_connected_to = _connected_network_description(src_data, src_index)
    if src_connected_to and not confirm:
        src_ethernet = src_data.get("ethernet") or []
        src_name = str(src_ethernet[src_index].get("name", f"index {src_index}"))
        return {
            "status": "confirmation_required",
            "message": (
                f"Node {node_id}: interface {src_name} (index {src_index}) is already "
                f"connected to {src_connected_to}. Connecting it to a new target will "
                "disconnect it from that, with no separate undo -- reply with "
                "confirm=true to proceed anyway, or choose a different, currently "
                "available interface instead."
            ),
        }

    resolved_network_id: int | str | None = None
    dst_index: int | None = None

    if node_to_node:
        assert target_node_id is not None  # guaranteed by node_to_node's own definition above
        dst_result = await client.get_node_interfaces(lab_path, target_node_id)
        dst_data = dst_result.get("data") or {}
        if not isinstance(dst_data, dict):
            dst_data = {}
        dst_resolved = _resolve_interface_selection(dst_data, target_interface, target_interface_selection)
        if "index" not in dst_resolved:
            dst_resolved = dict(dst_resolved)
            dst_resolved["message"] = f"Node {target_node_id} (target): {dst_resolved['message']}"
            return dst_resolved
        dst_index = dst_resolved["index"]

        dst_connected_to = _connected_network_description(dst_data, dst_index)
        if dst_connected_to and not confirm:
            dst_ethernet = dst_data.get("ethernet") or []
            dst_name = str(dst_ethernet[dst_index].get("name", f"index {dst_index}"))
            return {
                "status": "confirmation_required",
                "message": (
                    f"Node {target_node_id} (target): interface {dst_name} "
                    f"(index {dst_index}) is already connected to {dst_connected_to}. "
                    "Connecting it to a new target will disconnect it from that, with "
                    "no separate undo -- reply with confirm=true to proceed anyway, or "
                    "choose a different, currently available interface instead."
                ),
            }
    else:
        resolved_network_id = network_id
        if resolved_network_id is None:
            networks_result = await client.list_lab_networks(lab_path)
            networks_data = networks_result.get("data") or {}
            needle = (network_name or "").strip().lower()
            candidates = list(networks_data.items()) if isinstance(networks_data, dict) else []
            matches = [
                (key, net)
                for key, net in candidates
                if isinstance(net, dict) and str(net.get("name", "")).strip().lower() == needle
            ]
            if not matches:
                return {
                    "status": "cancelled",
                    "message": f"No network found named {network_name!r} in this lab.",
                }
            if len(matches) > 1:
                return {
                    "status": "error",
                    "message": (
                        f"{len(matches)} networks are named {network_name!r}; use "
                        "network_id instead to pick one unambiguously."
                    ),
                }
            key, net = matches[0]
            resolved_network_id = net.get("id", key)

    # Everything above is read-only / side-effect-free. From here on the
    # connection is confirmed workable, so it's safe to stop node(s) if
    # this is Community edition and they're running.
    status_result = await client.get_status()
    status_data = status_result.get("data") or {}
    is_pro = is_pro_edition(status_data if isinstance(status_data, dict) else {})

    stopped_nodes: list[int] = []
    if await _ensure_stopped_for_connection(client, lab_path, node_id, is_pro):
        stopped_nodes.append(node_id)
    if target_node_id is not None and await _ensure_stopped_for_connection(client, lab_path, target_node_id, is_pro):
        stopped_nodes.append(target_node_id)

    stop_note = ""
    if stopped_nodes:
        ids = ", ".join(str(n) for n in stopped_nodes)
        stop_note = f" (Community edition: stopped node(s) {ids} first, since interfaces can't be wired while running.)"

    if node_to_node:
        assert target_node_id is not None and dst_index is not None  # guaranteed by node_to_node's own definition
        network_result = await client.add_lab_network(
            lab_path,
            network_type="bridge",
            name=f"p2p_{node_id}_{src_index}_{target_node_id}_{dst_index}",
        )
        new_network_id = (network_result.get("data") or {}).get("id")
        if new_network_id is None:
            return {
                "status": "error",
                "message": (f"Created the backing bridge network but couldn't read back its id.{stop_note}"),
            }
        new_network_id = int(new_network_id)

        # EVE-NG has a confirmed timing issue where a just-created network
        # isn't immediately ready to be wired to -- wait for it to actually
        # show up before attempting to reference it, rather than failing
        # with a confusing "invalid network_id" error most of the time.
        if not await _wait_for_network_ready(client, lab_path, new_network_id):
            return {
                "status": "error",
                "message": (
                    f"Created bridge network (id {new_network_id}, reported success) but "
                    "it never showed up in list_lab_networks. This project previously had "
                    "a bug that caused exactly this (add_lab_network omitting left/top), "
                    f"now fixed -- if it's still happening, something else needs "
                    f"investigating rather than assuming it's just slow.{stop_note}"
                ),
            }

        await client.set_node_interface(lab_path, node_id, src_index, new_network_id)
        await client.set_node_interface(lab_path, target_node_id, dst_index, new_network_id)

        # Confirmed against a working reference implementation: rendering as
        # a direct line (not a separate network icon) is NOT something set
        # at creation time -- the bridge is created visible, both
        # interfaces are wired, and only then is its own visibility field
        # set to 0. Doing this at creation time instead (what this project
        # tried first) doesn't produce a direct line live -- confirmed by
        # the user seeing no cable rendered at all rather than one.
        await client.edit_lab_network(lab_path, new_network_id, visibility=0)

        return {
            "status": "success",
            "message": (
                f"Connected node {node_id} (interface {src_index}) to node "
                f"{target_node_id} (interface {dst_index}), via a new bridge "
                f"network (id {new_network_id}).{stop_note}"
            ),
        }

    assert resolved_network_id is not None  # guaranteed by the node_to_network branch above
    await client.set_node_interface(lab_path, node_id, src_index, int(resolved_network_id))

    return {
        "status": "success",
        "message": (f"Connected node {node_id} (interface {src_index}) to network {resolved_network_id}.{stop_note}"),
    }


async def _all_node_ids_and_names(client: EvengClient, lab_path: str) -> list[tuple[int, str]]:
    result = await client.list_lab_nodes(lab_path)
    data = result.get("data") or {}
    pairs = [
        (int(node.get("id", key)), str(node.get("name", f"id {key}"))) for key, node in iter_named_records(data, "name")
    ]
    pairs.sort(key=lambda p: p[0])
    return pairs


async def _loop_node_action(
    lab_path: str,
    nodes: list[tuple[int, str]],
    action: Callable[[str, int], Awaitable[Any]],
    past_tense: str,
) -> dict[str, Any]:
    """Loop a per-node action (start/stop) across every given node,
    rather than using EVE-NG's bulk "all nodes" endpoint.

    Confirmed live on a PRO server: the bulk endpoint (`GET
    /nodes/start` or `/nodes/stop` with no node id) is unreliable --
    bulk stop returned a genuine 500 Internal Server Error, and bulk
    start silently failed for one node while reporting success. A
    working reference implementation (evengsdk) independently confirms
    this isn't specific to this server: it deliberately avoids the bulk
    endpoint on PRO, looping per-node instead -- only Community edition
    uses it there. Individual per-node calls, looped here, are the same
    calls confirmed working correctly earlier in this project.

    Aggregates results rather than stopping at the first failure, so one
    bad node doesn't block every other one from being attempted.
    """
    if not nodes:
        return {"status": "cancelled", "message": "No nodes found in this lab."}

    succeeded: list[str] = []
    failed: list[str] = []
    for node_id, name in nodes:
        try:
            await action(lab_path, node_id)
            succeeded.append(f"{name} (id {node_id})")
        except Exception as exc:
            failed.append(f"{name} (id {node_id}): {exc}")

    if failed:
        return {
            "status": "success" if succeeded else "error",
            "message": (
                f"{past_tense.capitalize()} {len(succeeded)}/{len(nodes)} node(s), looped "
                "individually (not EVE-NG's bulk endpoint -- confirmed unreliable on this "
                f"server). Succeeded: {', '.join(succeeded) if succeeded else 'none'}. "
                f"Failed: {'; '.join(failed)}."
            ),
        }

    plural = "s" if len(succeeded) != 1 else ""
    return {
        "status": "success",
        "message": (
            f"{past_tense.capitalize()} all {len(succeeded)} node{plural}, looped individually "
            f"(not the bulk endpoint): {', '.join(succeeded)}."
        ),
    }


async def start_node(client: EvengClient, lab_path: str, node_id: int | None = None) -> dict[str, Any]:
    """Start one node, or every node in the lab if `node_id` is omitted.

    Starting every node loops through each one individually rather than
    using EVE-NG's bulk `/nodes/start` endpoint -- see `_loop_node_action`
    for why. Each node still respects its own configured `delay` (see
    `change_node_delay`) when started this way -- EVE-NG's staggered-boot
    behavior isn't tied to using the bulk endpoint specifically.
    """
    if node_id is not None:
        return await client.start_node(lab_path, node_id)
    nodes = await _all_node_ids_and_names(client, lab_path)
    return await _loop_node_action(lab_path, nodes, client.start_node, "started")


async def stop_node(client: EvengClient, lab_path: str, node_id: int | None = None) -> dict[str, Any]:
    """Stop one node, or every node in the lab if `node_id` is omitted.

    Stopping every node loops through each one individually rather than
    using EVE-NG's bulk `/nodes/stop` endpoint -- see `_loop_node_action`
    for why.
    """
    if node_id is not None:
        return await client.stop_node(lab_path, node_id)
    nodes = await _all_node_ids_and_names(client, lab_path)
    return await _loop_node_action(lab_path, nodes, client.stop_node, "stopped")


async def wipe_node(client: EvengClient, lab_path: str, node_id: int | None = None) -> dict[str, Any]:
    """Wipe one node (or all nodes), deleting saved config so it rebuilds from image."""
    return await client.wipe_node(lab_path, node_id)


async def export_node(client: EvengClient, lab_path: str, node_id: int | None = None) -> dict[str, Any]:
    """Export one node's (or all nodes') running config into the saved lab file.

    **PRO only.** Listed as a separate toggleable feature
    ("Export/Import configs or config packs to local PC") on EVE-NG's own
    official comparison page. Confirmed live: fails unconditionally on
    Community -- across VPCS and IOL, running and stopped, `config`
    "Saved" and "Unconfigured" -- while the identical request shape works
    normally for `start_node`/`stop_node`/`wipe_node` on the same server,
    ruling out a request-format problem. Checks the server's edition
    first (same signal `connect_interface`/`share_lab` use) and returns a
    clear error immediately on Community, rather than the generic
    "Request not valid" EVE-NG itself gives no useful detail on.
    """
    status_result = await client.get_status()
    status_data = status_result.get("data") if isinstance(status_result, dict) else None
    if not is_pro_edition(status_data if isinstance(status_data, dict) else {}):
        return {
            "status": "error",
            "message": (
                "Exporting node config is a PRO-only EVE-NG feature -- listed "
                "as a separate toggleable feature on EVE-NG's own official comparison "
                "page, and confirmed live to fail unconditionally on Community "
                "regardless of node type or state. This server is running Community "
                "edition, so export_node isn't available here."
            ),
        }
    return await client.export_node(lab_path, node_id)


def register(mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]) -> None:
    if enabled("list_lab_nodes"):

        @mcp.tool(name="list_lab_nodes")
        async def _list_lab_nodes(lab_path: str, node_id: int | None = None) -> dict[str, Any]:
            """List all nodes in a lab, or get a single node by id (includes console URL/status).

            Each node includes a best-effort `vendor` label extracted from its
            template's description -- EVE-NG's API has no explicit vendor field.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Specific node id, or omit to list all nodes.
            """
            return await list_lab_nodes(await get_client(), lab_path, node_id)

    if enabled("add_lab_node"):

        @mcp.tool(name="add_lab_node")
        async def _add_lab_node(
            lab_path: str,
            template: str = "",
            selection: str = "",
            node_type: str | None = None,
            name: str | None = None,
            image: str | None = None,
            config: str = "Unconfigured",
            left: str | None = None,
            top: str | None = None,
            ram: int | None = None,
            console: str | None = None,
            cpu: int | None = None,
            ethernet: int | None = None,
        ) -> dict[str, Any]:
            """Add a node to a lab's canvas, resolving the template by search and auto-placing it.

            `template` is a case-insensitive substring search against every
            template's id, name, and (best-effort) vendor -- not an exact id.
            Empty matches everything (lists them all); no matches cancels;
            exactly one match proceeds directly; more than one match lists
            them and asks you to call again with `selection` set to the
            number or exact id/name of the one you want.

            Once resolved, fetches the template's own defaults (node type,
            RAM, CPU, ethernet count, console type, icon, and every other
            field it reports, e.g. QEMU-specific ones) and uses them for
            anything you didn't specify -- this works the same way for every
            vendor's templates. If the template has more than one image and
            you didn't specify `image`, this returns the list of images
            (status "selection_required") and asks you to pick one instead of
            guessing; with exactly one image, it proceeds directly.

            Canvas position auto-places when not given: left to right, 5
            nodes per row, 100 units apart starting at (100, 100), wrapping to
            a new row 100 below; skips any grid slot within 50 units of an
            existing node on both axes.

            Args:
                lab_path: Full path to the .unl lab file.
                template: Template id, name, or vendor to search for -- a
                    fragment is enough, e.g. "vios", "cisco", or "juniper".
                    Empty lists every available template.
                selection: When multiple templates matched, the number or
                    exact id/name of the one to use.
                node_type: "qemu", "dynamips", or "iol". Defaults to the template's own type.
                name: Node display name. Defaults to the template's name/prefix.
                image: Image filename from `get_node_template`. Required if the
                    template has more than one image; auto-filled if it has exactly one.
                config: "Unconfigured" or "Saved".
                left: Exact canvas position from the left, e.g. "100". Auto-placed if omitted.
                top: Exact canvas position from the top, e.g. "100". Auto-placed if omitted.
                ram: RAM in MB. Defaults to the template's default.
                console: "telnet" or "vnc". Defaults to the template's default.
                cpu: Number of vCPUs. Defaults to the template's default.
                ethernet: Number of ethernet interfaces/portgroups. Defaults to
                    the template's default.
            """
            return await add_lab_node(
                await get_client(),
                lab_path,
                template,
                selection=selection,
                node_type=node_type,
                name=name,
                image=image,
                config=config,
                left=left,
                top=top,
                ram=ram,
                console=console,
                cpu=cpu,
                ethernet=ethernet,
            )

    if enabled("delete_lab_node"):

        @mcp.tool(name="delete_lab_node")
        async def _delete_lab_node(
            lab_path: str, name: str = "", selection: str = "", confirm: bool = False
        ) -> dict[str, Any]:
            """Delete node(s) from a lab, matched by name substring (case-insensitive).

            Matches on name only, never id. Search -> select -> confirm flow
            (see module docs). More than one node can be selected/deleted per
            call here.

            Args:
                lab_path: Full path to the .unl lab file.
                name: Node name or a fragment of one to delete. Required.
                selection: When multiple nodes matched, the number(s) and/or
                    exact name(s) of the one(s) to delete, space/comma separated.
                confirm: Set true on the final call to actually delete.
            """
            return await delete_lab_node(await get_client(), lab_path, name, selection, confirm)

    if enabled("edit_lab_node"):

        @mcp.tool(name="edit_lab_node")
        async def _edit_lab_node(
            lab_path: str,
            node_id: int,
            name: str | None = None,
            icon: str | None = None,
            image: str | None = None,
            ram: int | None = None,
            cpu: int | None = None,
            cpulimit: int | None = None,
            ethernet: int | None = None,
            console: str | None = None,
            config: str | None = None,
            left: str | None = None,
            top: str | None = None,
            delay: int | None = None,
            disable_offload: int | None = None,
            sat: str | None = None,
            eth_format: str | None = None,
            eth_name: list[str] | None = None,
            firstmac: str | None = None,
            qemu_version: str | None = None,
            qemu_arch: str | None = None,
            qemu_nic: str | None = None,
            qemu_options: str | None = None,
            rdp_user: str | None = None,
            rdp_password: str | None = None,
            confirm_duplicate_name: bool = False,
        ) -> dict[str, Any]:
            """Edit an existing node by id. Only supplied fields are changed.

            Covers every node field EVE-NG's own "Edit Node" dialog
            exposes (see get_node_template's `options` for the full
            reference) -- name, icon, image, ram/cpu/cpulimit/ethernet,
            console/config, canvas position, delay, the QEMU-specific
            fields, disable_offload, sat, eth_format/eth_name, and
            rdp_user/rdp_password (for rdp/rdp-tls console nodes).
            Deliberately excludes uuid -- an identity field EVE-NG assigns
            itself, not something meant to be user-edited.

            Targets exactly one node -- for ram/cpu/ethernet/icon/image
            across every node sharing a template at once, see
            edit_lab_nodes_by_template. For delay specifically with bulk
            ordering/incrementing across many nodes, see change_node_delay.

            EVE-NG requires a node to be stopped to edit it, on both PRO
            and Community (unlike connect_interface's wiring, which PRO
            allows on running nodes). This checks the node's current
            status first and stops it automatically if needed, before
            applying the edit -- you don't have to stop it yourself first.

            If `name` is being changed and another node already has that
            exact name (case-insensitive), this does NOT rename it --
            EVE-NG allows duplicate node names, but silently creating one
            seems worth avoiding by default. It returns status
            "confirmation_required" naming the conflicting node; call
            again with either a different name, or the same name plus
            confirm_duplicate_name=true to use it anyway.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Id of the node to edit (see list_lab_nodes).
                name: New name, if changing.
                icon: New icon filename, if changing.
                image: New image filename, if changing -- must be one of
                    the template's own valid images (see get_node_template).
                ram: New RAM in MB, if changing.
                cpu: New vCPU count, if changing.
                cpulimit: New CPU limit toggle (0/1), if changing.
                ethernet: New ethernet interface count, if changing.
                console: New console type ("telnet"/"vnc"/"rdp"/"rdp-tls"), if changing.
                config: New config state ("Unconfigured"/"Saved"), if changing.
                left: New canvas position from the left, if changing.
                top: New canvas position from the top, if changing.
                delay: New startup delay in seconds, if changing.
                disable_offload: New disable-offload toggle (0/1), if changing.
                sat: New satellite setting, if changing.
                eth_format: New interface name format string, if changing.
                eth_name: New explicit interface names list, if changing.
                firstmac: New first interface MAC address, if changing.
                qemu_version: New QEMU version, if changing.
                qemu_arch: New QEMU architecture, if changing.
                qemu_nic: New QEMU NIC model, if changing.
                qemu_options: New custom QEMU options string, if changing.
                rdp_user: New RDP username (rdp/rdp-tls console nodes), if changing.
                rdp_password: New RDP password (rdp/rdp-tls console nodes), if changing.
                confirm_duplicate_name: Set true to use `name` even if
                    another node already has it.
            """
            return await edit_lab_node(
                await get_client(),
                lab_path,
                node_id,
                name=name,
                icon=icon,
                image=image,
                ram=ram,
                cpu=cpu,
                cpulimit=cpulimit,
                ethernet=ethernet,
                console=console,
                config=config,
                left=left,
                top=top,
                delay=delay,
                disable_offload=disable_offload,
                sat=sat,
                eth_format=eth_format,
                eth_name=eth_name,
                firstmac=firstmac,
                qemu_version=qemu_version,
                qemu_arch=qemu_arch,
                qemu_nic=qemu_nic,
                qemu_options=qemu_options,
                rdp_user=rdp_user,
                rdp_password=rdp_password,
                confirm_duplicate_name=confirm_duplicate_name,
            )

    if enabled("change_node_delay"):

        @mcp.tool(name="change_node_delay")
        async def _change_node_delay(
            lab_path: str,
            node_id: int | None = None,
            delay: int | None = None,
            bulk: bool = False,
            names: str | list[str] = "",
            increment: int | None = None,
            order: str = "",
            confirm: bool = False,
        ) -> dict[str, Any]:
            """Change a node's startup delay (seconds before it auto-starts), one node or in bulk.

            `node_id` always means single-node mode, regardless of `bulk`:
            sets that one node's delay to `delay` (default 10).

            Otherwise `bulk=true` is required, in one of two forms:
              - `names` given (a name, or list of names -- case-insensitive
                substring match against every node's name): every match
                gets an incrementing delay (`increment`, default 10) --
                the first matched node gets `increment` seconds, the
                second `increment*2`, and so on, in the order the names
                were given.
              - `names` omitted: lists every node in the lab with its
                current delay (status "selection_required") and asks for
                `order` -- the list numbers, in the sequence you want
                increasing delays applied (e.g. "3,1,2"); node 3 gets
                `increment` seconds, node 1 gets `increment*2`, node 2
                gets `increment*3`.

            Every mode ends the same way: one more explicit confirmation
            summarizing every node and its new delay, warning that each
            will be stopped first (required regardless of PRO/Community,
            same as `edit_lab_node`). Reply "accept" or "yes" (`confirm`)
            to apply; anything else cancels. Nothing is stopped or
            changed before that.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Id of a single node to change. Overrides `bulk` if given.
                delay: New delay in seconds, for single-node mode. Default 10.
                bulk: Required (with node_id omitted) for multi-node mode.
                names: Node name or list of names to match (case-insensitive
                    substring), for bulk mode. Omit to be shown every node
                    and asked for `order` instead.
                increment: Delay increment in seconds between successive
                    nodes, for bulk mode. Default 10.
                order: When bulk mode listed every node, the numbers from
                    that list in the sequence you want increasing delays applied.
                confirm: Set true on the final call to actually apply.
            """
            return await change_node_delay(
                await get_client(),
                lab_path,
                node_id=node_id,
                delay=delay,
                bulk=bulk,
                names=names,
                increment=increment,
                order=order,
                confirm=confirm,
            )

    if enabled("edit_lab_nodes_by_template"):

        @mcp.tool(name="edit_lab_nodes_by_template")
        async def _edit_lab_nodes_by_template(
            lab_path: str,
            vendor: str = "",
            template: str = "",
            template_selection: str = "",
            node_selection: str = "",
            component: str | None = None,
            value: int | None = None,
            icon_search: str = "",
            icon_selection: str = "",
            image_search: str = "",
            image_selection: str = "",
            confirm: bool = False,
        ) -> dict[str, Any]:
            """Bulk-edit interfaces/cpu/memory/icon/image across nodes of exactly one template.

            Search by `vendor` and/or `template` (case-insensitive
            substring, at least one required). More than one template
            matching: lists every match (numbered) and asks you to narrow
            further -- a more specific vendor/template, or
            `template_selection` (number or exact template id) -- repeat
            until exactly one remains. Never targets more than one
            template per call.

            Once resolved, `node_selection` picks which of that template's
            nodes to target: "all", or number(s)/exact name(s)
            (space/comma separated).

            Then `component` (interfaces/cpu/memory/icon/image) and
            `value` say what to change. For `component="icon"`, `value` is
            unused -- `icon_search` narrows EVE-NG's icon catalog the same
            way template matches do, via `icon_selection`. For
            `component="image"`, `value` is also unused -- `image_search`
            narrows *this resolved template's own* valid images (not a
            global catalog -- images are template-scoped), via
            `image_selection`.

            Whatever isn't supplied is prompted for one piece at a time --
            each call re-derives everything fresh from what's currently
            given, there's no server-side session.

            Final confirmation always summarizes every affected node, the
            template, and the change, and warns that every affected node
            will be stopped first (required regardless of PRO/Community).
            Reply "accept" or "yes" (`confirm`) to apply; anything else
            cancels -- same wording as every delete tool.

            Args:
                lab_path: Full path to the .unl lab file.
                vendor: Vendor to search for, e.g. "cisco". At least this
                    or `template` is required.
                template: Template id/name fragment to search for, e.g. "vios".
                template_selection: When multiple templates matched, the
                    number or exact template id of the one you want.
                node_selection: "all", or the number(s)/exact name(s)
                    (space/comma separated) of the nodes to target.
                component: What to change: "interfaces", "cpu", "memory", "icon", or "image".
                value: New numeric value, for interfaces/cpu/memory.
                icon_search: Icon filename fragment to search for, for component="icon".
                icon_selection: When multiple icons matched, the number or
                    exact filename of the one you want.
                image_search: Image filename fragment to search for, for
                    component="image" -- searched within the resolved
                    template's own valid images only.
                image_selection: When multiple images matched, the number
                    or exact filename of the one you want.
                confirm: Set true on the final call to actually apply.
            """
            return await edit_lab_nodes_by_template(
                await get_client(),
                lab_path,
                vendor=vendor,
                template=template,
                template_selection=template_selection,
                node_selection=node_selection,
                component=component,
                value=value,
                icon_search=icon_search,
                icon_selection=icon_selection,
                image_search=image_search,
                image_selection=image_selection,
                confirm=confirm,
            )

    if enabled("get_node_interfaces"):

        @mcp.tool(name="get_node_interfaces")
        async def _get_node_interfaces(lab_path: str, node_id: int) -> dict[str, Any]:
            """Get a node's ethernet/serial interfaces and what they're wired to.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Id of the node.
            """
            return await get_node_interfaces(await get_client(), lab_path, node_id)

    if enabled("connect_interface"):

        @mcp.tool(name="connect_interface")
        async def _connect_interface(
            lab_path: str,
            node_id: int,
            interface: int | str | None = None,
            interface_selection: str = "",
            target_node_id: int | None = None,
            target_interface: int | str | None = None,
            target_interface_selection: str = "",
            network_id: int | None = None,
            network_name: str | None = None,
            confirm: bool = False,
        ) -> dict[str, Any]:
            """Connect one node's interface to another node, or to an existing network.

            Exactly one target is required: `target_node_id` (connects
            directly to another node -- EVE-NG has no dedicated "connect
            two nodes" API endpoint, so this creates a new bridge network
            behind the scenes and wires both nodes' interfaces to it,
            exactly what EVE-NG's own GUI does when you draw a line
            directly between two node icons; it renders as a plain line,
            not a separate network icon, because it ends up with exactly
            two node endpoints) or `network_id`/`network_name` (connects
            to a network you already created yourself, e.g. via
            `add_lab_network` -- this one stays visible on the canvas as
            its own icon, same as wiring a cloud/bridge manually in the GUI).

            `interface`/`target_interface`: an interface index used
            directly (even if already connected to something -- see
            `confirm` below), or any other string as a case-insensitive
            substring search against the node's *available* (unconnected)
            ethernet interface names, or omit entirely to match every
            available interface (search/omitted paths can never resolve
            to an already-connected interface). There's no
            auto-pick-the-first-available default -- if more than one
            interface matches, this returns status "selection_required"
            with a numbered list instead of guessing; reply with
            `interface_selection`/`target_interface_selection` -- the
            number from that list, or the exact interface name. Scoped to
            ethernet interfaces only.

            If an explicit index (source or target) is already connected
            to something, this does **not** silently rewire it --
            rewiring disconnects it from whatever it was previously wired
            to, with no separate undo. Instead it returns status
            "confirmation_required", naming which interface and what it's
            currently connected to; reply with `confirm=true` to proceed
            anyway, or supply a different interface instead.

            EVE-NG PRO allows wiring interfaces on running nodes;
            Community requires every node involved to be stopped first.
            This checks the server's edition automatically and, on
            Community only, stops any running node(s) involved before
            wiring them -- same stop-if-needed behavior as `edit_lab_node`.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Id of the node whose interface is being connected.
                interface: Which interface on node_id -- index, a search
                    string, or omit to see every available one.
                interface_selection: When multiple of node_id's
                    interfaces matched, the number or exact name of the
                    one you want.
                target_node_id: For a node-to-node connection: id of the
                    other node.
                target_interface: Which interface on target_node_id --
                    index, a search string, or omit to see every available one.
                target_interface_selection: When multiple of
                    target_node_id's interfaces matched, the number or
                    exact name of the one you want.
                network_id: For a node-to-network connection: the network's id.
                network_name: For a node-to-network connection: the
                    network's exact name (case-insensitive), if you don't
                    already know its id.
                confirm: Set true to proceed when an explicit index
                    (source or target) is already connected to something,
                    accepting that it will be disconnected from that.
            """
            return await connect_interface(
                await get_client(),
                lab_path,
                node_id,
                interface=interface,
                interface_selection=interface_selection,
                target_node_id=target_node_id,
                target_interface=target_interface,
                target_interface_selection=target_interface_selection,
                network_id=network_id,
                network_name=network_name,
                confirm=confirm,
            )

    if enabled("start_node"):

        @mcp.tool(name="start_node")
        async def _start_node(lab_path: str, node_id: int | None = None) -> dict[str, Any]:
            """Start one node, or every node in the lab if `node_id` is omitted.

            Starting every node loops through each one individually
            rather than using EVE-NG's bulk endpoint -- confirmed live on
            a PRO server that the bulk endpoint is unreliable, and a
            working reference implementation (evengsdk) independently
            confirms this, deliberately avoiding it on PRO too. Each
            node still respects its own configured `delay` (see
            `change_node_delay`) when started this way.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Node id to start, or omit to start all nodes.
            """
            return await start_node(await get_client(), lab_path, node_id)

    if enabled("stop_node"):

        @mcp.tool(name="stop_node")
        async def _stop_node(lab_path: str, node_id: int | None = None) -> dict[str, Any]:
            """Stop one node, or every node in the lab if `node_id` is omitted.

            Stopping every node loops through each one individually
            rather than using EVE-NG's bulk endpoint -- see `start_node`
            for why.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Node id to stop, or omit to stop all nodes.
            """
            return await stop_node(await get_client(), lab_path, node_id)

    if enabled("wipe_node"):

        @mcp.tool(name="wipe_node")
        async def _wipe_node(lab_path: str, node_id: int | None = None) -> dict[str, Any]:
            """Wipe one node (or all nodes), deleting saved config/VLANs so it rebuilds from image.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Node id to wipe, or omit to wipe all nodes.
            """
            return await wipe_node(await get_client(), lab_path, node_id)

    if enabled("export_node"):

        @mcp.tool(name="export_node")
        async def _export_node(lab_path: str, node_id: int | None = None) -> dict[str, Any]:
            """Export one node's (or all nodes') running config into the saved lab file.

            **PRO only** -- listed as a separate toggleable
            feature on EVE-NG's own official comparison page, and
            confirmed live to fail unconditionally on Community
            regardless of node type or state. Checks the server's
            edition first and returns a clear error immediately on
            Community.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Node id to export, or omit to export all nodes.
            """
            return await export_node(await get_client(), lab_path, node_id)
