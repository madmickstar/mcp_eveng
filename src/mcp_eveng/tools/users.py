"""MCP tools for EVENG user management."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from ..client import EvengClient
from ..confirmation import run_delete_flow
from ..search import find_by_name_case_insensitive, iter_named_records

GetClient = Callable[[], Awaitable[EvengClient]]


async def list_users(client: EvengClient) -> dict[str, Any]:
    """List every EVENG user account."""
    return await client.list_users()


async def get_user(client: EvengClient, username: str) -> dict[str, Any]:
    """Get details for a single EVENG user."""
    return await client.get_user(username)


async def add_user(
    client: EvengClient,
    username: str,
    password: str,
    name: str = "",
    email: str = "",
    role: str = "user",
) -> dict[str, Any]:
    """Create a new EVENG user account."""
    return await client.add_user(username, password, name=name, email=email, role=role)


async def edit_user(
    client: EvengClient,
    username: str,
    name: str | None = None,
    email: str | None = None,
    password: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Edit an existing EVENG user. Only supplied fields are changed."""
    fields = {
        k: v
        for k, v in {"name": name, "email": email, "password": password, "role": role}.items()
        if v is not None
    }
    return await client.edit_user(username, **fields)


async def _find_users_by_username(client: EvengClient, username: str) -> list[dict[str, Any]]:
    result = await client.list_users()
    data = result.get("data") or {}
    return find_by_name_case_insensitive(iter_named_records(data, "username"), username)


def _username_of(user: dict[str, Any]) -> str:
    return str(user.get("username", user.get("_key", "?")))


async def delete_user(
    client: EvengClient, username: str, selection: str = "", confirm: bool = False
) -> dict[str, Any]:
    """Delete an existing EVENG user, matched by username substring (case-insensitive).

    Search -> select -> confirm, no special MCP host capability required:
      1. Call with just `username`. Nothing is deleted -- if exactly one
         user matches, the response says to call again with confirm=true;
         if more than one match, it lists them and asks you to reply with
         `selection` (a number or the exact username).
      2. If there were multiple matches, call again with `selection` set;
         the response reports back exactly the one resolved user and asks
         you to call again with confirm=true.
      3. Call again with confirm=true to actually delete.

    Only one user can be deleted per call -- if `selection` still resolves
    to more than one, the call is refused.
    """
    if not username or not username.strip():
        return {
            "status": "error",
            "message": "A username is required to delete a user; none was supplied.",
        }

    candidates = await _find_users_by_username(client, username)

    async def _perform_delete(user: dict[str, Any]) -> str | None:
        await client.delete_user(_username_of(user))
        return None

    return await run_delete_flow(
        candidates,
        matches_exact=lambda u, needle: _username_of(u).strip().lower() == needle,
        describe=_username_of,
        noun="user",
        selection=selection,
        confirm=confirm,
        allow_multiple=False,
        perform_delete=_perform_delete,
    )


def register(
    mcp: FastMCP, get_client: GetClient, enabled: Callable[[str], bool]
) -> None:
    if enabled("list_users"):
        @mcp.tool(name="list_users")
        async def _list_users() -> dict[str, Any]:
            """List every EVENG user account."""
            return await list_users(await get_client())

    if enabled("get_user"):
        @mcp.tool(name="get_user")
        async def _get_user(username: str) -> dict[str, Any]:
            """Get details for a single EVENG user.

            Args:
                username: The account's username.
            """
            return await get_user(await get_client(), username)

    if enabled("add_user"):
        @mcp.tool(name="add_user")
        async def _add_user(
            username: str,
            password: str,
            name: str = "",
            email: str = "",
            role: str = "user",
        ) -> dict[str, Any]:
            """Create a new EVENG user account.

            Args:
                username: Unique login name (mandatory).
                password: Login password (mandatory).
                name: Display name / salutation.
                email: Contact email address.
                role: One of the roles from `list_user_roles` (default "user").
            """
            return await add_user(await get_client(), username, password, name=name, email=email, role=role)

    if enabled("edit_user"):
        @mcp.tool(name="edit_user")
        async def _edit_user(
            username: str,
            name: str | None = None,
            email: str | None = None,
            password: str | None = None,
            role: str | None = None,
        ) -> dict[str, Any]:
            """Edit an existing EVENG user. Only supplied fields are changed.

            Args:
                username: The account to edit.
                name: New display name, if changing.
                email: New email address, if changing.
                password: New password, if changing.
                role: New role, if changing.
            """
            return await edit_user(
                await get_client(), username, name=name, email=email, password=password, role=role
            )

    if enabled("delete_user"):
        @mcp.tool(name="delete_user")
        async def _delete_user(
            username: str = "", selection: str = "", confirm: bool = False
        ) -> dict[str, Any]:
            """Delete an existing EVENG user, matched by username substring (case-insensitive).

            Search -> select -> confirm flow (see module docs). Only one user
            can be deleted per call.

            Args:
                username: Username or a fragment of one to delete. Required.
                selection: When multiple users matched, the number or exact
                    username of the one to delete.
                confirm: Set true on the final call to actually delete.
            """
            return await delete_user(await get_client(), username, selection, confirm)
