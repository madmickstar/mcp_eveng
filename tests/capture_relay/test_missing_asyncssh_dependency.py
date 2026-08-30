from __future__ import annotations

import sys


def test_server_module_imports_without_asyncssh_installed(monkeypatch) -> None:
    """Regression test for a real failure: a plain `pip install -e .`
    (no `capture-relay` extra) used to crash the entire mcp-eveng server
    at startup, because `tools/capture.py` -> `ssh_client.py` did
    `import asyncssh` at module top level, and `server.py`
    unconditionally imports every tools module regardless of whether
    list_captures/get_capture are even enabled.

    Simulates asyncssh genuinely being absent by removing it (and every
    already-imported mcp_eveng module, so the import chain is exercised
    fresh) from sys.modules, then blocking any subsequent import of it.
    """
    for name in list(sys.modules):
        if name == "asyncssh" or name.startswith("asyncssh.") or name.startswith("mcp_eveng"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    monkeypatch.setitem(sys.modules, "asyncssh", None)  # any `import asyncssh` now raises

    import mcp_eveng.server  # noqa: F401 -- the import itself is the test
    from mcp_eveng.server import create_server

    server = create_server()
    assert server is not None


def test_ssh_client_module_itself_imports_without_asyncssh(monkeypatch) -> None:
    for name in list(sys.modules):
        if name == "asyncssh" or name.startswith("asyncssh."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "asyncssh", None)

    if "mcp_eveng.capture_relay.ssh_client" in sys.modules:
        monkeypatch.delitem(sys.modules, "mcp_eveng.capture_relay.ssh_client")

    import mcp_eveng.capture_relay.ssh_client as ssh_client

    assert ssh_client.is_available() is False
