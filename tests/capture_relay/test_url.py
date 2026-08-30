from __future__ import annotations

import pytest

from mcp_eveng.capture_relay.url import (
    build_pro_capture_url,
    is_community_style_path,
    parse_pro_capture_url,
)


def test_round_trips_all_fields() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="abc.def",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    parsed = parse_pro_capture_url(url)

    assert parsed.container == "Capture-2101248"
    assert parsed.token == "abc.def"
    assert parsed.relay_host == "192.168.1.50"
    assert parsed.relay_port == 8001
    assert parsed.eveng_host == "192.168.1.50"


def test_url_starts_with_capture_scheme_and_relay_host() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    assert url.startswith("capture://192.168.1.50/Capture-2101248/")


def test_url_has_no_query_string_at_all() -> None:
    # Two confirmed-live bugs in a row (& breaking cmd.exe parsing, then
    # =/? apparently truncating the argument before the .bat even saw
    # the rest of it) both traced back to query-string special
    # characters. This format has none left to break.
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    assert "?" not in url
    assert "&" not in url
    assert ";" not in url
    assert "=" not in url


def test_url_carries_no_mode_field() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    assert "mode" not in url


def test_url_never_contains_a_password_field() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    assert "password" not in url.lower() and "pw=" not in url.lower()


def test_url_segments_are_in_the_documented_order() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="abc.def",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.99",
    )

    assert url == "capture://192.168.1.50/Capture-2101248/abc.def/8001/192.168.1.99"


def test_parse_rejects_non_capture_scheme() -> None:
    with pytest.raises(ValueError):
        parse_pro_capture_url("https://192.168.1.50/Capture-2101248/tok/8001/192.168.1.50")


def test_parse_rejects_community_style_vunl_path() -> None:
    # Confirmed live: Community's own vunl<N>_<node>_<if> device names,
    # with no query string and only one path segment. parse_pro_capture_url
    # must refuse it rather than guess.
    with pytest.raises(ValueError):
        parse_pro_capture_url("capture://192.168.1.32/vunl1_6_2")


def test_parse_rejects_community_style_pnet_path() -> None:
    # Confirmed live: the OTHER Community device-name shape, for
    # network/cloud-attached captures.
    with pytest.raises(ValueError):
        parse_pro_capture_url("capture://192.168.1.32/pnet3")


def test_parse_rejects_wrong_segment_count() -> None:
    with pytest.raises(ValueError):
        parse_pro_capture_url("capture://192.168.1.50/Capture-2101248/tok")


def test_parse_rejects_non_numeric_relay_port() -> None:
    with pytest.raises(ValueError):
        parse_pro_capture_url("capture://192.168.1.50/Capture-2101248/tok/notaport/192.168.1.50")


def test_container_name_is_url_escaped_in_the_path() -> None:
    # Defensive -- container names aren't expected to contain characters
    # needing escaping in practice, but the path segment shouldn't break
    # if one ever did.
    url = build_pro_capture_url(
        container="Capture With Space",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    parsed = parse_pro_capture_url(url)
    assert parsed.container == "Capture With Space"


# -- is_community_style_path ---------------------------------------------


def test_is_community_style_path_matches_vunl() -> None:
    assert is_community_style_path("vunl1_6_2") is True


def test_is_community_style_path_matches_pnet() -> None:
    assert is_community_style_path("pnet3") is True


def test_is_community_style_path_is_case_insensitive() -> None:
    assert is_community_style_path("VUNL1_6_2") is True
    assert is_community_style_path("Pnet3") is True


def test_is_community_style_path_does_not_match_our_container_names() -> None:
    assert is_community_style_path("Capture-2101248") is False


def test_is_community_style_path_does_not_match_unrelated_strings() -> None:
    assert is_community_style_path("something-else") is False
    assert is_community_style_path("") is False
