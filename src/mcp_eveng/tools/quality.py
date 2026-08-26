"""MCP tool for EVE-NG PRO/Corporate's per-connection link-quality feature
(delay/jitter/packet-loss/bandwidth), set independently on each side of a
connection.

**PRO/Corporate only.** Not available on Community at all -- confirmed
directly by the user (no GUI option exists there), and unlike most of
this project's PRO/Community differences, there's no Community-side
source to cross-check against for this one (link quality has no
open-source `unetlab` equivalent at all -- it's PRO-exclusive from the
ground up, not a case of Community having a restricted version of it).

## Confirmed request shape

There is no documented public API reference for this feature -- EVE-NG's
own official API docs (`eve-ng.net/index.php/how-to-eve-ng-api`) don't
cover it, and PRO's backend is closed-source (unlike Community, the
open-source `unetlab`-derived codebase this project cross-checks
directly for other quirks -- see `tools/nodes.py`'s delay-workaround
note for an example). The shape below was captured live from a real PRO
server's own browser network traffic while using its GUI's "Edit
connection link quality" dialog -- not inferred, guessed, or taken from
any written documentation:

    PUT /api/labs/{lab_path}/quality
    {
      "source_label": "Gi0/1", "source_delay": 11, "source_jitter": 11,
      "source_loss": 11, "source_bandwidth": 11,
      "destination_label": "Gi2", "destination_delay": 22,
      "destination_jitter": 22, "destination_loss": 22,
      "destination_bandwidth": 22,
      "source": "48", "destination": "36",
      "source_interfaceId": 1, "destination_interfaceId": 1,
      "save": 1
    }

Confirmed from four separate live captures (two edits on a plain
node-to-node link, two on a node-to-network link):

- `source`/`destination` are the two endpoints of ONE existing
  connection -- a node id as a bare numeric string (e.g. `"48"`, NOT
  `"node48"` -- `get_lab_topology`'s own `"node48"`-style token needs its
  `"node"` prefix stripped before use here), or, when that side is
  attached to a network of ANY kind, `"network<id>"` (e.g. `"network10"`)
  -- this exactly matches `get_lab_topology`'s own token for a network
  endpoint, no transformation needed.
- `source_interfaceId`/`destination_interfaceId` are that side's
  interface index (int) for a node, or the literal string `"network"`
  for a network-attached side.
- `source_label`/`destination_label` are that side's interface display
  name (e.g. `"Gi0/1"`), or `""` for a network-attached side.
- **A network-attached side's delay/jitter/loss/bandwidth cannot be set
  at all.** Confirmed live: EVE-NG's own GUI greys out that side's
  inputs entirely and always submits `0` for all four regardless of
  what (if anything) was there before. This tool enforces the same: any
  side resolved as network-attached always sends 0 for that side, and
  any values the caller supplied for it are dropped, noted in the
  response rather than silently ignored. This generalizes the original
  "bridges only" suspicion into "any network-attached side" -- the
  captured case used a plain network attachment, not a network of
  bridge type specifically, and hit the identical restriction.
- `save`: `0` applies the change live without persisting it to the saved
  lab file (matches the GUI's "Apply" button); `1` does both persist and
  apply (matches "Save"). Confirmed live: a "Save" call in the same
  editing session always reused the same field values as the preceding
  "Apply" call, consistent with "Save" being a superset of "Apply"
  rather than a separate, independent action -- not confirmed whether
  "Save" alone (without a prior "Apply") also applies live immediately;
  assumed yes, since that's the more conservative reading (an unexpected
  need to also call "Apply" would surface immediately in testing).

## Reading current quality values: confirmed possible via get_lab_topology

Originally this tool required the far side's current values to be
supplied explicitly, since no read path had been found. That's since
been confirmed wrong: a live PRO server's `get_lab_topology` response
includes `source_delay`/`source_jitter`/`source_loss`/
`source_bandwidth` and the `destination_*` equivalents on every
connection entry -- the same topology call this tool already makes to
resolve the connection in the first place. (Not confirmed whether this
holds on every PRO/Corporate version -- only tested against the one
live server available -- but it's the same endpoint and same response
shape this tool already depends on for everything else, so no new call
is needed to use it.)

Because of this, the far side's current values are read directly from
that topology entry and reused automatically -- `far_delay`/
`far_jitter`/`far_loss`/`far_bandwidth` are optional overrides, not
required inputs. Supplying one changes just that value; leaving all
four unset preserves the far side exactly as it was. This removes the
earlier risk of silently zeroing the far side, without needing the
caller to already know its current values.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..edition import is_pro_edition

GetClient = Callable[[], Awaitable[EvengClient]]


def _find_interface_index(interfaces_data: dict[str, Any], label: str) -> int | None:
    """Exact (case-insensitive) match of an ethernet interface's name to
    its index. Deliberately not the *available-interfaces-only* resolver
    `tools/nodes.py` uses for `connect_interface` -- link quality only
    ever applies to an interface that's already connected, the opposite
    of what that resolver looks for."""
    ethernet = interfaces_data.get("ethernet")
    if not isinstance(ethernet, list):
        return None
    needle = label.strip().lower()
    for index, iface in enumerate(ethernet):
        if isinstance(iface, dict) and str(iface.get("name", "")).strip().lower() == needle:
            return index
    return None


def _find_connection(
    topology: list[Any], node_id: int, interface_label: str
) -> dict[str, Any] | None:
    """The one topology entry with `node_id`+`interface_label` on either end."""
    node_token = f"node{node_id}"
    needle = interface_label.strip().lower()
    for entry in topology:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("source_type") == "node"
            and entry.get("source") == node_token
            and str(entry.get("source_label", "")).strip().lower() == needle
        ):
            return entry
        if (
            entry.get("destination_type") == "node"
            and entry.get("destination") == node_token
            and str(entry.get("destination_label", "")).strip().lower() == needle
        ):
            return entry
    return None


def _endpoint_value(token: Any, token_type: Any) -> str:
    """A topology endpoint token (`"node48"`/`"network10"`-style) as the
    quality API's own `source`/`destination` field expects it: a bare
    numeric id for a node (the `"node"` prefix stripped), unchanged for
    a network (already in the exact `"network<id>"` form the API uses)."""
    text = str(token)
    if token_type == "node" and text.startswith("node"):
        return text[len("node") :]
    return text


async def set_link_quality(
    client: EvengClient,
    lab_path: str,
    node_id: int,
    interface: str,
    delay: int = 0,
    jitter: int = 0,
    loss: int = 0,
    bandwidth: int = 0,
    far_delay: int | None = None,
    far_jitter: int | None = None,
    far_loss: int | None = None,
    far_bandwidth: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Set link-quality (delay/jitter/packet loss/bandwidth) on one side
    of an existing connection. See this module's docstring for the
    confirmed request shape, the network-attached-side restriction, and
    how the far side's current values are read automatically.

    Args:
        lab_path: Full path to the .unl lab file.
        node_id: The node on the side you want to change.
        interface: That node's interface name (e.g. "Gi0/1") or 0-based
            index -- must already be connected; this only applies to an
            existing link, not a free interface.
        delay, jitter, loss, bandwidth: New quality values for
            `node_id`'s side.
        far_delay, far_jitter, far_loss, far_bandwidth: Optional
            overrides for the far side, if it's another node (not a
            network) -- each defaults to that side's current value,
            read directly from `get_lab_topology`'s own
            source_delay/jitter/loss/bandwidth (or destination_*)
            fields, so leaving all four unset preserves the far side
            exactly as it was. Ignored, with a note, if the far side is
            network-attached -- confirmed live, that side can't have
            quality set at all regardless of what's supplied.
        persist: True (default) saves to the lab file and applies live,
            matching the GUI's "Save". False applies live only without
            persisting -- matching "Apply" -- lost on next lab load/restart.
    """
    status_result = await client.get_status()
    status_data = status_result.get("data") if isinstance(status_result, dict) else None
    if not is_pro_edition(status_data if isinstance(status_data, dict) else {}):
        return {
            "status": "error",
            "message": (
                "Link quality (delay/jitter/packet loss/bandwidth per connection) "
                "is a PRO/Corporate-only EVE-NG feature, not available on "
                "Community at all. This server is running Community edition, "
                "so set_link_quality isn't available here."
            ),
        }

    interfaces_result = await client.get_node_interfaces(lab_path, node_id)
    interfaces_data = interfaces_result.get("data")
    if not isinstance(interfaces_data, dict):
        interfaces_data = {}

    text = str(interface).strip()
    if text.isdigit():
        near_index: int | None = int(text)
        ethernet = interfaces_data.get("ethernet")
        near_label = None
        if isinstance(ethernet, list) and 0 <= near_index < len(ethernet):
            iface = ethernet[near_index]
            if isinstance(iface, dict):
                near_label = str(iface.get("name", ""))
        if near_label is None:
            return {
                "status": "error",
                "message": f"interface index {near_index} not found on node {node_id}",
            }
    else:
        near_label = text
        near_index = _find_interface_index(interfaces_data, text)
        if near_index is None:
            return {
                "status": "error",
                "message": f"No interface named {text!r} found on node {node_id}.",
            }

    topo_result = await client.get_lab_topology(lab_path)
    topology = topo_result.get("data")
    if not isinstance(topology, list):
        topology = []

    entry = _find_connection(topology, node_id, near_label)
    if entry is None:
        return {
            "status": "error",
            "message": (
                f"No existing connection found for node {node_id} interface "
                f"{near_label!r} -- link quality only applies to an "
                "already-connected interface."
            ),
        }

    node_token = f"node{node_id}"
    near_is_source = entry.get("source_type") == "node" and entry.get("source") == node_token

    far_type = entry.get("destination_type") if near_is_source else entry.get("source_type")
    far_token_raw = entry.get("destination") if near_is_source else entry.get("source")
    far_label = str(entry.get("destination_label", "") if near_is_source else entry.get("source_label", ""))
    far_is_network = far_type == "network"

    note: str | None = None
    far_interface_id: int | str
    far_delay_v: int
    far_jitter_v: int
    far_loss_v: int
    far_bandwidth_v: int

    if far_is_network:
        far_delay_v = far_jitter_v = far_loss_v = far_bandwidth_v = 0
        far_interface_id = "network"
        if any(v is not None for v in (far_delay, far_jitter, far_loss, far_bandwidth)):
            note = (
                f"The far side ({far_token_raw}) is network-attached, so its "
                "quality can't be set -- EVE-NG forces it to 0 regardless of "
                "what's requested (confirmed live). Any far_* values you "
                "supplied were ignored."
            )
    else:
        # Read the far side's current values directly from this same
        # topology entry -- confirmed live (PRO server) that
        # source_delay/jitter/loss/bandwidth and the destination_*
        # equivalents are present on every connection entry. far_delay
        # etc. are optional overrides on top of that, not required inputs.
        far_current = (
            (
                entry.get("destination_delay"),
                entry.get("destination_jitter"),
                entry.get("destination_loss"),
                entry.get("destination_bandwidth"),
            )
            if near_is_source
            else (
                entry.get("source_delay"),
                entry.get("source_jitter"),
                entry.get("source_loss"),
                entry.get("source_bandwidth"),
            )
        )
        far_delay_v = far_delay if far_delay is not None else int(far_current[0] or 0)
        far_jitter_v = far_jitter if far_jitter is not None else int(far_current[1] or 0)
        far_loss_v = far_loss if far_loss is not None else int(far_current[2] or 0)
        far_bandwidth_v = far_bandwidth if far_bandwidth is not None else int(far_current[3] or 0)

        far_node_id = int(str(far_token_raw).removeprefix("node"))
        far_interfaces_result = await client.get_node_interfaces(lab_path, far_node_id)
        far_interfaces_data = far_interfaces_result.get("data")
        if not isinstance(far_interfaces_data, dict):
            far_interfaces_data = {}
        resolved_far_index = _find_interface_index(far_interfaces_data, far_label)
        if resolved_far_index is None:
            return {
                "status": "error",
                "message": (
                    f"Could not resolve interface {far_label!r} on far-side "
                    f"node {far_node_id} to an index."
                ),
            }
        far_interface_id = resolved_far_index

    api_source = _endpoint_value(entry.get("source"), entry.get("source_type"))
    api_destination = _endpoint_value(entry.get("destination"), entry.get("destination_type"))
    source_label = str(entry.get("source_label", ""))
    destination_label = str(entry.get("destination_label", ""))

    if near_is_source:
        source_interface_id: int | str = near_index
        destination_interface_id: int | str = far_interface_id
        source_quality = (delay, jitter, loss, bandwidth)
        destination_quality = (far_delay_v, far_jitter_v, far_loss_v, far_bandwidth_v)
    else:
        source_interface_id = far_interface_id
        destination_interface_id = near_index
        source_quality = (far_delay_v, far_jitter_v, far_loss_v, far_bandwidth_v)
        destination_quality = (delay, jitter, loss, bandwidth)

    payload: dict[str, Any] = {
        "source_label": source_label,
        "source_delay": source_quality[0],
        "source_jitter": source_quality[1],
        "source_loss": source_quality[2],
        "source_bandwidth": source_quality[3],
        "destination_label": destination_label,
        "destination_delay": destination_quality[0],
        "destination_jitter": destination_quality[1],
        "destination_loss": destination_quality[2],
        "destination_bandwidth": destination_quality[3],
        "source": api_source,
        "destination": api_destination,
        "source_interfaceId": source_interface_id,
        "destination_interfaceId": destination_interface_id,
        "save": 1 if persist else 0,
    }

    result = await client.set_link_quality(lab_path, payload)
    message = (
        f"Set link quality on node {node_id} interface {near_label!r} "
        f"(delay={delay}, jitter={jitter}, loss={loss}, bandwidth={bandwidth}), "
        f"{'persisted' if persist else 'applied live only, not persisted'}."
    )
    if note:
        message += f" {note}"
    return {"status": result.get("status", "success"), "message": message, "data": result}


def register(mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]) -> None:
    if enabled("set_link_quality"):

        @mcp.tool(name="set_link_quality")
        async def _set_link_quality(
            lab_path: str,
            node_id: int,
            interface: str,
            delay: int = 0,
            jitter: int = 0,
            loss: int = 0,
            bandwidth: int = 0,
            far_delay: int | None = None,
            far_jitter: int | None = None,
            far_loss: int | None = None,
            far_bandwidth: int | None = None,
            persist: bool = True,
        ) -> dict[str, Any]:
            """Set link-quality (delay/jitter/packet loss/bandwidth) on one
            side of an existing connection. PRO/Corporate only.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: The node on the side you want to change.
                interface: That node's interface name (e.g. "Gi0/1") or
                    0-based index -- must already be connected.
                delay, jitter, loss, bandwidth: New quality values for
                    node_id's side.
                far_delay, far_jitter, far_loss, far_bandwidth: Optional
                    overrides for the far end, if it's another node (not
                    a network) -- each defaults to that side's current
                    value, read automatically. Ignored if the far side
                    is network-attached (that side can never have
                    quality set).
                persist: True (default) saves to the lab file and
                    applies live. False applies live only, without
                    persisting.
            """
            return await set_link_quality(
                await get_client(),
                lab_path,
                node_id,
                interface,
                delay=delay,
                jitter=jitter,
                loss=loss,
                bandwidth=bandwidth,
                far_delay=far_delay,
                far_jitter=far_jitter,
                far_loss=far_loss,
                far_bandwidth=far_bandwidth,
                persist=persist,
            )
