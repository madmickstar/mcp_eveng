"""MCP tools for EVENG lab management."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..confirmation import format_numbered, resolve_selection, run_delete_flow
from ..edition import is_pro_edition

GetClient = Callable[[], Awaitable[EvengClient]]


async def get_lab(client: EvengClient, lab_path: str) -> dict[str, Any]:
    """Get metadata for a lab."""
    return await client.get_lab(lab_path)


async def create_lab(
    client: EvengClient,
    path: str,
    name: str,
    version: str = "1",
    author: str = "",
    description: str = "",
    body: str = "",
) -> dict[str, Any]:
    """Create a new (empty) lab."""
    return await client.create_lab(path, name, version=version, author=author, description=description, body=body)


async def edit_lab(
    client: EvengClient,
    lab_path: str,
    name: str | None = None,
    version: str | None = None,
    author: str | None = None,
    description: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Edit an existing lab's metadata. Only supplied fields are changed."""
    fields = {
        k: v
        for k, v in {
            "name": name,
            "version": version,
            "author": author,
            "description": description,
            "body": body,
        }.items()
        if v is not None
    }
    return await client.edit_lab(lab_path, **fields)


# -- share_lab: add users to a lab's `shared` list, via edit_lab ---------------

_SHARE_LIST_LIMIT = 20


async def _list_usernames(client: EvengClient) -> list[str]:
    """Every EVE-NG username, from list_users."""
    result = await client.list_users()
    data = result.get("data") or {}
    if isinstance(data, dict):
        return sorted(str(k) for k in data)
    if isinstance(data, list):
        return sorted(str(item["username"]) for item in data if isinstance(item, dict) and item.get("username"))
    return []


async def _current_shared_users(client: EvengClient, lab_path: str) -> list[str]:
    result = await client.get_lab(lab_path)
    data = result.get("data") or {}
    shared = data.get("shared") if isinstance(data, dict) else None
    return [str(u) for u in shared] if isinstance(shared, list) else []


async def share_lab(
    client: EvengClient,
    lab_path: str,
    search: str = "",
    selection: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Share a lab with one or more users, added to whoever it's already shared with.

    **PRO/Corporate only.** Listed as a separate toggleable feature
    ("Shared Lab", "Shared Project") on EVE-NG's own official
    features-compare page, and confirmed live on Community: `get_lab`
    never returns a `shared` key at all, and attempting to actually add a
    share fails with "Lab has not been modified" -- the request is
    accepted but silently has no effect. Confirmed directly (a Community
    user, not the official docs): there's no per-lab sharing concept to
    toggle at all on Community -- all labs are shared by default. This
    checks the server's edition first (same signal
    `connect_interface`/`export_node` use) and returns a clear error
    immediately on Community, rather than walking through the
    search/select flow only to fail at the very end.

    `search` is a case-insensitive substring match against every EVE-NG
    username -- empty matches everyone. The literal word "all" is a
    shortcut that bypasses searching/selecting entirely and shares with
    every user that exists.

    Otherwise: no matches cancels; more than 20 matches doesn't list them
    (unwieldy) -- it asks for a more specific search instead; exactly one
    match proceeds directly, no prompt; more than one (up to 20) is shown
    numbered, with an "all" option at the end meaning every *matched*
    user (not necessarily every user on the server, unless the search
    matched everyone). Pick via `selection` -- number(s), exact
    username(s), or "all".

    Existing shares are preserved: this adds to whoever the lab is
    already shared with via `edit_lab`, never replaces the list. Final
    confirmation lists every user about to be newly added; reply "accept"
    or "yes" (`confirm`) to apply -- same wording as every delete tool.
    """
    status_result = await client.get_status()
    status_data = status_result.get("data") if isinstance(status_result, dict) else None
    if not is_pro_edition(status_data if isinstance(status_data, dict) else {}):
        return {
            "status": "error",
            "message": (
                "Lab sharing is a PRO/Corporate-only EVE-NG feature -- listed as a "
                "separate toggleable feature on EVE-NG's own official comparison page, "
                "and confirmed live: on Community, get_lab never returns a 'shared' key "
                'at all, and attempting to actually add a share fails with "Lab has not '
                'been modified" (the request is silently accepted with no effect). This '
                "server is running Community edition, so lab sharing isn't available here."
            ),
        }

    all_users = await _list_usernames(client)
    if not all_users:
        return {"status": "cancelled", "message": "No users found on this server."}

    if search.strip().lower() == "all":
        target_users = list(all_users)
    else:
        needle = search.strip().lower()
        matches = [u for u in all_users if needle in u.lower()]
        described = f"{search!r}" if search.strip() else "(no search given -- everyone)"

        if not matches:
            return {"status": "cancelled", "message": f"No user found matching {described}."}

        if len(matches) > _SHARE_LIST_LIMIT:
            return {
                "status": "error",
                "message": (
                    f"{len(matches)} users match {described} -- too many to list (over "
                    f"{_SHARE_LIST_LIMIT}). Provide a more specific search string to narrow it down."
                ),
            }

        if len(matches) == 1:
            target_users = matches
        elif selection.strip().lower() == "all":
            target_users = list(matches)
        elif selection.strip():
            candidates = [{"username": u} for u in matches]
            resolved, invalid = resolve_selection(selection, candidates, lambda c, n: c["username"].lower() == n)
            if invalid or not resolved:
                return {
                    "status": "error",
                    "message": (
                        f"Could not match {selection!r} to any current user. Current "
                        f"matches:\n{format_numbered(matches)}"
                    ),
                    "data": {"matches": matches},
                }
            target_users = [c["username"] for c in resolved]
        else:
            return {
                "status": "selection_required",
                "message": (
                    f"{len(matches)} user(s) match {described}:\n{format_numbered(matches)}\n"
                    f"{len(matches) + 1}. all\n\n"
                    "Reply with `selection` set to the number(s), exact username(s), or "
                    '"all" to share with every user listed above.'
                ),
                "data": {"matches": matches},
            }

    existing = await _current_shared_users(client, lab_path)
    new_users = sorted(u for u in target_users if u not in existing)

    if not new_users:
        return {
            "status": "cancelled",
            "message": "Every selected user already has this lab shared with them; nothing to change.",
        }

    if not confirm:
        plural = "s" if len(new_users) != 1 else ""
        return {
            "status": "confirmation_required",
            "message": (
                f"Lab will be shared with {len(new_users)} new user{plural}: "
                f"{', '.join(new_users)}.\n"
                f"(Already shared with: {', '.join(existing) if existing else 'nobody'}.)\n\n"
                "Reply 'accept' or 'yes' to proceed; anything else cancels."
            ),
            "data": {"matches": new_users},
        }

    merged = sorted(set(existing) | set(new_users))
    await client.edit_lab(lab_path, shared=merged)

    plural = "s" if len(new_users) != 1 else ""
    return {
        "status": "success",
        "message": f"Shared lab with {len(new_users)} new user{plural}: {', '.join(new_users)}.",
    }


async def move_lab(client: EvengClient, lab_path: str, new_path: str) -> dict[str, Any]:
    """Move a lab to a different folder."""
    return await client.move_lab(lab_path, new_path)


async def get_lab_topology(client: EvengClient, lab_path: str) -> dict[str, Any]:
    """Get the full node/network connection topology of a lab."""
    return await client.get_lab_topology(lab_path)


async def get_lab_links(client: EvengClient, lab_path: str) -> dict[str, Any]:
    """Get all ethernet/serial endpoints available in a lab."""
    return await client.get_lab_links(lab_path)


async def list_lab_pictures(client: EvengClient, lab_path: str, picture_id: int | None = None) -> dict[str, Any]:
    """List background pictures/annotations placed in a lab, or get one by id."""
    return await client.list_lab_pictures(lab_path, picture_id)


async def list_labs(client: EvengClient, path: str = "/", search: str = "") -> dict[str, Any]:
    """Recursively list every lab under `path` (default: the whole server).

    Always recursive, regardless of `path` -- listing a specific folder
    walks the tree starting there. EVE-NG's API has no recursive-listing
    endpoint, so this walks the folder tree itself (see
    `EvengClient.list_all_labs` for the loop-safety details: every folder's
    ".." entry is skipped, each folder is visited at most once even if
    referenced more than once, and hard max_depth/max_folders ceilings
    guard against runaway recursion).

    `search`, if given, is a case-insensitive substring match against
    each lab's path or file name -- the same matching convention (and the
    same `_lab_matches` helper) as `delete_lab`/`open_lab`. Empty (the
    default) matches every lab found, same as everywhere else in this
    project an empty search string means "no filter".
    """
    labs = await client.list_all_labs(path)
    if search.strip():
        labs = [lab for lab in labs if _lab_matches(lab, search)]
    scope = f" matching {search!r}" if search.strip() else ""
    return {
        "status": "success",
        "message": f"Found {len(labs)} lab(s) under {path!r}{scope} (recursive).",
        "data": {"labs": labs, "count": len(labs)},
    }


def _lab_matches(lab: dict[str, Any], target: str) -> bool:
    """Case-insensitive substring match of `target` against a lab's path OR file name."""
    needle = target.strip().lower()
    file_name = str(lab.get("file", "")).lower()
    path = str(lab.get("path", "")).lower()
    return needle in file_name or needle in path


def _is_locked(lab_data: dict[str, Any]) -> bool:
    """Parse a lab's `lock` field, which EVE-NG may return as an int or a string."""
    lock = lab_data.get("lock", 0)
    if isinstance(lock, bool):
        return lock
    return str(lock).strip() not in ("0", "", "false", "False", "None")


def _lab_matches_exact(lab: dict[str, Any], needle: str) -> bool:
    """Exact (not substring) case-insensitive match against a lab's file name OR full path."""
    file_name = str(lab.get("file", "")).strip().lower()
    path = str(lab.get("path", "")).strip().lower()
    return needle in (file_name, path)


_OPEN_LAB_MENU = (
    "What would you like to do to it?\n\n"
    "* Add nodes \u2014 `add_lab_node` (pick a template via `list_node_templates`)\n"
    "* Add networks \u2014 `add_lab_network` (bridge, NAT, etc.)\n"
    "* Edit metadata \u2014 `edit_lab` (name, description, author, version, notes)"
)


async def open_lab(client: EvengClient, name: str, search_path: str = "/", selection: str = "") -> dict[str, Any]:
    """Look up a lab by path or name substring, report its lock status, and suggest next steps.

    Matching is a case-insensitive substring match, against either the
    lab's full path or its bare file name -- the same as `delete_lab`. The
    tree under `search_path` (default: everything) is searched recursively
    first, since EVE-NG's API has no server-side search.

    If exactly one lab matches, its status and the next-step menu are
    reported directly. If more than one matches, every match is listed
    (numbered) and you're asked to call again with `selection` set to
    either the list number or the lab's full name/path (case-insensitive)
    to pick which one to open.

    This is read-only: there is no "open a lab for editing" session in
    EVE-NG's API the way there is in its web GUI -- every change (adding a
    node, adding a network, editing metadata) is just its own direct API
    call, no prior "open" step required. This tool exists to look a lab up
    by a loose name/path and report what's there before you make one of
    those calls.
    """
    if not name or not name.strip():
        return {
            "status": "error",
            "message": "A lab name or path is required; none was supplied.",
        }

    all_labs = await client.list_all_labs(search_path)
    candidates = [lab for lab in all_labs if _lab_matches(lab, name)]

    if not candidates:
        return {
            "status": "cancelled",
            "message": f"No lab found matching {name!r} under {search_path!r}.",
        }

    if len(candidates) == 1:
        target = candidates[0]
    else:
        paths = [str(lab.get("path", lab.get("file", "?"))) for lab in candidates]

        if not selection.strip():
            return {
                "status": "selection_required",
                "message": (
                    f"{len(paths)} labs match {name!r}:\n{format_numbered(paths)}\n\n"
                    "Reply with the number or full name of the one you want to open."
                ),
                "data": {"matches": paths},
            }

        resolved, invalid = resolve_selection(selection, candidates, _lab_matches_exact)
        if invalid or not resolved:
            return {
                "status": "error",
                "message": (
                    f"Could not match {selection!r} to any current lab. Current matches:\n{format_numbered(paths)}"
                ),
                "data": {"matches": paths},
            }
        if len(resolved) > 1:
            return {
                "status": "error",
                "message": (f"Only one lab can be opened at a time. Pick exactly one:\n{format_numbered(paths)}"),
                "data": {"matches": paths},
            }
        target = resolved[0]

    lab_path = str(target["path"])
    result = await client.get_lab(lab_path)
    data = result.get("data") or {}
    locked = _is_locked(data)
    lock_label = "locked" if locked else "unlocked"
    lab_name = str(data.get("name") or target.get("file") or lab_path)

    return {
        "status": "success",
        "message": f"Lab {lab_name!r} is {lock_label}.\n\n{_OPEN_LAB_MENU}",
        "data": {**data, "lab_path": lab_path, "lab_name": lab_name, "lock": locked},
    }


async def delete_lab(
    client: EvengClient,
    name: str,
    search_path: str = "/",
    selection: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete exactly one lab, matched by path OR name substring (case-insensitive).

    Search -> select -> confirm, no special MCP host capability required:
      1. Call with just `name` (and optionally `search_path`). Nothing is
         deleted -- if exactly one lab matches, the response says to call
         again with confirm=true; if more than one match, it lists them
         and asks you to reply with `selection` (a number or the exact
         path/name).
      2. If there were multiple matches, call again with `selection` set;
         the response reports back exactly the one resolved lab and asks
         you to call again with confirm=true.
      3. Call again with confirm=true to actually delete it.

    Matching is a case-insensitive substring match (the search text just
    needs to appear anywhere), against either the lab's full path or its
    bare file name. The tree under `search_path` (default: everything) is
    searched recursively first, since EVE-NG's API has no server-side search.

    There is deliberately no bulk-delete option here, ever: only one lab
    can be deleted per call -- if `selection` still resolves to more than
    one, the call is refused.
    """
    if not name or not name.strip():
        return {
            "status": "error",
            "message": "A lab name or path is required to delete a lab; none was supplied.",
        }

    all_labs = await client.list_all_labs(search_path)
    candidates = [lab for lab in all_labs if _lab_matches(lab, name)]

    async def _perform_delete(lab: dict[str, Any]) -> str | None:
        await client.delete_lab(str(lab.get("path", "")))
        return None

    return await run_delete_flow(
        candidates,
        matches_exact=_lab_matches_exact,
        describe=lambda lab: str(lab.get("path", lab.get("file", "?"))),
        noun="lab",
        selection=selection,
        confirm=confirm,
        allow_multiple=False,
        perform_delete=_perform_delete,
    )


def register(mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]) -> None:
    if enabled("get_lab"):

        @mcp.tool(name="get_lab")
        async def _get_lab(lab_path: str) -> dict[str, Any]:
            """Get metadata for a lab.

            Args:
                lab_path: Full path to the .unl lab file, e.g. "/User1/Lab 1.unl".
            """
            return await get_lab(await get_client(), lab_path)

    if enabled("open_lab"):

        @mcp.tool(name="open_lab")
        async def _open_lab(name: str = "", search_path: str = "/", selection: str = "") -> dict[str, Any]:
            """Look up a lab by path or name substring, report its lock status, and suggest next steps.

            Read-only -- there is no "open for editing" session in EVE-NG's
            API the way there is in its web GUI; every change (add a node, add
            a network, edit metadata) is its own direct call, no prior "open"
            needed. This just looks the lab up and reports what's there first.
            Searches recursively under `search_path`; matching is a
            case-insensitive substring against path or file name, same as
            `delete_lab`. If more than one lab matches, they're listed and you
            pick one by number or full name/path (case-insensitive) via
            `selection`.

            Args:
                name: Lab file name/path, or a fragment of one. Required.
                search_path: Folder to search from, default "/" (the whole server).
                selection: When multiple labs matched, the number or full
                    name/path of the one to open.
            """
            return await open_lab(await get_client(), name, search_path, selection)

    if enabled("create_lab"):

        @mcp.tool(name="create_lab")
        async def _create_lab(
            path: str,
            name: str,
            version: str = "1",
            author: str = "",
            description: str = "",
            body: str = "",
        ) -> dict[str, Any]:
            """Create a new (empty) lab.

            Args:
                path: Destination folder, e.g. "/User1".
                name: Lab name (the ".unl" extension is added automatically).
                version: Free-form version string.
                author: Lab author.
                description: One-line description.
                body: Free-form lab notes/usage guide.
            """
            return await create_lab(
                await get_client(), path, name, version=version, author=author, description=description, body=body
            )

    if enabled("edit_lab"):

        @mcp.tool(name="edit_lab")
        async def _edit_lab(
            lab_path: str,
            name: str | None = None,
            version: str | None = None,
            author: str | None = None,
            description: str | None = None,
            body: str | None = None,
        ) -> dict[str, Any]:
            """Edit an existing lab's metadata. Only supplied fields are changed.

            Args:
                lab_path: Full path to the .unl lab file.
                name: New name, if changing.
                version: New version, if changing.
                author: New author, if changing.
                description: New description, if changing.
                body: New body/notes, if changing.
            """
            return await edit_lab(
                await get_client(),
                lab_path,
                name=name,
                version=version,
                author=author,
                description=description,
                body=body,
            )

    if enabled("share_lab"):

        @mcp.tool(name="share_lab")
        async def _share_lab(
            lab_path: str,
            search: str = "",
            selection: str = "",
            confirm: bool = False,
        ) -> dict[str, Any]:
            """Share a lab with one or more users, added to whoever it's already shared with.

            **PRO/Corporate only** -- listed as a separate toggleable
            feature on EVE-NG's own official comparison page, and
            confirmed live it doesn't actually work on Community despite
            appearing to accept the request -- there's no per-lab
            sharing concept there at all, since all labs are shared by
            default. Checks the server's edition first and returns a
            clear error immediately on Community.

            `search` is a case-insensitive substring match against every
            EVE-NG username -- empty matches everyone. The literal word
            "all" is a shortcut that bypasses searching/selecting
            entirely and shares with every user that exists.

            Otherwise: no matches cancels; more than 20 matches doesn't
            list them (unwieldy) -- asks for a more specific search
            instead; exactly one match proceeds directly, no prompt; more
            than one (up to 20) is shown numbered, with an "all" option
            at the end meaning every *matched* user, not necessarily
            every user on the server. Pick via `selection` -- number(s),
            exact username(s), or "all".

            Existing shares are preserved -- this adds to whoever the lab
            is already shared with, never replaces the list. Final
            confirmation lists every user about to be newly added; reply
            "accept" or "yes" (`confirm`) to apply -- same wording as
            every delete tool.

            Args:
                lab_path: Full path to the .unl lab file.
                search: Username fragment to search for, case-insensitive.
                    Empty matches every user; "all" shares with everyone directly.
                selection: When multiple users matched, the number(s),
                    exact username(s), or "all" (every matched user).
                confirm: Set true on the final call to actually apply.
            """
            return await share_lab(await get_client(), lab_path, search=search, selection=selection, confirm=confirm)

    if enabled("move_lab"):

        @mcp.tool(name="move_lab")
        async def _move_lab(lab_path: str, new_path: str) -> dict[str, Any]:
            """Move a lab to a different folder.

            Args:
                lab_path: Full path to the .unl lab file.
                new_path: Destination folder path.
            """
            return await move_lab(await get_client(), lab_path, new_path)

    if enabled("delete_lab"):

        @mcp.tool(name="delete_lab")
        async def _delete_lab(
            name: str = "", search_path: str = "/", selection: str = "", confirm: bool = False
        ) -> dict[str, Any]:
            """Delete exactly one lab, matched by path OR name substring (case-insensitive).

            Search -> select -> confirm flow (see module docs). Searches
            recursively under `search_path` (EVE-NG's API has no server-side
            search). Matching is a case-insensitive substring match against
            path or file name -- "test" matches "test.unl", "testing.unl", and
            "/User1/test.unl" alike. Only one lab can be deleted per call.

            Args:
                name: Lab file name/path, or a fragment of one, to delete, e.g.
                    "test", "test.unl", or "/User1/test.unl". Required.
                search_path: Folder to search from, default "/" (the whole server).
                selection: When multiple labs matched, the number or exact
                    path/name of the one to delete.
                confirm: Set true on the final call to actually delete.
            """
            return await delete_lab(await get_client(), name, search_path, selection, confirm)

    if enabled("get_lab_topology"):

        @mcp.tool(name="get_lab_topology")
        async def _get_lab_topology(lab_path: str) -> dict[str, Any]:
            """Get the full node/network connection topology of a lab.

            Args:
                lab_path: Full path to the .unl lab file.
            """
            return await get_lab_topology(await get_client(), lab_path)

    if enabled("get_lab_links"):

        @mcp.tool(name="get_lab_links")
        async def _get_lab_links(lab_path: str) -> dict[str, Any]:
            """Get all ethernet/serial endpoints available in a lab (useful before wiring nodes).

            Args:
                lab_path: Full path to the .unl lab file.
            """
            return await get_lab_links(await get_client(), lab_path)

    if enabled("list_lab_pictures"):

        @mcp.tool(name="list_lab_pictures")
        async def _list_lab_pictures(lab_path: str, picture_id: int | None = None) -> dict[str, Any]:
            """List background pictures/annotations placed in a lab, or get one by id.

            Args:
                lab_path: Full path to the .unl lab file.
                picture_id: Specific picture id, or omit to list all.
            """
            return await list_lab_pictures(await get_client(), lab_path, picture_id)

    if enabled("list_labs"):

        @mcp.tool(name="list_labs")
        async def _list_labs(path: str = "/", search: str = "") -> dict[str, Any]:
            """Recursively list every lab under `path` (default: the whole server).

            Always recursive -- listing a specific folder walks the tree
            starting there, not just that one level. EVE-NG's API has no
            recursive-listing endpoint, so this walks every folder in the tree
            itself, with loop protection (skips every ".." entry, never
            revisits a folder, and hard max_depth/max_folders ceilings).

            Args:
                path: Folder to start from, default "/" (the whole server).
                search: Case-insensitive substring to match against each
                    lab's path or file name -- same matching convention as
                    delete_lab/open_lab. Empty (the default) matches every
                    lab found under `path`.
            """
            return await list_labs(await get_client(), path, search)
