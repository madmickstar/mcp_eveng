"""MCP tools for EVENG folder management."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..confirmation import run_delete_flow

GetClient = Callable[[], Awaitable[EvengClient]]


async def list_folder(client: EvengClient, path: str = "/") -> dict[str, Any]:
    """List the folders and labs contained in an EVENG folder."""
    return await client.list_folder(path)


async def add_folder(client: EvengClient, path: str, name: str) -> dict[str, Any]:
    """Create a new folder inside an existing EVENG folder."""
    return await client.add_folder(path, name)


async def move_folder(client: EvengClient, path: str, new_path: str) -> dict[str, Any]:
    """Move or rename an existing folder."""
    return await client.move_folder(path, new_path)


async def _find_folders_by_path_substring(
    client: EvengClient, path_substring: str, search_path: str = "/"
) -> list[dict[str, Any]]:
    """Find every folder under `search_path` whose path contains `path_substring`."""
    all_folders = await client.list_all_folders(search_path)
    needle = path_substring.strip().lower()
    return [f for f in all_folders if needle in str(f.get("path", "")).lower()]


async def _folder_contents_bullets(client: EvengClient, path: str) -> list[str]:
    result = await client.list_folder(path)
    data = result.get("data") or {}
    bullets = [
        f"[folder] {f.get('name', f.get('path'))}" for f in data.get("folders", []) or [] if f.get("name") != ".."
    ]
    bullets += [f"[lab] {lab.get('file', lab.get('path'))}" for lab in data.get("labs", []) or []]
    return bullets


async def delete_folder(
    client: EvengClient,
    path: str,
    search_path: str = "/",
    selection: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a folder, matched by path substring (case-insensitive).

    Search -> select -> confirm, no special MCP host capability required:
      1. Call with just `path`. Nothing is deleted -- if exactly one
         folder matches, the response says to call again with
         confirm=true; if more than one match, it lists them and asks you
         to reply with `selection` (a number or the exact path).
      2. If there were multiple matches, call again with `selection` set;
         the response reports back exactly the one resolved folder and
         asks you to call again with confirm=true.
      3. Call again with confirm=true to actually delete it.

    Only one folder can be deleted per call -- if `selection` still
    resolves to more than one, the call is refused. Refuses to delete a
    folder that still has contents (subfolders or labs), listing them.
    Searches recursively under `search_path` (default: everything), since
    EVE-NG's API has no server-side search.
    """
    if not path or not path.strip():
        return {
            "status": "error",
            "message": "A folder path (or part of one) is required to delete a folder; none was supplied.",
        }

    candidates = await _find_folders_by_path_substring(client, path, search_path)

    def _matches_exact(folder: dict[str, Any], needle: str) -> bool:
        return str(folder.get("path", "")).strip().lower() == needle

    async def _perform_delete(folder: dict[str, Any]) -> str | None:
        folder_path = str(folder.get("path", ""))
        contents = await _folder_contents_bullets(client, folder_path)
        if contents:
            return "not empty:\n" + "\n".join(f"  - {c}" for c in contents)
        await client.delete_folder(folder_path)
        return None

    return await run_delete_flow(
        candidates,
        matches_exact=_matches_exact,
        describe=lambda f: str(f.get("path", "")),
        noun="folder",
        selection=selection,
        confirm=confirm,
        allow_multiple=False,
        perform_delete=_perform_delete,
    )


def register(mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]) -> None:
    if enabled("list_folder"):

        @mcp.tool(name="list_folder")
        async def _list_folder(path: str = "/") -> dict[str, Any]:
            """List the folders and labs contained in an EVENG folder.

            Args:
                path: Folder path, e.g. "/" or "/User1/Folder 1".
            """
            return await list_folder(await get_client(), path)

    if enabled("add_folder"):

        @mcp.tool(name="add_folder")
        async def _add_folder(path: str, name: str) -> dict[str, Any]:
            """Create a new folder inside an existing EVENG folder.

            Args:
                path: Parent folder path, e.g. "/User1".
                name: Name of the new folder to create.
            """
            return await add_folder(await get_client(), path, name)

    if enabled("move_folder"):

        @mcp.tool(name="move_folder")
        async def _move_folder(path: str, new_path: str) -> dict[str, Any]:
            """Move or rename an existing folder.

            Args:
                path: Current full folder path, e.g. "/User1/Old Name".
                new_path: Destination full folder path, e.g. "/User1/New Name".
            """
            return await move_folder(await get_client(), path, new_path)

    if enabled("delete_folder"):

        @mcp.tool(name="delete_folder")
        async def _delete_folder(
            path: str = "", search_path: str = "/", selection: str = "", confirm: bool = False
        ) -> dict[str, Any]:
            """Delete a folder, matched by path substring (case-insensitive).

            Search -> select -> confirm flow (see module docs). Only one
            folder can be deleted per call. Refuses to delete a folder that
            still has contents.

            Args:
                path: Folder path or a fragment of one, e.g. "/User1/Folder 1" or
                    "Folder 1". Required.
                search_path: Folder to search from, default "/" (the whole server).
                selection: When multiple folders matched, the number or exact path
                    of the one to delete.
                confirm: Set true on the final call to actually delete.
            """
            return await delete_folder(await get_client(), path, search_path, selection, confirm)
