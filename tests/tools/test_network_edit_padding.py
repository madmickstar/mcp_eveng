"""Network edits that flip none of EVE-NG's "modified" flags, and network icons.

Live finding (2026-10-05): a PUT to /networks/{id} containing only
icon/style/color/label/hideme returns HTTP 500 and strands EVE-NG's
server-side lab lock. Such payloads are padded with the network's own
current `name`, like the node `delay` workaround.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_eveng.tools import networks

LAB = "/testing-lock.unl"
RECORD = {"id": 1, "name": "net2", "type": "bridge", "left": "100", "top": "100", "visibility": 1}


def _client(data: Any) -> AsyncMock:
    client = AsyncMock()
    client.list_lab_networks.return_value = {"status": "success", "data": data}
    client.edit_lab_network.return_value = {"status": "success"}
    return client


@pytest.mark.parametrize(
    "fields",
    [
        {"icon": "Cloud-2D-Blue-S.svg"},
        {"style": "Solid"},
        {"color": "#ff0000"},
        {"label": "probe"},
        {"hideme": 1},
        {"icon": "01-Cloud-Default.svg", "label": "x"},
        {"hideme": 1, "style": "Solid", "color": "#ff0000"},
    ],
)
async def test_flagless_only_payload_is_padded_with_current_name(fields: dict[str, Any]) -> None:
    client = _client(RECORD)  # single-id GET returns the record itself

    result = await networks.edit_lab_network(client, LAB, 1, **fields)

    assert result["status"] == "success"
    client.list_lab_networks.assert_awaited_once_with(LAB, 1)
    client.edit_lab_network.assert_awaited_once_with(LAB, 1, **fields, name="net2")


async def test_padding_works_when_listing_is_keyed_by_id() -> None:
    client = _client({"1": RECORD, "2": {"id": 2, "name": "other"}})

    await networks.edit_lab_network(client, LAB, 1, icon="Cloud-2D-Blue-S.svg")

    assert client.edit_lab_network.await_args.kwargs["name"] == "net2"


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "x"},
        {"left": 5},
        {"top": "7"},
        {"name": "net2", "icon": "Cloud-2D-Blue-S.svg"},
        {"left": 1, "label": "x"},
        {"visibility": 0},  # production path (connect_interface): worked unpadded
    ],
)
async def test_payload_that_already_flips_the_flag_is_not_padded_and_costs_no_extra_read(
    fields: dict[str, Any],
) -> None:
    client = _client(RECORD)

    await networks.edit_lab_network(client, LAB, 1, **fields)

    client.list_lab_networks.assert_not_awaited()
    sent = client.edit_lab_network.await_args.kwargs
    assert set(sent) == {k for k in fields}


async def test_padding_does_not_change_other_caller_supplied_fields() -> None:
    client = _client(RECORD)

    await networks.edit_lab_network(client, LAB, 1, icon="Cloud-2D-Blue-S.svg", visibility=0)

    sent = client.edit_lab_network.await_args.kwargs
    assert sent == {"icon": "Cloud-2D-Blue-S.svg", "visibility": 0, "name": "net2"}


@pytest.mark.parametrize("data", [{}, None, [], {"1": "not-a-dict"}, {"id": 1, "type": "bridge"}])
async def test_unknown_network_sends_nothing_rather_than_a_blank_name(data: Any) -> None:
    client = _client(data)

    result = await networks.edit_lab_network(client, LAB, 9, icon="Cloud-2D-Blue-S.svg")

    assert result["status"] == "error"
    assert "9" in result["message"]
    client.edit_lab_network.assert_not_awaited()  # an unpadded PUT would 500 and strand the lock


async def test_padding_read_happens_inside_the_per_lab_lock() -> None:
    from mcp_eveng import dependencies

    seen: list[bool] = []

    client = AsyncMock()

    async def fake_list(*_a: Any, **_k: Any) -> dict[str, Any]:
        seen.append(dependencies._lab_locks[LAB].locked())
        return {"status": "success", "data": RECORD}

    client.list_lab_networks.side_effect = fake_list
    client.edit_lab_network.return_value = {"status": "success"}

    await networks.edit_lab_network(client, LAB, 1, icon="Cloud-2D-Blue-S.svg")

    assert seen == [True]


def _server(client: AsyncMock) -> FastMCP:
    mcp = FastMCP("network-edit-test")

    async def get_client() -> AsyncMock:
        return client

    networks.register(mcp, get_client, lambda _n: True)
    return mcp


async def test_registered_edit_lab_network_icon_only_is_padded() -> None:
    # The exact payload from the live report that 500'd and stranded the lock.
    client = _client(RECORD)

    await _server(client).call_tool(
        "edit_lab_network",
        {"lab_path": LAB, "network_id": 1, "icon": "Router-2D-Cat-Green-S.svg", "label": "probe-label"},
    )

    client.edit_lab_network.assert_awaited_once_with(
        LAB, 1, icon="Router-2D-Cat-Green-S.svg", label="probe-label", name="net2"
    )


async def test_registered_edit_lab_network_name_plus_icon_unchanged() -> None:
    client = _client(RECORD)

    await _server(client).call_tool(
        "edit_lab_network", {"lab_path": LAB, "network_id": 1, "name": "net2", "icon": "Cloud-2D-Blue-S.svg"}
    )

    client.edit_lab_network.assert_awaited_once_with(LAB, 1, name="net2", icon="Cloud-2D-Blue-S.svg")


# -- icon on add_lab_network ---------------------------------------------------


async def test_add_lab_network_forwards_icon_when_given() -> None:
    client = AsyncMock()
    client.add_lab_network.return_value = {"status": "success"}

    await networks.add_lab_network(client, LAB, "bridge", name="n", icon="Cloud-2D-Blue-S.svg")

    assert client.add_lab_network.await_args.kwargs["icon"] == "Cloud-2D-Blue-S.svg"


async def test_add_lab_network_omits_icon_when_not_given_so_client_default_applies() -> None:
    client = AsyncMock()
    client.add_lab_network.return_value = {"status": "success"}

    await networks.add_lab_network(client, LAB, "bridge")

    assert "icon" not in client.add_lab_network.await_args.kwargs


async def test_registered_add_lab_network_accepts_icon() -> None:
    client = AsyncMock()
    client.add_lab_network.return_value = {"status": "success"}

    await _server(client).call_tool(
        "add_lab_network", {"lab_path": LAB, "network_type": "bridge", "icon": "Cloud-2D-Blue-S.svg", "left": 10}
    )

    kwargs = client.add_lab_network.await_args.kwargs
    assert kwargs["icon"] == "Cloud-2D-Blue-S.svg"
    assert kwargs["left"] == "10"
