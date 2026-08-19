from __future__ import annotations

from unittest.mock import AsyncMock

from mcp_eveng.tools import system


def make_client(**method_returns) -> AsyncMock:
    client = AsyncMock()
    for name, value in method_returns.items():
        getattr(client, name).return_value = value
    return client


async def test_eve_get_status_delegates_to_client() -> None:
    client = make_client(get_status={"status": "success", "data": {"cpu": 1}})

    result = await system.get_status(client)

    client.get_status.assert_awaited_once_with()
    assert result["data"]["cpu"] == 1


async def test_list_node_templates_filters_out_hided_by_default() -> None:
    client = make_client(
        list_node_templates={
            "status": "success",
            "data": {
                "csr1000vng": "Cisco CSR 1000V (XE 16.x)",
                "asa": "Cisco ASA.hided",
            },
        }
    )

    result = await system.list_node_templates(client)

    ids = [t["id"] for t in result["data"]["templates"]]
    assert ids == ["csr1000vng"]
    assert result["data"]["count"] == 1


async def test_list_node_templates_include_without_images() -> None:
    client = make_client(
        list_node_templates={
            "status": "success",
            "data": {
                "csr1000vng": "Cisco CSR 1000V (XE 16.x)",
                "asa": "Cisco ASA.hided",
            },
        }
    )

    result = await system.list_node_templates(client, include_without_images=True)

    ids = {t["id"] for t in result["data"]["templates"]}
    assert ids == {"csr1000vng", "asa"}
    assert result["data"]["count"] == 2


async def test_list_node_templates_annotates_vendor_and_has_image() -> None:
    client = make_client(
        list_node_templates={
            "status": "success",
            "data": {"csr1000vng": "Cisco CSR 1000V (XE 16.x)"},
        }
    )

    result = await system.list_node_templates(client)

    template = result["data"]["templates"][0]
    assert template["vendor"] == "Cisco"
    assert template["has_image"] is True
    assert template["name"] == "Cisco CSR 1000V (XE 16.x)"


async def test_list_node_templates_strips_hided_suffix_when_included() -> None:
    client = make_client(
        list_node_templates={"status": "success", "data": {"asa": "Cisco ASA.hided"}}
    )

    result = await system.list_node_templates(client, include_without_images=True)

    template = result["data"]["templates"][0]
    assert template["name"] == "Cisco ASA"
    assert template["has_image"] is False


async def test_get_node_template_passes_template_id() -> None:
    client = make_client(
        get_node_template={
            "status": "success",
            "data": {"type": "iol", "description": "Cisco IOL", "options": {}},
        }
    )

    result = await system.get_node_template(client, "iol")

    client.get_node_template.assert_awaited_once_with("iol")
    assert result["data"]["type"] == "iol"


async def test_get_node_template_annotates_vendor() -> None:
    client = make_client(
        get_node_template={
            "status": "success",
            "data": {"description": "Juniper vEVO Router", "options": {}},
        }
    )

    result = await system.get_node_template(client, "vjunosevo")

    assert result["data"]["vendor"] == "Juniper"


async def test_get_node_template_has_image_true_when_image_list_non_empty() -> None:
    client = make_client(
        get_node_template={
            "status": "success",
            "data": {
                "description": "Cisco CSR 1000V (XE 16.x)",
                "options": {"image": {"list": {"csr1000vng-x": "csr1000vng-x"}}},
            },
        }
    )

    result = await system.get_node_template(client, "csr1000vng")

    assert result["data"]["has_image"] is True


async def test_get_node_template_has_image_false_when_image_list_empty() -> None:
    client = make_client(
        get_node_template={
            "status": "success",
            "data": {"description": "Cisco ASA", "options": {"image": {"list": {}}}},
        }
    )

    result = await system.get_node_template(client, "asa")

    assert result["data"]["has_image"] is False


async def test_eve_list_network_types_delegates_to_client() -> None:
    client = make_client(list_network_types={"status": "success", "data": {"bridge": "bridge"}})

    result = await system.list_network_types(client)

    client.list_network_types.assert_awaited_once_with()
    assert result["data"]["bridge"] == "bridge"


async def test_eve_list_user_roles_delegates_to_client() -> None:
    client = make_client(list_user_roles={"status": "success", "data": {"admin": "Administrator"}})

    result = await system.list_user_roles(client)

    client.list_user_roles.assert_awaited_once_with()
    assert result["data"]["admin"] == "Administrator"
