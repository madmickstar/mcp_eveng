from __future__ import annotations

from mcp_eveng.search import find_by_name_case_insensitive, iter_named_records


def test_iter_named_records_handles_dict_shape() -> None:
    data = {"1": {"name": "Core"}, "2": {"name": "Edge"}}

    records = iter_named_records(data, "name")

    assert ("Core", {"name": "Core", "_key": "1"}) in records
    assert ("Edge", {"name": "Edge", "_key": "2"}) in records


def test_iter_named_records_dict_shape_falls_back_to_key_as_name() -> None:
    data = {"admin": {"role": "admin"}}

    records = iter_named_records(data, "username")

    assert records == [("admin", {"role": "admin", "_key": "admin"})]


def test_iter_named_records_handles_list_shape() -> None:
    data = [{"file": "a.unl"}, {"file": "b.unl"}]

    records = iter_named_records(data, "file")

    assert records == [("a.unl", {"file": "a.unl"}), ("b.unl", {"file": "b.unl"})]


def test_iter_named_records_handles_empty_or_unexpected_shapes() -> None:
    assert iter_named_records(None, "name") == []
    assert iter_named_records("not a container", "name") == []
    assert iter_named_records({}, "name") == []
    assert iter_named_records([], "name") == []


def test_find_by_name_case_insensitive_substring_match() -> None:
    records = [("Admin", {"username": "Admin"}), ("operator", {"username": "operator"})]

    assert find_by_name_case_insensitive(records, "admin") == [{"username": "Admin"}]
    assert find_by_name_case_insensitive(records, "ADMIN") == [{"username": "Admin"}]
    assert find_by_name_case_insensitive(records, "Admi") == [{"username": "Admin"}]  # substring


def test_find_by_name_case_insensitive_no_match() -> None:
    records = [("Admin", {"username": "Admin"})]

    assert find_by_name_case_insensitive(records, "zzz") == []


def test_find_by_name_case_insensitive_strips_whitespace() -> None:
    records = [("Core", {"name": "Core"})]

    assert find_by_name_case_insensitive(records, "  core  ") == [{"name": "Core"}]


def test_find_by_name_case_insensitive_can_match_multiple() -> None:
    records = [("test", {"id": 1}), ("TEST", {"id": 2}), ("other", {"id": 3})]

    result = find_by_name_case_insensitive(records, "Test")

    assert result == [{"id": 1}, {"id": 2}]


def test_find_by_name_case_insensitive_never_matches_id() -> None:
    # Regression: matching used to also check a record's id/key via
    # find_by_name_or_id_case_insensitive, which was removed entirely --
    # only the `name` field (as passed into iter_named_records) is ever
    # searched now.
    records = iter_named_records({"11": {"name": "canvas-4"}}, "name")

    assert find_by_name_case_insensitive(records, "11") == []
