from __future__ import annotations

import warnings

import pytest

from mcp_eveng.config import MCPTransportSettings
from mcp_eveng.server import create_server

EXPECTED_TOOLS = {
    "get_status",
    "list_tools",
    "telnet_node",
    "list_node_templates",
    "get_node_template",
    "list_network_types",
    "list_user_roles",
    "list_folder",
    "add_folder",
    "move_folder",
    "delete_folder",
    "list_users",
    "get_user",
    "add_user",
    "edit_user",
    "delete_user",
    "get_lab",
    "open_lab",
    "create_lab",
    "edit_lab",
    "share_lab",
    "move_lab",
    "delete_lab",
    "get_lab_topology",
    "get_lab_links",
    "list_lab_pictures",
    "list_labs",
    "list_lab_networks",
    "add_lab_network",
    "edit_lab_network",
    "delete_lab_network",
    "list_lab_nodes",
    "add_lab_node",
    "delete_lab_node",
    "edit_lab_node",
    "change_node_delay",
    "edit_lab_nodes_by_template",
    "get_node_interfaces",
    "connect_interface",
    "start_node",
    "stop_node",
    "wipe_node",
    "export_node",
}


DISABLED_BY_DEFAULT_TOOLS = {
    "list_users",
    "get_user",
    "add_user",
    "edit_user",
    "delete_user",
    "list_user_roles",
    "delete_lab",
}


async def test_create_server_registers_every_enabled_tool_by_default() -> None:
    # Point at a path that can't exist, so this is never accidentally
    # influenced by a real tools.env sitting in the CWD -- falls back to
    # the built-in defaults, which disable the six user-management tools
    # and enable everything else.
    settings = MCPTransportSettings(
        tools_config_path="/nonexistent-path-for-tests/tools.env", _env_file=None  # type: ignore[call-arg]
    )
    mcp = create_server(settings, "stdio")

    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}

    assert (EXPECTED_TOOLS - DISABLED_BY_DEFAULT_TOOLS) <= tool_names
    assert tool_names.isdisjoint(DISABLED_BY_DEFAULT_TOOLS)


async def test_create_server_respects_tools_config_file(tmp_path) -> None:
    # Explicitly re-enable one normally-disabled tool and disable one
    # normally-enabled one -- both directions of the override must work.
    config_file = tmp_path / "tools.env"
    config_file.write_text("list_users=enabled\nget_status=disabled\n")
    settings = MCPTransportSettings(
        tools_config_path=str(config_file), _env_file=None  # type: ignore[call-arg]
    )

    mcp = create_server(settings, "stdio")

    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}

    assert "list_users" in tool_names
    assert "get_status" not in tool_names
    # Everything else keeps its usual default.
    assert "get_user" not in tool_names  # still disabled by default
    assert "list_folder" in tool_names  # still enabled by default


async def test_create_server_uses_given_settings_on_loopback_host() -> None:
    settings = MCPTransportSettings(host="127.0.0.1", port=9100, _env_file=None)  # type: ignore[call-arg]

    mcp = create_server(settings, "streamable-http")

    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 9100


async def test_create_server_applies_allowed_hosts_on_non_loopback_host() -> None:
    settings = MCPTransportSettings(
        host="0.0.0.0",
        port=8000,
        allowed_hosts="192.168.1.100:8000,192.168.1.150:*",
        _env_file=None,  # type: ignore[call-arg]
    )

    mcp = create_server(settings, "streamable-http")

    assert mcp.settings.host == "0.0.0.0"


async def test_create_server_applies_allowed_hosts_from_real_env_var(monkeypatch) -> None:
    # End-to-end regression for the NoDecode fix: go through get_mcp_settings()
    # (real EnvSettingsSource), not a direct constructor kwarg.
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "192.168.1.100:8000,192.168.1.150:*")
    settings = MCPTransportSettings(_env_file=None)  # type: ignore[call-arg]

    mcp = create_server(settings, "streamable-http")

    assert mcp.settings.host == "0.0.0.0"


async def test_create_server_rejects_non_loopback_host_without_allowed_hosts() -> None:
    # allowed_hosts now defaults to ["localhost:*"], not empty -- this test
    # exercises the explicit opt-out (MCP_ALLOWED_HOSTS="") to confirm the
    # rejection path still exists for a non-loopback host with no allowlist.
    settings = MCPTransportSettings(
        host="0.0.0.0", port=8000, allowed_hosts="", _env_file=None  # type: ignore[call-arg]
    )

    with pytest.raises(RuntimeError, match="MCP_ALLOWED_HOSTS"):
        create_server(settings, "streamable-http")


async def test_create_server_non_loopback_host_uses_default_allowed_hosts_without_rejecting() -> None:
    # Regression test for the new default: a non-loopback MCP_HOST no
    # longer fails fast if MCP_ALLOWED_HOSTS is simply left unset -- it
    # falls back to ["localhost:*"], which won't match real traffic to a
    # non-loopback host, so this is a real trade-off (see README).
    settings = MCPTransportSettings(host="0.0.0.0", port=8000, _env_file=None)  # type: ignore[call-arg]

    mcp = create_server(settings, "streamable-http")

    assert mcp.settings.host == "0.0.0.0"


async def test_create_server_skips_host_check_for_stdio() -> None:
    # stdio never binds a socket, so a non-loopback MCP_HOST shouldn't matter.
    settings = MCPTransportSettings(host="0.0.0.0", port=8000, _env_file=None)  # type: ignore[call-arg]

    mcp = create_server(settings, "stdio")

    assert mcp is not None


async def test_create_server_stateless_http_follows_stateful_flag() -> None:
    stateful_settings = MCPTransportSettings(host="127.0.0.1", _env_file=None)  # type: ignore[call-arg]
    stateless_settings = MCPTransportSettings(
        host="127.0.0.1", stateful=False, _env_file=None  # type: ignore[call-arg]
    )

    stateful_mcp = create_server(stateful_settings, "streamable-http")
    stateless_mcp = create_server(stateless_settings, "streamable-http")

    assert stateful_mcp.settings.stateless_http is False
    assert stateless_mcp.settings.stateless_http is True


async def test_create_server_suppresses_fastmcp_lifespan_warning() -> None:
    # The mcp SDK's own FastMCP Settings model has a self-referential
    # 'lifespan' forward reference it never calls model_rebuild() on, which
    # makes pydantic-settings emit a warning on every FastMCP construction.
    # We filter that specific message at import time (see server.py); make
    # sure it's actually suppressed. NOTE: deliberately does NOT call
    # warnings.simplefilter() here, since that would reset the filter list
    # and wipe out the very suppression we're trying to verify.
    settings = MCPTransportSettings(host="127.0.0.1", _env_file=None)  # type: ignore[call-arg]

    with warnings.catch_warnings(record=True) as caught:
        create_server(settings, "stdio")

    assert not any("incomplete definition" in str(w.message) for w in caught)


def test_run_handles_keyboard_interrupt_gracefully(monkeypatch, capsys) -> None:
    import mcp_eveng.server as server_module

    class _FakeMCP:
        def run(self, transport: str) -> None:  # noqa: ARG002
            raise KeyboardInterrupt

    monkeypatch.setattr(
        server_module, "get_mcp_settings", lambda: MCPTransportSettings(_env_file=None)
    )
    monkeypatch.setattr(
        server_module, "create_server", lambda settings, transport: _FakeMCP()
    )

    with pytest.raises(SystemExit) as exc_info:
        server_module.run("stdio")

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Goodbye" in captured.err
    # stdout is reserved for the stdio JSON-RPC stream -- never write here.
    assert captured.out == ""
