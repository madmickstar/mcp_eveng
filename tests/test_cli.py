from __future__ import annotations

import pytest

from mcp_eveng.__main__ import _parse_args, _resolve_transport


def test_no_flags_defaults_to_stdio() -> None:
    args = _parse_args([])
    assert args.sse is False
    assert args.http is False
    assert _resolve_transport(args) == "stdio"


def test_sse_flag_selects_sse_transport() -> None:
    args = _parse_args(["--sse"])
    assert args.sse is True
    assert _resolve_transport(args) == "sse"


def test_http_flag_selects_streamable_http_transport() -> None:
    args = _parse_args(["--http"])
    assert args.http is True
    assert _resolve_transport(args) == "streamable-http"


def test_sse_and_http_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--sse", "--http"])


def test_main_handles_keyboard_interrupt_gracefully(monkeypatch, capsys) -> None:
    import mcp_eveng.__main__ as main_module

    def _raise_interrupt(_transport):
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "run", _raise_interrupt)
    monkeypatch.setattr("sys.argv", ["mcp-eveng"])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Goodbye" in captured.err
    # stdout is reserved for the stdio JSON-RPC stream -- never write here.
    assert captured.out == ""
