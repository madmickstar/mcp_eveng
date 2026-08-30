"""MCP tools for EVE-NG PRO's Wireshark capture containers: listing
what's currently running, and minting a one-time `capture://` URL to
stream one to a local Wireshark via the standalone relay.

**PRO/Corporate only**, same as `tools/quality.py`. Community's own GUI
already generates working `capture://` links today (confirmed live --
`capture://<eveng-host>/<device-name>`) with no MCP involvement needed
at all; this module exists only for PRO, where the GUI instead forces
captures into an embedded Guacamole session.

## Why there's no node/interface -> container correlation

Triggering a capture can't be automated -- confirmed live that each
container's lifetime is tied to a heartbeat from the browser tab that
started it (refreshing the page kills captures off one by one, on a
staggered schedule matching each one's own idle timer, not all at
once). So the user still starts captures from the EVE-NG GUI, same as
today; this tool only helps with what happens after that.

The container's name (`Capture-nnnnnnn`) was confirmed live to be
PID-like, not derived from node id or interface -- consecutive captures
on the same node land on consecutive integers, but unrelated captures
started close together land far apart, matching general host process
churn rather than any node/interface-derived formula. So `list_captures`
shows what's running (container, age, status) for a person to recognize
by When-did-I-start-it, not by an automatic node match, and `get_capture`
takes a position from that list (or an exact container name/id) rather
than a node_id/interface.

## Token flow

`get_capture` mints a short-lived, single-container-scoped token (see
`tokens.py`) and returns a `capture://` URL (see `url.py`) carrying it.
The `.bat` companion registered against `capture://` on the client's
machine parses that URL, distinguishes it from Community's own links by
path pattern (see `url.py`'s `is_community_style_path`), and tries curl
against the relay first, falling back to plink straight into the EVE-NG
host (via the user's own already-configured SSH access) if curl or the
relay is unreachable. No password ever appears in the URL either way.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..edition import is_pro_edition
from ..capture_relay import ssh_client as _ssh_client
from ..capture_relay.config import CaptureSSHSettings, CaptureURLSettings
from ..capture_relay.docker_ps import DOCKER_PS_COMMAND, RunningCapture, parse_docker_ps_output
from ..capture_relay.ssh_client import run_command as _default_run_command
from ..capture_relay.tokens import issue_token
from ..capture_relay.url import build_pro_capture_url

GetClient = Callable[[], Awaitable[EvengClient]]
RunCommand = Callable[[CaptureSSHSettings, str], Awaitable[str]]


async def _require_pro(client: EvengClient) -> dict[str, Any] | None:
    """Shared edition gate for both tools below. Returns an error dict
    if the server isn't PRO/Corporate, else None."""
    status_result = await client.get_status()
    status_data = status_result.get("data") if isinstance(status_result, dict) else None
    if not is_pro_edition(status_data if isinstance(status_data, dict) else {}):
        return {
            "status": "error",
            "message": (
                "Capture container listing/streaming is a PRO/Corporate-only "
                "feature -- Community's capture:// links already work "
                "unmodified via its own GUI and need no MCP tool at all. "
                "This server is running Community edition, so this tool "
                "isn't available here."
            ),
        }
    return None


def _require_asyncssh() -> dict[str, Any] | None:
    """Checked before any SSH work -- gives a clear, actionable error
    instead of a raw ModuleNotFoundError bubbling out of an MCP tool
    call when the optional `capture-relay` extra isn't installed.
    Confirmed live: importing this module never requires asyncssh
    (ssh_client.py imports it lazily), but actually calling
    list_captures/get_capture obviously does."""
    if not _ssh_client.is_available():
        return {
            "status": "error",
            "message": (
                "This feature requires the optional 'capture-relay' extra "
                "-- run `pip install -e \".[capture-relay]\"` (or just "
                "`pip install asyncssh` for this side; Starlette/uvicorn "
                "are only needed by the standalone relay itself, not by "
                "list_captures/get_capture)."
            ),
        }
    return None


async def list_captures(
    client: EvengClient,
    ssh_settings: CaptureSSHSettings,
    _run_command: RunCommand = _default_run_command,
) -> dict[str, Any]:
    """List every currently-running EVE-NG capture container, oldest
    first, with a 1-based `position` for use with `get_capture`.

    Positions aren't stable across calls -- if a capture starts or ends
    between one `list_captures` and a later `get_capture`, positions can
    shift. `get_capture` always re-lists fresh rather than trusting a
    previously-seen position blindly, but the position you pass should
    still come from a recent listing, not a stale one.
    """
    error = await _require_pro(client)
    if error is not None:
        return error
    error = _require_asyncssh()
    if error is not None:
        return error

    output = await _run_command(ssh_settings, DOCKER_PS_COMMAND)
    captures = parse_docker_ps_output(output)

    if not captures:
        return {
            "status": "success",
            "message": "No capture containers currently running.",
            "data": {"captures": []},
        }

    return {
        "status": "success",
        "message": f"{len(captures)} capture container(s) running.",
        "data": {
            "captures": [
                {
                    "position": position,
                    "container_id": c.container_id,
                    "name": c.name,
                    "created_at": c.created_at,
                    "status": c.status,
                }
                for position, c in enumerate(captures, start=1)
            ]
        },
    }


def _resolve_capture(
    captures: list[RunningCapture], position: int | None, container: str | None
) -> RunningCapture | dict[str, Any]:
    """Resolve `position` or `container` against a fresh capture list.
    Returns the matched `RunningCapture`, or an error dict if it
    couldn't be resolved to exactly one."""
    if position is not None:
        if not (1 <= position <= len(captures)):
            return {
                "status": "error",
                "message": (
                    f"position {position} is out of range -- {len(captures)} "
                    "capture(s) currently running. Call list_captures again "
                    "to see current positions (they can shift if captures "
                    "started or stopped since your last list_captures call)."
                ),
            }
        return captures[position - 1]

    needle = str(container).strip().lower()
    matches = [
        c for c in captures if c.name.lower() == needle or c.container_id.lower().startswith(needle)
    ]
    if not matches:
        return {"status": "error", "message": f"No running capture matches {container!r}."}
    if len(matches) > 1:
        return {
            "status": "error",
            "message": f"{container!r} matches more than one running capture -- use position instead.",
        }
    return matches[0]


async def get_capture(
    client: EvengClient,
    ssh_settings: CaptureSSHSettings,
    url_settings: CaptureURLSettings,
    position: int | None = None,
    container: str | None = None,
    _run_command: RunCommand = _default_run_command,
) -> dict[str, Any]:
    """Mint a one-time `capture://` URL for one currently-running
    capture container, identified by `position` (from a recent
    `list_captures` call) or an exact `container` name/id -- exactly
    one of the two, not both.

    The returned URL carries a token scoped to that one container,
    valid for `ssh_settings.token_ttl_seconds` (60s by default) -- long
    enough for the `.bat` companion to act on it, short enough that a
    leaked URL stops being useful quickly. There's no revocation beyond
    letting it expire.
    """
    error = await _require_pro(client)
    if error is not None:
        return error
    error = _require_asyncssh()
    if error is not None:
        return error

    if (position is None) == (container is None):
        return {
            "status": "error",
            "message": "Specify exactly one of position or container, not both or neither.",
        }

    output = await _run_command(ssh_settings, DOCKER_PS_COMMAND)
    captures = parse_docker_ps_output(output)

    if not captures:
        return {"status": "error", "message": "No capture containers currently running."}

    resolved = _resolve_capture(captures, position, container)
    if isinstance(resolved, dict):
        return resolved

    token = issue_token(
        resolved.name,
        ssh_settings.token_secret.get_secret_value(),
        ssh_settings.token_ttl_seconds,
    )
    capture_url = build_pro_capture_url(
        container=resolved.name,
        token=token,
        relay_host=url_settings.advertise_host,
        relay_port=url_settings.advertise_port,
        eveng_host=ssh_settings.ssh_host,
    )

    return {
        "status": "success",
        "message": f"capture:// URL for {resolved.name} (expires in {ssh_settings.token_ttl_seconds}s).",
        "data": {
            "container": resolved.name,
            "capture_url": capture_url,
            "expires_in_seconds": ssh_settings.token_ttl_seconds,
        },
    }


def register(mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]) -> None:
    from ..capture_relay.config import get_capture_ssh_settings, get_capture_url_settings

    if enabled("list_captures"):

        @mcp.tool(name="list_captures")
        async def _list_captures() -> dict[str, Any]:
            """List every currently-running EVE-NG capture container
            (started via the GUI's right-click "Capture" menu), oldest
            first, with a position number for use with get_capture.
            PRO/Corporate only.
            """
            return await list_captures(await get_client(), get_capture_ssh_settings())

    if enabled("get_capture"):

        @mcp.tool(name="get_capture")
        async def _get_capture(
            position: int | None = None,
            container: str | None = None,
        ) -> dict[str, Any]:
            """Mint a one-time capture:// URL to stream one running
            capture to a local Wireshark. PRO/Corporate only.

            Args:
                position: 1-based position from a recent list_captures
                    call. Exactly one of position/container is required.
                container: Exact container name or id, if you already
                    know it instead of a position.
            """
            return await get_capture(
                await get_client(),
                get_capture_ssh_settings(),
                get_capture_url_settings(),
                position=position,
                container=container,
            )
