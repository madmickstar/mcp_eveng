from __future__ import annotations

from unittest.mock import AsyncMock

from mcp_eveng.capture_relay.config import CaptureSSHSettings, CaptureURLSettings
from mcp_eveng.capture_relay.tokens import verify_token
from mcp_eveng.tools import capture

PRO_STATUS = {"status": "success", "data": {"version": "6.5.0-27-PRO"}}
COMMUNITY_STATUS = {"status": "success", "data": {"version": "6.2.0-4"}}

SAMPLE_DOCKER_PS_NEWEST_FIRST = (
    "d24266e8c286\tCapture-2099202\t19 seconds ago\tUp 18 seconds\n"
    "e567d998609b\tCapture-2098178\t43 seconds ago\tUp 41 seconds\n"
    "b60f9be62ee3\tCapture-2101248\t3 minutes ago\tUp 3 minutes\n"
)


def make_client(status=PRO_STATUS) -> AsyncMock:
    client = AsyncMock()
    client.get_status.return_value = status
    return client


def ssh_settings(**overrides) -> CaptureSSHSettings:
    defaults = dict(
        ssh_host="172.16.130.14",
        ssh_username="capture-svc",
        ssh_key_path="/etc/mcp-eveng/capture-relay.key",
        token_secret="s3cret",
    )
    defaults.update(overrides)
    return CaptureSSHSettings(_env_file=None, **defaults)  # type: ignore[call-arg]


def url_settings(**overrides) -> CaptureURLSettings:
    defaults = dict(advertise_host="172.16.130.14")
    defaults.update(overrides)
    return CaptureURLSettings(_env_file=None, **defaults)  # type: ignore[call-arg]


def fake_run_command(output: str):
    async def _run(settings, command) -> str:
        return output

    return _run


# -- edition gating -----------------------------------------------------------


async def test_list_captures_refuses_on_community() -> None:
    client = make_client(COMMUNITY_STATUS)

    result = await capture.list_captures(client, ssh_settings())

    assert result["status"] == "error"
    assert "Community" in result["message"]


async def test_get_capture_refuses_on_community() -> None:
    client = make_client(COMMUNITY_STATUS)

    result = await capture.get_capture(client, ssh_settings(), url_settings(), position=1)

    assert result["status"] == "error"
    assert "Community" in result["message"]


# -- list_captures --------------------------------------------------------------


async def test_list_captures_returns_oldest_first_with_positions() -> None:
    client = make_client()

    result = await capture.list_captures(
        client, ssh_settings(), _run_command=fake_run_command(SAMPLE_DOCKER_PS_NEWEST_FIRST)
    )

    assert result["status"] == "success"
    captures = result["data"]["captures"]
    assert len(captures) == 3
    assert captures[0]["position"] == 1
    assert captures[0]["name"] == "Capture-2101248"  # oldest
    assert captures[-1]["position"] == 3
    assert captures[-1]["name"] == "Capture-2099202"  # newest


async def test_list_captures_empty_is_still_success() -> None:
    client = make_client()

    result = await capture.list_captures(client, ssh_settings(), _run_command=fake_run_command(""))

    assert result["status"] == "success"
    assert result["data"]["captures"] == []


# -- get_capture: input validation -----------------------------------------------


async def test_get_capture_requires_exactly_one_of_position_or_container() -> None:
    client = make_client()

    neither = await capture.get_capture(client, ssh_settings(), url_settings())
    both = await capture.get_capture(
        client, ssh_settings(), url_settings(), position=1, container="Capture-2101248"
    )

    assert neither["status"] == "error"
    assert both["status"] == "error"


async def test_get_capture_errors_when_nothing_running() -> None:
    client = make_client()

    result = await capture.get_capture(
        client, ssh_settings(), url_settings(), position=1, _run_command=fake_run_command("")
    )

    assert result["status"] == "error"


async def test_get_capture_position_out_of_range() -> None:
    client = make_client()

    result = await capture.get_capture(
        client,
        ssh_settings(),
        url_settings(),
        position=99,
        _run_command=fake_run_command(SAMPLE_DOCKER_PS_NEWEST_FIRST),
    )

    assert result["status"] == "error"
    assert "out of range" in result["message"]


# -- get_capture: resolution + token/URL construction ----------------------------


async def test_get_capture_by_position_mints_token_and_url() -> None:
    client = make_client()

    result = await capture.get_capture(
        client,
        ssh_settings(),
        url_settings(),
        position=1,
        _run_command=fake_run_command(SAMPLE_DOCKER_PS_NEWEST_FIRST),
    )

    assert result["status"] == "success"
    assert result["data"]["container"] == "Capture-2101248"  # position 1 = oldest
    assert result["data"]["capture_url"].startswith("capture://172.16.130.14/Capture-2101248?")
    assert "mode=pro" in result["data"]["capture_url"]


async def test_get_capture_by_exact_container_name() -> None:
    client = make_client()

    result = await capture.get_capture(
        client,
        ssh_settings(),
        url_settings(),
        container="Capture-2099202",
        _run_command=fake_run_command(SAMPLE_DOCKER_PS_NEWEST_FIRST),
    )

    assert result["status"] == "success"
    assert result["data"]["container"] == "Capture-2099202"


async def test_get_capture_by_container_id_prefix() -> None:
    client = make_client()

    result = await capture.get_capture(
        client,
        ssh_settings(),
        url_settings(),
        container="d24266e8",
        _run_command=fake_run_command(SAMPLE_DOCKER_PS_NEWEST_FIRST),
    )

    assert result["status"] == "success"
    assert result["data"]["container"] == "Capture-2099202"


async def test_get_capture_unknown_container_errors() -> None:
    client = make_client()

    result = await capture.get_capture(
        client,
        ssh_settings(),
        url_settings(),
        container="does-not-exist",
        _run_command=fake_run_command(SAMPLE_DOCKER_PS_NEWEST_FIRST),
    )

    assert result["status"] == "error"


async def test_get_capture_token_verifies_against_the_resolved_container() -> None:
    client = make_client()
    settings = ssh_settings(token_secret="the-shared-secret")

    result = await capture.get_capture(
        client,
        settings,
        url_settings(),
        position=1,
        _run_command=fake_run_command(SAMPLE_DOCKER_PS_NEWEST_FIRST),
    )

    from mcp_eveng.capture_relay.url import parse_pro_capture_url

    parsed_url = parse_pro_capture_url(result["data"]["capture_url"])
    verified = verify_token(parsed_url.token, "the-shared-secret")
    assert verified.container == "Capture-2101248"


async def test_get_capture_expires_in_seconds_matches_settings() -> None:
    client = make_client()
    settings = ssh_settings(token_ttl_seconds=30)

    result = await capture.get_capture(
        client,
        settings,
        url_settings(),
        position=1,
        _run_command=fake_run_command(SAMPLE_DOCKER_PS_NEWEST_FIRST),
    )

    assert result["data"]["expires_in_seconds"] == 30
