# Upgrading

There is only ONE source checkout, shared by both apps — `mcp-relay`
doesn't have its own separate clone, just its own separate venv. Pull
once, reinstall into whichever venv(s) you have.

## mcp-eveng app

**systemd deployment (Linux):**

```bash
cd /opt/mcp_eveng
sudo git pull
sudo -u mcp-eveng /opt/mcp_eveng/.venv/bin/pip install -e ".[dev]"
sudo systemctl restart mcp-eveng.service
```

**Manual/dev install (any OS):**

```bash
cd mcp_eveng
git pull
pip install -e ".[dev]"
```

Restart your running `mcp-eveng` (or `python -m mcp_eveng`) process.
Windows: use your venv's own `pip` (`.venv\Scripts\pip.exe`, or an
activated venv) for the same command.

## mcp-relay app

**systemd deployment (Linux):**

```bash
sudo -u mcp-eveng /opt/mcp_relay/.venv/bin/pip install "/opt/mcp_eveng[capture-relay]"
sudo systemctl restart mcp-relay.service
```

**Manual/dev install (any OS):**

```bash
pip install "/path/to/mcp_eveng[capture-relay]"
```

Restart your running `python -m mcp_eveng.capture_relay` (or
`mcp-eveng-capture-relay`) process.

## Note

`git pull` alone doesn't install new or changed dependencies — always
re-run the `pip install` command after pulling, for both apps.
