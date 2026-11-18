from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_eveng.tools import labs


def make_client(**method_returns) -> AsyncMock:
    client = AsyncMock()
    for name, value in method_returns.items():
        getattr(client, name).return_value = value
    return client


# -- unchanged CRUD (just renamed) --------------------------------------------


async def test_get_lab_passes_path() -> None:
    client = make_client(get_lab={"status": "success", "data": {"name": "Lab 1"}})

    result = await labs.get_lab(client, "/User1/Lab 1.unl")

    client.get_lab.assert_awaited_once_with("/User1/Lab 1.unl")
    assert result["data"]["name"] == "Lab 1"


async def test_create_lab_forwards_all_fields() -> None:
    client = make_client(create_lab={"status": "success"})

    await labs.create_lab(client, "/User1", "New Lab", version="2", author="Me", description="desc", body="body")

    client.create_lab.assert_awaited_once_with(
        "/User1", "New Lab", version="2", author="Me", description="desc", body="body"
    )


async def test_edit_lab_drops_none_fields() -> None:
    client = make_client(edit_lab={"status": "success"})

    await labs.edit_lab(client, "/User1/Lab 1.unl", name="Renamed", version=None)

    client.edit_lab.assert_awaited_once_with("/User1/Lab 1.unl", name="Renamed")


async def test_get_lab_topology_passes_path() -> None:
    client = make_client(get_lab_topology={"status": "success", "data": []})

    result = await labs.get_lab_topology(client, "/User1/Lab 1.unl")

    client.get_lab_topology.assert_awaited_once_with("/User1/Lab 1.unl")
    assert result["data"] == []


async def test_list_lab_pictures_passes_optional_id() -> None:
    client = make_client(list_lab_pictures={"status": "success", "data": {}})

    await labs.list_lab_pictures(client, "/User1/Lab 1.unl", 3)

    client.list_lab_pictures.assert_awaited_once_with("/User1/Lab 1.unl", 3)


# -- share_lab: search/select users, add to existing shares, confirm ----------


def _users_data(*usernames: str) -> dict:
    return {"status": "success", "data": {name: {"username": name} for name in usernames}}


def _lab_with_shared(*shared: str) -> dict:
    return {"status": "success", "data": {"shared": list(shared)}}


def _pro_client(**method_returns) -> AsyncMock:
    # share_lab is PRO-only and checks the server's edition
    # first -- every test below except the edition-gate tests themselves
    # needs a PRO get_status to reach the rest of the logic at all.
    client = make_client(**method_returns)
    client.get_status.return_value = {"status": "success", "data": {"version": "6.5.0-27-PRO"}}
    return client


async def test_share_lab_rejects_immediately_on_community_edition() -> None:
    # PRO-only, per EVE-NG's own official comparison page and
    # confirmed live -- must reject before even fetching usernames, not
    # walk through search/select only to fail at the end.
    client = AsyncMock()
    client.get_status.return_value = {"status": "success", "data": {"version": "6.2.0-4"}}

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="alice")

    assert result["status"] == "error"
    assert "community" in result["message"].lower()
    client.list_users.assert_not_awaited()
    client.get_lab.assert_not_awaited()


async def test_share_lab_rejects_on_missing_version_conservatively() -> None:
    # No/unrecognized version string -- treated as Community, the
    # conservative default (same reasoning as connect_interface/export_node).
    client = AsyncMock()
    client.get_status.return_value = {"status": "success", "data": {}}

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="alice")

    assert result["status"] == "error"
    client.list_users.assert_not_awaited()


async def test_share_lab_no_users_on_server_is_cancelled() -> None:
    client = _pro_client()
    client.list_users.return_value = {"status": "success", "data": {}}

    result = await labs.share_lab(client, "/User1/Lab 1.unl")

    assert result["status"] == "cancelled"
    client.get_lab.assert_not_awaited()


async def test_share_lab_search_no_match_is_cancelled() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "bob")

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="zzz")

    assert result["status"] == "cancelled"


async def test_share_lab_more_than_twenty_matches_asks_to_narrow() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data(*(f"user{i}" for i in range(25)))

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="user")

    assert result["status"] == "error"
    assert "too many" in result["message"]
    client.get_lab.assert_not_awaited()


async def test_share_lab_empty_search_matches_everyone() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "bob")
    client.get_lab.return_value = _lab_with_shared()

    result = await labs.share_lab(client, "/User1/Lab 1.unl")

    assert result["status"] == "selection_required"
    assert set(result["data"]["matches"]) == {"alice", "bob"}


async def test_share_lab_single_match_proceeds_without_prompt() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "bob")
    client.get_lab.return_value = _lab_with_shared()

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="ali")

    assert result["status"] == "confirmation_required"
    assert "alice" in result["message"]
    assert "bob" not in result["message"]


async def test_share_lab_multiple_matches_lists_numbered_with_all_option() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "alan")

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="al")

    assert result["status"] == "selection_required"
    assert "all" in result["message"]
    assert set(result["data"]["matches"]) == {"alice", "alan"}
    client.get_lab.assert_not_awaited()


async def test_share_lab_selection_by_number() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alan", "alice")
    client.get_lab.return_value = _lab_with_shared()

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="al", selection="1")

    # all_users sorted -> ["alan", "alice"]; "1" -> "alan"
    assert "alan" in result["message"]
    assert "alice" not in result["message"]


async def test_share_lab_selection_by_exact_username() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alan", "alice")
    client.get_lab.return_value = _lab_with_shared()

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="al", selection="alice")

    assert "alice" in result["message"]
    assert "alan" not in result["message"]


async def test_share_lab_selection_all_means_every_matched_user() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alan", "alice", "bob")
    client.get_lab.return_value = _lab_with_shared()

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="al", selection="all")

    assert "alan" in result["message"]
    assert "alice" in result["message"]
    assert "bob" not in result["message"]  # doesn't match search "al" at all


async def test_share_lab_invalid_selection_is_error() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alan", "alice")

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="al", selection="zzz")

    assert result["status"] == "error"
    client.get_lab.assert_not_awaited()


async def test_share_lab_search_all_bypasses_search_and_selection_entirely() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "bob", "carol")
    client.get_lab.return_value = _lab_with_shared()

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="all")

    assert result["status"] == "confirmation_required"
    assert "alice" in result["message"]
    assert "bob" in result["message"]
    assert "carol" in result["message"]


async def test_share_lab_preserves_existing_shares() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "bob")
    client.get_lab.return_value = _lab_with_shared("carol")  # already shared with carol

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="ali", confirm=True)

    client.edit_lab.assert_awaited_once_with("/User1/Lab 1.unl", shared=["alice", "carol"])
    assert result["status"] == "success"


async def test_share_lab_already_shared_user_is_cancelled_no_op() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "bob")
    client.get_lab.return_value = _lab_with_shared("alice")  # already shared

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="ali")

    assert result["status"] == "cancelled"
    client.edit_lab.assert_not_awaited()


async def test_share_lab_confirmation_message_says_accept_or_yes() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "bob")
    client.get_lab.return_value = _lab_with_shared()

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="ali")

    assert "accept" in result["message"]
    assert "yes" in result["message"]
    client.edit_lab.assert_not_awaited()


async def test_share_lab_confirm_applies_the_edit() -> None:
    client = _pro_client()
    client.list_users.return_value = _users_data("alice", "bob")
    client.get_lab.return_value = _lab_with_shared()
    client.edit_lab.return_value = {"status": "success"}

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="ali", confirm=True)

    client.edit_lab.assert_awaited_once_with("/User1/Lab 1.unl", shared=["alice"])
    assert result["status"] == "success"


async def test_share_lab_list_users_data_as_list_shape() -> None:
    # Defensive handling in case list_users' data is ever a list rather
    # than a dict-keyed-by-username shape.
    client = _pro_client()
    client.list_users.return_value = {
        "status": "success",
        "data": [{"username": "alice"}, {"username": "bob"}],
    }
    client.get_lab.return_value = _lab_with_shared()

    result = await labs.share_lab(client, "/User1/Lab 1.unl", search="ali")

    assert result["status"] == "confirmation_required"
    assert "alice" in result["message"]


# -- list_labs (always recursive, delegates to the client's own traversal) ----


async def test_list_labs_delegates_to_client_and_wraps_result() -> None:
    found = [{"file": "a.unl", "path": "/a.unl"}, {"file": "b.unl", "path": "/Sub/b.unl"}]
    client = AsyncMock()
    client.list_all_labs.return_value = found

    result = await labs.list_labs(client, "/")

    client.list_all_labs.assert_awaited_once_with("/")
    assert result["status"] == "success"
    assert result["data"]["count"] == 2
    assert result["data"]["labs"] == found


async def test_list_labs_defaults_to_root() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = []

    await labs.list_labs(client)

    client.list_all_labs.assert_awaited_once_with("/")


async def test_list_labs_from_a_specific_folder_is_still_recursive() -> None:
    # Listing a specific folder must walk the tree from there, not just
    # return that one folder's immediate contents.
    client = AsyncMock()
    client.list_all_labs.return_value = [{"file": "a.unl", "path": "/Sub/Deeper/a.unl"}]

    result = await labs.list_labs(client, "/Sub")

    client.list_all_labs.assert_awaited_once_with("/Sub")
    assert result["data"]["labs"] == [{"file": "a.unl", "path": "/Sub/Deeper/a.unl"}]


async def test_list_labs_search_filters_by_case_insensitive_substring() -> None:
    found = [
        {"file": "mickshine_ai_testing.unl", "path": "/mickshine_ai_testing.unl"},
        {"file": "other.unl", "path": "/other.unl"},
    ]
    client = AsyncMock()
    client.list_all_labs.return_value = found

    result = await labs.list_labs(client, search="MICKSHINE")

    assert result["data"]["count"] == 1
    assert result["data"]["labs"] == [found[0]]


async def test_list_labs_search_matches_against_path_too() -> None:
    found = [
        {"file": "a.unl", "path": "/Shared/a.unl"},
        {"file": "b.unl", "path": "/Users/bob/b.unl"},
    ]
    client = AsyncMock()
    client.list_all_labs.return_value = found

    result = await labs.list_labs(client, search="shared")

    assert result["data"]["labs"] == [found[0]]


async def test_list_labs_empty_search_matches_everything() -> None:
    found = [{"file": "a.unl", "path": "/a.unl"}, {"file": "b.unl", "path": "/b.unl"}]
    client = AsyncMock()
    client.list_all_labs.return_value = found

    result = await labs.list_labs(client)

    assert result["data"]["labs"] == found


async def test_list_labs_search_no_match_returns_empty() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = [{"file": "a.unl", "path": "/a.unl"}]

    result = await labs.list_labs(client, search="zzz")

    assert result["data"]["labs"] == []
    assert result["data"]["count"] == 0


async def test_list_labs_message_mentions_search_term_when_given() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = [{"file": "a.unl", "path": "/a.unl"}]

    result = await labs.list_labs(client, search="a")

    assert "'a'" in result["message"]


# -- open_lab: lookup + lock status + next-step menu ---------------------------


def _labs_for_open(*names_and_paths: tuple[str, str]) -> list[dict]:
    return [{"file": file, "path": path} for file, path in names_and_paths]


async def test_open_lab_requires_non_empty_name() -> None:
    client = AsyncMock()

    result = await labs.open_lab(client, "")

    assert result["status"] == "error"
    client.list_all_labs.assert_not_awaited()


async def test_open_lab_no_match() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("other.unl", "/other.unl"))

    result = await labs.open_lab(client, "missing")

    assert result["status"] == "cancelled"
    client.get_lab.assert_not_awaited()


async def test_open_lab_multiple_matches_asks_to_narrow() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("test.unl", "/User1/test.unl"), ("test.unl", "/User2/test.unl"))

    result = await labs.open_lab(client, "test")

    assert result["status"] == "selection_required"
    client.get_lab.assert_not_awaited()


async def test_open_lab_single_match_reports_unlocked() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("test.unl", "/User1/test.unl"))
    client.get_lab.return_value = {"status": "success", "data": {"lock": 0, "name": "test"}}

    result = await labs.open_lab(client, "test")

    client.get_lab.assert_awaited_once_with("/User1/test.unl")
    assert result["status"] == "success"
    assert "unlocked" in result["message"]
    assert result["data"]["lock"] is False


async def test_open_lab_single_match_reports_locked() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("test.unl", "/User1/test.unl"))
    client.get_lab.return_value = {"status": "success", "data": {"lock": 1}}

    result = await labs.open_lab(client, "test")

    assert "locked" in result["message"]
    assert "unlocked" not in result["message"]
    assert result["data"]["lock"] is True


async def test_open_lab_lock_field_as_string_zero_is_unlocked() -> None:
    # Guards against Python's bool("0") == True footgun -- EVE-NG's API may
    # return lock as either an int or a string.
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("test.unl", "/User1/test.unl"))
    client.get_lab.return_value = {"status": "success", "data": {"lock": "0"}}

    result = await labs.open_lab(client, "test")

    assert result["data"]["lock"] is False
    assert "unlocked" in result["message"]


async def test_open_lab_message_includes_the_menu() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("test.unl", "/User1/test.unl"))
    client.get_lab.return_value = {"status": "success", "data": {"lock": 0}}

    result = await labs.open_lab(client, "test")

    assert "add_lab_node" in result["message"]
    assert "add_lab_network" in result["message"]
    assert "edit_lab" in result["message"]


async def test_open_lab_searches_from_given_search_path() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = []

    await labs.open_lab(client, "test", search_path="/User1")

    client.list_all_labs.assert_awaited_once_with("/User1")


async def test_open_lab_message_states_the_labs_actual_name() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("mickshine_ai_testing.unl", "/mickshine_ai_testing.unl"))
    client.get_lab.return_value = {
        "status": "success",
        "data": {"lock": 0, "name": "mickshine_ai_testing"},
    }

    result = await labs.open_lab(client, "mickshine")

    assert "mickshine_ai_testing" in result["message"]
    assert result["data"]["lab_name"] == "mickshine_ai_testing"


async def test_open_lab_selection_by_number() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(
        ("micks_delete_test.unl", "/micks_delete_test.unl"),
        ("mickshine_ai_testing.unl", "/mickshine_ai_testing.unl"),
    )
    client.get_lab.return_value = {"status": "success", "data": {"lock": 0, "name": "mickshine_ai_testing"}}

    result = await labs.open_lab(client, "mick", selection="2")

    client.get_lab.assert_awaited_once_with("/mickshine_ai_testing.unl")
    assert result["status"] == "success"
    assert "mickshine_ai_testing" in result["message"]


async def test_open_lab_selection_by_full_name_case_insensitive() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(
        ("micks_delete_test.unl", "/micks_delete_test.unl"),
        ("mickshine_ai_testing.unl", "/mickshine_ai_testing.unl"),
    )
    client.get_lab.return_value = {"status": "success", "data": {"lock": 0, "name": "mickshine_ai_testing"}}

    result = await labs.open_lab(client, "mick", selection="MICKSHINE_AI_TESTING.UNL")

    client.get_lab.assert_awaited_once_with("/mickshine_ai_testing.unl")
    assert result["status"] == "success"


async def test_open_lab_selection_by_full_path() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("test.unl", "/User1/test.unl"), ("test.unl", "/User2/test.unl"))
    client.get_lab.return_value = {"status": "success", "data": {"lock": 0, "name": "test"}}

    result = await labs.open_lab(client, "test", selection="/User2/test.unl")

    client.get_lab.assert_awaited_once_with("/User2/test.unl")
    assert result["status"] == "success"


async def test_open_lab_invalid_selection_is_error() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(("test.unl", "/User1/test.unl"), ("test.unl", "/User2/test.unl"))

    result = await labs.open_lab(client, "test", selection="zzz")

    client.get_lab.assert_not_awaited()
    assert result["status"] == "error"


async def test_open_lab_selection_matching_more_than_one_is_error() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs_for_open(
        ("test.unl", "/User1/test.unl"),
        ("test.unl", "/User2/test.unl"),
        ("test.unl", "/User3/test.unl"),
    )

    result = await labs.open_lab(client, "test", selection="1,2")

    client.get_lab.assert_not_awaited()
    assert result["status"] == "error"
    assert "one lab" in result["message"]


# -- delete_lab: case-insensitive path-or-name match, search/select/confirm ---


def _labs(*names_and_paths: tuple[str, str]) -> list[dict]:
    return [{"file": file, "path": path} for file, path in names_and_paths]


async def test_delete_lab_requires_non_empty_string() -> None:
    client = AsyncMock()

    result = await labs.delete_lab(client, "")

    assert result["status"] == "error"
    client.list_all_labs.assert_not_awaited()


async def test_delete_lab_no_match_does_not_prompt_or_delete() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs(("other.unl", "/other.unl"))

    result = await labs.delete_lab(client, "missing")

    assert result["status"] == "cancelled"
    client.delete_lab.assert_not_awaited()


async def test_delete_lab_first_call_does_not_delete() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs(("test.unl", "/User1/test.unl"))

    result = await labs.delete_lab(client, "test")

    client.delete_lab.assert_not_awaited()
    assert result["status"] == "confirmation_required"
    assert "/User1/test.unl" in result["message"]


async def test_delete_lab_matches_by_substring() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs(("testing.unl", "/testing.unl"))
    client.delete_lab.return_value = {"status": "success"}

    result = await labs.delete_lab(client, "test", confirm=True)

    client.delete_lab.assert_awaited_once_with("/testing.unl")
    assert result["status"] == "success"


async def test_delete_lab_matches_by_full_path_case_insensitive() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs(("test.unl", "/User1/test.unl"))
    client.delete_lab.return_value = {"status": "success"}

    await labs.delete_lab(client, "/USER1/TEST.UNL", confirm=True)

    client.delete_lab.assert_awaited_once_with("/User1/test.unl")


async def test_delete_lab_multiple_matches_require_selection() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs(("test.unl", "/User1/test.unl"), ("test.unl", "/User2/test.unl"))

    result = await labs.delete_lab(client, "test")

    assert result["status"] == "selection_required"
    client.delete_lab.assert_not_awaited()


async def test_delete_lab_multiple_matches_never_allows_selecting_more_than_one() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs(
        ("test.unl", "/A/test.unl"), ("test.unl", "/B/test.unl"), ("test.unl", "/C/test.unl")
    )

    result = await labs.delete_lab(client, "test", selection="1,2", confirm=True)

    client.delete_lab.assert_not_awaited()
    assert result["status"] == "error"


async def test_delete_lab_narrowing_by_exact_path_resolves_ambiguity() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs(("test.unl", "/User1/test.unl"), ("test.unl", "/User2/test.unl"))
    client.delete_lab.return_value = {"status": "success"}

    result = await labs.delete_lab(client, "test", selection="/User2/test.unl", confirm=True)

    client.delete_lab.assert_awaited_once_with("/User2/test.unl")
    assert result["status"] == "success"


async def test_delete_lab_narrowing_by_number_then_confirm() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = _labs(("test.unl", "/User1/test.unl"), ("test.unl", "/User2/test.unl"))
    client.delete_lab.return_value = {"status": "success"}

    narrowed = await labs.delete_lab(client, "test", selection="2")
    assert narrowed["status"] == "confirmation_required"
    assert narrowed["data"]["matches"] == ["/User2/test.unl"]

    result = await labs.delete_lab(client, "test", selection="2", confirm=True)
    client.delete_lab.assert_awaited_once_with("/User2/test.unl")
    assert result["status"] == "success"


async def test_delete_lab_searches_from_given_search_path() -> None:
    client = AsyncMock()
    client.list_all_labs.return_value = []

    await labs.delete_lab(client, "test", search_path="/User1")

    client.list_all_labs.assert_awaited_once_with("/User1")


# -- lab satellite -----------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("any", "-1"),
        ("ANY", "-1"),
        ("master", "0"),
        ("satellite1", "1"),
        ("Satellite 3", "3"),
        ("sat2", "2"),
        (1, "1"),
        ("0", "0"),
        (-1, "-1"),
        (None, None),
        ("", None),
    ],
)
def test_resolve_satellite(given: str | int | None, expected: str | None) -> None:
    assert labs._resolve_satellite(given) == expected


@pytest.mark.parametrize("bad", ["satellite", "nope", "-5", "satelliteX"])
def test_resolve_satellite_rejects_unknown(bad: str) -> None:
    with pytest.raises(ValueError, match="Unknown satellite"):
        labs._resolve_satellite(bad)


async def test_create_lab_with_satellite_sends_sat_and_verifies() -> None:
    client = make_client(
        create_lab={"status": "success"},
        get_lab={"status": "success", "data": {"sat": "1"}},
    )

    result = await labs.create_lab(client, "/User1", "clustertest", satellite="satellite1")

    client.create_lab.assert_awaited_once_with(
        "/User1", "clustertest", version="1", author="", description="", body="", sat="1"
    )
    client.get_lab.assert_awaited_once_with("/User1/clustertest.unl")
    assert "warning" not in result


async def test_create_lab_warns_when_satellite_not_stored() -> None:
    client = make_client(
        create_lab={"status": "success"},
        get_lab={"status": "success", "data": {"sat": "-1"}},
    )

    result = await labs.create_lab(client, "/User1/", "clustertest", satellite="satellite2")

    client.get_lab.assert_awaited_once_with("/User1/clustertest.unl")
    assert "did not apply the satellite" in result["warning"]


async def test_create_lab_without_satellite_sends_no_sat_and_skips_verify() -> None:
    client = make_client(create_lab={"status": "success"})

    await labs.create_lab(client, "/User1", "plain")

    assert "sat" not in client.create_lab.await_args.kwargs
    client.get_lab.assert_not_awaited()


async def test_create_lab_invalid_satellite_creates_nothing() -> None:
    client = make_client()

    result = await labs.create_lab(client, "/User1", "x", satellite="bogus")

    assert result["status"] == "error"
    client.create_lab.assert_not_awaited()


async def test_edit_lab_satellite_sends_sat_and_verifies() -> None:
    client = make_client(
        edit_lab={"status": "success"},
        get_lab={"status": "success", "data": {"sat": "0"}},
    )

    result = await labs.edit_lab(client, "/User1/Lab 1.unl", satellite="master")

    client.edit_lab.assert_awaited_once_with("/User1/Lab 1.unl", sat="0")
    assert "warning" not in result


async def test_edit_lab_satellite_verify_failure_is_a_warning_not_an_error() -> None:
    client = make_client(edit_lab={"status": "success"})
    client.get_lab.side_effect = RuntimeError("boom")

    result = await labs.edit_lab(client, "/User1/Lab 1.unl", satellite="any")

    assert result["status"] == "success"
    assert "Could not re-read" in result["warning"]


# -- live satellite list ---------------------------------------------------------

_CLUSTER = {
    "status": "success",
    "data": {
        "1": {"id": "0", "name": "master", "pubkey": "", "online": 1},
        "0": {"id": "-1", "name": "any", "pubkey": "", "online": 1},
        "2": {"id": "1", "name": "satellite1", "pubkey": "k1", "online": 1},
        "3": {"id": "2", "name": "satellite2", "pubkey": "k2", "online": 0},
        "4": {"id": "3", "name": "satellite3", "pubkey": "k3", "online": 1},
    },
}


async def test_create_lab_refuses_satellite_the_cluster_does_not_have() -> None:
    client = make_client(list_satellites=_CLUSTER)

    result = await labs.create_lab(client, "/User1", "test-cluster-id4", satellite="satellite4")

    assert result["status"] == "error"
    assert "satellite4" in result["message"]
    assert "satellite3 (id 3)" in result["message"]
    assert "Nothing was created" in result["message"]
    client.create_lab.assert_not_awaited()


async def test_create_lab_uses_live_list_and_warns_when_offline() -> None:
    client = make_client(
        list_satellites=_CLUSTER,
        create_lab={"status": "success"},
        get_lab={"status": "success", "data": {"sat": "2"}},
    )

    result = await labs.create_lab(client, "/User1", "x", satellite="Satellite2")

    assert client.create_lab.await_args.kwargs["sat"] == "2"
    assert "offline" in result["warning"]


async def test_edit_lab_refuses_unknown_satellite_without_editing() -> None:
    client = make_client(list_satellites=_CLUSTER)

    result = await labs.edit_lab(client, "/User1/Lab 1.unl", satellite=9)

    assert result["status"] == "error"
    client.edit_lab.assert_not_awaited()


async def test_satellite_falls_back_to_static_mapping_when_list_unavailable() -> None:
    client = make_client(create_lab={"status": "success"}, get_lab={"status": "success", "data": {"sat": "4"}})
    client.list_satellites.side_effect = RuntimeError("404")

    await labs.create_lab(client, "/User1", "x", satellite="satellite4")

    assert client.create_lab.await_args.kwargs["sat"] == "4"


async def test_satellite_matches_custom_names_from_live_list() -> None:
    cluster = {
        "data": {"0": {"id": "-1", "name": "any", "online": 1}, "1": {"id": "7", "name": "lab-east", "online": 1}}
    }
    client = make_client(
        list_satellites=cluster,
        create_lab={"status": "success"},
        get_lab={"status": "success", "data": {"sat": "7"}},
    )

    await labs.create_lab(client, "/User1", "x", satellite="lab-east")

    assert client.create_lab.await_args.kwargs["sat"] == "7"


# -- create_lab / edit_lab: share_with / unshare_with -------------------------


def _share_client(existing: tuple[str, ...] = (), *users: str) -> AsyncMock:
    client = _pro_client(
        create_lab={"status": "success", "message": "Lab created."},
        edit_lab={"status": "success", "message": "Lab saved."},
        list_users=_users_data(*(users or ("alice", "alice2", "bob"))),
    )
    client.get_lab.return_value = _lab_with_shared(*existing)
    return client


async def test_create_lab_share_exact_match_no_prompt() -> None:
    client = _share_client()
    client.get_lab.return_value = _lab_with_shared("alice")

    result = await labs.create_lab(client, "/User1", "L", share_with="alice")

    client.edit_lab.assert_awaited_once_with("/User1/L.unl", shared=["alice"])
    assert result["sharing"]["added"] == ["alice"]
    assert "warning" not in result


async def test_create_lab_share_ambiguous_creates_lab_but_prompts_and_skips_share() -> None:
    client = _share_client()

    result = await labs.create_lab(client, "/User1", "L", share_with="ali")

    client.create_lab.assert_awaited_once()
    client.edit_lab.assert_not_awaited()
    assert result["sharing"]["selection_required"] is True
    assert "1. alice" in result["message"] and "2. alice2" in result["message"]


async def test_create_lab_share_exact_beats_longer_partial() -> None:
    client = _share_client()
    client.get_lab.return_value = _lab_with_shared("alice")

    await labs.create_lab(client, "/User1", "L", share_with=["ALICE"])

    client.edit_lab.assert_awaited_once_with("/User1/L.unl", shared=["alice"])


async def test_create_lab_share_refused_on_community_before_creating() -> None:
    client = _share_client()
    client.get_status.return_value = {"status": "success", "data": {"version": "6.2.0-4"}}

    result = await labs.create_lab(client, "/User1", "L", share_with="alice")

    assert result["status"] == "error"
    client.create_lab.assert_not_awaited()


async def test_create_lab_without_share_never_touches_users() -> None:
    client = _share_client()

    await labs.create_lab(client, "/User1", "L")

    client.list_users.assert_not_awaited()
    client.get_status.assert_not_awaited()


async def test_edit_lab_share_adds_and_keeps_existing() -> None:
    client = _share_client(("bob",))
    client.get_lab.side_effect = [_lab_with_shared("bob"), _lab_with_shared("alice", "bob")]

    result = await labs.edit_lab(client, "/User1/L.unl", share_with="alice")

    client.edit_lab.assert_awaited_once_with("/User1/L.unl", shared=["alice", "bob"])
    assert result["sharing"]["added"] == ["alice"]


async def test_edit_lab_unshare_removes_only_named_user() -> None:
    client = _share_client(("alice", "bob"))
    client.get_lab.side_effect = [_lab_with_shared("alice", "bob"), _lab_with_shared("bob")]

    result = await labs.edit_lab(client, "/User1/L.unl", unshare_with="alice")

    client.edit_lab.assert_awaited_once_with("/User1/L.unl", shared=["bob"])
    assert result["sharing"]["removed"] == ["alice"]


async def test_edit_lab_unshare_all_clears_shares() -> None:
    client = _share_client(("alice", "bob"))
    client.get_lab.side_effect = [_lab_with_shared("alice", "bob"), _lab_with_shared()]

    await labs.edit_lab(client, "/User1/L.unl", unshare_with="all")

    client.edit_lab.assert_awaited_once_with("/User1/L.unl", shared=[])


async def test_edit_lab_unshare_user_not_shared_prompts_and_changes_nothing() -> None:
    client = _share_client(("bob",))

    result = await labs.edit_lab(client, "/User1/L.unl", unshare_with="alice")

    client.edit_lab.assert_not_awaited()
    assert result["status"] == "selection_required"
    assert "not currently shared" in result["message"]


async def test_edit_lab_ambiguous_share_still_applies_other_fields() -> None:
    client = _share_client()

    result = await labs.edit_lab(client, "/User1/L.unl", description="d", share_with="ali")

    client.edit_lab.assert_awaited_once_with("/User1/L.unl", description="d")
    assert result["sharing"]["selection_required"] is True


async def test_edit_lab_share_and_unshare_same_user_is_error() -> None:
    client = _share_client(("alice",))

    result = await labs.edit_lab(client, "/User1/L.unl", share_with="alice", unshare_with="alice")

    assert result["status"] == "error"
    client.edit_lab.assert_not_awaited()


async def test_edit_lab_already_shared_is_noop_without_put() -> None:
    client = _share_client(("alice",))

    result = await labs.edit_lab(client, "/User1/L.unl", share_with="alice")

    client.edit_lab.assert_not_awaited()
    assert result["status"] == "success"


async def test_edit_lab_warns_when_eveng_did_not_store_shares() -> None:
    client = _share_client(())
    client.get_lab.side_effect = [_lab_with_shared(), _lab_with_shared()]

    result = await labs.edit_lab(client, "/User1/L.unl", share_with="alice")

    assert "did not apply the sharing change" in result["warning"]


async def test_edit_lab_comma_string_shares_several() -> None:
    client = _share_client()
    client.get_lab.side_effect = [_lab_with_shared(), _lab_with_shared("alice", "bob")]

    await labs.edit_lab(client, "/User1/L.unl", share_with="alice, bob")

    client.edit_lab.assert_awaited_once_with("/User1/L.unl", shared=["alice", "bob"])
