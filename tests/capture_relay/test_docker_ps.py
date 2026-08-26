from __future__ import annotations

from mcp_eveng.capture_relay.docker_ps import parse_docker_ps_output

# Modeled on the real `docker ps` output captured live from a PRO server
# (see CHANGELOG), reformatted as this project's own tab-separated
# --format request would produce it. Docker's own default ordering is
# newest-first; the six rows below are in that same newest-first order.
SAMPLE_OUTPUT_NEWEST_FIRST = (
    "d24266e8c286\tCapture-2099202\t19 seconds ago\tUp 18 seconds\n"
    "e567d998609b\tCapture-2098178\t43 seconds ago\tUp 41 seconds\n"
    "ccf3b58041f7\tCapture-2102273\tAbout a minute ago\tUp About a minute\n"
    "cf6f4ff1f238\tCapture-2102272\tAbout a minute ago\tUp About a minute\n"
    "df05365884c7\tCapture-2101249\tAbout a minute ago\tUp About a minute\n"
    "b60f9be62ee3\tCapture-2101248\t3 minutes ago\tUp 3 minutes\n"
)


def test_parses_all_rows() -> None:
    result = parse_docker_ps_output(SAMPLE_OUTPUT_NEWEST_FIRST)

    assert len(result) == 6


def test_reverses_docker_default_order_to_oldest_first() -> None:
    result = parse_docker_ps_output(SAMPLE_OUTPUT_NEWEST_FIRST)

    # Docker's own output is newest-first (d24266e8c286 first); the
    # parser should hand back oldest-first, so position 1 is the
    # longest-running capture -- b60f9be62ee3 / Capture-2101248.
    assert result[0].container_id == "b60f9be62ee3"
    assert result[0].name == "Capture-2101248"
    assert result[-1].container_id == "d24266e8c286"
    assert result[-1].name == "Capture-2099202"


def test_parses_individual_fields_correctly() -> None:
    result = parse_docker_ps_output(SAMPLE_OUTPUT_NEWEST_FIRST)

    oldest = result[0]
    assert oldest.container_id == "b60f9be62ee3"
    assert oldest.name == "Capture-2101248"
    assert oldest.created_at == "3 minutes ago"
    assert oldest.status == "Up 3 minutes"


def test_empty_output_returns_empty_list() -> None:
    assert parse_docker_ps_output("") == []


def test_blank_lines_are_skipped() -> None:
    output = "\n\nb60f9be62ee3\tCapture-2101248\t3 minutes ago\tUp 3 minutes\n\n"

    result = parse_docker_ps_output(output)

    assert len(result) == 1


def test_malformed_line_with_wrong_field_count_is_skipped_not_raised() -> None:
    output = (
        "b60f9be62ee3\tCapture-2101248\t3 minutes ago\tUp 3 minutes\n"
        "this-line-is-garbled-and-has-no-tabs-at-all\n"
        "df05365884c7\tCapture-2101249\tAbout a minute ago\tUp About a minute\n"
    )

    result = parse_docker_ps_output(output)

    # Only the two well-formed lines survive; the garbled one is
    # dropped, not raised as an error for the whole listing.
    assert len(result) == 2
    assert {c.name for c in result} == {"Capture-2101248", "Capture-2101249"}


def test_windows_style_line_endings_are_handled() -> None:
    output = "b60f9be62ee3\tCapture-2101248\t3 minutes ago\tUp 3 minutes\r\n"

    result = parse_docker_ps_output(output)

    assert len(result) == 1
    assert result[0].status == "Up 3 minutes"
