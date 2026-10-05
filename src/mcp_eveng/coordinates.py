"""Canvas coordinate (`left`/`top`) normalization shared by the node and network tools.

EVE-NG's REST API takes canvas positions as strings (e.g. ``"380"``, and
even percentages like ``"35%"``). AI agents very commonly send plain
integers instead, which the tool schemas used to reject outright with a
pydantic validation error that agents then ignored and repeated. Tools now
accept either, and this converts an integer to the string EVE-NG expects.
"""

from __future__ import annotations


def normalize_coordinate(value: str | int | None) -> str | None:
    """Return `value` as the string EVE-NG expects.

    - ``None`` stays ``None`` (meaning "not supplied").
    - An ``int`` becomes its decimal string (``77`` -> ``"77"``).
    - A ``str`` is passed through unchanged (``"380"``, ``"35%"``).
    - A ``bool`` is rejected: it is an ``int`` subclass in Python, so it
      would otherwise silently become ``"True"``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"canvas position must be an integer or numeric string, not a boolean: {value!r}")
    if isinstance(value, int):
        return str(value)
    return value
