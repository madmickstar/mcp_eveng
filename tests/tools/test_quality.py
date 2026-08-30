from __future__ import annotations

from unittest.mock import AsyncMock

from mcp_eveng.tools import quality

PRO_STATUS = {"status": "success", "data": {"version": "6.5.0-27-PRO"}}
COMMUNITY_STATUS = {"status": "success", "data": {"version": "6.2.0-4"}}


def make_client(**method_returns) -> AsyncMock:
    client = AsyncMock()
    for name, value in method_returns.items():
        getattr(client, name).return_value = value
    return client


def node_interfaces(*names: str) -> dict:
    return {
        "status": "success",
        "data": {"ethernet": [{"name": n, "network_id": 1} for n in names]},
    }


# -- edition gating -----------------------------------------------------------


async def test_set_link_quality_refuses_on_community() -> None:
    client = make_client(get_status=COMMUNITY_STATUS)

    result = await quality.set_link_quality(client, "/Lab 1.unl", node_id=48, interface="Gi0/1")

    assert result["status"] == "error"
    assert "Community" in result["message"]
    client.get_lab_topology.assert_not_awaited()


# -- node-to-node connection: full round trip against the real capture -------
#
# Ground truth: PUT /api/labs/Shared/Cisco%20SD-WAN/learning%20components.unl/quality
# {"source_label":"Gi0/1","source_delay":11,"source_jitter":11,"source_loss":11,
#  "source_bandwidth":11,"destination_label":"Gi2","destination_delay":22,
#  "destination_jitter":22,"destination_loss":22,"destination_bandwidth":22,
#  "source":"48","destination":"36","source_interfaceId":1,
#  "destination_interfaceId":1,"save":1}


NODE_TO_NODE_TOPOLOGY = [
    {
        "type": "ethernet",
        "source": "node48",
        "source_type": "node",
        "source_label": "Gi0/1",
        "destination": "node36",
        "destination_type": "node",
        "destination_label": "Gi2",
        "network_id": 1,
        "source_delay": 0,
        "source_jitter": 0,
        "source_loss": 0,
        "source_bandwidth": 0,
        "destination_delay": 0,
        "destination_jitter": 0,
        "destination_loss": 0,
        "destination_bandwidth": 0,
    }
]


async def test_set_link_quality_node_to_node_matches_real_capture() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": NODE_TO_NODE_TOPOLOGY},
        set_link_quality={"code": 201, "status": "success", "message": "Lab has been saved (60023)."},
    )
    # node 48's own interfaces (near side), then node 36's (far side) --
    # AsyncMock resolves get_node_interfaces calls in order.
    client.get_node_interfaces.side_effect = [
        node_interfaces("Gi0/0", "Gi0/1"),
        node_interfaces("Gi1", "Gi2"),
    ]

    result = await quality.set_link_quality(
        client,
        "/Shared/Cisco SD-WAN/learning components.unl",
        node_id=48,
        interface="Gi0/1",
        delay=11,
        jitter=11,
        loss=11,
        bandwidth=11,
        far_delay=22,
        far_jitter=22,
        far_loss=22,
        far_bandwidth=22,
        persist=True,
    )

    client.set_link_quality.assert_awaited_once_with(
        "/Shared/Cisco SD-WAN/learning components.unl",
        {
            "source_label": "Gi0/1",
            "source_delay": 11,
            "source_jitter": 11,
            "source_loss": 11,
            "source_bandwidth": 11,
            "destination_label": "Gi2",
            "destination_delay": 22,
            "destination_jitter": 22,
            "destination_loss": 22,
            "destination_bandwidth": 22,
            "source": "48",
            "destination": "36",
            "source_interfaceId": 1,
            "destination_interfaceId": 1,
            "save": 1,
        },
    )
    assert result["status"] == "success"


async def test_set_link_quality_apply_only_sends_save_zero() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": NODE_TO_NODE_TOPOLOGY},
        set_link_quality={"status": "success"},
    )
    client.get_node_interfaces.side_effect = [
        node_interfaces("Gi0/0", "Gi0/1"),
        node_interfaces("Gi1", "Gi2"),
    ]

    await quality.set_link_quality(
        client,
        "/Lab 1.unl",
        node_id=48,
        interface="Gi0/1",
        delay=11,
        jitter=11,
        loss=11,
        bandwidth=11,
        far_delay=22,
        far_jitter=22,
        far_loss=22,
        far_bandwidth=22,
        persist=False,
    )

    sent_payload = client.set_link_quality.await_args.args[1]
    assert sent_payload["save"] == 0


async def test_set_link_quality_reads_far_side_current_values_when_omitted() -> None:
    # Confirmed live (PRO server): get_lab_topology includes
    # source_delay/jitter/loss/bandwidth and destination_* on every
    # connection entry. When far_* aren't supplied, the far side's
    # CURRENT values (from this topology entry) are reused automatically
    # -- not required from the caller, not reset to 0.
    topology_with_existing_far_quality = [
        {
            **NODE_TO_NODE_TOPOLOGY[0],
            "destination_delay": 5,
            "destination_jitter": 6,
            "destination_loss": 7,
            "destination_bandwidth": 8,
        }
    ]
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": topology_with_existing_far_quality},
        set_link_quality={"status": "success"},
    )
    client.get_node_interfaces.side_effect = [
        node_interfaces("Gi0/0", "Gi0/1"),
        node_interfaces("Gi1", "Gi2"),
    ]

    result = await quality.set_link_quality(
        client,
        "/Lab 1.unl",
        node_id=48,
        interface="Gi0/1",
        delay=11,
        jitter=11,
        loss=11,
        bandwidth=11,
        # far_delay/far_jitter/far_loss/far_bandwidth deliberately omitted
    )

    sent_payload = client.set_link_quality.await_args.args[1]
    assert sent_payload["destination_delay"] == 5
    assert sent_payload["destination_jitter"] == 6
    assert sent_payload["destination_loss"] == 7
    assert sent_payload["destination_bandwidth"] == 8
    assert result["status"] == "success"


async def test_set_link_quality_far_override_takes_precedence_over_current() -> None:
    topology_with_existing_far_quality = [
        {
            **NODE_TO_NODE_TOPOLOGY[0],
            "destination_delay": 5,
            "destination_jitter": 6,
            "destination_loss": 7,
            "destination_bandwidth": 8,
        }
    ]
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": topology_with_existing_far_quality},
        set_link_quality={"status": "success"},
    )
    client.get_node_interfaces.side_effect = [
        node_interfaces("Gi0/0", "Gi0/1"),
        node_interfaces("Gi1", "Gi2"),
    ]

    await quality.set_link_quality(
        client,
        "/Lab 1.unl",
        node_id=48,
        interface="Gi0/1",
        delay=11,
        # Only overriding jitter -- delay/loss/bandwidth on the far side
        # should still come from the current (topology) values, not 0.
        far_jitter=99,
    )

    sent_payload = client.set_link_quality.await_args.args[1]
    assert sent_payload["destination_jitter"] == 99  # overridden
    assert sent_payload["destination_delay"] == 5  # untouched, read from topology
    assert sent_payload["destination_loss"] == 7
    assert sent_payload["destination_bandwidth"] == 8


# -- node-to-network connection: matches the bridge-side capture -------------
#
# Ground truth:
# {"source_label":"e1","source_delay":33,"source_jitter":33,"source_loss":33,
#  "source_bandwidth":33,"destination_label":"","destination_delay":0,
#  "destination_jitter":0,"destination_loss":0,"destination_bandwidth":0,
#  "source":"39","destination":"network10","source_interfaceId":1,
#  "destination_interfaceId":"network","save":1}


NODE_TO_NETWORK_TOPOLOGY = [
    {
        "type": "ethernet",
        "source": "node39",
        "source_type": "node",
        "source_label": "e1",
        "destination": "network10",
        "destination_type": "network",
        "destination_label": "",
    }
]


async def test_set_link_quality_node_to_network_forces_far_side_to_zero() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": NODE_TO_NETWORK_TOPOLOGY},
        set_link_quality={"status": "success"},
    )
    client.get_node_interfaces.return_value = node_interfaces("e0", "e1")

    result = await quality.set_link_quality(
        client,
        "/Lab 1.unl",
        node_id=39,
        interface="e1",
        delay=33,
        jitter=33,
        loss=33,
        bandwidth=33,
        # No far_* supplied -- and none needed, since the far side is a network.
    )

    client.set_link_quality.assert_awaited_once_with(
        "/Lab 1.unl",
        {
            "source_label": "e1",
            "source_delay": 33,
            "source_jitter": 33,
            "source_loss": 33,
            "source_bandwidth": 33,
            "destination_label": "",
            "destination_delay": 0,
            "destination_jitter": 0,
            "destination_loss": 0,
            "destination_bandwidth": 0,
            "source": "39",
            "destination": "network10",
            "source_interfaceId": 1,
            "destination_interfaceId": "network",
            "save": 1,
        },
    )
    assert result["status"] == "success"
    # Only one get_node_interfaces call -- no attempt to resolve a far-side
    # node interface, since the far side is a network.
    client.get_node_interfaces.assert_called_once()


async def test_set_link_quality_notes_and_drops_far_values_for_network_side() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": NODE_TO_NETWORK_TOPOLOGY},
        set_link_quality={"status": "success"},
    )
    client.get_node_interfaces.return_value = node_interfaces("e0", "e1")

    result = await quality.set_link_quality(
        client,
        "/Lab 1.unl",
        node_id=39,
        interface="e1",
        delay=33,
        jitter=33,
        loss=33,
        bandwidth=33,
        far_delay=99,  # should be dropped, not sent
    )

    sent_payload = client.set_link_quality.await_args.args[1]
    assert sent_payload["destination_delay"] == 0
    assert "ignored" in result["message"]


# -- interface not connected / not found -------------------------------------


async def test_set_link_quality_errors_when_interface_not_connected() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": NODE_TO_NODE_TOPOLOGY},
    )
    client.get_node_interfaces.return_value = node_interfaces("Gi0/0", "Gi0/1", "Gi0/2")

    result = await quality.set_link_quality(client, "/Lab 1.unl", node_id=48, interface="Gi0/2", delay=5)

    assert result["status"] == "error"
    assert "No existing connection" in result["message"]
    client.set_link_quality.assert_not_awaited()


async def test_set_link_quality_errors_on_unknown_interface_name() -> None:
    client = make_client(get_status=PRO_STATUS)
    client.get_node_interfaces.return_value = node_interfaces("Gi0/0", "Gi0/1")

    result = await quality.set_link_quality(client, "/Lab 1.unl", node_id=48, interface="Gi9/9", delay=5)

    assert result["status"] == "error"
    assert "Gi9/9" in result["message"]


# ============================================================================
# get_link_quality
# ============================================================================


GET_QUALITY_TOPOLOGY = [
    {
        "type": "ethernet",
        "source": "node48",
        "source_type": "node",
        "source_label": "Gi0/1",
        "destination": "node36",
        "destination_type": "node",
        "destination_label": "Gi2",
        "network_id": 1,
        "source_delay": 11,
        "source_jitter": 12,
        "source_loss": 13,
        "source_bandwidth": 14,
        "destination_delay": 21,
        "destination_jitter": 22,
        "destination_loss": 23,
        "destination_bandwidth": 24,
    }
]

GET_QUALITY_NODE_TO_NETWORK_TOPOLOGY = [
    {
        "type": "ethernet",
        "source": "node39",
        "source_type": "node",
        "source_label": "e1",
        "destination": "network10",
        "destination_type": "network",
        "destination_label": "",
        "source_delay": 5,
        "source_jitter": 6,
        "source_loss": 7,
        "source_bandwidth": 8,
    }
]


async def test_get_link_quality_refuses_on_community() -> None:
    client = make_client(get_status=COMMUNITY_STATUS)

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_id=48, interface="Gi0/1")

    assert result["status"] == "error"
    assert "Community" in result["message"]
    client.get_lab_topology.assert_not_awaited()


async def test_get_link_quality_requires_exactly_one_of_node_id_or_node_name() -> None:
    client = make_client(get_status=PRO_STATUS)

    neither = await quality.get_link_quality(client, "/Lab 1.unl", interface="Gi0/1")
    both = await quality.get_link_quality(client, "/Lab 1.unl", node_id=48, node_name="foo", interface="Gi0/1")

    assert neither["status"] == "error"
    assert both["status"] == "error"


async def test_get_link_quality_node_to_node_reads_both_sides() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": GET_QUALITY_TOPOLOGY},
    )
    client.get_node_interfaces.return_value = node_interfaces("Gi0/0", "Gi0/1")

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_id=48, interface="Gi0/1")

    assert result["status"] == "success"
    near = result["data"]["near"]
    far = result["data"]["far"]
    assert near == {
        "node_id": 48,
        "interface": "Gi0/1",
        "delay": 11,
        "jitter": 12,
        "loss": 13,
        "bandwidth": 14,
        "settable": True,
    }
    assert far == {
        "node_id": 36,
        "interface": "Gi2",
        "delay": 21,
        "jitter": 22,
        "loss": 23,
        "bandwidth": 24,
        "settable": True,
    }


async def test_get_link_quality_by_numeric_interface_index() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": GET_QUALITY_TOPOLOGY},
    )
    client.get_node_interfaces.return_value = node_interfaces("Gi0/0", "Gi0/1")

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_id=48, interface="1")

    assert result["status"] == "success"
    assert result["data"]["near"]["interface"] == "Gi0/1"


async def test_get_link_quality_node_to_network_reports_settable_false_and_zero() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": GET_QUALITY_NODE_TO_NETWORK_TOPOLOGY},
        list_lab_networks={"status": "success", "data": {"id": 10, "name": "Bridge1", "type": "bridge"}},
    )
    client.get_node_interfaces.return_value = node_interfaces("e0", "e1")

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_id=39, interface="e1")

    assert result["status"] == "success"
    near = result["data"]["near"]
    far = result["data"]["far"]
    assert near["settable"] is True
    assert near["delay"] == 5
    assert far["settable"] is False
    assert far["delay"] == 0 and far["jitter"] == 0 and far["loss"] == 0 and far["bandwidth"] == 0
    assert far["network"] == "Bridge1"
    client.list_lab_networks.assert_awaited_once_with("/Lab 1.unl", 10)


async def test_get_link_quality_node_to_network_falls_back_to_token_if_name_unavailable() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": GET_QUALITY_NODE_TO_NETWORK_TOPOLOGY},
        list_lab_networks={"status": "error", "data": None},
    )
    client.get_node_interfaces.return_value = node_interfaces("e0", "e1")

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_id=39, interface="e1")

    assert result["status"] == "success"
    assert result["data"]["far"]["network"] == "network10"


async def test_get_link_quality_by_node_name_single_match() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": GET_QUALITY_TOPOLOGY},
        list_lab_nodes={"status": "success", "data": {"48": {"id": 48, "name": "R1-Core"}}},
    )
    client.get_node_interfaces.return_value = node_interfaces("Gi0/0", "Gi0/1")

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_name="core", interface="Gi0/1")

    assert result["status"] == "success"
    assert result["data"]["near"]["node_id"] == 48


async def test_get_link_quality_by_node_name_no_match() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        list_lab_nodes={"status": "success", "data": {"48": {"id": 48, "name": "R1-Core"}}},
    )

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_name="nonexistent", interface="Gi0/1")

    assert result["status"] == "error"
    assert "No node matches" in result["message"]


async def test_get_link_quality_by_node_name_multiple_matches_needs_selection() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        list_lab_nodes={
            "status": "success",
            "data": {
                "48": {"id": 48, "name": "R1-Core"},
                "49": {"id": 49, "name": "R2-Core"},
            },
        },
    )

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_name="core", interface="Gi0/1")

    assert result["status"] == "selection_required"
    assert len(result["data"]["matches"]) == 2
    client.get_lab_topology.assert_not_awaited()


async def test_get_link_quality_errors_when_interface_not_connected() -> None:
    client = make_client(
        get_status=PRO_STATUS,
        get_lab_topology={"status": "success", "data": GET_QUALITY_TOPOLOGY},
    )
    client.get_node_interfaces.return_value = node_interfaces("Gi0/0", "Gi0/1", "Gi0/2")

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_id=48, interface="Gi0/2")

    assert result["status"] == "error"
    assert "No existing connection" in result["message"]


async def test_get_link_quality_errors_on_unknown_interface_name() -> None:
    client = make_client(get_status=PRO_STATUS)
    client.get_node_interfaces.return_value = node_interfaces("Gi0/0", "Gi0/1")

    result = await quality.get_link_quality(client, "/Lab 1.unl", node_id=48, interface="Gi9/9")

    assert result["status"] == "error"
    assert "Gi9/9" in result["message"]
