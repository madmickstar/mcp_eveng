"""Async client for the EVENG REST API.

Reference: https://www.eve-ng.net/index.php/how-to-eve-ng-api/

EVENG speaks JSend: every response is a JSON object with a `status` field
("success", "fail", "error", "unauthorized", "forbidden") a `message`, and
an optional `data` payload. Authentication is cookie/session based -- you
POST credentials to `/api/auth/login` and reuse the returned session cookie
for every subsequent call.

Per EVE-NG's own documentation, "unauthorized" covers two distinct HTTP
codes with the same meaning: a bare 401 ("user should login") and 400
("user session has timed out") -- notably including a session invalidated
by the same account logging in elsewhere, since EVE-NG only allows one
active session per user ("If the same user login twice, the second login
disable the first one."). This client transparently relogins and retries
once whenever either HTTP status code comes back -- trusting the status
code itself, not the response body's own JSend `status` field, since a
session invalidated this way is confirmed live (server audit log,
timestamped) to come back as a bare 400 with a *generic* `"fail"` status
and EVE-NG's generic "Request not valid" message, not self-identifying
as an auth problem in the body at all.

This client owns a single `httpx.AsyncClient` (with cookie jar) per
instance, exposes an async context manager for lifecycle management, and
transparently (re)authenticates on first use.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from .config import EvengSettings, get_eveng_settings
from .exceptions import EvengAPIError, EvengAuthError, EvengError, EvengNotFoundError

JsonDict = dict[str, Any]


def _quote_path(path: str) -> str:
    """URL-encode a folder/lab path, preserving the '/' separators."""
    return quote(path, safe="/")


class EvengClient:
    """Thin async wrapper around the EVENG REST API."""

    def __init__(self, settings: EvengSettings | None = None, *, client: httpx.AsyncClient | None = None):
        self._settings = settings or get_eveng_settings()
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=self._settings.timeout_seconds,
            verify=self._settings.verify_ssl,
        )
        self._authenticated = False

    # -- lifecycle -----------------------------------------------------

    async def __aenter__(self) -> "EvengClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    # -- core request plumbing -----------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: JsonDict | None = None,
        params: JsonDict | None = None,
        auto_login: bool = True,
    ) -> JsonDict | None:
        response = await self._http.request(method, path, json=json, params=params)
        payload: JsonDict | None
        try:
            payload = response.json()
        except ValueError:
            payload = None

        # EVE-NG's own documentation maps BOTH a bare HTTP 401 ("user
        # should login") AND HTTP 400 ("user session has timed out") to
        # "unauthorized" -- both mean the session is no longer valid,
        # (re)authenticate and retry once. Trust the HTTP status code
        # alone here, not the response body's own JSend `status` field:
        # confirmed live (server audit log, timestamped) that a session
        # invalidated by the same account logging in elsewhere -- EVE-NG
        # only allows one active session per user, "the second login
        # disables the first" -- comes back as a bare 400 with a
        # *generic* `"fail"` status and EVE-NG's generic "Request not
        # valid" message, not self-identifying as an auth problem in the
        # body at all, contradicting how the documentation describes it.
        # An earlier version of this check only matched a literal
        # `status == "unauthorized"` in the body and missed this case
        # entirely for exactly that reason.
        #
        # Trade-off, accepted deliberately: this means EVERY 400 gets one
        # retry-with-relogin, including genuine validation failures
        # unrelated to auth (e.g. an invalid template name) -- for those,
        # the retry just reproduces the same 400 (relogging in doesn't
        # fix bad parameters), so the final error the caller sees is
        # identical, at the cost of one extra round-trip. That's a better
        # trade than silently missing real session invalidation, which
        # is confirmed to happen and previously had no reliable signal
        # to detect from the response body alone.
        needs_relogin = auto_login and response.status_code in (400, 401)
        if needs_relogin:
            self._authenticated = False
            await self.login()
            return await self._request(method, path, json=json, params=params, auto_login=False)

        if payload is None:
            if response.status_code >= 500:
                raise EvengAPIError(
                    (
                        f"EVE-NG server returned {response.status_code} "
                        f"{response.reason_phrase} for {method} {path}, with no JSON error "
                        "body -- this usually means an unhandled exception on the EVE-NG "
                        "server itself, not a problem with the request.\n\n"
                        "A common cause is a stale lock file left behind by an earlier "
                        "interrupted request. On the EVE-NG server, check for one with:\n"
                        "  find /opt/unetlab/labs/ -name '*.lock'\n"
                        "and remove any found with:\n"
                        "  find /opt/unetlab/labs/ -name '*.lock' -exec rm {} \\;\n"
                        "then retry. If that doesn't resolve it, check the EVE-NG server's "
                        "own logs for the underlying exception."
                    ),
                    code=response.status_code,
                    status="server_error",
                )
            response.raise_for_status()
            return None

        status = payload.get("status")
        if status == "success":
            return payload
        if response.status_code == 404:
            raise EvengNotFoundError(payload.get("message", "Not found"))
        if status in {"unauthorized", "forbidden"}:
            raise EvengAuthError(payload.get("message", "Not authenticated"))
        raise EvengAPIError(
            payload.get("message", f"EVENG API error ({response.status_code})"),
            code=payload.get("code", response.status_code),
            status=status,
        )

    async def _get(self, path: str, **kw: Any) -> JsonDict | None:
        return await self._request("GET", path, **kw)

    async def _post(self, path: str, json: JsonDict | None = None, **kw: Any) -> JsonDict | None:
        return await self._request("POST", path, json=json, **kw)

    async def _put(self, path: str, json: JsonDict | None = None, **kw: Any) -> JsonDict | None:
        return await self._request("PUT", path, json=json, **kw)

    async def _delete(self, path: str, **kw: Any) -> JsonDict | None:
        return await self._request("DELETE", path, **kw)

    # -- auth ------------------------------------------------------------

    async def login(self) -> JsonDict:
        payload = {
            "username": self._settings.username,
            "password": self._settings.password.get_secret_value(),
            "html5": self._settings.html5,
        }
        result = await self._request("POST", "/auth/login", json=payload, auto_login=False)
        if result is None:
            raise EvengAuthError("Login failed: empty response from EVENG")
        self._authenticated = True
        return result

    async def logout(self) -> JsonDict:
        result = await self._get("/auth/logout", auto_login=False)
        self._authenticated = False
        return result or {"status": "success", "message": "Logged out"}

    async def whoami(self) -> JsonDict:
        result = await self._get("/auth")
        assert result is not None
        return result

    async def ensure_authenticated(self) -> None:
        if not self._authenticated:
            await self.login()

    # -- system ------------------------------------------------------------

    async def get_status(self) -> JsonDict:
        result = await self._get("/status")
        assert result is not None
        return result

    async def list_node_templates(self) -> JsonDict:
        result = await self._get("/list/templates/")
        assert result is not None
        return result

    async def get_node_template(self, template: str) -> JsonDict:
        result = await self._get(f"/list/templates/{quote(template)}")
        assert result is not None
        return result

    async def list_network_types(self) -> JsonDict:
        result = await self._get("/list/networks")
        assert result is not None
        return result

    async def list_user_roles(self) -> JsonDict:
        result = await self._get("/list/roles")
        assert result is not None
        return result

    # -- folders -----------------------------------------------------------

    async def list_folder(self, path: str = "/") -> JsonDict:
        result = await self._get(f"/folders{_quote_path(path)}")
        assert result is not None
        return result

    async def add_folder(self, path: str, name: str) -> JsonDict:
        result = await self._post("/folders", json={"path": path, "name": name})
        assert result is not None
        return result

    async def move_folder(self, path: str, new_path: str) -> JsonDict:
        result = await self._put(f"/folders{_quote_path(path)}", json={"path": new_path})
        assert result is not None
        return result

    async def delete_folder(self, path: str) -> JsonDict:
        result = await self._delete(f"/folders{_quote_path(path)}")
        assert result is not None
        return result

    async def list_all_labs(
        self,
        start_path: str = "/",
        *,
        max_depth: int = 25,
        max_folders: int = 500,
    ) -> list[JsonDict]:
        """Recursively list every lab reachable under `start_path`.

        EVE-NG's `GET /api/folders/{path}` endpoint (confirmed against the
        actual server source, api.php's `apiGetFolders()` route) only ever
        returns the immediate children of one folder -- there is no
        recursive/depth parameter. This walks the tree itself, one
        `list_folder` call per directory (breadth-first).

        Loop safety (the API always includes a ".." entry pointing back to
        the parent in every folder listing, and EVE-NG also exposes a
        virtual "/Running" folder that mirrors labs living elsewhere):
          - The ".." entry is always skipped, never followed as a child.
          - Each folder path is only ever queued/visited once (`visited`),
            even if it's referenced from more than one place.
          - `max_depth` (relative to `start_path`) and `max_folders` (total
            folders visited) are hard ceilings as a last line of defense
            against any future/unexpected API response shape.

        Labs are deduplicated by their `path` field, since EVE-NG's
        "/Running" view can otherwise list the same lab twice.
        """
        visited: set[str] = set()
        labs_by_path: dict[str, JsonDict] = {}
        queue: list[tuple[str, int]] = [(start_path, 0)]

        while queue:
            if len(visited) >= max_folders:
                break
            path, depth = queue.pop(0)
            if path in visited:
                continue
            visited.add(path)

            result = await self.list_folder(path)
            data = result.get("data") or {}

            for lab in data.get("labs", []) or []:
                lab_path = lab.get("path")
                if lab_path:
                    labs_by_path[lab_path] = lab

            if depth >= max_depth:
                continue
            for folder in data.get("folders", []) or []:
                name = folder.get("name")
                child_path = folder.get("path")
                if name == ".." or not child_path or child_path in visited:
                    continue
                queue.append((child_path, depth + 1))

        return sorted(labs_by_path.values(), key=lambda lab: lab.get("path", ""))

    async def list_all_folders(
        self,
        start_path: str = "/",
        *,
        max_depth: int = 25,
        max_folders: int = 500,
    ) -> list[JsonDict]:
        """Recursively list every folder reachable under `start_path`.

        Same approach and loop-safety guarantees as `list_all_labs` (see
        there for the detailed rationale): no recursive endpoint exists, so
        this walks the tree itself, breadth-first, always skipping the
        ".." entry every folder listing includes, never revisiting a folder
        path twice, and enforcing `max_depth`/`max_folders` ceilings.

        `start_path` itself is not included in the results (only folders
        found while walking beneath it), matching how `list_all_labs`
        doesn't include the folder it started from either.
        """
        visited: set[str] = set()
        folders_by_path: dict[str, JsonDict] = {}
        queue: list[tuple[str, int]] = [(start_path, 0)]

        while queue:
            if len(visited) >= max_folders:
                break
            path, depth = queue.pop(0)
            if path in visited:
                continue
            visited.add(path)

            result = await self.list_folder(path)
            data = result.get("data") or {}

            for folder in data.get("folders", []) or []:
                name = folder.get("name")
                child_path = folder.get("path")
                if name == ".." or not child_path or child_path in visited:
                    continue
                # Always record a discovered folder, even at the depth limit
                # -- only further recursion into it is what gets skipped.
                folders_by_path[child_path] = folder
                if depth < max_depth:
                    queue.append((child_path, depth + 1))

        return sorted(folders_by_path.values(), key=lambda f: f.get("path", ""))

    # -- users ---------------------------------------------------------------

    async def list_users(self) -> JsonDict:
        result = await self._get("/users/")
        assert result is not None
        return result

    async def get_user(self, username: str) -> JsonDict:
        result = await self._get(f"/users/{quote(username)}")
        assert result is not None
        return result

    async def add_user(
        self,
        username: str,
        password: str,
        *,
        name: str = "",
        email: str = "",
        role: str = "user",
        expiration: str = "-1",
        pod: int = 0,
        pexpiration: str = "-1",
    ) -> JsonDict:
        payload = {
            "username": username,
            "password": password,
            "name": name,
            "email": email,
            "role": role,
            "expiration": expiration,
            "pod": pod,
            "pexpiration": pexpiration,
        }
        result = await self._post("/users", json=payload)
        assert result is not None
        return result

    async def edit_user(self, username: str, **fields: Any) -> JsonDict:
        result = await self._put(f"/users/{quote(username)}", json=fields)
        assert result is not None
        return result

    async def delete_user(self, username: str) -> JsonDict:
        result = await self._delete(f"/users/{quote(username)}")
        assert result is not None
        return result

    # -- labs -----------------------------------------------------------------

    async def get_lab(self, lab_path: str) -> JsonDict:
        result = await self._get(f"/labs{_quote_path(lab_path)}")
        assert result is not None
        return result

    async def create_lab(
        self,
        path: str,
        name: str,
        *,
        version: str = "1",
        author: str = "",
        description: str = "",
        body: str = "",
    ) -> JsonDict:
        payload = {
            "path": path,
            "name": name,
            "version": version,
            "author": author,
            "description": description,
            "body": body,
        }
        result = await self._post("/labs", json=payload)
        assert result is not None
        return result

    async def edit_lab(self, lab_path: str, **fields: Any) -> JsonDict:
        result = await self._put(f"/labs{_quote_path(lab_path)}", json=fields)
        assert result is not None
        return result

    async def move_lab(self, lab_path: str, new_path: str) -> JsonDict:
        result = await self._put(f"/labs{_quote_path(lab_path)}/move", json={"path": new_path})
        assert result is not None
        return result

    async def delete_lab(self, lab_path: str) -> JsonDict:
        result = await self._delete(f"/labs{_quote_path(lab_path)}")
        assert result is not None
        return result

    async def get_lab_topology(self, lab_path: str) -> JsonDict:
        result = await self._get(f"/labs{_quote_path(lab_path)}/topology")
        assert result is not None
        return result

    async def get_lab_links(self, lab_path: str) -> JsonDict:
        """All ethernet/serial endpoints available for connecting nodes."""
        result = await self._get(f"/labs{_quote_path(lab_path)}/links")
        assert result is not None
        return result

    # -- lab networks -----------------------------------------------------------

    async def list_lab_networks(self, lab_path: str, network_id: int | None = None) -> JsonDict:
        suffix = f"/{network_id}" if network_id is not None else ""
        result = await self._get(f"/labs{_quote_path(lab_path)}/networks{suffix}")
        assert result is not None
        return result

    async def add_lab_network(
        self,
        lab_path: str,
        network_type: str,
        *,
        name: str | None = None,
        left: str = "0",
        top: str = "0",
        style: str = "Solid",
        icon: str = "01-Cloud-Default.svg",
        width: int = 0,
        linkstyle: str = "Straight",
        color: str = "",
        label: str = "",
        visibility: int = 1,
        hideme: int = 0,
        native_vlan: int = 1,
        smart: int = 0,
        pnet_out: str = "",
    ) -> JsonDict:
        """Create a network. Sends every field EVE-NG's own GUI sends when
        creating one, with matching defaults (confirmed live by comparing
        two networks created directly through the GUI, left behind
        specifically for this comparison, against what this project's own
        request was sending) -- not just `type`/`left`/`top`/`name`. Even
        after fixing the confirmed `left`/`top` omission bug, network
        creation was still silently failing to persist (reports success
        with an id, but never actually shows up), so rather than keep
        guessing at which single field matters, every field the GUI sends
        is sent here too. `count` and `id` are excluded: both are
        server-assigned/computed, not something a create request sets.

        `hideme` (0/1) is what actually controls whether a network renders
        as its own icon or as an invisible direct line -- NOT `visibility`
        (both of the GUI's own comparison networks had `visibility: 1`,
        differing only in `hideme`).
        """
        payload: JsonDict = {
            "type": network_type,
            "left": left,
            "top": top,
            "style": style,
            "icon": icon,
            "width": width,
            "linkstyle": linkstyle,
            "color": color,
            "label": label,
            "visibility": visibility,
            "hideme": hideme,
            "native_vlan": native_vlan,
            "smart": smart,
            "pnet_out": pnet_out,
        }
        if name is not None:
            payload["name"] = name
        result = await self._post(f"/labs{_quote_path(lab_path)}/networks", json=payload)
        assert result is not None
        return result

    async def delete_lab_network(self, lab_path: str, network_id: int) -> JsonDict:
        result = await self._delete(f"/labs{_quote_path(lab_path)}/networks/{network_id}")
        assert result is not None
        return result

    async def edit_lab_network(self, lab_path: str, network_id: int, **fields: Any) -> JsonDict:
        """PUT a partial update to an existing network. Only supplied fields are changed.

        Confirmed against a real, working reference implementation (a
        community EVE-NG SDK's `connect_node_to_node`): the way a
        node-to-node bridge actually ends up rendering as a direct line
        (not a separate network icon) is NOT a field set at creation time
        -- the bridge is created with `visibility=1` (visible), both
        interfaces are wired to it, and only then is `visibility` set to
        `0` via a separate PUT here. Setting it at creation time (what
        this project tried first, using `hideme`) doesn't produce the
        same result live -- confirmed by the user seeing no cable
        rendered at all, rather than a direct line.
        """
        result = await self._put(f"/labs{_quote_path(lab_path)}/networks/{network_id}", json=fields)
        assert result is not None
        return result

    # -- lab nodes --------------------------------------------------------------

    async def list_lab_nodes(self, lab_path: str, node_id: int | None = None) -> JsonDict:
        suffix = f"/{node_id}" if node_id is not None else ""
        result = await self._get(f"/labs{_quote_path(lab_path)}/nodes{suffix}")
        assert result is not None
        return result

    async def add_lab_node(
        self,
        lab_path: str,
        *,
        node_type: str,
        template: str,
        name: str | None = None,
        image: str | None = None,
        config: str = "Unconfigured",
        delay: int = 0,
        icon: str = "Router.png",
        left: str = "0",
        top: str = "0",
        ram: int | None = None,
        console: str = "telnet",
        cpu: int = 1,
        ethernet: int | None = None,
        extra: JsonDict | None = None,
    ) -> JsonDict:
        payload: JsonDict = {
            "type": node_type,
            "template": template,
            "config": config,
            "delay": delay,
            "icon": icon,
            "console": console,
            "cpu": cpu,
            # EVE-NG's own api_nodes.php (apiAddLabNode) reads $_POST['left']
            # unconditionally with no isset() check -- confirmed via a live
            # server's own error log: "Undefined array key 'left'" thrown as
            # a fatal ErrorException (PHP 8's undefined-array-key warning,
            # promoted to an exception by EVE-NG's error handler) whenever
            # this key is missing from the request body, producing a 500
            # with no JSON body. So "left"/"top" must ALWAYS be present in
            # the payload, unlike every other optional field here -- never
            # omit them even when the caller didn't specify a canvas
            # position.
            "left": left,
            "top": top,
        }
        for key, value in (
            ("name", name),
            ("image", image),
            ("ram", ram),
            ("ethernet", ethernet),
        ):
            if value is not None:
                payload[key] = value
        if extra:
            payload.update(extra)
        result = await self._post(f"/labs{_quote_path(lab_path)}/nodes", json=payload)
        assert result is not None
        return result

    async def delete_lab_node(self, lab_path: str, node_id: int) -> JsonDict:
        result = await self._delete(f"/labs{_quote_path(lab_path)}/nodes/{node_id}")
        assert result is not None
        return result

    async def edit_lab_node(self, lab_path: str, node_id: int, **fields: Any) -> JsonDict:
        """PUT a partial update to an existing node. Only supplied fields are changed.

        Same pattern as `edit_lab`. EVE-NG generally requires a node to be
        stopped before some fields (notably `name`) can be changed -- the
        tool layer (`tools/nodes.py`) enforces that, not this method, which
        just performs the raw PUT.
        """
        result = await self._put(f"/labs{_quote_path(lab_path)}/nodes/{node_id}", json=fields)
        assert result is not None
        return result

    async def get_node_interfaces(self, lab_path: str, node_id: int) -> JsonDict:
        result = await self._get(f"/labs{_quote_path(lab_path)}/nodes/{node_id}/interfaces")
        assert result is not None
        return result

    async def set_node_interface(
        self, lab_path: str, node_id: int, interface_index: int, network_id: int
    ) -> JsonDict:
        """Wire one of a node's interfaces to a network.

        EVE-NG has no dedicated "connect two nodes" endpoint -- this is
        the actual primitive underneath every kind of connection, node-to-
        node included (see `tools/nodes.py`'s `connect_interface` for how
        a node-to-node connection is built from this: create a bridge
        network, then call this once per node against the same network id).
        Confirmed against EVE-NG's own API docs and cheat sheet: `PUT
        /nodes/{id}/interfaces` with a body of `{"<index>": "<network_id>"}`.
        """
        payload = {str(interface_index): str(network_id)}
        result = await self._put(
            f"/labs{_quote_path(lab_path)}/nodes/{node_id}/interfaces", json=payload
        )
        assert result is not None
        return result

    async def _node_action(self, lab_path: str, action: str, node_id: int | None) -> JsonDict:
        suffix = f"/{node_id}/{action}" if node_id is not None else f"/{action}"
        result = await self._get(f"/labs{_quote_path(lab_path)}/nodes{suffix}")
        assert result is not None
        return result

    async def start_node(self, lab_path: str, node_id: int | None = None) -> JsonDict:
        """Start a single node, or every node in the lab if `node_id` is None."""
        return await self._node_action(lab_path, "start", node_id)

    async def stop_node(self, lab_path: str, node_id: int | None = None) -> JsonDict:
        return await self._node_action(lab_path, "stop", node_id)

    async def wipe_node(self, lab_path: str, node_id: int | None = None) -> JsonDict:
        return await self._node_action(lab_path, "wipe", node_id)

    async def export_node(self, lab_path: str, node_id: int | None = None) -> JsonDict:
        return await self._node_action(lab_path, "export", node_id)

    # -- pictures -----------------------------------------------------------

    async def list_lab_pictures(self, lab_path: str, picture_id: int | None = None) -> JsonDict:
        suffix = f"/{picture_id}" if picture_id is not None else ""
        result = await self._get(f"/labs{_quote_path(lab_path)}/pictures{suffix}")
        assert result is not None
        return result


__all__ = [
    "EvengClient",
    "EvengError",
    "EvengAuthError",
    "EvengNotFoundError",
    "EvengAPIError",
]
