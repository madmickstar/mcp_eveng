# Capture relay (PRO/Corporate only)

Streams an EVE-NG PRO capture (started from the GUI's right-click
"Capture" menu, same as always) to a local Wireshark, without every
analyst needing their own personal SSH+sudo account on the EVE-NG host.

**Status: fully implemented (59 tests across `capture_relay/` and
`tools/capture.py`, plus a written `.bat` companion), but not yet
exercised against a live EVE-NG server.** The token scheme, `docker ps`
parsing, URL building, and the relay's HTTP/streaming logic are all
tested directly; the actual SSH connections (`ssh_client.py`'s
`run_command`/`streaming_process`) are thin wrappers around `asyncssh`
that this project's test environment has no way to exercise live, and
`scripts/eve-capture.bat` can't be run/verified outside a real Windows
machine at all. Treat this as ready for a supervised first end-to-end
test, not yet a proven production path.

Community needs none of this -- its own GUI already generates working
`capture://` links with no MCP involvement at all.

## Why this exists

EVE-NG PRO forces captures into an embedded Guacamole session rather
than handing off to a local Wireshark the way Community's `capture://`
protocol-handler link does. Triggering a capture can't be automated --
confirmed live that each capture container's lifetime is tied to a
heartbeat from the browser tab that started it (refreshing the page
kills captures off one by one, on each one's own staggered idle timer,
not all at once) -- so the person still starts captures from the GUI,
same as today. This feature only helps with what happens *after* that:
finding out what's running, and getting the bytes to a local Wireshark
without a personal SSH+sudo account on the EVE-NG box.

## Architecture

```
 EVE-NG GUI                Windows client                 Linux host
┌───────────┐  starts    ┌───────────────┐   capture://  ┌──────────────────┐
│ right-click│ ─────────▶│ eve-wireshark │──────────────▶│ .bat companion   │
│ > Capture  │  container │  container   │   URL (from   │ (registered      │
└───────────┘             └───────────────┘   get_capture)│ against capture://)│
                                                            └─────────┬────────┘
                                                    mode=pro │ mode=community
                                    ┌───────────────────────┘         │
                                    ▼                                 ▼
                          curl (primary) or plink (fallback)   plink (existing,
                                    │                           unmodified path)
                                    ▼
                    mcp-eveng-capture-relay.service (own systemd unit,
                    verifies token, SSHes into EVE-NG, docker exec ...
                    dumpcap, streams the result back over plain chunked
                    HTTP) ──▶ Wireshark (-k -i -)
```

`list_captures`/`get_capture` (in the main `mcp-eveng` process) and the
relay authenticate as the **same** SSH account -- see below -- but for
two different purposes: the main process only ever runs `docker ps`
(discovery), the relay is the only thing that ever runs `docker exec`.

## 1. Create a single dedicated SSH service account + group

One account (`mcp-relay`), one group (`capture_relay`) -- both
processes authenticate as the same account, and sudo access to the
commands each needs is granted to the *group*, not the username, so
adding anyone/anything else that needs the same rights later is just
adding it to the group, not editing sudoers again.

```bash
sudo groupadd capture_relay
sudo useradd --system --no-create-home --shell /usr/sbin/nologin --groups capture_relay mcp-relay

# One keypair, used by both the main process's .env and the relay's own .env.
sudo -u mcp-relay ssh-keygen -t ed25519 -f /home/mcp-relay/.ssh/id_ed25519 -N ""
```

(A `--no-create-home` system account still needs an `.ssh` directory for
its own key -- create `/home/mcp-relay/.ssh` with `0700` permissions
owned by `mcp-relay` first if `ssh-keygen` doesn't create it
automatically.)

## 2. Scope the group's sudo rights to exactly what's needed

`/etc/sudoers.d/mcp-eveng-capture-relay` (edit with `visudo -f` to get
syntax validation):

```
%capture_relay ALL=(root) NOPASSWD: /usr/bin/docker ps --filter ancestor\=eve-wireshark --format *, /usr/bin/docker exec * dumpcap -i eth0 -w -
```

One rule, both commands, applied to the `%capture_relay` group -- any
account in that group (just `mcp-relay` for now) can run either.

Confirm the exact path to `docker` on your EVE-NG host first (`which
docker`) -- sudoers command matching is exact-path, not `$PATH`-aware.
The `*` wildcards are broader than ideal (sudoers doesn't support
matching "any container name" more precisely without a wrapper script),
but this is still restricted to exactly these two specific docker
subcommand shapes, not arbitrary docker access.

## 3. Configure two SEPARATE `.env` files

**Two example files, two different processes -- don't mix them.**
Confusing the two is easy since several variable names are shared
(`CAPTURE_SSH_*`, `CAPTURE_TOKEN_SECRET`) with the SAME *values* now
(one shared account) but a couple of names look similar and aren't
(`CAPTURE_RELAY_LISTEN_*` vs. `CAPTURE_RELAY_ADVERTISE_*`) -- both
example files below are heavily commented specifically to head this
off.

- **`.env.example`** (project root) → copy to the main `mcp-eveng`
  process's `.env`. Now includes a `list_captures`/`get_capture` section
  in addition to the existing `EVENG_*`/`MCP_*` variables.
- **`.env.capture-relay.example`** (project root) → copy to the
  standalone relay's own `.env`, in whatever `WorkingDirectory` its
  systemd unit uses (e.g. `/opt/mcp-eveng-capture-relay/.env`) -- a
  different location from the main process's `.env`, even if you keep
  both checkouts under the same parent directory.

`CAPTURE_SSH_HOST`/`_PORT`/`_USERNAME`/`_KEY_PATH` are now **identical**
in both files -- the same `mcp-relay` account, per step 1.

`CAPTURE_TOKEN_SECRET` **must be the exact same value** in both files --
generate it once (`openssl rand -hex 32`) and copy it into both, don't
generate it twice.

## 4. Install and enable the relay as its own systemd service

```bash
cd /opt/mcp-eveng-capture-relay   # separate checkout/venv from mcp-eveng.service's
sudo python3 -m venv .venv
source .venv/bin/activate
pip install "/opt/mcp_eveng[capture-relay]"   # from the same source checkout
deactivate
sudo chown mcp-relay:capture_relay -R /opt/mcp-eveng-capture-relay
```

```bash
sudo vi /etc/systemd/system/mcp-eveng-capture-relay.service
```

```ini
# /etc/systemd/system/mcp-eveng-capture-relay.service

[Unit]
Description=Standalone relay for EVE-NG PRO capture streaming (mcp-eveng)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

# The shared account/group from step 1 -- deliberately separate from
# mcp-eveng.service's own account (whatever that's configured as).
User=mcp-relay
Group=capture_relay

WorkingDirectory=/opt/mcp-eveng-capture-relay
ExecStart=/opt/mcp-eveng-capture-relay/.venv/bin/mcp-eveng-capture-relay

Restart=on-failure
RestartSec=5

StandardOutput=journal
StandardError=journal

# --- Light sandboxing -- relax/remove any of these if they cause problems ---
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/mcp-eveng-capture-relay

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl start mcp-eveng-capture-relay.service
sudo systemctl status mcp-eveng-capture-relay.service
sudo systemctl enable mcp-eveng-capture-relay.service
```

Independent of `mcp-eveng.service` entirely -- a crash or hang in the
relay can't take the main MCP tool server down, and vice versa.

## 5. Enable the tools on the main mcp-eveng process

`list_captures`/`get_capture` ship **disabled by default even on PRO**
(unlike most PRO-only tools in this project) -- deliberately, since
they depend on infrastructure (the SSH account/group and the relay
service above) that doesn't exist until you set it up. Once steps 1-4
are done:

```bash
# in /opt/mcp_eveng/tools.env
list_captures=enabled
get_capture=enabled
```

## 6. The `.bat` companion and Windows registration

`scripts/eve-capture.bat` -- parses the `capture://` URL's `mode`
field and branches: `mode=pro` tries curl against the relay first
(no SSH credentials needed on the client at all), falling back to
plink straight into `eveng_host` only if curl or the relay is
unreachable (using the user's own already-configured SSH access via
the sudoers-scoped group from your *original* setup -- no password
ever appears in the URL either way). No `mode` at all (Community's
existing link shape) skips all of the above entirely and runs
unmodified.

**Edit the top of the script before deploying it:**

```bat
set WIRESHARK=C:\Program Files\Wireshark\Wireshark.exe
set PLINK=C:\Path\To\plink.exe
set COMMUNITY_SSH_USER=eve-capture-user
```

**The Community-mode and plink-fallback command blocks in this script
were reconstructed from a prose description of your existing working
setup, not copied from your actual `.bat`.** Compare them against what
you already have and replace them if they differ at all -- this
project doesn't have your original file's exact text.

Windows registration (same mechanism your existing Community setup
already uses -- if `capture://` is already registered, skip this):

```reg
Windows Registry Editor Version 5.00

[HKEY_CLASSES_ROOT\capture]
@="URL:EVE-NG Capture Protocol"
"URL Protocol"=""

[HKEY_CLASSES_ROOT\capture\shell]

[HKEY_CLASSES_ROOT\capture\shell\open]

[HKEY_CLASSES_ROOT\capture\shell\open\command]
@="\"C:\\Path\\To\\eve-capture.bat\" \"%1\""
```

Adjust the path in the last line to wherever `eve-capture.bat` actually
lives, then double-click the `.reg` file (or import it via `regedit`)
to install it.

## Known limitations

- **Unverified against live infrastructure** -- see the status note at
  the top.
- **The `list_captures`/`get_capture` venv still needs `asyncssh`
  installed** even though `server.py` itself no longer requires it just
  to start -- `pip install -e ".[capture-relay]"` (or just `pip install
  asyncssh`; Starlette/uvicorn are only needed by the relay's own
  entrypoint, not by these two tools). A missing `asyncssh` now gives a
  clear error when the tool is actually called, rather than crashing the
  whole server at startup (confirmed live -- this was a real bug caught
  during initial testing, fixed by making the `asyncssh` import lazy).
- **One relay per EVE-NG host in this version** -- `get_capture`'s URL
  always points at `CAPTURE_RELAY_ADVERTISE_HOST`/`_PORT`, a single
  fixed address. Multiple EVE-NG servers need their own relay each.
- **No revocation beyond token expiry** -- a leaked `capture://` URL is
  valid for `CAPTURE_TOKEN_TTL_SECONDS` (60s default) regardless of
  anything else. Keep this short rather than relying on any other
  mitigation.
- **`docker` path in sudoers is hardcoded to `/usr/bin/docker`** --
  confirm this matches your EVE-NG host before relying on the sudoers
  rules above.
