from __future__ import annotations

from mcp_eveng.confirmation import format_bullets, format_numbered, resolve_selection, run_delete_flow


def _matches_name(item: dict, needle: str) -> bool:
    return str(item.get("name", "")).strip().lower() == needle


# -- formatting ----------------------------------------------------------------


def test_format_bullets() -> None:
    assert format_bullets(["a", "b"]) == "- a\n- b"
    assert format_bullets([]) == ""


def test_format_numbered() -> None:
    assert format_numbered(["a", "b"]) == "1. a\n2. b"
    assert format_numbered([]) == ""


# -- resolve_selection -----------------------------------------------------------


def test_resolve_selection_by_number() -> None:
    candidates = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    resolved, invalid = resolve_selection("2", candidates, _matches_name)

    assert resolved == [{"name": "b"}]
    assert invalid == []


def test_resolve_selection_by_exact_name_case_insensitive() -> None:
    candidates = [{"name": "canvas-14"}, {"name": "canvas-15"}]

    resolved, invalid = resolve_selection("CANVAS-15", candidates, _matches_name)

    assert resolved == [{"name": "canvas-15"}]
    assert invalid == []


def test_resolve_selection_number_out_of_range_is_invalid() -> None:
    candidates = [{"name": "a"}]

    resolved, invalid = resolve_selection("5", candidates, _matches_name)

    assert resolved == []
    assert invalid == ["5"]


def test_resolve_selection_unknown_name_is_invalid() -> None:
    candidates = [{"name": "a"}]

    resolved, invalid = resolve_selection("zzz", candidates, _matches_name)

    assert resolved == []
    assert invalid == ["zzz"]


def test_resolve_selection_comma_separated() -> None:
    candidates = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    resolved, invalid = resolve_selection("1,3", candidates, _matches_name)

    assert resolved == [{"name": "a"}, {"name": "c"}]
    assert invalid == []


def test_resolve_selection_space_separated() -> None:
    candidates = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    resolved, invalid = resolve_selection("1 3", candidates, _matches_name)

    assert resolved == [{"name": "a"}, {"name": "c"}]


def test_resolve_selection_mixed_comma_and_space() -> None:
    candidates = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    resolved, invalid = resolve_selection("1, 3", candidates, _matches_name)

    assert resolved == [{"name": "a"}, {"name": "c"}]


def test_resolve_selection_dedupes_when_number_and_name_hit_same_item() -> None:
    candidates = [{"name": "a"}, {"name": "b"}]

    resolved, invalid = resolve_selection("1,a", candidates, _matches_name)

    assert resolved == [{"name": "a"}]
    assert invalid == []


def test_resolve_selection_partial_invalid() -> None:
    candidates = [{"name": "a"}, {"name": "b"}]

    resolved, invalid = resolve_selection("1,zzz", candidates, _matches_name)

    assert resolved == [{"name": "a"}]
    assert invalid == ["zzz"]


def test_resolve_selection_ambiguous_name_match_is_invalid() -> None:
    # Two candidates share the same name -- an exact-name token can't
    # disambiguate, so it must not silently pick one.
    candidates = [{"name": "dup"}, {"name": "dup"}]

    resolved, invalid = resolve_selection("dup", candidates, _matches_name)

    assert resolved == []
    assert invalid == ["dup"]


def test_resolve_selection_empty_string() -> None:
    candidates = [{"name": "a"}]

    resolved, invalid = resolve_selection("", candidates, _matches_name)

    assert resolved == []
    assert invalid == []


# -- run_delete_flow -------------------------------------------------------------


def _describe(item: dict) -> str:
    return str(item.get("name", "?"))


async def _ok_delete(item: dict) -> str | None:
    return None


async def test_run_delete_flow_no_candidates_is_cancelled() -> None:
    result = await run_delete_flow(
        [],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="",
        confirm=False,
        allow_multiple=False,
        perform_delete=_ok_delete,
    )

    assert result["status"] == "cancelled"


async def test_run_delete_flow_single_candidate_no_confirm_asks_to_confirm() -> None:
    result = await run_delete_flow(
        [{"name": "only"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="",
        confirm=False,
        allow_multiple=False,
        perform_delete=_ok_delete,
    )

    assert result["status"] == "confirmation_required"
    assert "only" in result["message"]
    assert "accept" in result["message"] or "yes" in result["message"]


async def test_run_delete_flow_single_candidate_confirm_deletes() -> None:
    deleted_items = []

    async def _track_delete(item: dict) -> str | None:
        deleted_items.append(item)
        return None

    result = await run_delete_flow(
        [{"name": "only"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="",
        confirm=True,
        allow_multiple=False,
        perform_delete=_track_delete,
    )

    assert result["status"] == "success"
    assert deleted_items == [{"name": "only"}]


async def test_run_delete_flow_single_candidate_delete_refused_is_error() -> None:
    async def _refuse(item: dict) -> str | None:
        return "not empty"

    result = await run_delete_flow(
        [{"name": "only"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="",
        confirm=True,
        allow_multiple=False,
        perform_delete=_refuse,
    )

    assert result["status"] == "error"
    assert "not empty" in result["message"]


async def test_run_delete_flow_multiple_candidates_no_selection_asks_to_select() -> None:
    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="",
        confirm=False,
        allow_multiple=False,
        perform_delete=_ok_delete,
    )

    assert result["status"] == "selection_required"
    assert "1. a" in result["message"]
    assert "2. b" in result["message"]


async def test_run_delete_flow_multiple_candidates_selection_narrows_to_confirm() -> None:
    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="2",
        confirm=False,
        allow_multiple=False,
        perform_delete=_ok_delete,
    )

    assert result["status"] == "confirmation_required"
    assert result["data"]["matches"] == ["b"]


async def test_run_delete_flow_selection_and_confirm_together_deletes() -> None:
    deleted_items = []

    async def _track_delete(item: dict) -> str | None:
        deleted_items.append(item)
        return None

    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="2",
        confirm=True,
        allow_multiple=False,
        perform_delete=_track_delete,
    )

    assert result["status"] == "success"
    assert deleted_items == [{"name": "b"}]


async def test_run_delete_flow_invalid_selection_is_error() -> None:
    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="zzz",
        confirm=False,
        allow_multiple=False,
        perform_delete=_ok_delete,
    )

    assert result["status"] == "error"
    assert "zzz" in result["message"]


async def test_run_delete_flow_disallows_multiple_when_not_allowed() -> None:
    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="1,2",
        confirm=True,
        allow_multiple=False,
        perform_delete=_ok_delete,
    )

    assert result["status"] == "error"
    assert "one" in result["message"].lower()


async def test_run_delete_flow_allows_multiple_when_allowed() -> None:
    deleted_items = []

    async def _track_delete(item: dict) -> str | None:
        deleted_items.append(item)
        return None

    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="1,3",
        confirm=True,
        allow_multiple=True,
        perform_delete=_track_delete,
    )

    assert result["status"] == "success"
    assert deleted_items == [{"name": "a"}, {"name": "c"}]


async def test_run_delete_flow_partial_success_when_some_refused() -> None:
    async def _refuse_b(item: dict) -> str | None:
        return "refused" if item["name"] == "b" else None

    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="1,2",
        confirm=True,
        allow_multiple=True,
        perform_delete=_refuse_b,
    )

    assert result["status"] == "partial"
    assert "a" in result["message"]
    assert "refused" in result["message"]


async def test_run_delete_flow_multiple_candidates_single_only_selection_hint() -> None:
    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="",
        confirm=False,
        allow_multiple=False,
        perform_delete=_ok_delete,
    )

    assert "the number or exact name of the one you want" in result["message"]


async def test_run_delete_flow_multiple_candidates_multi_selection_hint() -> None:
    result = await run_delete_flow(
        [{"name": "a"}, {"name": "b"}],
        matches_exact=_matches_name,
        describe=_describe,
        noun="thing",
        selection="",
        confirm=False,
        allow_multiple=True,
        perform_delete=_ok_delete,
    )

    assert "separated by spaces or commas" in result["message"]
