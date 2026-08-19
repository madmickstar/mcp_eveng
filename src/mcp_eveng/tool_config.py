"""Per-tool enable/disable configuration.

Every MCP tool this server exposes can be individually enabled or
disabled, via a dedicated dotenv-syntax file (default: `tools.env`) --
kept separate from the main `.env` so tool visibility is easy to review
and diff independently of connection/transport settings. Each line is
`tool_name=enabled` or `tool_name=disabled`; any tool not listed defaults
to enabled, and any value other than "disabled" (case-insensitive) is
treated as enabled, so a malformed line fails safe (visible) rather than
silently hiding a tool.

The six user-management tools (`list_users`, `get_user`, `add_user`,
`edit_user`, `delete_user`, `list_user_roles`) are disabled by default --
`_DEFAULT_DISABLED` below -- so a server started with no `tools.env` file
at all still starts with those hidden, matching this project's stated
default posture. `telnet_node` sends arbitrary CLI commands to a live
running device's console with no command-safety filtering -- a
materially different risk profile than the rest of this project's tools,
which only manage EVE-NG's own lab-topology metadata -- but is enabled by
default like everything else here; if you'd rather it be opt-in, set
`telnet_node=disabled` in `tools.env` yourself.
Copy `tools.env.example` to `tools.env` to change any of this.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from dotenv import dotenv_values

_DEFAULT_DISABLED = {
    "list_users",
    "get_user",
    "add_user",
    "edit_user",
    "delete_user",
    "list_user_roles",
}


def load_tool_status(path: str | Path) -> dict[str, bool]:
    """Load a `tool_name -> enabled` mapping from a dotenv-syntax config file.

    If `path` doesn't exist, falls back to just `_DEFAULT_DISABLED` (every
    other tool enabled). A key present in the file always overrides the
    default, in either direction -- explicitly setting
    `list_users=enabled` in the file un-hides it.
    """
    values = dotenv_values(str(path)) if Path(path).is_file() else {}
    status: dict[str, bool] = {name: False for name in _DEFAULT_DISABLED}
    for key, value in values.items():
        status[key] = str(value).strip().lower() != "disabled"
    return status


def make_enabled_predicate(status: dict[str, bool]) -> Callable[[str], bool]:
    """Build a `tool_name -> bool` predicate; anything unlisted defaults to enabled."""

    def enabled(tool_name: str) -> bool:
        return status.get(tool_name, True)

    return enabled
