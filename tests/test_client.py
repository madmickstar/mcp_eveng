from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from mcp_eveng.client import EvengClient
from mcp_eveng.exceptions import EvengAPIError, EvengAuthError, EvengNotFoundError


async def test_login_success(client: EvengClient, base_url: str, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/login",
        json={"code": 200, "status": "success", "message": "User logged in (90013)."},
    )

    result = await client.login()

    assert result["status"] == "success"
    assert client._authenticated is True


async def test_login_failure_raises_auth_error(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/login",
        status_code=401,
        json={"code": 401, "status": "unauthorized", "message": "Login failed"},
    )

    with pytest.raises(EvengAuthError):
        await client.login()


async def test_get_status_returns_data(client: EvengClient, base_url: str, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        json={
            "code": 200,
            "status": "success",
            "data": {"cpu": 1, "mem": 8, "version": "development"},
            "message": "Fetched system status (60001).",
        },
    )

    result = await client.get_status()

    assert result["data"]["version"] == "development"


async def test_not_found_raises_not_found_error(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/labs/User1/Missing.unl",
        status_code=404,
        json={"code": 404, "status": "fail", "message": "Requested lab does not exist (60008)."},
    )

    with pytest.raises(EvengNotFoundError):
        await client.get_lab("/User1/Missing.unl")


async def test_generic_api_error(client: EvengClient, base_url: str, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs",
        status_code=400,
        json={"code": 400, "status": "fail", "message": "Bad request"},
    )

    with pytest.raises(EvengAPIError):
        await client.create_lab("/User1", "Lab X")


async def test_500_with_no_json_body_suggests_stale_lock_file(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # EVE-NG's own generic 500 error pages aren't JSON, unlike its normal
    # JSend error responses -- this is the case a stale lock file from an
    # earlier interrupted request typically produces.
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs/User1/Lab%201.unl/nodes",
        status_code=500,
        content=b"<html>Internal Server Error</html>",
    )

    with pytest.raises(EvengAPIError) as exc_info:
        await client.add_lab_node("/User1/Lab 1.unl", node_type="qemu", template="linux")

    message = str(exc_info.value)
    assert "500" in message
    assert "find /opt/unetlab/labs/ -name '*.lock'" in message
    assert "find /opt/unetlab/labs/ -name '*.lock' -exec rm {} \\;" in message
    assert exc_info.value.code == 500


async def test_5xx_with_no_json_body_also_suggests_stale_lock_file(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # Not just literally 500 -- any 5xx with an unparseable body gets the
    # same guidance, since a stale lock can plausibly surface as other
    # 5xx codes depending on what's in front of EVE-NG.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        status_code=503,
        content=b"Service Unavailable",
    )

    with pytest.raises(EvengAPIError) as exc_info:
        await client.get_status()

    assert "find /opt/unetlab/labs/ -name '*.lock'" in str(exc_info.value)


async def test_4xx_with_no_json_body_does_not_get_lock_file_message(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # A 4xx with no JSON body is a different failure mode (e.g. a
    # misconfigured reverse proxy) -- must not get the 5xx-specific advice,
    # and should still raise (via response.raise_for_status()) rather than
    # silently succeed.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        status_code=404,
        content=b"Not Found",
    )

    with pytest.raises(Exception) as exc_info:
        await client.get_status()

    assert "lock" not in str(exc_info.value).lower()


async def test_401_triggers_relogin_and_retries(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # First call to /status: session expired.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        status_code=401,
        json={"code": 401, "status": "unauthorized", "message": "Session timed out"},
    )
    # The client should transparently log back in...
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/login",
        json={"code": 200, "status": "success", "message": "User logged in (90013)."},
    )
    # ...and retry the original request.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        json={"code": 200, "status": "success", "data": {"version": "development"}, "message": "ok"},
    )

    result = await client.get_status()

    assert result["data"]["version"] == "development"
    assert client._authenticated is True


async def test_400_unauthorized_also_triggers_relogin_and_retries(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # Regression test: EVE-NG's own documentation defines "unauthorized"
    # for BOTH a bare 401 ("should login") AND 400 ("session has timed
    # out") -- e.g. from the same account logging in elsewhere, since
    # EVE-NG only allows one active session per user. This project
    # previously only checked for a bare 401, missing this documented
    # 400 case entirely.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        status_code=400,
        json={"code": 400, "status": "unauthorized", "message": "Session timed out"},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/login",
        json={"code": 200, "status": "success", "message": "User logged in (90013)."},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        json={"code": 200, "status": "success", "data": {"version": "development"}, "message": "ok"},
    )

    result = await client.get_status()

    assert result["data"]["version"] == "development"
    assert client._authenticated is True


async def test_unauthorized_still_after_relogin_raises_auth_error(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # If it's STILL unauthorized after a fresh relogin, that's a genuine,
    # non-recoverable auth problem (e.g. wrong credentials) -- must not
    # loop forever, and must surface a clear error.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        status_code=400,
        json={"code": 400, "status": "unauthorized", "message": "Session timed out"},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/login",
        json={"code": 200, "status": "success", "message": "User logged in (90013)."},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/status",
        status_code=400,
        json={"code": 400, "status": "unauthorized", "message": "Session timed out"},
    )

    with pytest.raises(EvengAuthError):
        await client.get_status()


async def test_generic_400_fail_also_triggers_one_relogin_retry(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # The actual real-world case, confirmed live via a timestamped EVE-NG
    # server audit log: a session invalidated by the same account logging
    # in elsewhere comes back as a bare 400 with a *generic* "fail"
    # status and EVE-NG's generic "Request not valid (60027)" message --
    # not self-identifying as "unauthorized" in the body at all. Still
    # must trigger exactly one relogin-and-retry.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/labs/User1/Lab%201.unl/nodes/3/stop",
        status_code=400,
        json={"code": 60027, "status": "fail", "message": "Request not valid (60027)."},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/login",
        json={"code": 200, "status": "success", "message": "User logged in (90013)."},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/labs/User1/Lab%201.unl/nodes/3/stop",
        json={"code": 200, "status": "success", "message": "Node stopped (80051)."},
    )

    result = await client.stop_node("/User1/Lab 1.unl", 3)

    assert result["message"] == "Node stopped (80051)."


async def test_genuine_validation_400_reproduces_same_error_after_retry(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # A real, non-auth-related 400 (bad parameters) still gets one
    # wasted relogin-retry under the broadened check -- accepted
    # trade-off -- but must surface the SAME final error, not something
    # different or a silent success.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/list/templates/bogus-template",
        status_code=400,
        json={"code": 60033, "status": "fail", "message": "Requested template is not valid (60033)."},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/login",
        json={"code": 200, "status": "success", "message": "User logged in (90013)."},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/list/templates/bogus-template",
        status_code=400,
        json={"code": 60033, "status": "fail", "message": "Requested template is not valid (60033)."},
    )

    with pytest.raises(EvengAPIError) as exc_info:
        await client.get_node_template("bogus-template")

    assert "not valid" in str(exc_info.value).lower()


async def test_ensure_authenticated_only_logs_in_once(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/login",
        json={"code": 200, "status": "success", "message": "User logged in (90013)."},
    )

    await client.ensure_authenticated()
    await client.ensure_authenticated()  # should be a no-op the second time

    requests = httpx_mock.get_requests(url=f"{base_url}/auth/login")
    assert len(requests) == 1


async def test_add_lab_node_sends_expected_payload(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs/User1/Lab%201.unl/nodes",
        status_code=201,
        json={"code": 201, "status": "success", "message": "Lab has been saved (60023)."},
    )

    await client.add_lab_node(
        "/User1/Lab 1.unl",
        node_type="iol",
        template="iol",
        name="R1",
        ethernet=2,
    )

    request = httpx_mock.get_requests()[0]
    body = json.loads(request.content)
    assert body["type"] == "iol"
    assert body["template"] == "iol"
    assert body["name"] == "R1"
    assert body["ethernet"] == 2
    assert "image" not in body  # omitted because it was left as None
    # "left"/"top" must NEVER be omitted -- see the regression test below.
    assert body["left"] == "0"
    assert body["top"] == "0"


async def test_add_lab_node_never_omits_left_and_top(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # Regression test for a real bug found live against an EVE-NG PRO
    # server: EVE-NG's own api_nodes.php (apiAddLabNode) reads
    # $_POST['left'] with no isset() check, so omitting it from the
    # request body throws "Undefined array key 'left'" server-side --
    # promoted to a fatal ErrorException by EVE-NG's error handler,
    # producing a 500 with no JSON body. Confirmed via the server's own
    # error log. "left"/"top" must always be present, unlike every other
    # optional field on this call.
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs/User1/Lab%201.unl/nodes",
        status_code=201,
        json={"code": 201, "status": "success", "message": "Lab has been saved (60023)."},
    )

    await client.add_lab_node("/User1/Lab 1.unl", node_type="qemu", template="viosl2")

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert "left" in body
    assert "top" in body
    assert body["left"] == "0"
    assert body["top"] == "0"


async def test_add_lab_node_left_and_top_can_still_be_overridden(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs/User1/Lab%201.unl/nodes",
        status_code=201,
        json={"code": 201, "status": "success", "message": "Lab has been saved (60023)."},
    )

    await client.add_lab_node(
        "/User1/Lab 1.unl", node_type="qemu", template="viosl2", left="35%", top="25%"
    )

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["left"] == "35%"
    assert body["top"] == "25%"


async def test_edit_lab_node_sends_only_supplied_fields(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="PUT",
        url=f"{base_url}/labs/User1/Lab%201.unl/nodes/9",
        status_code=200,
        json={"code": 200, "status": "success", "message": "Node has been saved (60024)."},
    )

    await client.edit_lab_node("/User1/Lab 1.unl", 9, name="RingSW1")

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body == {"name": "RingSW1"}


async def test_add_lab_network_never_omits_left_and_top(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # Regression test for a real bug found live against an EVE-NG PRO
    # server: omitting "left"/"top" from the network-creation payload
    # doesn't produce a clean error like add_lab_node's version of this
    # bug does -- EVE-NG reports 201 Created with a plausible id, but the
    # network never actually persists (confirmed: doesn't show up in
    # list_lab_networks, get_lab_topology, or a direct by-id lookup,
    # immediately or later). "left"/"top" must always be present, unlike
    # every other optional field on this call.
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs/User1/Lab%201.unl/networks",
        status_code=201,
        json={"code": 201, "status": "success", "message": "Network has been added (60006).", "data": {"id": 1}},
    )

    await client.add_lab_network("/User1/Lab 1.unl", "bridge")

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert "left" in body
    assert "top" in body
    assert body["left"] == "0"
    assert body["top"] == "0"


async def test_add_lab_network_left_and_top_can_still_be_overridden(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs/User1/Lab%201.unl/networks",
        status_code=201,
        json={"code": 201, "status": "success", "message": "Network has been added (60006).", "data": {"id": 1}},
    )

    await client.add_lab_network("/User1/Lab 1.unl", "bridge", left="380", top="153")

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["left"] == "380"
    assert body["top"] == "153"


async def test_add_lab_network_sends_every_field_the_gui_sends(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # Regression test for a real bug found live: only sending
    # type/left/top/name (even with left/top always present, the fix
    # applied first) still silently failed to persist. Comparing two
    # networks created directly through EVE-NG's own GUI (one visible,
    # one hidden, left behind specifically for this comparison) against
    # what this project's request was sending revealed 10 more fields the
    # GUI always sends that this project didn't. This locks in that every
    # one of them is present, with the GUI's own observed defaults for the
    # "visible" network of the pair.
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs/User1/Lab%201.unl/networks",
        status_code=201,
        json={"code": 201, "status": "success", "message": "Network has been added (60006).", "data": {"id": 1}},
    )

    await client.add_lab_network("/User1/Lab 1.unl", "bridge")

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["style"] == "Solid"
    assert body["icon"] == "01-Cloud-Default.svg"
    assert body["width"] == 0
    assert body["linkstyle"] == "Straight"
    assert body["color"] == ""
    assert body["label"] == ""
    assert body["visibility"] == 1
    assert body["hideme"] == 0
    assert body["native_vlan"] == 1
    assert body["smart"] == 0
    assert body["pnet_out"] == ""
    # count/id are server-assigned -- never part of a create request.
    assert "count" not in body
    assert "id" not in body


async def test_add_lab_network_hideme_can_be_overridden(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/labs/User1/Lab%201.unl/networks",
        status_code=201,
        json={"code": 201, "status": "success", "message": "Network has been added (60006).", "data": {"id": 1}},
    )

    await client.add_lab_network("/User1/Lab 1.unl", "bridge", hideme=1)

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["hideme"] == 1


async def test_edit_lab_network_sends_only_supplied_fields(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="PUT",
        url=f"{base_url}/labs/User1/Lab%201.unl/networks/7",
        status_code=200,
        json={"code": 200, "status": "success", "message": "Network has been saved (60007)."},
    )

    await client.edit_lab_network("/User1/Lab 1.unl", 7, visibility=0)

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body == {"visibility": 0}


async def test_set_node_interface_sends_index_to_network_id_mapping(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="PUT",
        url=f"{base_url}/labs/User1/Lab%201.unl/nodes/1/interfaces",
        status_code=200,
        json={"code": 200, "status": "success", "message": "Interfaces has been saved (60031)."},
    )

    await client.set_node_interface("/User1/Lab 1.unl", 1, 0, 7)

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body == {"0": "7"}


async def test_context_manager_closes_owned_client(eveng_settings) -> None:
    async with EvengClient(settings=eveng_settings) as c:
        assert c._http.is_closed is False
    assert c._http.is_closed is True


# -- list_all_labs: recursion + loop safety ----------------------------------


async def test_list_all_labs_walks_the_whole_tree(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "..", "path": "/.."}, {"name": "A", "path": "/A"}],
                "labs": [{"file": "root.unl", "path": "/root.unl"}],
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "..", "path": "/"}],
                "labs": [{"file": "a.unl", "path": "/A/a.unl"}],
            },
        },
    )

    labs = await client.list_all_labs("/")

    paths = {lab["path"] for lab in labs}
    assert paths == {"/root.unl", "/A/a.unl"}
    # Exactly two folder requests: "/" and "/A" -- the ".." entries were
    # never followed, so no third (or more) request happened.
    assert len(httpx_mock.get_requests()) == 2


async def test_list_all_labs_never_revisits_a_folder(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # Defense in depth: even if a folder listing (hypothetically, due to a
    # future/unexpected API response) referenced a folder already visited
    # -- not just literally named ".." -- the visited-set must still stop
    # it from being queued again.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={
            "status": "success",
            "data": {
                # "Self" is not named ".." but points right back at "/".
                "folders": [{"name": "Self", "path": "/"}, {"name": "A", "path": "/A"}],
                "labs": [],
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A",
        json={"status": "success", "data": {"folders": [], "labs": [{"file": "a.unl", "path": "/A/a.unl"}]}},
    )

    labs = await client.list_all_labs("/")

    assert {lab["path"] for lab in labs} == {"/A/a.unl"}
    # "/" was only ever requested once, despite being referenced as its own child.
    assert len(httpx_mock.get_requests()) == 2


async def test_list_all_labs_deduplicates_labs_by_path(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    # Mirrors EVE-NG's real "/Running" virtual folder, which lists labs that
    # also appear at their real location.
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "Running", "path": "/Running"}],
                "labs": [{"file": "root.unl", "path": "/root.unl"}],
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/Running",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "..", "path": "/"}],
                "labs": [{"file": "root.unl", "path": "/root.unl"}],
            },
        },
    )

    labs = await client.list_all_labs("/")

    assert len(labs) == 1
    assert labs[0]["path"] == "/root.unl"


async def test_list_all_labs_respects_max_depth(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={
            "status": "success",
            "data": {"folders": [{"name": "A", "path": "/A"}], "labs": []},
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A",
        json={
            "status": "success",
            "data": {"folders": [{"name": "B", "path": "/A/B"}], "labs": [{"file": "a.unl", "path": "/A/a.unl"}]},
        },
    )
    # "/A/B" would 404/never be requested since max_depth=1 stops before descending into it.

    labs = await client.list_all_labs("/", max_depth=1)

    assert {lab["path"] for lab in labs} == {"/A/a.unl"}
    assert len(httpx_mock.get_requests()) == 2


async def test_list_all_labs_respects_max_folders(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "A", "path": "/A"}, {"name": "B", "path": "/B"}],
                "labs": [],
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A",
        json={"status": "success", "data": {"folders": [], "labs": [{"file": "a.unl", "path": "/A/a.unl"}]}},
    )
    # "/B" is never requested because max_folders=2 ("/" and "/A") is hit first.

    labs = await client.list_all_labs("/", max_folders=2)

    assert len(httpx_mock.get_requests()) == 2
    assert {lab["path"] for lab in labs} == {"/A/a.unl"}


# -- list_all_folders: recursion + loop safety -------------------------------


async def test_list_all_folders_walks_the_whole_tree(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "..", "path": "/.."}, {"name": "A", "path": "/A"}],
                "labs": [],
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "..", "path": "/"}, {"name": "B", "path": "/A/B"}],
                "labs": [],
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A/B",
        json={"status": "success", "data": {"folders": [{"name": "..", "path": "/A"}], "labs": []}},
    )

    folders = await client.list_all_folders("/")

    paths = {f["path"] for f in folders}
    assert paths == {"/A", "/A/B"}
    assert len(httpx_mock.get_requests()) == 3


async def test_list_all_folders_never_revisits_a_folder(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "Self", "path": "/"}, {"name": "A", "path": "/A"}],
                "labs": [],
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A",
        json={"status": "success", "data": {"folders": [{"name": "..", "path": "/"}], "labs": []}},
    )

    folders = await client.list_all_folders("/")

    assert {f["path"] for f in folders} == {"/A"}
    assert len(httpx_mock.get_requests()) == 2


async def test_list_all_folders_respects_max_depth(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={"status": "success", "data": {"folders": [{"name": "A", "path": "/A"}], "labs": []}},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A",
        json={"status": "success", "data": {"folders": [{"name": "B", "path": "/A/B"}], "labs": []}},
    )
    # "/A/B" is never requested because max_depth=1 stops before descending into it.

    folders = await client.list_all_folders("/", max_depth=1)

    assert {f["path"] for f in folders} == {"/A", "/A/B"}
    assert len(httpx_mock.get_requests()) == 2


async def test_list_all_folders_respects_max_folders(
    client: EvengClient, base_url: str, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/",
        json={
            "status": "success",
            "data": {
                "folders": [{"name": "A", "path": "/A"}, {"name": "B", "path": "/B"}],
                "labs": [],
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/folders/A",
        json={"status": "success", "data": {"folders": [], "labs": []}},
    )
    # "/B" is never requested because max_folders=2 ("/" and "/A") is hit first.

    folders = await client.list_all_folders("/", max_folders=2)

    assert len(httpx_mock.get_requests()) == 2
    assert {f["path"] for f in folders} == {"/A", "/B"}
