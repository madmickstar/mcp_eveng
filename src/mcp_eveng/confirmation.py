"""Shared selection/confirmation state machine for the delete tools.

Every delete tool follows the same stateless, up-to-three-call protocol (no
MCP host capability required -- Claude Desktop doesn't support MCP
elicitation, see README):

  1. Call with just the search string. Nothing is deleted.
     - No matches: reported, nothing else happens.
     - Exactly one match: reported as a 1-item numbered list; call again
       with confirm=true to delete it.
     - More than one match: the full numbered list is reported (status
       "selection_required"); call again with `selection` set to the
       number(s) and/or exact name(s) of the item(s) you want.
  2. (only if there were multiple matches) Call again with `selection`
     set. The search is re-run fresh and `selection` is resolved against
     the current results; the resolved item(s) are reported back as a new
     numbered list (status "confirmation_required"); call again with the
     same `selection` plus confirm=true to delete them.
  3. Call again with confirm=true (and the same `selection`, if one was
     used) to actually delete.

Every call re-runs the search from scratch -- nothing is ever deleted
based on stale/cached state from an earlier call.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Sequence


def format_bullets(items: Sequence[str]) -> str:
    """Render a plain bullet list, e.g. for a "folder not empty" contents listing."""
    return "\n".join(f"- {item}" for item in items)


def format_numbered(items: Sequence[str]) -> str:
    """Render a plain numbered list, e.g. for a "here's what matched" listing."""
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))


def resolve_selection(
    selection: str,
    candidates: Sequence[dict[str, Any]],
    matches_exact: Callable[[dict[str, Any], str], bool],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve a `selection` string against the current `candidates`.

    Each token -- separated by commas and/or whitespace -- is either a
    1-based list number, or an exact (case-insensitive) name/path match
    via `matches_exact(candidate, lowercased_token)`. Returns
    `(resolved_items, invalid_tokens)`: resolved_items preserves
    first-seen order with duplicates removed; invalid_tokens is every
    token that didn't resolve to exactly one item (not found, or
    ambiguous).
    """
    tokens = [t for t in re.split(r"[,\s]+", selection.strip()) if t]
    resolved: list[dict[str, Any]] = []
    invalid: list[str] = []
    for token in tokens:
        item: dict[str, Any] | None = None
        if token.isdigit():
            index = int(token)
            if 1 <= index <= len(candidates):
                item = candidates[index - 1]
        if item is None:
            needle = token.strip().lower()
            name_matches = [c for c in candidates if matches_exact(c, needle)]
            if len(name_matches) == 1:
                item = name_matches[0]
        if item is None:
            invalid.append(token)
        elif item not in resolved:
            resolved.append(item)
    return resolved, invalid


async def run_delete_flow(
    candidates: Sequence[dict[str, Any]],
    *,
    matches_exact: Callable[[dict[str, Any], str], bool],
    describe: Callable[[dict[str, Any]], str],
    noun: str,
    selection: str,
    confirm: bool,
    allow_multiple: bool,
    perform_delete: Callable[[dict[str, Any]], Awaitable[str | None]],
) -> dict[str, Any]:
    """Drive the search -> select -> confirm -> delete state machine.

    `candidates` must already be this call's fresh substring-search
    results. `perform_delete` actually deletes one item and returns None
    on success, or a short reason string if it refused (e.g. "not empty")
    -- that item is then reported as skipped rather than deleted.

    Never raises for ordinary user-input problems (invalid selection,
    ambiguity, asking to delete more than one where that's not allowed);
    those come back as a normal error/selection_required/
    confirmation_required response instead.
    """
    if not candidates:
        return {"status": "cancelled", "message": f"No {noun} found; nothing was deleted."}

    labels = [describe(c) for c in candidates]

    if selection.strip():
        resolved, invalid = resolve_selection(selection, candidates, matches_exact)
        if invalid or not resolved:
            bad = ", ".join(invalid) if invalid else selection
            return {
                "status": "error",
                "message": (
                    f"Could not match {bad!r} to any current {noun}. Current matches:\n"
                    f"{format_numbered(labels)}"
                ),
                "data": {"matches": labels},
            }
        if not allow_multiple and len(resolved) > 1:
            return {
                "status": "error",
                "message": (
                    f"Only one {noun} can be deleted at a time here. Pick exactly one:\n"
                    f"{format_numbered(labels)}"
                ),
                "data": {"matches": labels},
            }
        target = resolved
    elif len(candidates) == 1:
        target = list(candidates)
    else:
        plural = "s" if len(labels) != 1 else ""
        how = (
            "the number(s) or exact name(s), separated by spaces or commas,"
            if allow_multiple
            else "the number or exact name of the one you want"
        )
        return {
            "status": "selection_required",
            "message": (
                f"{len(labels)} {noun}{plural} match:\n{format_numbered(labels)}\n\n"
                f"Reply with {how} to select, then confirm."
            ),
            "data": {"matches": labels},
        }

    target_labels = [describe(t) for t in target]

    if not confirm:
        plural = "s" if len(target_labels) != 1 else ""
        return {
            "status": "confirmation_required",
            "message": (
                f"{format_numbered(target_labels)}\n\n"
                f"Reply 'accept' or 'yes' to delete the above {noun}{plural}."
            ),
            "data": {"matches": target_labels},
        }

    deleted: list[str] = []
    skipped: list[tuple[str, str]] = []
    for item in target:
        reason = await perform_delete(item)
        if reason is None:
            deleted.append(describe(item))
        else:
            skipped.append((describe(item), reason))

    if skipped:
        detail = "\n\n".join(f"{label}: {reason}" for label, reason in skipped)
        message = (
            (f"Deleted: {', '.join(deleted)}. " if deleted else "")
            + f"The following could not be deleted:\n{detail}"
        )
        return {"status": "partial" if deleted else "error", "message": message}

    plural = "s" if len(deleted) != 1 else ""
    return {
        "status": "success",
        "message": f"Deleted {len(deleted)} {noun}{plural}: {', '.join(deleted)}.",
    }
