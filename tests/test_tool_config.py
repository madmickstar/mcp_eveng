from __future__ import annotations

from mcp_eveng.tool_config import load_tool_status, make_enabled_predicate


def test_load_tool_status_missing_file_uses_built_in_defaults(tmp_path) -> None:
    status = load_tool_status(tmp_path / "does-not-exist.env")

    assert status["list_users"] is False
    assert status["get_user"] is False
    assert status["add_user"] is False
    assert status["edit_user"] is False
    assert status["delete_user"] is False
    assert status["list_user_roles"] is False
    # telnet_node is enabled by default, unlike the user-management tools --
    # not even mentioned in the default-disabled map.
    assert "telnet_node" not in status
    # Nothing else is even mentioned when there's no file.
    assert "get_status" not in status


def test_load_tool_status_file_overrides_defaults_both_directions(tmp_path) -> None:
    config_file = tmp_path / "tools.env"
    config_file.write_text("list_users=enabled\nget_status=disabled\n")

    status = load_tool_status(config_file)

    assert status["list_users"] is True  # explicitly re-enabled
    assert status["get_status"] is False  # explicitly disabled
    # Unmentioned default-disabled tools keep their default.
    assert status["get_user"] is False


def test_load_tool_status_unknown_value_is_treated_as_enabled(tmp_path) -> None:
    config_file = tmp_path / "tools.env"
    config_file.write_text("get_status=typo\nlist_folder=Disabled\n")

    status = load_tool_status(config_file)

    assert status["get_status"] is True  # fails safe -- not "disabled" literally
    assert status["list_folder"] is False  # case-insensitive match


def test_load_tool_status_value_matching_is_case_insensitive(tmp_path) -> None:
    config_file = tmp_path / "tools.env"
    config_file.write_text("get_status=DISABLED\n")

    status = load_tool_status(config_file)

    assert status["get_status"] is False


def test_make_enabled_predicate_defaults_unlisted_to_true() -> None:
    enabled = make_enabled_predicate({"get_status": False})

    assert enabled("get_status") is False
    assert enabled("some_other_tool") is True


def test_make_enabled_predicate_respects_explicit_true() -> None:
    enabled = make_enabled_predicate({"list_users": True})

    assert enabled("list_users") is True
