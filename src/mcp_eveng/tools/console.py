"""MCP tool for configuring a running node's console over telnet.

Fundamentally different from every other tool in this project: everything
else wraps EVE-NG's own REST API for managing lab topology (nodes, networks,
wiring). This connects directly to a running node's console -- a raw TCP
session to the host:port EVE-NG itself reports (`list_lab_nodes`' own `url`
field) -- to send it live CLI commands, the same as opening its console in
the EVE-NG web GUI. EVE-NG's management API has no endpoint for this; there
is no way to configure a running device's VLANs, interfaces, or anything
else in its own CLI except by talking to its console directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..telnet import telnet_session

GetClient = Callable[[], Awaitable[EvengClient]]


def _is_running(node_data: dict[str, Any]) -> bool:
    status = node_data.get("status")
    try:
        return int(status) != 0  # type: ignore[arg-type]  # deliberately unguarded -- caught below
    except (TypeError, ValueError):
        return False


async def telnet_node(
    client: EvengClient,
    lab_path: str,
    node_id: int,
    commands: str | list[str],
    wait_seconds: float = 2.0,
) -> dict[str, Any]:
    """Send one or more CLI commands to a running node's console over telnet.

    The node must already be running (`start_node` first) and use a telnet
    console (most node types do; some, e.g. Docker/GUI nodes, use rdp/vnc
    instead and aren't supported here). Commands are sent one at a time,
    each only after the previous one's output has settled -- entering
    config mode, for instance, changes the prompt, so the next command
    can't be sent blind.

    This sends whatever `commands` says, verbatim, to a live device's
    console -- exactly as if you'd typed it yourself over telnet. There's
    no vendor-aware safety filtering here (that would require parsing
    every possible CLI's command syntax, which isn't something this tool
    attempts): the same judgment that applies to any live console access
    applies here too.

    Returns the full session transcript (banner/prompt plus every
    command's output), not just a success/failure flag, since the actual
    device output is usually what's wanted.
    """
    command_list = [commands] if isinstance(commands, str) else list(commands)
    if not command_list:
        return {"status": "error", "message": "At least one command is required."}

    result = await client.list_lab_nodes(lab_path, node_id)
    data = result.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    if not _is_running(data):
        return {
            "status": "error",
            "message": f"Node {node_id} is not running -- use start_node first.",
        }

    console_type = str(data.get("console", "")).strip().lower()
    if console_type != "telnet":
        return {
            "status": "error",
            "message": (
                f"Node {node_id}'s console type is {console_type or 'unknown'!r}, "
                "not telnet -- this tool only supports telnet consoles."
            ),
        }

    url = str(data.get("url", ""))
    parsed = urlparse(url)
    if parsed.scheme != "telnet" or not parsed.hostname or not parsed.port:
        return {
            "status": "error",
            "message": (f"Could not parse a telnet host/port from node {node_id}'s reported console url ({url!r})."),
        }

    try:
        transcript = await telnet_session(parsed.hostname, parsed.port, command_list, idle_timeout=wait_seconds)
    except (OSError, ConnectionError) as exc:
        return {
            "status": "error",
            "message": f"Telnet session to {parsed.hostname}:{parsed.port} failed: {exc}",
        }

    plural = "s" if len(command_list) != 1 else ""
    return {
        "status": "success",
        "message": f"Sent {len(command_list)} command{plural} to node {node_id}.",
        "data": {"transcript": transcript},
    }


def register(mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]) -> None:
    if enabled("telnet_node"):

        @mcp.tool(name="telnet_node")
        async def _telnet_node(
            lab_path: str,
            node_id: int,
            commands: str | list[str],
            wait_seconds: float = 2.0,
        ) -> dict[str, Any]:
            """Send one or more CLI commands to a running node's console over telnet.

            The node must already be running (`start_node` first) and use
            a telnet console (most node types do; Docker/GUI nodes use
            rdp/vnc instead and aren't supported here). Commands are sent
            one at a time, each only after the previous one's output has
            settled, so entering config mode (which changes the prompt)
            doesn't race ahead of what the device is actually ready for.

            Sends whatever `commands` says verbatim to a live device's
            console -- the same judgment that applies to any live console
            access applies here; there's no vendor-aware command-safety
            filtering.

            Args:
                lab_path: Full path to the .unl lab file.
                node_id: Id of the (running) node to send commands to.
                commands: One command, or a list of commands to send in order.
                wait_seconds: How long to wait for a command's output to
                    settle (no new data) before considering it done and
                    moving to the next one. Increase for commands with
                    large or slow output.
            """
            return await telnet_node(await get_client(), lab_path, node_id, commands, wait_seconds=wait_seconds)
