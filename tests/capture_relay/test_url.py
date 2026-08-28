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


def test_url_starts_with_capture_scheme() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    assert url.startswith("capture://192.168.1.50/Capture-2101248?")


def test_url_uses_semicolon_not_ampersand_as_query_separator() -> None:
    # Regression test: confirmed live that & broke the .bat's parsing --
    # cmd.exe (always the interpreter for a .bat, however it's invoked)
    # treats an unescaped & as a command separator. ; isn't one of
    # cmd.exe's special characters.
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    query = url.split("?", 1)[1]
    assert "&" not in query
    assert ";" in query


def test_url_carries_no_mode_field() -> None:
    # Mode detection moved to path-pattern matching (see
    # is_community_style_path) -- there's no artificial mode= field to
    # get wrong in the first place.
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    assert "mode=" not in url


def test_url_never_contains_a_password_field() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="192.168.1.50",
        relay_port=8001,
        eveng_host="192.168.1.50",
    )

    assert "password" not in url.lower() and "pw=" not in url.lower()


def test_parse_rejects_non_capture_scheme() -> None:
    with pytest.raises(ValueError):
        parse_pro_capture_url("https://192.168.1.50/Capture-2101248?token=x;relay_port=8001;eveng_host=x")


def test_parse_rejects_community_style_vunl_path() -> None:
    # Confirmed live: Community's own vunl<N>_<node>_<if> device names,
    # with no query string at all. parse_pro_capture_url must refuse it
    # rather than guess.
    with pytest.raises(ValueError):
        parse_pro_capture_url("capture://192.168.1.32/vunl1_6_2")


def test_parse_rejects_community_style_pnet_path() -> None:
    # Confirmed live: the OTHER Community device-name shape, for
    # network/cloud-attached captures.
    with pytest.raises(ValueError):
        parse_pro_capture_url("capture://192.168.1.32/pnet3")


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
