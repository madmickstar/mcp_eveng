# Upgrading

`mcp-eveng` and `mcp-relay` share ONE source checkout, ONE venv, and
ONE `.env` file — not separate installs. One `git pull` + one
`pip install` covers both; stop both services first, and start them
again once you're done.

**systemd deployment (Linux):**

```bash
systemctl status mcp-eveng
sudo systemctl stop mcp-eveng
systemctl status mcp-eveng

cd /opt/mcp_eveng
sudo -u mcp-eveng git pull
sudo -u mcp-eveng /opt/mcp_eveng/.venv/bin/pip install /opt/mcp_eveng

sudo systemctl start mcp-eveng
systemctl status mcp-eveng
```

The two `systemctl status` calls around the `stop` aren't optional
busywork — the first shows what you're changing, the second confirms it
actually stopped before you touch anything under it; the same two calls
around `start` confirm it came back up cleanly afterward. Running `git
pull` and `pip install` as `-u mcp-eveng` (the service account itself,
not root) means the pulled files are already owned by the right user —
no `chown` needed as part of the normal flow.

If you run `mcp-relay.service` too, repeat the same six commands for it
(`systemctl status mcp-relay`, `sudo systemctl stop mcp-relay`, etc.) —
they share the same checkout and venv, so one `pip install` covers both;
you only need to stop/start each service that's actually running.

If `git pull` or `pip install` fails with a permissions error — most
likely because an earlier upgrade was run as root (e.g. `sudo git pull`)
and left some files root-owned — fix ownership once with:

```bash
sudo chown mcp-eveng:mcp-eveng -R /opt/mcp_eveng
```

then retry the `git pull`/`pip install` lines above as `-u mcp-eveng`.

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
