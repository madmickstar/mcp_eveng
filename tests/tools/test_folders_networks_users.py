from __future__ import annotations

from unittest.mock import AsyncMock

from mcp_eveng.tools import folders, networks, users


def make_client(**method_returns) -> AsyncMock:
    client = AsyncMock()
    for name, value in method_returns.items():
        getattr(client, name).return_value = value
    return client


def _folder(path: str, name: str | None = None) -> dict:
    return {"name": name or path.rsplit("/", 1)[-1], "path": path}


# -- folders: list/add/move (unchanged) ----------------------------------------


async def test_list_folder_defaults_to_root() -> None:
    client = make_client(list_folder={"status": "success", "data": {}})

    await folders.list_folder(client)

    client.list_folder.assert_awaited_once_with("/")


async def test_add_folder_forwards_args() -> None:
    client = make_client(add_folder={"status": "success"})

    await folders.add_folder(client, "/User1", "New Folder")

    client.add_folder.assert_awaited_once_with("/User1", "New Folder")


async def test_move_folder() -> None:
    client = make_client(move_folder={"status": "success"})

    await folders.move_folder(client, "/User1/Old", "/User1/New")

    client.move_folder.assert_awaited_once_with("/User1/Old", "/User1/New")


# -- folders: delete_folder -----------------------------------------------------


async def test_delete_folder_requires_non_empty_path() -> None:
    client = AsyncMock()

    result = await folders.delete_folder(client, "")

    assert result["status"] == "error"
    client.list_all_folders.assert_not_awaited()


async def test_delete_folder_substring_search_no_match() -> None:
    client = AsyncMock()
    client.list_all_folders.return_value = [_folder("/User1/Other")]

    result = await folders.delete_folder(client, "Missing")

    assert result["status"] == "cancelled"
    client.delete_folder.assert_not_awaited()


async def test_delete_folder_single_match_case_insensitive_confirm_deletes() -> None:
    client = AsyncMock()
    client.list_all_folders.return_value = [_folder("/User1/Empty")]
    client.list_folder.return_value = {"status": "success", "data": {"folders": [], "labs": []}}
    client.delete_folder.return_value = {"status": "success"}

    result = await folders.delete_folder(client, "EMPTY", confirm=True)

    client.delete_folder.assert_awaited_once_with("/User1/Empty")
    assert result["status"] == "success"


async def test_delete_folder_first_call_does_not_delete() -> None:
    client = AsyncMock()
    client.list_all_folders.return_value = [_folder("/User1/Empty")]

    result = await folders.delete_folder(client, "Empty")

    client.delete_folder.assert_not_awaited()
    assert result["status"] == "confirmation_required"


async def test_delete_folder_refuses_when_not_empty() -> None:
    client = AsyncMock()
    client.list_all_folders.return_value = [_folder("/User1/NotEmpty")]
    client.list_folder.return_value = {
        "status": "success",
        "data": {
            "folders": [{"name": "Sub", "path": "/User1/NotEmpty/Sub"}],
            "labs": [{"file": "a.unl", "path": "/User1/NotEmpty/a.unl"}],
        },
    }

    result = await folders.delete_folder(client, "NotEmpty", confirm=True)

    client.delete_folder.assert_not_awaited()
    assert result["status"] == "error"
    assert "not empty" in result["message"]


async def test_delete_folder_multiple_matches_require_selection() -> None:
    client = AsyncMock()
    client.list_all_folders.return_value = [_folder("/User1/Test"), _folder("/User2/Test")]

    result = await folders.delete_folder(client, "Test")

    assert result["status"] == "selection_required"
    client.delete_folder.assert_not_awaited()


async def test_delete_folder_selection_by_exact_path_then_confirm() -> None:
    client = AsyncMock()
    client.list_all_folders.return_value = [_folder("/User1/Test"), _folder("/User2/Test")]
    client.list_folder.return_value = {"status": "success", "data": {"folders": [], "labs": []}}
    client.delete_folder.return_value = {"status": "success"}

    result = await folders.delete_folder(
        client, "Test", selection="/User2/Test", confirm=True
    )

    client.delete_folder.assert_awaited_once_with("/User2/Test")
    assert result["status"] == "success"


async def test_delete_folder_selection_cannot_pick_multiple() -> None:
    client = AsyncMock()
    client.list_all_folders.return_value = [_folder("/User1/Test"), _folder("/User2/Test")]

    result = await folders.delete_folder(client, "Test", selection="1,2", confirm=True)

    client.delete_folder.assert_not_awaited()
    assert result["status"] == "error"


async def test_delete_folder_searches_from_given_search_path() -> None:
    client = AsyncMock()
    client.list_all_folders.return_value = []

    await folders.delete_folder(client, "Test", search_path="/User1")

    client.list_all_folders.assert_awaited_once_with("/User1")


# -- networks -----------------------------------------------------------------


async def test_add_lab_network_forwards_kwargs() -> None:
    client = make_client(add_lab_network={"status": "success"})

    await networks.add_lab_network(
        client, "/User1/Lab 1.unl", "bridge", name="Core", left="35%", top="25%"
    )

    client.add_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", "bridge", name="Core", left="35%", top="25%"
    )


async def test_add_lab_network_never_forwards_bare_none_for_left_or_top() -> None:
    # Regression test for the same class of bug as add_lab_node's: this
    # tool always explicitly called client.add_lab_network(left=left,
    # top=top), so an unspecified left/top (None) would override the
    # client's own "0"/"0" default with an explicit null.
    client = make_client(add_lab_network={"status": "success"})

    await networks.add_lab_network(client, "/User1/Lab 1.unl", "bridge")

    client.add_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", "bridge", name=None, left="0", top="0"
    )


async def test_add_lab_network_hideme_omitted_by_default() -> None:
    client = make_client(add_lab_network={"status": "success"})

    await networks.add_lab_network(client, "/User1/Lab 1.unl", "bridge")

    # Not passed at all when not given -- lets the client's own default apply.
    assert "hideme" not in client.add_lab_network.await_args.kwargs


async def test_add_lab_network_hideme_forwarded_when_given() -> None:
    client = make_client(add_lab_network={"status": "success"})

    await networks.add_lab_network(client, "/User1/Lab 1.unl", "bridge", hideme=1)

    client.add_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", "bridge", name=None, left="0", top="0", hideme=1
    )


async def test_add_lab_network_no_type_prompts_with_list() -> None:
    client = AsyncMock()
    client.list_network_types.return_value = {
        "status": "success",
        "data": {"bridge": {}, "pnet0": {}, "nat0": {}},
    }

    result = await networks.add_lab_network(client, "/User1/Lab 1.unl")

    assert result["status"] == "selection_required"
    assert result["data"]["types"] == ["bridge", "nat0", "pnet0"]  # sorted
    client.add_lab_network.assert_not_awaited()


async def test_add_lab_network_no_types_available_is_error() -> None:
    client = AsyncMock()
    client.list_network_types.return_value = {"status": "success", "data": {}}

    result = await networks.add_lab_network(client, "/User1/Lab 1.unl")

    assert result["status"] == "error"
    client.add_lab_network.assert_not_awaited()


async def test_add_lab_network_type_by_exact_name_does_not_prompt() -> None:
    client = make_client(add_lab_network={"status": "success"})

    await networks.add_lab_network(client, "/User1/Lab 1.unl", "bridge")

    client.list_network_types.assert_not_awaited()
    client.add_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", "bridge", name=None, left="0", top="0"
    )


async def test_add_lab_network_type_cloud_alias_resolves_to_pnet0() -> None:
    client = make_client(add_lab_network={"status": "success"})

    await networks.add_lab_network(client, "/User1/Lab 1.unl", "cloud")

    client.list_network_types.assert_not_awaited()
    client.add_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", "pnet0", name=None, left="0", top="0"
    )


async def test_add_lab_network_type_cloud0_through_cloud9_resolve_to_matching_pnet() -> None:
    for i in range(10):
        client = make_client(add_lab_network={"status": "success"})

        await networks.add_lab_network(client, "/User1/Lab 1.unl", f"cloud{i}")

        client.add_lab_network.assert_awaited_once_with(
            "/User1/Lab 1.unl", f"pnet{i}", name=None, left="0", top="0"
        )


async def test_add_lab_network_type_cloud_alias_is_case_insensitive() -> None:
    client = make_client(add_lab_network={"status": "success"})

    await networks.add_lab_network(client, "/User1/Lab 1.unl", "Cloud5")

    client.add_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", "pnet5", name=None, left="0", top="0"
    )


async def test_add_lab_network_type_cloud10_is_not_a_recognized_alias() -> None:
    # Only cloud0-cloud9 exist (10 total, confirmed against EVE-NG's own
    # docs) -- "cloud10" must fall through as a literal (invalid) type,
    # not silently resolve to something.
    client = make_client(add_lab_network={"status": "success"})

    await networks.add_lab_network(client, "/User1/Lab 1.unl", "cloud10")

    client.add_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", "cloud10", name=None, left="0", top="0"
    )


async def test_add_lab_network_type_by_number_resolves() -> None:
    client = AsyncMock()
    client.list_network_types.return_value = {
        "status": "success",
        "data": {"bridge": {}, "pnet0": {}, "nat0": {}},
    }
    client.add_lab_network.return_value = {"status": "success"}

    await networks.add_lab_network(client, "/User1/Lab 1.unl", "2")

    # sorted -> ["bridge", "nat0", "pnet0"]; "2" -> "nat0"
    client.add_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", "nat0", name=None, left="0", top="0"
    )


async def test_add_lab_network_type_by_number_out_of_range_is_error() -> None:
    client = AsyncMock()
    client.list_network_types.return_value = {"status": "success", "data": {"bridge": {}}}

    result = await networks.add_lab_network(client, "/User1/Lab 1.unl", "99")

    assert result["status"] == "error"
    client.add_lab_network.assert_not_awaited()


async def test_edit_lab_network_requires_at_least_one_field() -> None:
    client = AsyncMock()

    result = await networks.edit_lab_network(client, "/User1/Lab 1.unl", 7)

    assert result["status"] == "error"
    client.edit_lab_network.assert_not_awaited()


async def test_edit_lab_network_forwards_only_supplied_fields() -> None:
    client = make_client(edit_lab_network={"status": "success"})

    await networks.edit_lab_network(client, "/User1/Lab 1.unl", 7, visibility=0)

    client.edit_lab_network.assert_awaited_once_with("/User1/Lab 1.unl", 7, visibility=0)


async def test_edit_lab_network_forwards_multiple_fields() -> None:
    client = make_client(edit_lab_network={"status": "success"})

    await networks.edit_lab_network(
        client, "/User1/Lab 1.unl", 7, name="Backbone", hideme=1, color="#FF0000"
    )

    client.edit_lab_network.assert_awaited_once_with(
        "/User1/Lab 1.unl", 7, name="Backbone", hideme=1, color="#FF0000"
    )


async def test_delete_lab_network_requires_non_empty_name() -> None:
    client = AsyncMock()

    result = await networks.delete_lab_network(client, "/User1/Lab 1.unl", "")

    assert result["status"] == "error"
    client.list_lab_networks.assert_not_awaited()


async def test_delete_lab_network_matches_by_name_substring_not_id() -> None:
    client = AsyncMock()
    client.list_lab_networks.return_value = {
        "status": "success",
        "data": {"11": {"name": "Core-Bridge", "type": "bridge"}},
    }
    client.delete_lab_network.return_value = {"status": "success"}

    # "11" is the id, not the name -- must NOT match.
    no_match = await networks.delete_lab_network(client, "/User1/Lab 1.unl", "11")
    assert no_match["status"] == "cancelled"

    result = await networks.delete_lab_network(client, "/User1/Lab 1.unl", "bridge", confirm=True)
    client.delete_lab_network.assert_awaited_once_with("/User1/Lab 1.unl", 11)
    assert result["status"] == "success"


async def test_delete_lab_network_allows_multiple() -> None:
    client = AsyncMock()
    client.list_lab_networks.return_value = {
        "status": "success",
        "data": {"0": {"name": "test-a"}, "1": {"name": "test-b"}},
    }
    client.delete_lab_network.return_value = {"status": "success"}

    result = await networks.delete_lab_network(
        client, "/User1/Lab 1.unl", "test", selection="1,2", confirm=True
    )

    assert client.delete_lab_network.await_count == 2
    assert result["status"] == "success"


async def test_delete_lab_network_no_match_does_not_prompt() -> None:
    client = AsyncMock()
    client.list_lab_networks.return_value = {"status": "success", "data": {}}

    result = await networks.delete_lab_network(client, "/User1/Lab 1.unl", "Nope")

    assert result["status"] == "cancelled"
    client.delete_lab_network.assert_not_awaited()


# -- users --------------------------------------------------------------------


async def test_add_user_forwards_fields() -> None:
    client = make_client(add_user={"status": "success"})

    await users.add_user(client, "op1", "pw", name="Operator", email="op@example.com", role="editor")

    client.add_user.assert_awaited_once_with(
        "op1", "pw", name="Operator", email="op@example.com", role="editor"
    )


async def test_edit_user_only_sends_changed_fields() -> None:
    client = make_client(edit_user={"status": "success"})

    await users.edit_user(client, "op1", email="new@example.com")

    client.edit_user.assert_awaited_once_with("op1", email="new@example.com")


async def test_delete_user_requires_non_empty_username() -> None:
    client = AsyncMock()

    result = await users.delete_user(client, "")

    assert result["status"] == "error"
    client.list_users.assert_not_awaited()


async def test_delete_user_matches_by_substring_confirm_deletes() -> None:
    client = AsyncMock()
    client.list_users.return_value = {
        "status": "success",
        "data": {"operator1": {"username": "operator1"}},
    }
    client.delete_user.return_value = {"status": "success"}

    result = await users.delete_user(client, "erat", confirm=True)

    client.delete_user.assert_awaited_once_with("operator1")
    assert result["status"] == "success"


async def test_delete_user_no_match_does_not_prompt() -> None:
    client = AsyncMock()
    client.list_users.return_value = {"status": "success", "data": {}}

    result = await users.delete_user(client, "ghost")

    assert result["status"] == "cancelled"
    client.delete_user.assert_not_awaited()


async def test_delete_user_multiple_matches_cannot_select_more_than_one() -> None:
    client = AsyncMock()
    client.list_users.return_value = {
        "status": "success",
        "data": {"a": {"username": "test1"}, "b": {"username": "test2"}},
    }

    result = await users.delete_user(client, "test", selection="1,2", confirm=True)

    client.delete_user.assert_not_awaited()
    assert result["status"] == "error"
