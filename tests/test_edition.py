from __future__ import annotations

from mcp_eveng.edition import is_pro_edition


def test_is_pro_edition_true_for_pro_suffix() -> None:
    assert is_pro_edition({"version": "6.5.0-27-PRO"}) is True
    assert is_pro_edition({"version": "6.5.0-27-pro"}) is True  # case-insensitive


def test_is_pro_edition_true_for_confirmed_live_pro_version_string() -> None:
    # Confirmed live against a real PRO server this session.
    assert is_pro_edition({"version": "6.5.0-27-PRO"}) is True


def test_is_pro_edition_false_for_confirmed_live_community_version_string() -> None:
    # Confirmed live against a real Community server this session.
    assert is_pro_edition({"version": "6.2.0-4"}) is False


def test_is_pro_edition_false_for_community_or_missing() -> None:
    assert is_pro_edition({"version": "6.5.0-27"}) is False
    assert is_pro_edition({}) is False
    assert is_pro_edition({"version": ""}) is False
