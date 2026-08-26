"""Shared helpers for case-insensitive substring search over EVE-NG list responses.

EVE-NG's "list X" endpoints return `data` in one of two shapes depending on
the endpoint: a dict keyed by id/name (e.g. node templates, users), or a
list of records (e.g. folders, labs). `iter_named_records` normalizes
either shape into `(name, record)` pairs so callers don't need to care
which one a given endpoint uses.

All matching here is a case-insensitive SUBSTRING match on name/path only
-- never on an id -- so delete tools let you type a fragment rather than
the full exact value, and never delete something just because its
internal id happened to match. Because a substring can match more than
one item, every delete tool using these helpers goes through the
search -> select -> confirm flow in `confirmation.py` before anything is
actually deleted.
"""

from __future__ import annotations

from typing import Any


def iter_named_records(data: Any, name_field: str) -> list[tuple[str, dict[str, Any]]]:
    """Normalize a list-endpoint's `data` into `(name, record)` pairs.

    For a dict-shaped response, the outer key is preserved on the record as
    `_key` (falling back to it for `name` too) in case the endpoint doesn't
    repeat an id/name inside the value itself.
    """
    if isinstance(data, dict):
        items: list[tuple[str, dict[str, Any]]] = []
        for key, value in data.items():
            if isinstance(value, dict):
                record = dict(value)
                record.setdefault("_key", key)
                name = record.get(name_field, key)
                items.append((str(name), record))
        return items
    if isinstance(data, list):
        return [(str(item.get(name_field, "")), item) for item in data if isinstance(item, dict)]
    return []


def find_by_name_case_insensitive(
    records: list[tuple[str, dict[str, Any]]], target: str
) -> list[dict[str, Any]]:
    """Case-insensitive substring match of `target` against record names."""
    needle = target.strip().lower()
    return [record for name, record in records if needle in name.strip().lower()]

