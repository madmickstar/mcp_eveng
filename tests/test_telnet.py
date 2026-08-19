from __future__ import annotations

import asyncio

import pytest

from mcp_eveng.telnet import IAC, _process_telnet_bytes, telnet_session

# -- _process_telnet_bytes: IAC option negotiation stripping -----------------


def test_process_telnet_bytes_plain_text_passes_through() -> None:
    clean, replies, tail = _process_telnet_bytes(b"hello world")

    assert clean == b"hello world"
    assert replies == b""
    assert tail == b""


def test_process_telnet_bytes_refuses_will_with_dont() -> None:
    # IAC WILL ECHO (option 1)
    data = bytes([IAC, 251, 1])

    clean, replies, tail = _process_telnet_bytes(data)

    assert clean == b""
    assert replies == bytes([IAC, 254, 1])  # IAC DONT 1
    assert tail == b""


def test_process_telnet_bytes_refuses_do_with_wont() -> None:
    # IAC DO SUPPRESS-GO-AHEAD (option 3)
    data = bytes([IAC, 253, 3])

    clean, replies, tail = _process_telnet_bytes(data)

    assert clean == b""
    assert replies == bytes([IAC, 252, 3])  # IAC WONT 3


def test_process_telnet_bytes_wont_and_dont_need_no_reply() -> None:
    data = bytes([IAC, 252, 1]) + bytes([IAC, 254, 3])  # IAC WONT 1, IAC DONT 3

    clean, replies, tail = _process_telnet_bytes(data)

    assert replies == b""


def test_process_telnet_bytes_escaped_iac_byte_is_literal_0xff() -> None:
    data = bytes([65, IAC, IAC, 66])  # "A" + escaped 0xFF + "B"

    clean, replies, tail = _process_telnet_bytes(data)

    assert clean == bytes([65, IAC, 66])


def test_process_telnet_bytes_strips_subnegotiation() -> None:
    # IAC SB <opt> ... IAC SE, surrounded by real text.
    data = b"before" + bytes([IAC, 250, 24, 1, 2, 3, IAC, 240]) + b"after"

    clean, replies, tail = _process_telnet_bytes(data)

    assert clean == b"beforeafter"


def test_process_telnet_bytes_incomplete_sequence_returns_as_tail() -> None:
    # A WILL negotiation cut off mid-sequence (missing the option byte) --
    # must not be misinterpreted, and must be handed back so the caller
    # can prepend it once more data arrives.
    data = b"text" + bytes([IAC, 251])

    clean, replies, tail = _process_telnet_bytes(data)

    assert clean == b"text"
    assert replies == b""
    assert tail == bytes([IAC, 251])


def test_process_telnet_bytes_bare_trailing_iac_returns_as_tail() -> None:
    data = b"text" + bytes([IAC])

    clean, replies, tail = _process_telnet_bytes(data)

    assert clean == b"text"
    assert tail == bytes([IAC])


def test_process_telnet_bytes_nop_is_consumed() -> None:
    data = b"a" + bytes([IAC, 241]) + b"b"  # IAC NOP

    clean, replies, tail = _process_telnet_bytes(data)

    assert clean == b"ab"
    assert replies == b""


# -- telnet_session: fakes for asyncio.open_connection ------------------------


class _FakeWriter:
    def __init__(self) -> None:
        self.written = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _FakeReader:
    """Yields scripted chunks one per `read()` call, then blocks (simulating
    an idle connection) until the caller's own timeout cancels it."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, n: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        await asyncio.sleep(100)
        return b""


def _fake_open_connection(chunks: list[bytes]):
    writer = _FakeWriter()

    async def _open(host: str, port: int):
        return _FakeReader(list(chunks)), writer

    return _open, writer


async def test_telnet_session_sends_commands_and_returns_transcript() -> None:
    open_conn, writer = _fake_open_connection([b"Switch>"])

    transcript = await telnet_session(
        "host", 1234, ["enable", "show vlan"], idle_timeout=0.05, open_connection=open_conn
    )

    assert transcript == "Switch>"
    assert writer.written == b"enable\r\nshow vlan\r\n"


async def test_telnet_session_strips_iac_sequences_from_transcript() -> None:
    banner = bytes([IAC, 253, 3]) + b"Switch>"  # IAC DO 3, then the real banner
    open_conn, writer = _fake_open_connection([banner])

    transcript = await telnet_session(
        "host", 1234, ["show version"], idle_timeout=0.05, open_connection=open_conn
    )

    assert transcript == "Switch>"
    # The refusal reply (IAC WONT 3) must have been written back.
    assert bytes([IAC, 252, 3]) in bytes(writer.written)


async def test_telnet_session_closes_writer() -> None:
    open_conn, writer = _fake_open_connection([b""])

    await telnet_session("host", 1234, ["show version"], idle_timeout=0.05, open_connection=open_conn)

    assert writer.closed is True


async def test_telnet_session_retries_connection_then_succeeds() -> None:
    attempts = {"count": 0}
    writer = _FakeWriter()

    async def _flaky_open(host: str, port: int):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise OSError("connection refused")
        return _FakeReader([b"ok"]), writer

    transcript = await telnet_session(
        "host",
        1234,
        ["show version"],
        idle_timeout=0.05,
        connect_attempts=3,
        connect_retry_delay=0.01,
        open_connection=_flaky_open,
    )

    assert attempts["count"] == 2
    assert transcript == "ok"


async def test_telnet_session_raises_connection_error_after_exhausting_retries() -> None:
    async def _always_fails(host: str, port: int):
        raise OSError("connection refused")

    with pytest.raises(ConnectionError):
        await telnet_session(
            "host",
            1234,
            ["show version"],
            connect_attempts=2,
            connect_retry_delay=0.01,
            open_connection=_always_fails,
        )
