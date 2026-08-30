"""Minimal async telnet client for sending CLI commands to a node's console.

This is deliberately not built on `telnetlib` -- that module was deprecated
in Python 3.11 and removed in 3.13 (PEP 594), so relying on it in new code
would be a dead end. This implements just enough of RFC 854 to work with
EVE-NG's emulated device consoles: IAC (Interpret As Command) option
negotiation is handled by refusing every option offered (WONT to WILL, DONT
to DO), which keeps the session as plain text -- exactly what capturing
scripted command/response output needs, not a fully negotiated interactive
terminal with echo, window size, etc.

Nothing here talks to EVE-NG's REST API at all -- this is a raw TCP
connection directly to the host:port EVE-NG itself reports for a node's
console (`list_lab_nodes`' own `url` field), same as what a real telnet
client (or EVE-NG's own web console button) connects to.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

IAC = 255
WILL = 251
WONT = 252
DO = 253
DONT = 254
SB = 250
SE = 240

OpenConnection = Callable[[str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


def _process_telnet_bytes(data: bytes) -> tuple[bytes, bytes, bytes]:
    """Strip telnet IAC sequences from `data`.

    Returns `(clean_text, negotiation_replies, unconsumed_tail)`. The tail
    is non-empty only when an IAC sequence is cut off at the end of `data`
    (e.g. split across two separate socket reads) -- the caller should
    prepend it to the next chunk before processing again, rather than
    losing or misinterpreting the partial sequence.
    """
    clean = bytearray()
    replies = bytearray()
    i = 0
    n = len(data)
    in_subneg = False

    while i < n:
        byte = data[i]

        if in_subneg:
            if byte == IAC and i + 1 < n and data[i + 1] == SE:
                in_subneg = False
                i += 2
                continue
            if byte == IAC and i + 1 >= n:
                return bytes(clean), bytes(replies), data[i:]
            i += 1
            continue

        if byte == IAC:
            if i + 1 >= n:
                return bytes(clean), bytes(replies), data[i:]
            cmd = data[i + 1]
            if cmd == IAC:
                clean.append(IAC)  # escaped literal 0xFF byte
                i += 2
                continue
            if cmd in (WILL, WONT, DO, DONT):
                if i + 2 >= n:
                    return bytes(clean), bytes(replies), data[i:]
                option = data[i + 2]
                if cmd == WILL:
                    replies += bytes([IAC, DONT, option])
                elif cmd == DO:
                    replies += bytes([IAC, WONT, option])
                # WONT/DONT from the remote end need no reply.
                i += 3
                continue
            if cmd == SB:
                in_subneg = True
                i += 2
                continue
            i += 2  # NOP, AYT, and other single-byte commands -- just consume
            continue

        clean.append(byte)
        i += 1

    return bytes(clean), bytes(replies), b""


async def _read_until_idle(reader: asyncio.StreamReader, idle_timeout: float) -> bytes:
    """Read from `reader` until no new data arrives for `idle_timeout` seconds.

    There's no reliable fixed "command finished" marker across different
    device CLIs (prompts vary: `Switch>`, `Switch#`, `Switch(config)#`,
    ...), so this uses the same idle-based approach real interactive
    telnet sessions rely on: keep reading while data keeps arriving, and
    consider it settled once a full `idle_timeout` window passes with
    nothing new.
    """
    buffer = bytearray()
    while True:
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=idle_timeout)
        except asyncio.TimeoutError:
            break
        if not chunk:
            break  # connection closed by the remote end
        buffer += chunk
    return bytes(buffer)


async def telnet_session(
    host: str,
    port: int,
    commands: list[str],
    *,
    idle_timeout: float = 2.0,
    connect_timeout: float = 10.0,
    connect_attempts: int = 3,
    connect_retry_delay: float = 2.0,
    open_connection: OpenConnection = asyncio.open_connection,
) -> str:
    """Open a telnet session, send `commands` one at a time, return the full transcript.

    Each command is sent only after the previous one's output has settled
    (see `_read_until_idle`) -- sending them all at once would race ahead
    of prompt changes (e.g. entering config mode changes what the device
    is ready to accept next).

    A freshly-started node's console server may not be listening
    immediately -- retries the initial connection a few times with a short
    delay before giving up, the same "give EVE-NG a moment" pattern used
    elsewhere in this project for other timing-sensitive operations.

    Raises `ConnectionError` if the connection can't be established at all
    after `connect_attempts` tries.
    """
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    last_error: Exception | None = None

    for attempt in range(connect_attempts):
        try:
            reader, writer = await asyncio.wait_for(open_connection(host, port), timeout=connect_timeout)
            break
        except (OSError, asyncio.TimeoutError) as exc:
            last_error = exc
            if attempt < connect_attempts - 1:
                await asyncio.sleep(connect_retry_delay)

    if reader is None or writer is None:
        raise ConnectionError(f"Could not connect to {host}:{port} after {connect_attempts} attempt(s): {last_error}")

    transcript = bytearray()
    pending = bytearray()

    async def _drain_available() -> None:
        raw = await _read_until_idle(reader, idle_timeout)
        combined = bytes(pending) + raw
        clean, replies, tail = _process_telnet_bytes(combined)
        pending.clear()
        pending.extend(tail)
        transcript.extend(clean)
        if replies:
            writer.write(replies)
            await writer.drain()

    try:
        await _drain_available()  # banner / initial prompt, if the device sends one
        for command in commands:
            writer.write(command.encode() + b"\r\n")
            await writer.drain()
            await _drain_available()
    finally:
        writer.close()
        with contextlib.suppress(Exception):  # best-effort close; the session's already done its job
            await writer.wait_closed()

    return transcript.decode(errors="replace")
