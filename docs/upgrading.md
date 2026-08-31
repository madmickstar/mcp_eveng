# Upgrading

There is only ONE source checkout, shared by both apps — `mcp-relay`
doesn't have its own separate clone, just its own separate venv. Pull
once, reinstall into whichever venv(s) you have.

## mcp-eveng app

**systemd deployment (Linux):**

```bash
cd /opt/mcp_eveng
sudo git pull
sudo -u mcp-eveng /opt/mcp_eveng/.venv/bin/pip install /opt/mcp_eveng
sudo systemctl restart mcp-eveng.service
```

**Manual install (any OS):**

```bash
cd mcp_eveng
git pull
pip install -e .
```

Restart your running `mcp-eveng` (or `python -m mcp_eveng`) process.
Windows: use your venv's own `pip` (`.venv\Scripts\pip.exe`, or an
activated venv) for the same command.

If you're doing development work on this project itself (running the
test suite, linting), use `.[dev]` instead of the plain commands above,
in either scenario.

## mcp-relay app

**systemd deployment (Linux):**

```bash
sudo -u mcp-eveng /opt/mcp_relay/.venv/bin/pip install "/opt/mcp_eveng[capture-relay]"
sudo systemctl restart mcp-relay.service
```

**Manual install (any OS):**

```bash
pip install "/path/to/mcp_eveng[capture-relay]"
```

Restart your running `python -m mcp_eveng.capture_relay` (or
`mcp-eveng-capture-relay`) process.

## Note

`git pull` alone updates the source checkout, but not what's actually
running or installed:

- **systemd (non-editable install)**: nothing changes until you
  re-run the `pip install` command — not just new dependencies, the
  code itself stays exactly as it was at the last install.
- **Manual (editable install, `-e`)**: the code updates immediately,
  but new or changed dependencies still need `pip install` re-run to
  actually get installed.

Either way: always re-run the `pip install` command shown above after
pulling, for both apps.
