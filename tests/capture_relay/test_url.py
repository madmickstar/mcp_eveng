from __future__ import annotations

import pytest

from mcp_eveng.capture_relay.url import build_pro_capture_url, parse_pro_capture_url


def test_round_trips_all_fields() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="abc.def",
        relay_host="172.16.130.14",
        relay_port=8001,
        eveng_host="172.16.130.14",
    )

    parsed = parse_pro_capture_url(url)

    assert parsed.container == "Capture-2101248"
    assert parsed.token == "abc.def"
    assert parsed.relay_host == "172.16.130.14"
    assert parsed.relay_port == 8001
    assert parsed.eveng_host == "172.16.130.14"


def test_url_starts_with_capture_scheme() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="172.16.130.14",
        relay_port=8001,
        eveng_host="172.16.130.14",
    )

    assert url.startswith("capture://172.16.130.14/Capture-2101248?")


def test_url_carries_mode_pro_explicitly() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="172.16.130.14",
        relay_port=8001,
        eveng_host="172.16.130.14",
    )

    assert "mode=pro" in url


def test_url_never_contains_a_password_field() -> None:
    url = build_pro_capture_url(
        container="Capture-2101248",
        token="tok",
        relay_host="172.16.130.14",
        relay_port=8001,
        eveng_host="172.16.130.14",
    )

    assert "password" not in url.lower() and "pw=" not in url.lower()


def test_parse_rejects_non_capture_scheme() -> None:
    with pytest.raises(ValueError):
        parse_pro_capture_url("https://172.16.130.14/Capture-2101248?mode=pro")


def test_parse_rejects_community_style_link_with_no_mode() -> None:
    # The existing, unmodified Community link format -- two path
    # segments, no query string at all. parse_pro_capture_url must
    # refuse it rather than guess, since it's not a PRO-mode link.
    with pytest.raises(ValueError):
        parse_pro_capture_url("capture://192.168.1.32/vunl1_6_2")


def test_container_name_is_url_escaped_in_the_path() -> None:
    # Defensive -- container names aren't expected to contain characters
    # needing escaping in practice, but the path segment shouldn't break
    # if one ever did.
    url = build_pro_capture_url(
        container="Capture With Space",
        token="tok",
        relay_host="172.16.130.14",
        relay_port=8001,
        eveng_host="172.16.130.14",
    )

    parsed = parse_pro_capture_url(url)
    assert parsed.container == "Capture With Space"
