from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_eveng.tools import nodes


def make_client(**method_returns) -> AsyncMock:
    client = AsyncMock()
    for name, value in method_returns.items():
        getattr(client, name).return_value = value
    return client


async def test_eve_list_lab_nodes_passes_optional_node_id() -> None:
    client = make_client(list_lab_nodes={"status": "success", "data": {}})

    await nodes.list_lab_nodes(client, "/User1/Lab 1.unl", 2)

    client.list_lab_nodes.assert_awaited_once_with("/User1/Lab 1.unl", 2)


async def test_list_lab_nodes_annotates_vendor_dict_shape() -> None:
    client = make_client(
        list_lab_nodes={
            "status": "success",
            "data": {"1": {"name": "R1", "template": "csr1000vng"}},
        },
        list_node_templates={
            "status": "success",
            "data": {"csr1000vng": "Cisco CSR 1000V (XE 16.x)"},
        },
    )

    result = await nodes.list_lab_nodes(client, "/User1/Lab 1.unl")

    assert result["data"]["1"]["vendor"] == "Cisco"
    assert result["data"]["1"]["name"] == "R1"


async def test_list_lab_nodes_annotates_vendor_single_node_shape() -> None:
    client = make_client(
        list_lab_nodes={
            "status": "success",
            "data": {"name": "R1", "template": "vjunosevo"},
        },
        list_node_templates={
            "status": "success",
            "data": {"vjunosevo": "Juniper vEVO Router"},
        },
    )

    result = await nodes.list_lab_nodes(client, "/User1/Lab 1.unl", 21)

    assert result["data"]["vendor"] == "Juniper"


async def test_list_lab_nodes_unknown_template_gets_unknown_vendor() -> None:
    client = make_client(
        list_lab_nodes={
            "status": "success",
            "data": {"1": {"name": "R1", "template": "nonexistent"}},
        },
        list_node_templates={"status": "success", "data": {}},
    )

    result = await nodes.list_lab_nodes(client, "/User1/Lab 1.unl")

    assert result["data"]["1"]["vendor"] == "Unknown"


# -- add_lab_node: template search -----------------------------------------


def _templates_data(*id_desc_pairs: tuple[str, str]) -> dict:
    return {"status": "success", "data": dict(id_desc_pairs)}


async def test_add_lab_node_requires_template_lookup_no_labs_call_when_no_templates() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data()

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="cisco")

    assert result["status"] == "cancelled"
    client.get_node_template.assert_not_awaited()
    client.add_lab_node.assert_not_awaited()


async def test_add_lab_node_empty_search_lists_every_template() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(
        ("csr1000vng", "Cisco CSR 1000V (XE 16.x)"),
        ("vjunosevo", "Juniper vEVO Router"),
    )

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl")

    assert result["status"] == "selection_required"
    assert "Cisco" in result["message"]
    assert "Juniper" in result["message"]
    client.add_lab_node.assert_not_awaited()


async def test_add_lab_node_search_no_match_is_cancelled() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("csr1000vng", "Cisco CSR 1000V (XE 16.x)"))

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="juniper")

    assert result["status"] == "cancelled"
    assert "juniper" in result["message"]


async def test_add_lab_node_search_by_vendor_single_match_proceeds_without_prompt() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("vjunosevo", "Juniper vEVO Router"))
    client.get_node_template.return_value = {
        "status": "success",
        "data": {"type": "qemu", "options": {"image": {"value": "x", "list": {"x": "x"}}}},
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="juniper")

    client.get_node_template.assert_awaited_once_with("vjunosevo")
    assert result["status"] == "success"


async def test_add_lab_node_search_multiple_matches_requires_selection() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(
        ("csr1000vng", "Cisco CSR 1000V (XE 16.x)"),
        ("c8000v", "Cisco Catalyst 8000v"),
    )

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="cisco")

    assert result["status"] == "selection_required"
    assert len(result["data"]["matches"]) == 2
    client.get_node_template.assert_not_awaited()


async def test_add_lab_node_selection_by_number_resolves_template() -> None:
    client = AsyncMock()
    # Different vendors -> unambiguous sort order ("Arista" < "Cisco"), so
    # choice "2" deterministically means the second (Cisco) entry. Empty
    # search matches both (the mock only contains these two templates).
    client.list_node_templates.return_value = _templates_data(
        ("veos", "Arista vEOS Router"),
        ("csr1000vng", "Cisco CSR 1000V (XE 16.x)"),
    )
    client.get_node_template.return_value = {
        "status": "success",
        "data": {"type": "qemu", "options": {}},
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="", selection="2")

    client.get_node_template.assert_awaited_once_with("csr1000vng")
    assert client.add_lab_node.await_args.kwargs["template"] == "csr1000vng"


async def test_add_lab_node_selection_by_exact_id_resolves_template() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(
        ("c8000v", "Cisco Catalyst 8000v"),
        ("csr1000vng", "Cisco CSR 1000V (XE 16.x)"),
    )
    client.get_node_template.return_value = {
        "status": "success",
        "data": {"type": "qemu", "options": {}},
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="cisco", selection="csr1000vng")

    client.get_node_template.assert_awaited_once_with("csr1000vng")
    assert client.add_lab_node.await_args.kwargs["template"] == "csr1000vng"


async def test_add_lab_node_selection_by_exact_name_resolves_template() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(
        ("c8000v", "Cisco Catalyst 8000v"),
        ("csr1000vng", "Cisco CSR 1000V (XE 16.x)"),
    )
    client.get_node_template.return_value = {
        "status": "success",
        "data": {"type": "qemu", "options": {}},
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="cisco", selection="Cisco Catalyst 8000v")

    client.get_node_template.assert_awaited_once_with("c8000v")


async def test_add_lab_node_invalid_selection_is_error() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(
        ("c8000v", "Cisco Catalyst 8000v"),
        ("csr1000vng", "Cisco CSR 1000V (XE 16.x)"),
    )

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="cisco", selection="zzz")

    assert result["status"] == "error"
    client.get_node_template.assert_not_awaited()
    client.add_lab_node.assert_not_awaited()


async def test_add_lab_node_templates_without_image_are_excluded_from_search() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(
        ("asa", "Cisco ASA.hided"),  # no image -- must be excluded
        ("c8000v", "Cisco Catalyst 8000v"),
    )
    client.get_node_template.return_value = {
        "status": "success",
        "data": {"type": "qemu", "options": {}},
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="cisco")

    # Only one has an image -- proceeds directly, never mentions "asa".
    assert result["status"] == "success"
    client.get_node_template.assert_awaited_once_with("c8000v")


# -- add_lab_node: template defaults, image selection, extra fields (unchanged behavior) --


async def test_add_lab_node_fills_defaults_from_template() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("vjunosevo", "Juniper vEVO Router"))
    client.get_node_template.return_value = {
        "status": "success",
        "data": {
            "type": "qemu",
            "description": "Juniper vEVO Router",
            "options": {
                "name": {"value": "vEVO"},
                "console": {"value": "vnc"},
                "icon": {"value": "Juniper-2D-Router-S.svg"},
                "ram": {"value": 4096},
                "cpu": {"value": 2},
                "ethernet": {"value": 6},
                "image": {"value": "vjunosevo-24.2R1", "list": {"vjunosevo-24.2R1": "vjunosevo-24.2R1"}},
            },
        },
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="vjunosevo")

    client.get_node_template.assert_awaited_once_with("vjunosevo")
    client.add_lab_node.assert_awaited_once_with(
        "/User1/Lab 1.unl",
        node_type="qemu",
        template="vjunosevo",
        name="vEVO",
        image="vjunosevo-24.2R1",
        config="Unconfigured",
        icon="Juniper-2D-Router-S.svg",
        left="100",
        top="100",
        ram=4096,
        console="vnc",
        cpu=2,
        ethernet=6,
        extra={},
    )


async def test_add_lab_node_explicit_args_win_over_template_defaults() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("vjunosevo", "Juniper vEVO Router"))
    client.get_node_template.return_value = {
        "status": "success",
        "data": {
            "type": "qemu",
            "options": {
                "console": {"value": "vnc"},
                "ram": {"value": 4096},
                "cpu": {"value": 2},
                "image": {"value": "default-image", "list": {"default-image": "default-image"}},
            },
        },
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(
        client,
        "/User1/Lab 1.unl",
        template="vjunosevo",
        console="telnet",
        ram=2048,
        cpu=1,
        image="custom-image",
        left="500",
        top="500",
    )

    call = client.add_lab_node.await_args
    assert call.kwargs["console"] == "telnet"
    assert call.kwargs["ram"] == 2048
    assert call.kwargs["cpu"] == 1
    assert call.kwargs["image"] == "custom-image"
    assert call.kwargs["left"] == "500"
    assert call.kwargs["top"] == "500"


async def test_add_lab_node_single_image_does_not_prompt() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("linux", "Linux"))
    client.get_node_template.return_value = {
        "status": "success",
        "data": {"type": "qemu", "options": {"image": {"list": {"only-image": "only-image"}}}},
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="linux")

    client.add_lab_node.assert_awaited_once()
    assert client.add_lab_node.await_args.kwargs["image"] == "only-image"
    assert result["status"] == "success"


async def test_add_lab_node_multiple_images_prompts_instead_of_guessing() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("linux", "Linux"))
    client.get_node_template.return_value = {
        "status": "success",
        "data": {
            "type": "qemu",
            "options": {
                "image": {
                    "value": "linux-ubuntu-22.04-server",
                    "list": {
                        "linux-ubuntu-22.04-server": "linux-ubuntu-22.04-server",
                        "linux-alpine-3.21.3": "linux-alpine-3.21.3",
                    },
                }
            },
        },
    }

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="linux")

    client.add_lab_node.assert_not_awaited()
    assert result["status"] == "selection_required"
    assert "linux-ubuntu-22.04-server" in result["message"]
    assert "linux-alpine-3.21.3" in result["message"]
    assert set(result["data"]["images"]) == {"linux-ubuntu-22.04-server", "linux-alpine-3.21.3"}


async def test_add_lab_node_multiple_images_but_image_given_does_not_prompt() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("linux", "Linux"))
    client.get_node_template.return_value = {
        "status": "success",
        "data": {
            "type": "qemu",
            "options": {
                "image": {
                    "list": {
                        "linux-ubuntu-22.04-server": "linux-ubuntu-22.04-server",
                        "linux-alpine-3.21.3": "linux-alpine-3.21.3",
                    }
                }
            },
        },
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    result = await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="linux", image="linux-alpine-3.21.3")

    client.add_lab_node.assert_awaited_once()
    assert client.add_lab_node.await_args.kwargs["image"] == "linux-alpine-3.21.3"
    assert result["status"] == "success"


async def test_add_lab_node_node_type_defaults_from_template() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("iol", "Cisco IOL"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "iol", "options": {}}}
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="iol")

    assert client.add_lab_node.await_args.kwargs["node_type"] == "iol"


async def test_add_lab_node_never_forwards_bare_none_for_left_or_top() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2")

    call = client.add_lab_node.await_args.kwargs
    assert call["left"] is not None
    assert call["top"] is not None


async def test_add_lab_node_left_and_top_still_overridable_via_tool() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2", left="35%", top="25%")

    call = client.add_lab_node.await_args.kwargs
    assert call["left"] == "35%"
    assert call["top"] == "25%"
    client.list_lab_nodes.assert_not_awaited()  # no need to compute placement


async def test_add_lab_node_missing_template_data_falls_back_to_safe_defaults() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("unknown", "Something Unknown"))
    client.get_node_template.return_value = {"status": "success", "data": {}}
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="unknown")

    call = client.add_lab_node.await_args.kwargs
    assert call["node_type"] == "qemu"
    assert call["console"] == "telnet"
    assert call["cpu"] == 1
    assert call["icon"] == "Router.png"
    assert call["extra"] == {}


async def test_add_lab_node_forwards_extra_qemu_fields_to_client() -> None:
    # End-to-end regression for the live bug: vmx crashed (500, no JSON
    # body) when qemu_version/qemu_arch/qemu_nic/qemu_options were
    # omitted, even with image/ram/cpu/ethernet all supplied explicitly.
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("vmx", "Juniper vMX"))
    client.get_node_template.return_value = {
        "status": "success",
        "data": {
            "type": "qemu",
            "options": {
                "qemu_version": {"value": "2.4.0"},
                "qemu_arch": {"value": "x86_64"},
                "qemu_nic": {"value": "", "list": {"": "tpl(e1000)"}},
                "qemu_options": {"value": "-machine type=pc,accel=kvm -cpu host"},
            },
        },
    }
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(
        client,
        "/User1/Lab 1.unl",
        template="vmx",
        image="vmx-14.1.R1",
        ram=2048,
        cpu=1,
        ethernet=12,
    )

    extra = client.add_lab_node.await_args.kwargs["extra"]
    assert extra["qemu_version"] == "2.4.0"
    assert extra["qemu_arch"] == "x86_64"
    assert extra["qemu_nic"] == "e1000"
    assert extra["qemu_options"] == "-machine type=pc,accel=kvm -cpu host"


# -- add_lab_node: canvas auto-placement ---------------------------------------


def _existing_nodes(*positions: tuple[int, int]) -> dict:
    return {
        "status": "success",
        "data": {str(i): {"left": left, "top": top} for i, (left, top) in enumerate(positions)},
    }


async def test_add_lab_node_first_node_placed_at_start_position() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = _existing_nodes()  # empty lab
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2")

    call = client.add_lab_node.await_args.kwargs
    assert call["left"] == "100"
    assert call["top"] == "100"


async def test_add_lab_node_second_node_placed_100_to_the_right() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = _existing_nodes((100, 100))
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2")

    call = client.add_lab_node.await_args.kwargs
    assert call["left"] == "200"
    assert call["top"] == "100"


async def test_add_lab_node_sixth_node_wraps_to_new_row() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = _existing_nodes((100, 100), (200, 100), (300, 100), (400, 100), (500, 100))
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2")

    call = client.add_lab_node.await_args.kwargs
    assert call["left"] == "100"
    assert call["top"] == "200"


async def test_add_lab_node_skips_slot_too_close_to_existing_node() -> None:
    # A node sitting at (120, 110) is within the 50-unit gap of the (100,
    # 100) grid slot on both axes, so that slot must be skipped in favor
    # of the next one.
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = _existing_nodes((120, 110))
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2")

    call = client.add_lab_node.await_args.kwargs
    assert (call["left"], call["top"]) != ("100", "100")
    assert call["left"] == "200"
    assert call["top"] == "100"


async def test_add_lab_node_does_not_skip_slot_far_enough_from_existing_node() -> None:
    # A node at (500, 500) is nowhere near the (100, 100) grid slot -- must
    # not cause any skipping.
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = _existing_nodes((500, 500))
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2")

    call = client.add_lab_node.await_args.kwargs
    assert call["left"] == "100"
    assert call["top"] == "100"


async def test_add_lab_node_placement_ignores_nodes_with_unparseable_positions() -> None:
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"1": {"left": None, "top": None}},
    }
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2")

    call = client.add_lab_node.await_args.kwargs
    assert call["left"] == "100"
    assert call["top"] == "100"


async def test_add_lab_node_placement_handles_single_node_response_shape() -> None:
    # list_lab_nodes with a node_id returns the node dict directly, not
    # wrapped in an outer id-keyed dict -- placement must still work.
    client = AsyncMock()
    client.list_node_templates.return_value = _templates_data(("viosl2", "Cisco vIOS Switch"))
    client.get_node_template.return_value = {"status": "success", "data": {"type": "qemu", "options": {}}}
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "R1", "template": "viosl2", "left": 100, "top": 100},
    }
    client.add_lab_node.return_value = {"status": "success"}

    await nodes.add_lab_node(client, "/User1/Lab 1.unl", template="viosl2")

    call = client.add_lab_node.await_args.kwargs
    assert call["left"] == "200"
    assert call["top"] == "100"


def test_grid_positions_order() -> None:
    gen = nodes._grid_positions()
    first_row = [next(gen) for _ in range(5)]
    assert first_row == [(100, 100), (200, 100), (300, 100), (400, 100), (500, 100)]
    second_row = [next(gen) for _ in range(2)]
    assert second_row == [(100, 200), (200, 200)]


def test_position_is_free() -> None:
    existing = [(100, 100)]
    assert nodes._position_is_free((200, 100), existing) is True
    assert nodes._position_is_free((120, 110), existing) is False
    assert nodes._position_is_free((100, 100), existing) is False


async def test_eve_start_node_all_nodes_when_id_omitted_loops_individually() -> None:
    # Regression test: bulk start/stop confirmed unreliable live on a PRO
    # server (500 on bulk stop; bulk start silently no-opped for one node
    # while reporting success) -- must loop per-node, never call
    # client.start_node(lab_path, None).
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {
            "1": {"id": 1, "name": "RTR-101"},
            "2": {"id": 2, "name": "RTR-102"},
        },
    }
    client.start_node.return_value = {"status": "success"}

    result = await nodes.start_node(client, "/User1/Lab 1.unl")

    assert client.start_node.await_count == 2
    client.start_node.assert_any_await("/User1/Lab 1.unl", 1)
    client.start_node.assert_any_await("/User1/Lab 1.unl", 2)
    # Never the bulk (node_id=None) call.
    for call in client.start_node.await_args_list:
        assert call.args[1] is not None
    assert result["status"] == "success"
    assert "RTR-101" in result["message"]
    assert "RTR-102" in result["message"]


async def test_eve_start_node_single_node() -> None:
    client = make_client(start_node={"status": "success"})

    await nodes.start_node(client, "/User1/Lab 1.unl", 1)

    client.start_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)
    client.list_lab_nodes.assert_not_awaited()


async def test_eve_stop_node_all_nodes_when_id_omitted_loops_individually() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"1": {"id": 1, "name": "RTR-101"}},
    }
    client.stop_node.return_value = {"status": "success"}

    result = await nodes.stop_node(client, "/User1/Lab 1.unl")

    client.stop_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)
    assert result["status"] == "success"


async def test_eve_start_node_all_nodes_no_nodes_in_lab_is_cancelled() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}

    result = await nodes.start_node(client, "/User1/Lab 1.unl")

    assert result["status"] == "cancelled"
    client.start_node.assert_not_awaited()


async def test_eve_start_node_all_nodes_one_failure_does_not_block_others() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {
            "1": {"id": 1, "name": "RTR-101"},
            "2": {"id": 2, "name": "RTR-102"},
            "3": {"id": 3, "name": "vIOS-SW1"},
        },
    }

    async def _start(lab_path: str, node_id: int):
        if node_id == 2:
            raise RuntimeError("Request not valid (60027)")
        return {"status": "success"}

    client.start_node.side_effect = _start

    result = await nodes.start_node(client, "/User1/Lab 1.unl")

    # All three attempted, despite node 2 failing.
    assert client.start_node.await_count == 3
    assert result["status"] == "success"  # partial success: 2 of 3 succeeded
    assert "RTR-101" in result["message"]
    assert "vIOS-SW1" in result["message"]
    assert "RTR-102" in result["message"]
    assert "Request not valid" in result["message"]


async def test_eve_start_node_all_nodes_every_failure_is_error_status() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"1": {"id": 1, "name": "RTR-101"}},
    }
    client.start_node.side_effect = RuntimeError("Request not valid (60027)")

    result = await nodes.start_node(client, "/User1/Lab 1.unl")

    assert result["status"] == "error"


async def test_eve_stop_wipe_delegate_correctly() -> None:
    client = make_client(
        stop_node={"status": "success"},
        wipe_node={"status": "success"},
    )

    await nodes.stop_node(client, "/User1/Lab 1.unl", 1)
    await nodes.wipe_node(client, "/User1/Lab 1.unl", 1)

    client.stop_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)
    client.wipe_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)


# -- export_node: PRO-only, edition-gated -----------------------------


async def test_export_node_delegates_on_pro() -> None:
    client = make_client(export_node={"status": "success"})
    client.get_status.return_value = {"status": "success", "data": {"version": "6.5.0-27-PRO"}}

    result = await nodes.export_node(client, "/User1/Lab 1.unl", 1)

    client.export_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)
    assert result["status"] == "success"


async def test_export_node_rejects_immediately_on_community_edition() -> None:
    # PRO-only, per EVE-NG's own official comparison page and
    # confirmed live to fail unconditionally on Community -- must reject
    # before ever calling the underlying client method.
    client = AsyncMock()
    client.get_status.return_value = {"status": "success", "data": {"version": "6.2.0-4"}}

    result = await nodes.export_node(client, "/User1/Lab 1.unl", 1)

    assert result["status"] == "error"
    assert "community" in result["message"].lower()
    client.export_node.assert_not_awaited()


async def test_export_node_rejects_on_missing_version_conservatively() -> None:
    client = AsyncMock()
    client.get_status.return_value = {"status": "success", "data": {}}

    result = await nodes.export_node(client, "/User1/Lab 1.unl", 1)

    assert result["status"] == "error"
    client.export_node.assert_not_awaited()


async def test_export_node_all_nodes_delegates_on_pro() -> None:
    client = make_client(export_node={"status": "success"})
    client.get_status.return_value = {"status": "success", "data": {"version": "6.5.0-27-PRO"}}

    await nodes.export_node(client, "/User1/Lab 1.unl")

    client.export_node.assert_awaited_once_with("/User1/Lab 1.unl", None)


async def test_eve_get_node_interfaces_passes_ids() -> None:
    client = make_client(get_node_interfaces={"status": "success", "data": {}})

    await nodes.get_node_interfaces(client, "/User1/Lab 1.unl", 3)

    client.get_node_interfaces.assert_awaited_once_with("/User1/Lab 1.unl", 3)


# -- connect_interface: interface resolution --------------------------------


def test_available_ethernet_interfaces_finds_unconnected_ones() -> None:
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 1},
            {"name": "Gi0/1", "network_id": 0},
            {"name": "Gi0/2", "network_id": 0},
        ]
    }
    available = nodes._available_ethernet_interfaces(data)
    assert [index for index, _ in available] == [1, 2]


def test_available_ethernet_interfaces_all_connected_returns_empty() -> None:
    data = {"ethernet": [{"name": "Gi0/0", "network_id": 1}, {"name": "Gi0/1", "network_id": 2}]}
    assert nodes._available_ethernet_interfaces(data) == []


def test_available_ethernet_interfaces_treats_string_zero_as_free() -> None:
    data = {"ethernet": [{"name": "Gi0/0", "network_id": "0"}]}
    available = nodes._available_ethernet_interfaces(data)
    assert [index for index, _ in available] == [0]


def test_available_ethernet_interfaces_missing_or_malformed_data() -> None:
    assert nodes._available_ethernet_interfaces({}) == []
    assert nodes._available_ethernet_interfaces({"ethernet": "not-a-list"}) == []
    assert nodes._available_ethernet_interfaces({"ethernet": []}) == []


def test_resolve_interface_selection_explicit_int_in_range() -> None:
    data = {"ethernet": [{"name": "Gi0/0"}, {"name": "Gi0/1"}]}
    result = nodes._resolve_interface_selection(data, 1, "")
    assert result == {"index": 1}


def test_resolve_interface_selection_explicit_int_out_of_range() -> None:
    data = {"ethernet": [{"name": "Gi0/0"}]}
    result = nodes._resolve_interface_selection(data, 5, "")
    assert result["status"] == "error"
    assert "out of range" in result["message"]


def test_resolve_interface_selection_digit_string_treated_as_literal_index() -> None:
    data = {"ethernet": [{"name": "eth0"}, {"name": "eth1"}]}
    result = nodes._resolve_interface_selection(data, "1", "")
    assert result == {"index": 1}


def test_resolve_interface_selection_digit_string_out_of_range() -> None:
    data = {"ethernet": [{"name": "eth0"}]}
    result = nodes._resolve_interface_selection(data, "5", "")
    assert result["status"] == "error"
    assert "out of range" in result["message"]


def test_resolve_interface_selection_no_available_interfaces_errors() -> None:
    data = {"ethernet": [{"name": "Gi0/0", "network_id": 1}]}
    result = nodes._resolve_interface_selection(data, None, "")
    assert result["status"] == "error"
    assert "no available" in result["message"]


def test_resolve_interface_selection_none_single_available_resolves_directly() -> None:
    # Never auto-picks by default when there's a choice -- but with only
    # one available interface, there's no actual choice to make, so no
    # prompt is needed.
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 1},
            {"name": "Gi0/1", "network_id": 0},
        ]
    }
    result = nodes._resolve_interface_selection(data, None, "")
    assert result == {"index": 1}


def test_resolve_interface_selection_none_multiple_available_requires_selection() -> None:
    # This is the actual "no auto-pick-first-available" behavior change:
    # multiple free interfaces and no interface given must prompt, not
    # silently pick one.
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 0},
            {"name": "Gi0/1", "network_id": 0},
        ]
    }
    result = nodes._resolve_interface_selection(data, None, "")
    assert result["status"] == "selection_required"
    assert result["data"]["matches"] == ["Gi0/0 (index 0)", "Gi0/1 (index 1)"]


def test_resolve_interface_selection_search_single_match_resolves_directly() -> None:
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 0},
            {"name": "Gi0/1", "network_id": 0},
        ]
    }
    result = nodes._resolve_interface_selection(data, "gi0/1", "")
    assert result == {"index": 1}


def test_resolve_interface_selection_search_is_case_insensitive_substring() -> None:
    data = {"ethernet": [{"name": "GigabitEthernet0/0", "network_id": 0}]}
    result = nodes._resolve_interface_selection(data, "gigabit", "")
    assert result == {"index": 0}


def test_resolve_interface_selection_search_scoped_to_available_only() -> None:
    # A connected interface matching the search string must not show up
    # -- it isn't a valid target either way.
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 5},
            {"name": "Gi0/1", "network_id": 0},
        ]
    }
    result = nodes._resolve_interface_selection(data, "gi0", "")
    assert result == {"index": 1}


def test_resolve_interface_selection_search_no_match_errors() -> None:
    data = {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}
    result = nodes._resolve_interface_selection(data, "Gi0/9", "")
    assert result["status"] == "error"
    assert "no available ethernet interface" in result["message"]


def test_resolve_interface_selection_search_multiple_matches_requires_selection() -> None:
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 0},
            {"name": "Gi0/1", "network_id": 0},
            {"name": "Se1/0", "network_id": 0},
        ]
    }
    result = nodes._resolve_interface_selection(data, "gi", "")
    assert result["status"] == "selection_required"
    assert result["data"]["matches"] == ["Gi0/0 (index 0)", "Gi0/1 (index 1)"]


def test_resolve_interface_selection_selection_by_number() -> None:
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 0},
            {"name": "Gi0/1", "network_id": 0},
        ]
    }
    result = nodes._resolve_interface_selection(data, "gi", "2")
    assert result == {"index": 1}


def test_resolve_interface_selection_selection_by_exact_name() -> None:
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 0},
            {"name": "Gi0/1", "network_id": 0},
        ]
    }
    result = nodes._resolve_interface_selection(data, "gi", "Gi0/1")
    assert result == {"index": 1}


def test_resolve_interface_selection_invalid_selection_is_error() -> None:
    data = {
        "ethernet": [
            {"name": "Gi0/0", "network_id": 0},
            {"name": "Gi0/1", "network_id": 0},
        ]
    }
    result = nodes._resolve_interface_selection(data, "gi", "zzz")
    assert result["status"] == "error"
    assert "Could not match" in result["message"]


# -- connect_interface: PRO/Community edition helpers --------------------------


async def test_ensure_stopped_for_connection_noop_on_pro() -> None:
    client = AsyncMock()

    stopped = await nodes._ensure_stopped_for_connection(client, "/User1/Lab 1.unl", 1, True)

    assert stopped is False
    client.list_lab_nodes.assert_not_awaited()
    client.stop_node.assert_not_awaited()


async def test_ensure_stopped_for_connection_stops_running_node_on_community() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"status": 2}}

    stopped = await nodes._ensure_stopped_for_connection(client, "/User1/Lab 1.unl", 1, False)

    assert stopped is True
    client.stop_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)


async def test_ensure_stopped_for_connection_leaves_stopped_node_alone_on_community() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"status": 0}}

    stopped = await nodes._ensure_stopped_for_connection(client, "/User1/Lab 1.unl", 1, False)

    assert stopped is False
    client.stop_node.assert_not_awaited()


# -- connect_interface: network-ready polling (works around a confirmed --
# EVE-NG timing bug where a just-created network isn't immediately usable)


async def test_wait_for_network_ready_true_when_present_in_dict_shape() -> None:
    client = AsyncMock()
    client.list_lab_networks.return_value = {"status": "success", "data": {"7": {"id": 7}}}

    ready = await nodes._wait_for_network_ready(client, "/User1/Lab 1.unl", 7)

    assert ready is True
    client.list_lab_networks.assert_awaited_once()


async def test_wait_for_network_ready_true_when_present_in_list_shape() -> None:
    client = AsyncMock()
    client.list_lab_networks.return_value = {"status": "success", "data": [{"id": 7}]}

    ready = await nodes._wait_for_network_ready(client, "/User1/Lab 1.unl", 7)

    assert ready is True


async def test_wait_for_network_ready_retries_then_succeeds(monkeypatch) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(nodes.asyncio, "sleep", _fake_sleep)

    client = AsyncMock()
    client.list_lab_networks.side_effect = [
        {"status": "success", "data": {}},  # not ready yet
        {"status": "success", "data": {}},  # still not ready
        {"status": "success", "data": {"7": {"id": 7}}},  # ready on 3rd try
    ]

    ready = await nodes._wait_for_network_ready(client, "/User1/Lab 1.unl", 7)

    assert ready is True
    assert client.list_lab_networks.await_count == 3
    assert len(sleeps) == 2  # slept between attempts 1->2 and 2->3, not after success


async def test_wait_for_network_ready_gives_up_after_max_attempts(monkeypatch) -> None:
    async def _fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(nodes.asyncio, "sleep", _fake_sleep)

    client = AsyncMock()
    client.list_lab_networks.return_value = {"status": "success", "data": {}}

    ready = await nodes._wait_for_network_ready(client, "/User1/Lab 1.unl", 7, attempts=3)

    assert ready is False
    assert client.list_lab_networks.await_count == 3


async def test_connect_interface_reports_clear_error_when_network_never_ready(monkeypatch) -> None:
    async def _fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(nodes.asyncio, "sleep", _fake_sleep)

    client = _pro_client()
    client.get_node_interfaces.side_effect = [
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
    ]
    client.add_lab_network.return_value = {"status": "success", "data": {"id": 7}}
    client.list_lab_networks.return_value = {"status": "success", "data": {}}  # never shows up

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2)

    assert result["status"] == "error"
    assert "never showed up" in result["message"]
    client.set_node_interface.assert_not_awaited()


# -- connect_interface: node-to-node (creates a bridge, wires both sides) ----
#
# client.get_status is explicitly mocked to PRO in most of these, so the
# Community stop-first behavior (tested separately below) never triggers
# and doesn't muddy what each test is actually checking.


def _pro_client() -> AsyncMock:
    client = AsyncMock()
    client.get_status.return_value = {"status": "success", "data": {"version": "6.5.0-27-PRO"}}
    return client


async def test_connect_interface_requires_exactly_one_target() -> None:
    client = AsyncMock()

    neither = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1)
    assert neither["status"] == "error"

    both = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2, network_id=5)
    assert both["status"] == "error"

    client.get_node_interfaces.assert_not_awaited()
    client.get_status.assert_not_awaited()  # never even checked edition


async def test_connect_interface_multiple_available_requires_selection_end_to_end() -> None:
    # Integration-level regression test for the actual behavior change:
    # multiple free interfaces and no interface given must return
    # selection_required through the full function, without touching
    # anything else (edition check, network creation, wiring) -- same
    # side-effect-free-until-resolved discipline as an interface error.
    client = AsyncMock()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {
            "ethernet": [
                {"name": "Gi0/0", "network_id": 0},
                {"name": "Gi0/1", "network_id": 0},
            ]
        },
    }

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2)

    assert result["status"] == "selection_required"
    assert "Node 1" in result["message"]
    assert result["data"]["matches"] == ["Gi0/0 (index 0)", "Gi0/1 (index 1)"]
    client.get_node_interfaces.assert_awaited_once()  # never checked node 2's interfaces
    client.get_status.assert_not_awaited()
    client.add_lab_network.assert_not_awaited()


async def test_connect_interface_selection_by_number_resolves_end_to_end() -> None:
    client = _pro_client()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {
            "ethernet": [
                {"name": "Gi0/0", "network_id": 0},
                {"name": "Gi0/1", "network_id": 0},
            ]
        },
    }
    client.add_lab_network.return_value = {"status": "success", "data": {"id": 3}}
    client.list_lab_networks.return_value = {"status": "success", "data": {"3": {"id": 3}}}
    client.set_node_interface.return_value = {"status": "success"}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, interface_selection="2", network_id=3)

    assert result["status"] == "success"
    client.set_node_interface.assert_awaited_once_with("/User1/Lab 1.unl", 1, 1, 3)


async def test_connect_interface_node_to_node_omitted_interface_resolves_when_unambiguous() -> None:
    # No auto-pick-first-available anymore -- but with exactly one
    # available interface on each node, there's no actual ambiguity to
    # prompt about, so it still resolves directly.
    client = _pro_client()
    client.get_node_interfaces.side_effect = [
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
    ]
    client.add_lab_network.return_value = {"status": "success", "data": {"id": 7}}
    client.list_lab_networks.return_value = {"status": "success", "data": {"7": {"id": 7}}}
    client.set_node_interface.return_value = {"status": "success"}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2)

    client.add_lab_network.assert_awaited_once_with("/User1/Lab 1.unl", network_type="bridge", name="p2p_1_0_2_0")
    assert client.set_node_interface.await_args_list[0].args == ("/User1/Lab 1.unl", 1, 0, 7)
    assert client.set_node_interface.await_args_list[1].args == ("/User1/Lab 1.unl", 2, 0, 7)
    client.edit_lab_network.assert_awaited_once_with("/User1/Lab 1.unl", 7, visibility=0)
    assert result["status"] == "success"
    assert "node 1" in result["message"]
    assert "node 2" in result["message"]
    assert "Community" not in result["message"]  # PRO -- no stop note
    client.stop_node.assert_not_awaited()


async def test_connect_interface_node_to_node_explicit_interfaces() -> None:
    client = _pro_client()
    client.get_node_interfaces.side_effect = [
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0"}, {"name": "Gi0/1"}]}},
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0"}, {"name": "Gi0/1"}]}},
    ]
    client.add_lab_network.return_value = {"status": "success", "data": {"id": 3}}
    client.list_lab_networks.return_value = {"status": "success", "data": {"3": {"id": 3}}}
    client.set_node_interface.return_value = {"status": "success"}

    await nodes.connect_interface(
        client, "/User1/Lab 1.unl", 1, interface="Gi0/1", target_node_id=2, target_interface=0
    )

    client.add_lab_network.assert_awaited_once_with("/User1/Lab 1.unl", network_type="bridge", name="p2p_1_1_2_0")
    client.edit_lab_network.assert_awaited_once_with("/User1/Lab 1.unl", 3, visibility=0)


# -- connect_interface: explicit index into an already-connected interface -----
# Regression tests for a real reported issue: a weaker/smaller model was
# observed connecting interfaces it wasn't asked to, and sometimes leaving
# an interface disconnected entirely -- traced to explicit numeric indices
# silently overwriting an already-connected interface, since that path
# (unlike the search/omitted paths) was never checked against connection
# status at all.


async def test_connect_interface_explicit_index_already_connected_requires_confirmation() -> None:
    client = AsyncMock()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 5}, {"name": "Gi0/1", "network_id": 0}]},
    }

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, interface=0, network_id=9)

    assert result["status"] == "confirmation_required"
    assert "Gi0/0" in result["message"]
    assert "network 5" in result["message"]
    # No side effects at all -- not even the edition check, matching the
    # same discipline as an interface-resolution error.
    client.get_status.assert_not_awaited()
    client.set_node_interface.assert_not_awaited()
    client.add_lab_network.assert_not_awaited()


async def test_connect_interface_explicit_index_already_connected_confirm_true_proceeds() -> None:
    client = _pro_client()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 5}]},
    }
    client.set_node_interface.return_value = {"status": "success"}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, interface=0, network_id=9, confirm=True)

    assert result["status"] == "success"
    client.set_node_interface.assert_awaited_once_with("/User1/Lab 1.unl", 1, 0, 9)


async def test_connect_interface_explicit_index_free_never_needs_confirmation() -> None:
    # Baseline: a genuinely free interface at an explicit index never
    # triggers the new check, confirm defaults to False and still works.
    client = _pro_client()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]},
    }
    client.set_node_interface.return_value = {"status": "success"}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, interface=0, network_id=9)

    assert result["status"] == "success"
    client.set_node_interface.assert_awaited_once_with("/User1/Lab 1.unl", 1, 0, 9)


async def test_connect_interface_target_explicit_index_already_connected_requires_confirmation() -> None:
    # Same check on the target node's side, node-to-node mode.
    client = AsyncMock()
    client.get_node_interfaces.side_effect = [
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
        {
            "status": "success",
            "data": {"ethernet": [{"name": "Gi0/0", "network_id": 7}, {"name": "Gi0/1", "network_id": 0}]},
        },
    ]

    result = await nodes.connect_interface(
        client, "/User1/Lab 1.unl", 1, interface=0, target_node_id=2, target_interface=0
    )

    assert result["status"] == "confirmation_required"
    assert "target" in result["message"].lower()
    assert "network 7" in result["message"]
    client.get_status.assert_not_awaited()
    client.set_node_interface.assert_not_awaited()
    client.add_lab_network.assert_not_awaited()


async def test_connect_interface_search_path_never_resolves_to_connected_interface() -> None:
    # The search/omitted paths are unaffected by this check entirely --
    # they can never resolve to an already-connected interface in the
    # first place, by construction, so no confirmation is ever needed there.
    client = _pro_client()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {
            "ethernet": [
                {"name": "Gi0/0", "network_id": 5},  # connected, excluded from search
                {"name": "Gi0/1", "network_id": 0},  # free, the only match
            ]
        },
    }
    client.set_node_interface.return_value = {"status": "success"}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, interface="gi", network_id=9)

    assert result["status"] == "success"
    client.set_node_interface.assert_awaited_once_with("/User1/Lab 1.unl", 1, 1, 9)


async def test_connect_interface_node_to_node_src_interface_error_stops_before_dst_lookup() -> None:
    client = AsyncMock()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 1}]},  # none free
    }

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2)

    assert result["status"] == "error"
    assert "Node 1" in result["message"]
    client.get_node_interfaces.assert_awaited_once()  # never checked node 2's interfaces
    client.get_status.assert_not_awaited()  # never even reached the edition check
    client.add_lab_network.assert_not_awaited()


async def test_connect_interface_node_to_node_dst_interface_error_never_stops_either_node() -> None:
    # Regression test for correct ordering: if the connection can't
    # proceed, neither node should ever be stopped as a side effect, even
    # on Community edition.
    client = AsyncMock()
    client.get_node_interfaces.side_effect = [
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 1}]}},  # none free
    ]

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2)

    assert result["status"] == "error"
    assert "Node 2" in result["message"]
    client.add_lab_network.assert_not_awaited()
    client.get_status.assert_not_awaited()
    client.stop_node.assert_not_awaited()


async def test_connect_interface_node_to_node_missing_network_id_in_response() -> None:
    client = _pro_client()
    client.get_node_interfaces.side_effect = [
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
    ]
    client.add_lab_network.return_value = {"status": "success", "data": {}}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2)

    assert result["status"] == "error"
    client.set_node_interface.assert_not_awaited()


async def test_connect_interface_community_edition_stops_running_nodes_first() -> None:
    client = AsyncMock()
    client.get_status.return_value = {"status": "success", "data": {"version": "6.5.0-27"}}
    client.get_node_interfaces.side_effect = [
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
    ]
    client.list_lab_nodes.side_effect = [
        {"status": "success", "data": {"status": 2}},  # node 1 running
        {"status": "success", "data": {"status": 0}},  # node 2 already stopped
    ]
    client.add_lab_network.return_value = {"status": "success", "data": {"id": 9}}
    client.list_lab_networks.return_value = {"status": "success", "data": {"9": {"id": 9}}}
    client.set_node_interface.return_value = {"status": "success"}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2)

    client.stop_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)  # only node 1
    assert result["status"] == "success"
    assert "Community edition" in result["message"]
    assert "stopped node(s) 1" in result["message"]


async def test_connect_interface_pro_edition_never_stops_running_nodes() -> None:
    client = _pro_client()
    client.get_node_interfaces.side_effect = [
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
        {"status": "success", "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]}},
    ]
    client.add_lab_network.return_value = {"status": "success", "data": {"id": 1}}
    client.list_lab_networks.return_value = {"status": "success", "data": {"1": {"id": 1}}}
    client.set_node_interface.return_value = {"status": "success"}

    await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, target_node_id=2)

    client.list_lab_nodes.assert_not_awaited()
    client.stop_node.assert_not_awaited()


# -- connect_interface: node-to-network ----------------------------------------


async def test_connect_interface_node_to_network_by_id() -> None:
    client = _pro_client()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]},
    }
    client.set_node_interface.return_value = {"status": "success"}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, network_id=4)

    client.set_node_interface.assert_awaited_once_with("/User1/Lab 1.unl", 1, 0, 4)
    client.list_lab_networks.assert_not_awaited()  # id given directly, no lookup needed
    assert result["status"] == "success"


async def test_connect_interface_node_to_network_by_name_single_match() -> None:
    client = _pro_client()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]},
    }
    client.list_lab_networks.return_value = {
        "status": "success",
        "data": {"4": {"name": "Backbone", "id": 4}},
    }
    client.set_node_interface.return_value = {"status": "success"}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, network_name="backbone")

    client.set_node_interface.assert_awaited_once_with("/User1/Lab 1.unl", 1, 0, 4)
    assert result["status"] == "success"


async def test_connect_interface_node_to_network_by_name_no_match() -> None:
    client = AsyncMock()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]},
    }
    client.list_lab_networks.return_value = {"status": "success", "data": {}}

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, network_name="nonexistent")

    assert result["status"] == "cancelled"
    client.set_node_interface.assert_not_awaited()
    client.get_status.assert_not_awaited()  # never reached -- resolution failed first


async def test_connect_interface_node_to_network_by_name_ambiguous() -> None:
    client = AsyncMock()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 0}]},
    }
    client.list_lab_networks.return_value = {
        "status": "success",
        "data": {"4": {"name": "Backbone", "id": 4}, "5": {"name": "Backbone", "id": 5}},
    }

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, network_name="backbone")

    assert result["status"] == "error"
    client.set_node_interface.assert_not_awaited()


async def test_connect_interface_node_to_network_interface_error() -> None:
    client = AsyncMock()
    client.get_node_interfaces.return_value = {
        "status": "success",
        "data": {"ethernet": [{"name": "Gi0/0", "network_id": 1}]},  # none free
    }

    result = await nodes.connect_interface(client, "/User1/Lab 1.unl", 1, network_id=4)

    assert result["status"] == "error"
    client.set_node_interface.assert_not_awaited()
    client.get_status.assert_not_awaited()


def test_is_running_true_for_nonzero_status() -> None:
    assert nodes._is_running({"status": 2}) is True
    assert nodes._is_running({"status": "2"}) is True


def test_is_running_false_for_zero_status() -> None:
    assert nodes._is_running({"status": 0}) is False
    assert nodes._is_running({"status": "0"}) is False


def test_is_running_conservative_when_status_missing_or_unparseable() -> None:
    assert nodes._is_running({}) is True
    assert nodes._is_running({"status": None}) is True
    assert nodes._is_running({"status": "not-a-number"}) is True


async def test_edit_lab_node_requires_at_least_one_field() -> None:
    client = AsyncMock()

    result = await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 9)

    assert result["status"] == "error"
    client.list_lab_nodes.assert_not_awaited()
    client.edit_lab_node.assert_not_awaited()


async def test_edit_lab_node_stopped_node_does_not_stop_first() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "status": 0},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 9, name="RingSW1")

    client.stop_node.assert_not_awaited()
    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 9, name="RingSW1")
    assert result["status"] == "success"
    assert "stopped it first" not in result["message"]


async def test_edit_lab_node_running_node_stops_first_then_edits() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "status": 2},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 1, name="RealSW1")

    client.stop_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)
    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 1, name="RealSW1")
    assert result["status"] == "success"
    assert "stopped it first" in result["message"]


async def test_edit_lab_node_stop_happens_before_edit_call_order() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "status": 2},
    }
    call_order: list[str] = []
    client.stop_node.side_effect = lambda *a, **k: call_order.append("stop")
    client.edit_lab_node.side_effect = lambda *a, **k: call_order.append("edit") or {"status": "success"}

    await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 1, name="RealSW1")

    assert call_order == ["stop", "edit"]


async def test_edit_lab_node_only_sends_supplied_fields() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"status": 0}}
    client.edit_lab_node.return_value = {"status": "success"}

    await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 9, ram=2048)

    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 9, ram=2048)


async def test_edit_lab_node_supports_every_expanded_field() -> None:
    # Regression test for the "edit_node needs to support updating all the
    # node template parameters" request -- every field beyond the
    # original small set must actually reach the client call.
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"status": 0}}
    client.edit_lab_node.return_value = {"status": "success"}

    await nodes.edit_lab_node(
        client,
        "/User1/Lab 1.unl",
        9,
        image="c8000v-26.01.01",
        cpulimit=1,
        delay=15,
        disable_offload=1,
        sat="-1",
        eth_format="Gi{0}/{0-3}",
        eth_name=["Gi0/0", "Gi0/1"],
        firstmac="50:12:00:09:00:00",
        qemu_version="4.1.0",
        qemu_arch="x86_64",
        qemu_nic="virtio-net-pci",
        qemu_options="-machine type=pc,accel=kvm",
        rdp_user="admin",
        rdp_password="secret",
    )

    client.edit_lab_node.assert_awaited_once_with(
        "/User1/Lab 1.unl",
        9,
        image="c8000v-26.01.01",
        cpulimit=1,
        delay=15,
        disable_offload=1,
        sat="-1",
        eth_format="Gi{0}/{0-3}",
        eth_name=["Gi0/0", "Gi0/1"],
        firstmac="50:12:00:09:00:00",
        qemu_version="4.1.0",
        qemu_arch="x86_64",
        qemu_nic="virtio-net-pci",
        qemu_options="-machine type=pc,accel=kvm",
        rdp_user="admin",
        rdp_password="secret",
    )


async def test_edit_lab_node_never_touches_uuid() -> None:
    # uuid is deliberately not an exposed parameter -- confirm the
    # function signature has no way to pass it through at all.
    import inspect

    sig = inspect.signature(nodes.edit_lab_node)
    assert "uuid" not in sig.parameters


async def test_edit_lab_node_message_includes_node_name_and_id() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "status": 0},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 9, name="RingSW1")

    assert "SW1" in result["message"]
    assert "9" in result["message"]


# -- edit_lab_node: duplicate-name detection ------------------------------------


async def test_find_duplicate_name_finds_another_node_with_same_name() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"1": {"id": 1, "name": "SW1"}, "9": {"id": 9, "name": "SW1"}},
    }

    duplicate = await nodes._find_duplicate_name(client, "/User1/Lab 1.unl", 9, "SW1")

    assert duplicate == {"id": 1, "name": "SW1"}


async def test_find_duplicate_name_is_case_insensitive() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"1": {"id": 1, "name": "SW1"}},
    }

    duplicate = await nodes._find_duplicate_name(client, "/User1/Lab 1.unl", 9, "sw1")

    assert duplicate == {"id": 1, "name": "SW1"}


async def test_find_duplicate_name_ignores_the_node_itself() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"9": {"id": 9, "name": "SW1"}},
    }

    duplicate = await nodes._find_duplicate_name(client, "/User1/Lab 1.unl", 9, "SW1")

    assert duplicate is None


async def test_find_duplicate_name_no_match_returns_none() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"1": {"id": 1, "name": "R1"}},
    }

    duplicate = await nodes._find_duplicate_name(client, "/User1/Lab 1.unl", 9, "SW1")

    assert duplicate is None


async def test_edit_lab_node_name_change_with_duplicate_asks_for_confirmation() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"1": {"id": 1, "name": "SW1"}, "9": {"id": 9, "name": "RingSW1"}},
    }

    result = await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 9, name="SW1")

    assert result["status"] == "confirmation_required"
    assert result["data"]["duplicate_node_id"] == 1
    client.edit_lab_node.assert_not_awaited()
    client.stop_node.assert_not_awaited()  # never even reached the status check


async def test_edit_lab_node_name_change_no_duplicate_proceeds_directly() -> None:
    client = AsyncMock()
    client.list_lab_nodes.side_effect = [
        {"status": "success", "data": {"1": {"id": 1, "name": "R1"}}},  # duplicate check
        {"status": "success", "data": {"name": "RingSW1", "status": 0}},  # status check
    ]
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 9, name="SW1")

    assert result["status"] == "success"
    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 9, name="SW1")


async def test_edit_lab_node_confirm_duplicate_name_bypasses_the_check() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"name": "SW1", "status": 0}}
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 9, name="SW1", confirm_duplicate_name=True)

    assert result["status"] == "success"
    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 9, name="SW1")


async def test_edit_lab_node_field_other_than_name_never_checks_duplicates() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"status": 0}}
    client.edit_lab_node.return_value = {"status": "success"}

    await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 9, ram=2048)

    # Only one list_lab_nodes call (the status check) -- no duplicate-name
    # lookup ever happens when name isn't being changed.
    client.list_lab_nodes.assert_awaited_once_with("/User1/Lab 1.unl", 9)


# -- change_node_delay: single node, bulk-by-name, bulk-by-order ---------------


def _delay_node(node_id: int, name: str, delay: int = 0, status: int = 0) -> dict:
    return {"id": node_id, "name": name, "delay": delay, "status": status}


def _delay_lab_nodes(*nodes: dict) -> dict:
    return {"status": "success", "data": {str(n["id"]): n for n in nodes}}


# -- single-node mode (node_id always wins) -----------------------------------


async def test_change_node_delay_single_node_requires_confirmation() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {"name": "SW1", "delay": 0}}

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", node_id=9)

    assert result["status"] == "confirmation_required"
    assert "10" in result["message"]  # default delay
    client.stop_node.assert_not_awaited()
    client.edit_lab_node.assert_not_awaited()


async def test_change_node_delay_single_node_default_delay_is_ten() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "delay": 0, "status": 0},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", node_id=9, confirm=True)

    # EVE-NG Community bug workaround: a delay-only edit doesn't flip the
    # server's internal "modified" flag and is silently rejected, so the
    # node's own current name is resent alongside delay (see
    # _with_delay_workaround).
    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 9, delay=10, name="SW1")
    assert result["status"] == "success"


async def test_change_node_delay_single_node_explicit_delay() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "delay": 0, "status": 0},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    await nodes.change_node_delay(client, "/User1/Lab 1.unl", node_id=9, delay=30, confirm=True)

    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 9, delay=30, name="SW1")


# -- EVE-NG Community delay-modified-flag bug workaround -----------------
#
# Confirmed live: a delay-only edit is silently rejected by EVE-NG
# Community's own node-edit code (its internal "modified" flag is never
# set by the delay branch alone), surfacing as a generic "cannot edit
# node" error. The workaround resends the node's own current name
# alongside delay, since name unconditionally sets the flag server-side.


def test_with_delay_workaround_pads_name_when_delay_is_the_only_field() -> None:
    current = {"name": "VMX-1", "delay": 0}
    assert nodes._with_delay_workaround({"delay": 11}, current) == {
        "delay": 11,
        "name": "VMX-1",
    }


def test_with_delay_workaround_does_not_override_an_explicit_name() -> None:
    current = {"name": "VMX-1", "delay": 0}
    assert nodes._with_delay_workaround({"delay": 11, "name": "NewName"}, current) == {
        "delay": 11,
        "name": "NewName",
    }


def test_with_delay_workaround_skips_padding_when_another_flag_field_present() -> None:
    current = {"name": "VMX-1", "delay": 0}
    assert nodes._with_delay_workaround({"delay": 11, "left": "200"}, current) == {
        "delay": 11,
        "left": "200",
    }


def test_with_delay_workaround_is_a_no_op_without_delay() -> None:
    current = {"name": "VMX-1", "delay": 0}
    assert nodes._with_delay_workaround({"icon": "Router.png"}, current) == {
        "icon": "Router.png",
    }


async def test_edit_lab_node_delay_only_pads_name_in_the_actual_api_call() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "VMX-1", "delay": 0, "status": 0},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_node(client, "/User1/Lab 1.unl", 1, delay=11)

    # The actual EVE-NG call is padded with the node's current name...
    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 1, delay=11, name="VMX-1")
    # ...but the reported message only mentions what the caller asked to change.
    assert "delay=11" in result["message"]
    assert "name=" not in result["message"]


async def test_change_node_delay_single_node_stops_if_running() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "delay": 0, "status": 2},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    await nodes.change_node_delay(client, "/User1/Lab 1.unl", node_id=9, confirm=True)

    client.stop_node.assert_awaited_once_with("/User1/Lab 1.unl", 9)


async def test_change_node_delay_single_node_does_not_stop_if_already_stopped() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "delay": 0, "status": 0},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    await nodes.change_node_delay(client, "/User1/Lab 1.unl", node_id=9, confirm=True)

    client.stop_node.assert_not_awaited()


async def test_change_node_delay_node_id_overrides_bulk_flag() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"name": "SW1", "delay": 0, "status": 0},
    }
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", node_id=9, bulk=True, confirm=True)

    # Single-node mode still applies -- only one node touched, no bulk search.
    assert result["status"] == "success"
    assert client.edit_lab_node.await_count == 1


# -- error/validation ------------------------------------------------------------


async def test_change_node_delay_requires_node_id_or_bulk() -> None:
    client = AsyncMock()

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl")

    assert result["status"] == "error"
    client.list_lab_nodes.assert_not_awaited()


# -- bulk mode, names given: substring match, order = order names given --------


async def test_change_node_delay_bulk_by_name_no_match_is_cancelled() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "R1"))

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, names="SW")

    assert result["status"] == "cancelled"


async def test_change_node_delay_bulk_by_name_single_term_multiple_matches() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(
        _delay_node(2, "SW2"), _delay_node(1, "SW1"), _delay_node(3, "SW3")
    )

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, names="SW")

    # Sorted by id within a single search term: SW1(10s), SW2(20s), SW3(30s).
    assert result["status"] == "confirmation_required"
    assert "SW1 (id 1): 0s -> 10s" in result["message"]
    assert "SW2 (id 2): 0s -> 20s" in result["message"]
    assert "SW3 (id 3): 0s -> 30s" in result["message"]


async def test_change_node_delay_bulk_by_name_list_preserves_given_order() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "SW1"), _delay_node(2, "R2"))

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, names=["R2", "SW1"])

    # "R2" term given first -> gets increment*1; "SW1" term second -> increment*2.
    assert "R2 (id 2): 0s -> 10s" in result["message"]
    assert "SW1 (id 1): 0s -> 20s" in result["message"]


async def test_change_node_delay_bulk_by_name_dedupes_node_matching_multiple_terms() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "RingSW1"))

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, names=["Ring", "SW1"])

    # Matches both terms but must appear -- and be assigned a delay -- once only.
    assert result["message"].count("RingSW1") == 1
    assert "-> 10s" in result["message"]
    assert "-> 20s" not in result["message"]


async def test_change_node_delay_bulk_by_name_custom_increment() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "SW1"), _delay_node(2, "SW2"))

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, names="SW", increment=5)

    assert "-> 5s" in result["message"]
    assert "-> 10s" in result["message"]


async def test_change_node_delay_bulk_by_name_confirm_applies_and_stops_running() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(
        _delay_node(1, "SW1", status=2), _delay_node(2, "SW2", status=0)
    )
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, names="SW", confirm=True)

    client.stop_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)  # only the running one
    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 1, delay=10, name="SW1")
    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 2, delay=20, name="SW2")
    assert result["status"] == "success"


# -- bulk mode, no names: list all + ask for order ------------------------------


async def test_change_node_delay_bulk_no_names_no_order_lists_all_nodes() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(
        _delay_node(1, "SW1", delay=5), _delay_node(2, "SW2", delay=15)
    )

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True)

    assert result["status"] == "selection_required"
    assert len(result["data"]["matches"]) == 2
    assert "current delay 5s" in result["message"]
    assert "order" in result["message"]


async def test_change_node_delay_bulk_no_names_empty_lab_is_cancelled() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True)

    assert result["status"] == "cancelled"


async def test_change_node_delay_bulk_order_applies_chosen_sequence() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(
        _delay_node(1, "SW1"), _delay_node(2, "SW2"), _delay_node(3, "SW3")
    )

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, order="3,1,2")

    # order "3,1,2" -> SW3 first (10s), SW1 second (20s), SW2 third (30s).
    assert "SW3 (id 3): 0s -> 10s" in result["message"]
    assert "SW1 (id 1): 0s -> 20s" in result["message"]
    assert "SW2 (id 2): 0s -> 30s" in result["message"]


async def test_change_node_delay_bulk_order_accepts_space_separated() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "SW1"), _delay_node(2, "SW2"))

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, order="2 1")

    assert "SW2 (id 2): 0s -> 10s" in result["message"]
    assert "SW1 (id 1): 0s -> 20s" in result["message"]


async def test_change_node_delay_bulk_order_partial_subset_allowed() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(
        _delay_node(1, "SW1"), _delay_node(2, "SW2"), _delay_node(3, "SW3")
    )

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, order="2")

    assert "SW2" in result["message"]
    assert "SW1" not in result["message"]
    assert "SW3" not in result["message"]


async def test_change_node_delay_bulk_order_non_numeric_token_is_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "SW1"))

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, order="abc")

    assert result["status"] == "error"


async def test_change_node_delay_bulk_order_out_of_range_is_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "SW1"))

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, order="99")

    assert result["status"] == "error"


async def test_change_node_delay_bulk_order_confirm_applies() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "SW1"), _delay_node(2, "SW2"))
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, order="2,1", confirm=True)

    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 2, delay=10, name="SW2")
    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 1, delay=20, name="SW1")
    assert result["status"] == "success"


async def test_change_node_delay_confirmation_message_says_accept_or_yes() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _delay_lab_nodes(_delay_node(1, "SW1"))

    result = await nodes.change_node_delay(client, "/User1/Lab 1.unl", bulk=True, order="1")

    assert "accept" in result["message"]
    assert "yes" in result["message"]
    assert "stopped" in result["message"]


# -- edit_lab_nodes_by_template: bulk interfaces/cpu/memory/icon by template ----


def _lab_nodes(*nodes: dict) -> dict:
    return {"status": "success", "data": {str(n["id"]): n for n in nodes}}


def _templates_catalog(*id_desc_pairs: tuple[str, str]) -> dict:
    return {"status": "success", "data": dict(id_desc_pairs)}


def _node(node_id: int, name: str, template: str, status: int = 0) -> dict:
    return {"id": node_id, "name": name, "template": template, "status": status}


async def test_edit_lab_nodes_by_template_requires_vendor_or_template() -> None:
    client = AsyncMock()

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl")

    assert result["status"] == "error"
    client.list_lab_nodes.assert_not_awaited()


async def test_edit_lab_nodes_by_template_no_match_is_cancelled() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "R1", "vmx"))
    client.list_node_templates.return_value = _templates_catalog(("vmx", "Juniper vMX"))

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", template="cisco")

    assert result["status"] == "cancelled"


async def test_edit_lab_nodes_by_template_single_template_skips_to_node_selection() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "SW2", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", template="vios")

    assert result["status"] == "selection_required"
    assert len(result["data"]["matches"]) == 2  # the two nodes, not templates
    assert "node_selection" in result["message"]


async def test_edit_lab_nodes_by_template_multiple_templates_requires_narrowing() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(
        ("viosl2", "Cisco vIOS Switch"), ("c8000v", "Cisco Catalyst 8000v")
    )

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", vendor="cisco")

    assert result["status"] == "selection_required"
    assert len(result["data"]["matches"]) == 2  # two templates
    assert "only ever targets one template" in result["message"]


async def test_edit_lab_nodes_by_template_selection_by_number() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(
        ("c8000v", "Cisco Catalyst 8000v"), ("viosl2", "Cisco vIOS Switch")
    )

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", vendor="cisco", template_selection="1")

    # Sorted template_ids alphabetically: c8000v < viosl2 -> "1" = c8000v.
    assert result["status"] == "selection_required"
    assert "node_selection" in result["message"]
    assert len(result["data"]["matches"]) == 1
    assert "C8K1" in result["data"]["matches"][0]


async def test_edit_lab_nodes_by_template_selection_by_exact_id() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(
        ("c8000v", "Cisco Catalyst 8000v"), ("viosl2", "Cisco vIOS Switch")
    )

    result = await nodes.edit_lab_nodes_by_template(
        client, "/User1/Lab 1.unl", vendor="cisco", template_selection="viosl2"
    )

    assert "SW1" in result["data"]["matches"][0]


async def test_edit_lab_nodes_by_template_selection_matching_more_than_one_is_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(
        ("c8000v", "Cisco Catalyst 8000v"), ("viosl2", "Cisco vIOS Switch")
    )

    result = await nodes.edit_lab_nodes_by_template(
        client, "/User1/Lab 1.unl", vendor="cisco", template_selection="1,2"
    )

    assert result["status"] == "error"
    assert "one template" in result["message"]


async def test_edit_lab_nodes_by_template_invalid_template_selection_is_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(
        ("c8000v", "Cisco Catalyst 8000v"), ("viosl2", "Cisco vIOS Switch")
    )

    result = await nodes.edit_lab_nodes_by_template(
        client, "/User1/Lab 1.unl", vendor="cisco", template_selection="zzz"
    )

    assert result["status"] == "error"


async def test_edit_lab_nodes_by_template_node_selection_all() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "SW2", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", template="vios", node_selection="all")

    assert result["status"] == "selection_required"  # now prompts for component
    assert len(result["data"]["matches"]) == 2
    assert "component" in result["message"]


async def test_edit_lab_nodes_by_template_node_selection_specific_number() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "SW2", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", template="vios", node_selection="2")

    assert len(result["data"]["matches"]) == 1
    assert "SW2" in result["data"]["matches"][0]


async def test_edit_lab_nodes_by_template_node_selection_invalid_is_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "SW2", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", template="vios", node_selection="99")

    assert result["status"] == "error"


async def test_edit_lab_nodes_by_template_no_component_prompts() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", template="vios", node_selection="all")

    assert result["status"] == "selection_required"
    assert "interfaces, cpu, memory, icon, or image" in result["message"]


async def test_edit_lab_nodes_by_template_invalid_component_is_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(
        client, "/User1/Lab 1.unl", template="vios", node_selection="all", component="bogus"
    )

    assert result["status"] == "error"


@pytest.mark.parametrize(
    ("alias", "expected_field"),
    [
        ("interfaces", "ethernet"),
        ("interface", "ethernet"),
        ("ethernet", "ethernet"),
        ("cpu", "cpu"),
        ("cpus", "cpu"),
        ("memory", "ram"),
        ("ram", "ram"),
        ("mem", "ram"),
    ],
)
async def test_edit_lab_nodes_by_template_component_aliases(alias, expected_field) -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(
        client, "/User1/Lab 1.unl", template="vios", node_selection="all", component=alias
    )

    assert expected_field in result["message"]


async def test_edit_lab_nodes_by_template_component_given_no_value_prompts() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(
        client, "/User1/Lab 1.unl", template="vios", node_selection="all", component="cpu"
    )

    assert result["status"] == "selection_required"
    assert "value" in result["message"].lower()


async def test_edit_lab_nodes_by_template_value_given_requires_final_confirmation() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "SW2", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="all",
        component="interfaces",
        value=16,
    )

    assert result["status"] == "confirmation_required"
    assert "stopped" in result["message"]
    assert "accept" in result["message"]
    assert "yes" in result["message"]
    client.edit_lab_node.assert_not_awaited()


async def test_edit_lab_nodes_by_template_confirm_applies_and_stops_running_nodes() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(
        _node(1, "SW1", "viosl2", status=2), _node(2, "SW2", "viosl2", status=0)
    )
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="all",
        component="ethernet",
        value=16,
        confirm=True,
    )

    client.stop_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)  # only the running one
    assert client.edit_lab_node.await_count == 2
    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 1, ethernet=16)
    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 2, ethernet=16)
    assert result["status"] == "success"


async def test_edit_lab_nodes_by_template_node_selection_targets_only_chosen_subset() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(
        _node(1, "SW1", "viosl2"), _node(2, "SW2", "viosl2"), _node(3, "SW3", "viosl2")
    )
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="1,3",
        component="cpu",
        value=2,
        confirm=True,
    )

    assert client.edit_lab_node.await_count == 2
    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 1, cpu=2)
    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 3, cpu=2)
    assert "SW1" in result["message"]
    assert "SW3" in result["message"]
    assert "SW2" not in result["message"]


# -- edit_lab_nodes_by_template: icon component (its own search/narrow) --------


async def test_edit_lab_nodes_by_template_icon_no_search_prompts() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))

    result = await nodes.edit_lab_nodes_by_template(
        client, "/User1/Lab 1.unl", template="vios", node_selection="all", component="icon"
    )

    assert result["status"] == "selection_required"
    assert "icon_search" in result["message"]
    client.list_network_types.assert_not_awaited()


async def test_edit_lab_nodes_by_template_icon_search_no_match_is_cancelled() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))
    client.list_network_types.return_value = {"icons": {"lan.png": "lan.png"}}

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="all",
        component="icon",
        icon_search="zzz",
    )

    assert result["status"] == "cancelled"


async def test_edit_lab_nodes_by_template_icon_search_single_match_goes_to_confirmation() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))
    client.list_network_types.return_value = {"icons": {"lan.png": "lan.png", "Switch2.png": "Switch2.png"}}

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="all",
        component="icon",
        icon_search="lan",
    )

    assert result["status"] == "confirmation_required"
    assert "lan.png" in result["message"]


async def test_edit_lab_nodes_by_template_icon_search_multiple_requires_selection() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))
    client.list_network_types.return_value = {
        "icons": {"Switch2.png": "x", "Switch-2D-L2-Generic-S.svg": "x", "Switch-2D-L3-Generic-S.svg": "x"}
    }

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="all",
        component="icon",
        icon_search="switch",
    )

    assert result["status"] == "selection_required"
    assert len(result["data"]["matches"]) == 3
    assert "icon_selection" in result["message"]


async def test_edit_lab_nodes_by_template_icon_selection_by_number() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))
    client.list_network_types.return_value = {"icons": {"Switch2.png": "x", "Switch-2D-L2-Generic-S.svg": "x"}}

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="all",
        component="icon",
        icon_search="switch",
        icon_selection="1",
    )

    # sorted() -> "Switch-2D-L2-Generic-S.svg" < "Switch2.png" (ASCII '-' < '2')
    assert result["status"] == "confirmation_required"
    assert "Switch-2D-L2-Generic-S.svg" in result["message"]


async def test_edit_lab_nodes_by_template_icon_selection_by_exact_filename() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))
    client.list_network_types.return_value = {"icons": {"Switch2.png": "x", "Switch-2D-L2-Generic-S.svg": "x"}}

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="all",
        component="icon",
        icon_search="switch",
        icon_selection="Switch2.png",
    )

    assert "Switch2.png" in result["message"]


async def test_edit_lab_nodes_by_template_icon_confirm_applies() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"))
    client.list_node_templates.return_value = _templates_catalog(("viosl2", "Cisco vIOS Switch"))
    client.list_network_types.return_value = {"icons": {"lan.png": "x"}}
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="vios",
        node_selection="all",
        component="icon",
        icon_search="lan",
        confirm=True,
    )

    client.edit_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 1, icon="lan.png")
    assert result["status"] == "success"


# -- edit_lab_nodes_by_template: image component (template-scoped search) ------


def _template_with_images(*image_names: str) -> dict:
    return {
        "status": "success",
        "data": {"options": {"image": {"list": {name: name for name in image_names}}}},
    }


async def test_edit_lab_nodes_by_template_image_no_search_prompts() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))

    result = await nodes.edit_lab_nodes_by_template(
        client, "/User1/Lab 1.unl", template="c8000v", node_selection="all", component="image"
    )

    assert result["status"] == "selection_required"
    assert "image_search" in result["message"]
    client.get_node_template.assert_not_awaited()


async def test_edit_lab_nodes_by_template_image_searches_resolved_template_only() -> None:
    # Confirms images come from THIS template's own list, not a global
    # catalog -- get_node_template is called with the resolved template id.
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))
    client.get_node_template.return_value = _template_with_images("c8000v-26.01.01")
    client.edit_lab_node.return_value = {"status": "success"}

    await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="c8000v",
        node_selection="all",
        component="image",
        image_search="26",
    )

    client.get_node_template.assert_awaited_once_with("c8000v")


async def test_edit_lab_nodes_by_template_image_search_no_match_is_cancelled() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))
    client.get_node_template.return_value = _template_with_images("c8000v-26.01.01")

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="c8000v",
        node_selection="all",
        component="image",
        image_search="zzz",
    )

    assert result["status"] == "cancelled"


async def test_edit_lab_nodes_by_template_image_single_match_goes_to_confirmation() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))
    client.get_node_template.return_value = _template_with_images("c8000v-26.01.01")

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="c8000v",
        node_selection="all",
        component="image",
        image_search="26",
    )

    assert result["status"] == "confirmation_required"
    assert "c8000v-26.01.01" in result["message"]


async def test_edit_lab_nodes_by_template_image_multiple_matches_requires_selection() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))
    client.get_node_template.return_value = _template_with_images(
        "c8000v-17.06.02", "c8000v-17.18.02", "c8000v-26.01.01"
    )

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="c8000v",
        node_selection="all",
        component="image",
        image_search="c8000v",
    )

    assert result["status"] == "selection_required"
    assert len(result["data"]["matches"]) == 3
    assert "image_selection" in result["message"]


async def test_edit_lab_nodes_by_template_image_selection_by_number() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))
    client.get_node_template.return_value = _template_with_images("c8000v-17.06.02", "c8000v-26.01.01")

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="c8000v",
        node_selection="all",
        component="image",
        image_search="c8000v",
        image_selection="2",
    )

    # sorted() -> ["c8000v-17.06.02", "c8000v-26.01.01"]
    assert "c8000v-26.01.01" in result["message"]


async def test_edit_lab_nodes_by_template_image_selection_by_exact_filename() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))
    client.get_node_template.return_value = _template_with_images("c8000v-17.06.02", "c8000v-26.01.01")

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="c8000v",
        node_selection="all",
        component="image",
        image_search="c8000v",
        image_selection="c8000v-17.06.02",
    )

    assert "c8000v-17.06.02" in result["message"]


async def test_edit_lab_nodes_by_template_image_invalid_selection_is_error() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))
    client.get_node_template.return_value = _template_with_images("c8000v-17.06.02", "c8000v-26.01.01")

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="c8000v",
        node_selection="all",
        component="image",
        image_search="c8000v",
        image_selection="zzz",
    )

    assert result["status"] == "error"


async def test_edit_lab_nodes_by_template_image_confirm_applies_across_all_matching_nodes() -> None:
    # This is the actual "update image in bulk for all devices with same
    # node template" behavior the request asked for.
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "C8K1", "c8000v"), _node(2, "C8K2", "c8000v"))
    client.list_node_templates.return_value = _templates_catalog(("c8000v", "Cisco Catalyst 8000v"))
    client.get_node_template.return_value = _template_with_images("c8000v-26.01.01")
    client.edit_lab_node.return_value = {"status": "success"}

    result = await nodes.edit_lab_nodes_by_template(
        client,
        "/User1/Lab 1.unl",
        template="c8000v",
        node_selection="all",
        component="image",
        image_search="26",
        confirm=True,
    )

    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 1, image="c8000v-26.01.01")
    client.edit_lab_node.assert_any_await("/User1/Lab 1.unl", 2, image="c8000v-26.01.01")
    assert result["status"] == "success"


async def test_edit_lab_nodes_by_template_vendor_and_template_combined_and() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = _lab_nodes(_node(1, "SW1", "viosl2"), _node(2, "R1", "vjunosrouter"))
    client.list_node_templates.return_value = _templates_catalog(
        ("viosl2", "Cisco vIOS Switch"), ("vjunosrouter", "Juniper vRouter")
    )

    # vendor=cisco AND template=vios -> only viosl2/SW1, not vjunosrouter.
    result = await nodes.edit_lab_nodes_by_template(client, "/User1/Lab 1.unl", vendor="cisco", template="vios")

    assert len(result["data"]["matches"]) == 1
    assert "SW1" in result["data"]["matches"][0]


async def test_delete_lab_node_requires_non_empty_name() -> None:
    client = AsyncMock()

    result = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "")

    assert result["status"] == "error"
    client.list_lab_nodes.assert_not_awaited()


async def test_delete_lab_node_no_match_does_not_prompt() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {"status": "success", "data": {}}

    result = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "Ghost")

    assert result["status"] == "cancelled"
    client.delete_lab_node.assert_not_awaited()


async def test_delete_lab_node_matches_by_name_substring_not_id() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"11": {"name": "canvas-4", "type": "qemu"}},
    }
    client.delete_lab_node.return_value = {"status": "success"}

    # "11" is the id, not the name -- must NOT match (no ID matching allowed).
    no_match = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "11")
    assert no_match["status"] == "cancelled"

    result = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "canvas", confirm=True)
    client.delete_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 11)
    assert result["status"] == "success"


async def test_delete_lab_node_label_includes_vendor_context() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"21": {"name": "canvas-14", "template": "vjunosevo"}},
    }
    client.list_node_templates.return_value = {
        "status": "success",
        "data": {"vjunosevo": "Juniper vEVO Router"},
    }

    result = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "canvas")

    assert result["data"]["matches"] == ["canvas-14 [Juniper] (id 21)"]


async def test_delete_lab_node_first_call_multiple_matches_requires_selection() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"0": {"name": "canvas-14"}, "1": {"name": "canvas-15"}},
    }

    result = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "canvas")

    assert result["status"] == "selection_required"
    assert "canvas-14" in result["message"]
    assert "canvas-15" in result["message"]
    client.delete_lab_node.assert_not_awaited()


async def test_delete_lab_node_narrowing_by_exact_name_then_confirm() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"0": {"name": "canvas-14"}, "1": {"name": "canvas-15"}},
    }
    client.delete_lab_node.return_value = {"status": "success"}

    result = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "canvas", selection="canvas-15", confirm=True)

    client.delete_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 1)
    assert result["status"] == "success"


async def test_delete_lab_node_allows_multiple_selection() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"0": {"name": "canvas-14"}, "1": {"name": "canvas-15"}, "2": {"name": "SW1"}},
    }
    client.delete_lab_node.return_value = {"status": "success"}

    result = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "canvas", selection="1,2", confirm=True)

    assert client.delete_lab_node.await_count == 2
    assert result["status"] == "success"


async def test_delete_lab_node_no_selection_still_works_for_single_match() -> None:
    client = AsyncMock()
    client.list_lab_nodes.return_value = {
        "status": "success",
        "data": {"0": {"name": "SW1"}},
    }
    client.delete_lab_node.return_value = {"status": "success"}

    first = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "SW1")
    assert first["status"] == "confirmation_required"
    client.delete_lab_node.assert_not_awaited()

    result = await nodes.delete_lab_node(client, "/User1/Lab 1.unl", "SW1", confirm=True)
    client.delete_lab_node.assert_awaited_once_with("/User1/Lab 1.unl", 0)
    assert result["status"] == "success"
