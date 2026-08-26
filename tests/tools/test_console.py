from __future__ import annotations

from unittest.mock import AsyncMock, patch

from mcp_eveng.tools import console


async def test_telnet_node_requires_at_least_one_command() -> None:
    client = AsyncMock()

    result = await console.telnet_node(client, "/User1/Lab 1.unl", 9, [])

    assert result["status"] == "error"
    client.list_lab_nodes.assert_not_awaited()


async def test_telnet_node_single_string_command_is_wrapped_in_a_list() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"status": 2, "console": "telnet", "url": "telnet://172.16.130.14:41041"},
    }

    with patch("mcp_eveng.tools.console.telnet_session", new=AsyncMock(return_value="ok")) as mock_session:
        result = await console.telnet_node(client, "/User1/Lab 1.unl", 9, "show vlan")

    mock_session.assert_awaited_once()
    assert mock_session.await_args.args[2] == ["show vlan"]
    assert result["status"] == "success"


async def test_telnet_node_requires_node_to_be_running() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"status": 0, "console": "telnet", "url": "telnet://172.16.130.14:41041"},
    }

    result = await console.telnet_node(client, "/User1/Lab 1.unl", 9, ["show vlan"])

    assert result["status"] == "error"
    assert "not running" in result["message"]


async def test_telnet_node_requires_telnet_console_type() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"status": 2, "console": "vnc", "url": "vnc://172.16.130.14:5900"},
    }

    result = await console.telnet_node(client, "/User1/Lab 1.unl", 9, ["show vlan"])

    assert result["status"] == "error"
    assert "telnet" in result["message"].lower()


async def test_telnet_node_unparseable_url_is_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"status": 2, "console": "telnet", "url": "not-a-valid-url"},
    }

    result = await console.telnet_node(client, "/User1/Lab 1.unl", 9, ["show vlan"])

    assert result["status"] == "error"


async def test_telnet_node_success_calls_telnet_session_with_parsed_host_port() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"status": 2, "console": "telnet", "url": "telnet://172.16.130.14:41041"},
    }

    with patch(
        "mcp_eveng.tools.console.telnet_session", new=AsyncMock(return_value="Switch#")
    ) as mock_session:
        result = await console.telnet_node(
            client, "/User1/Lab 1.unl", 9, ["vlan 20", "name testing"], wait_seconds=3.0
        )

    mock_session.assert_awaited_once_with(
        "172.16.130.14", 41041, ["vlan 20", "name testing"], idle_timeout=3.0
    )
    assert result["status"] == "success"
    assert result["data"]["transcript"] == "Switch#"


async def test_telnet_node_connection_failure_is_reported_as_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"status": 2, "console": "telnet", "url": "telnet://172.16.130.14:41041"},
    }

    async def _raise(*args, **kwargs):
        raise ConnectionError("Could not connect to 172.16.130.14:41041 after 3 attempt(s)")

    with patch("mcp_eveng.tools.console.telnet_session", new=_raise):
        result = await console.telnet_node(client, "/User1/Lab 1.unl", 9, ["show vlan"])

    assert result["status"] == "error"
    assert "41041" in result["message"]


async def test_telnet_node_status_as_string_is_handled() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"status": "2", "console": "telnet", "url": "telnet://172.16.130.14:41041"},
    }

    with patch("mcp_eveng.tools.console.telnet_session", new=AsyncMock(return_value="ok")):
        result = await console.telnet_node(client, "/User1/Lab 1.unl", 9, ["show vlan"])

    assert result["status"] == "success"
