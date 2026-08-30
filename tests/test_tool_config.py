from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

from mcp_eveng.tool_config import load_tool_status, make_enabled_predicate


def test_load_tool_status_missing_file_uses_built_in_defaults(tmp_path) -> None:
    status = load_tool_status(tmp_path / "does-not-exist.env")

    assert status["list_users"] is False
    assert status["get_user"] is False
    assert status["add_user"] is False
    assert status["edit_user"] is False
    assert status["delete_user"] is False
    assert status["list_user_roles"] is False
    assert status["delete_lab"] is False
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


# -- the actual shipped example files, not hand-copied strings -----------------
#
# Regression tests against the real files: guards against a future edit
# breaking the inline-comment syntax on the disabled lines, or forgetting
# to disable a tool, in a way a hand-written test string wouldn't catch.

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_tools_env_pro_example_enables_edition_gated_tools() -> None:
    status = load_tool_status(_REPO_ROOT / "tools.env.pro.example")

    assert status["export_node"] is True
    assert status["share_lab"] is True


def test_tools_env_comm_example_disables_edition_gated_tools() -> None:
    # export_node/share_lab are PRO/Corporate-only -- confirmed against
    # EVE-NG's own official features-compare page, live testing, and
    # direct manual testing against a real Community server (see the
    # README's "PRO vs Community differences" section) -- disabled here
    # since there's nothing they can actually do on Community.
    status = load_tool_status(_REPO_ROOT / "tools.env.comm.example")

    assert status["export_node"] is False
    assert status["share_lab"] is False


def test_tools_env_comm_example_lists_user_management_tools_same_as_pro() -> None:
    # Regression test for a corrected assumption: an earlier version of
    # this file omitted the six user-management tools entirely on the
    # assumption user administration wasn't supported on Community at
    # all. Direct manual testing against a real Community server (adding
    # a second admin user) confirmed that assumption was wrong -- they're
    # disabled by default on both editions for the same general reason
    # (not exposing user administration to an LLM by default), not
    # because Community can't support it. Checked against raw file
    # content (dotenv_values), not the processed status dict, since that
    # dict always merges in _DEFAULT_DISABLED's keys regardless of
    # whether the file mentions them and so can't distinguish "listed as
    # disabled" from "never mentioned at all".
    pro_raw = dotenv_values(_REPO_ROOT / "tools.env.pro.example")
    comm_raw = dotenv_values(_REPO_ROOT / "tools.env.comm.example")

    for tool in ("list_users", "get_user", "add_user", "edit_user", "delete_user", "list_user_roles"):
        assert tool in comm_raw, f"{tool} should be listed, not omitted"
        assert comm_raw[tool] == pro_raw[tool] == "disabled"


def test_tools_env_comm_example_has_full_parity_with_pro_except_four_tools() -> None:
    # The two files must list exactly the same set of tools -- Community
    # only differs from PRO in *values*, never in which tools are even
    # mentioned, except for export_node/share_lab/set_link_quality/
    # get_link_quality, which can't be safely omitted the way a
    # _DEFAULT_DISABLED tool could: none of the four is in that set, so
    # omitting their lines would make them enabled by default -- the
    # opposite of intended -- so they're the only four genuinely
    # edition-gated lines in the file.
    pro_raw = dotenv_values(_REPO_ROOT / "tools.env.pro.example")
    comm_raw = dotenv_values(_REPO_ROOT / "tools.env.comm.example")

    assert set(pro_raw.keys()) == set(comm_raw.keys())
    differing = {k for k in pro_raw if pro_raw[k] != comm_raw[k]}
    assert differing == {"export_node", "share_lab", "set_link_quality", "get_link_quality"}


def test_tools_env_comm_example_disables_exactly_thirteen_tools() -> None:
    # End-to-end functional check via make_enabled_predicate (what
    # actually gets registered), not just individual assertions: exactly
    # the six user-management tools plus
    # export_node/share_lab/set_link_quality/get_link_quality/delete_lab/
    # list_captures/get_capture should be unavailable on Community;
    # everything else should be enabled.
    status = load_tool_status(_REPO_ROOT / "tools.env.comm.example")
    enabled = make_enabled_predicate(status)

    all_tools = [
        "get_status",
        "list_node_templates",
        "get_node_template",
        "list_network_types",
        "list_user_roles",
        "list_tools",
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
        "set_link_quality",
        "get_link_quality",
        "telnet_node",
        "list_captures",
        "get_capture",
    ]
    disabled_tools = {t for t in all_tools if not enabled(t)}
    assert disabled_tools == {
        "list_users",
        "get_user",
        "add_user",
        "edit_user",
        "delete_user",
        "list_user_roles",
        "share_lab",
        "export_node",
        "set_link_quality",
        "get_link_quality",
        "delete_lab",
        "list_captures",
        "get_capture",
    }
