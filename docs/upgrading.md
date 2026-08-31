# Upgrading

`mcp-eveng` and `mcp-relay` share ONE source checkout, ONE venv, and
ONE `.env` file — not separate installs. One `git pull` + one
`pip install` covers both; restart whichever systemd service(s) you
run afterward.

**systemd deployment (Linux):**

```bash
cd /opt/mcp_eveng
sudo git pull
sudo -u mcp-eveng /opt/mcp_eveng/.venv/bin/pip install /opt/mcp_eveng
sudo systemctl restart mcp-eveng.service
sudo systemctl restart mcp-relay.service   # only if you run this too
```

**Manual install (any OS):**

```bash
cd mcp_eveng
git pull
pip install -e .
```

Restart whichever process(es) you have running (`mcp-eveng`,
`python -m mcp_eveng`, `mcp-eveng-capture-relay`, or
`python -m mcp_eveng.capture_relay`). Windows: use your venv's own
`pip` (`.venv\Scripts\pip.exe`, or an activated venv) for the same
command.

If you're doing development work on this project itself (running the
test suite, linting), use `.[dev]` instead of the plain commands above.

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
pulling.
