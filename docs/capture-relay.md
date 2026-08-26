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
                    own SSH service account, verifies token, SSHes into
                    EVE-NG, docker exec ... dumpcap, streams the result
                    back over plain chunked HTTP) ──▶ Wireshark (-k -i -)
```

`list_captures`/`get_capture` (in the main `mcp-eveng` process) use a
**separate** SSH service account from the relay's -- see below --
purely for `docker ps` discovery; they never touch the capture stream
itself.

## 1. Create two dedicated SSH service accounts on the EVE-NG host

Two, not one -- `list_captures` only ever needs read-only `docker ps`;
giving it `docker exec` rights it never uses would be needless
privilege. The relay is the only thing that ever runs `docker exec`.

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin mcp-eveng-capture-list
sudo useradd --system --no-create-home --shell /usr/sbin/nologin mcp-eveng-capture-relay

# Generate a dedicated keypair for each -- do not reuse a personal key.
sudo -u mcp-eveng-capture-list ssh-keygen -t ed25519 -f /home/mcp-eveng-capture-list/.ssh/id_ed25519 -N ""
sudo -u mcp-eveng-capture-relay ssh-keygen -t ed25519 -f /home/mcp-eveng-capture-relay/.ssh/id_ed25519 -N ""
```

(A `--no-create-home` system account still needs an `.ssh` directory for
its own key -- create `/home/<user>/.ssh` with `0700` permissions owned
by that user first if `ssh-keygen` doesn't create it automatically.)

## 2. Scope each account's sudo rights to exactly what it needs

`/etc/sudoers.d/mcp-eveng-capture` (edit with `visudo -f` to get syntax
validation):

```
mcp-eveng-capture-list  ALL=(root) NOPASSWD: /usr/bin/docker ps --filter ancestor\=eve-wireshark --format *
mcp-eveng-capture-relay ALL=(root) NOPASSWD: /usr/bin/docker exec * dumpcap -i eth0 -w -
```

Confirm the exact path to `docker` on your EVE-NG host first (`which
docker`) -- sudoers command matching is exact-path, not `$PATH`-aware.
The `*` wildcards are broader than ideal (sudoers doesn't support
matching "any container name" more precisely without a wrapper script),
but each account is still restricted to exactly one specific docker
subcommand shape, not arbitrary docker access.

## 3. Configure `.env` (shared by both processes if colocated)

```bash
# -- list_captures' account --
CAPTURE_SSH_HOST=172.16.130.14
CAPTURE_SSH_USERNAME=mcp-eveng-capture-list
CAPTURE_SSH_KEY_PATH=/home/mcp-eveng-capture-list/.ssh/id_ed25519
# CAPTURE_SSH_KNOWN_HOSTS=/etc/mcp-eveng/known_hosts   # set this for anything beyond a lab -- see config.py

CAPTURE_TOKEN_SECRET=<a long random string -- e.g. `openssl rand -hex 32`>
# CAPTURE_TOKEN_TTL_SECONDS=60   # default; how long a get_capture URL stays valid

# -- the relay's own listen/advertise address --
CAPTURE_RELAY_LISTEN_HOST=0.0.0.0        # bind address
CAPTURE_RELAY_LISTEN_PORT=8001
CAPTURE_RELAY_ADVERTISE_HOST=172.16.130.14  # what the .bat actually connects to
CAPTURE_RELAY_ADVERTISE_PORT=8001
```

**The relay itself uses the SAME `CAPTURE_SSH_*` variable names**, but
needs them pointed at the *relay's* account instead
(`mcp-eveng-capture-relay`, its own key) -- if both processes read the
same `.env` file, put the relay in its own separate `.env` (e.g.
`/opt/mcp-eveng-capture-relay/.env`) with its own `WorkingDirectory`,
rather than trying to make one `.env` serve two different SSH
identities under the same variable names.

`CAPTURE_TOKEN_SECRET` **must be identical** in both `.env` files --
it's the shared HMAC secret `get_capture` signs with and the relay
verifies against.

## 4. Install and enable the relay as its own systemd service

```bash
cd /opt/mcp-eveng-capture-relay   # separate checkout/venv from mcp-eveng.service's
sudo python3 -m venv .venv
source .venv/bin/activate
pip install "/opt/mcp_eveng[capture-relay]"   # from the same source checkout
deactivate
sudo chown mcp-eveng-capture-relay:mcp-eveng-capture-relay -R /opt/mcp-eveng-capture-relay
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

# Its own dedicated account (step 1 above) -- deliberately separate from
# mcp-eveng.service's own account, and from list_captures' account too.
User=mcp-eveng-capture-relay
Group=mcp-eveng-capture-relay

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
they depend on infrastructure (the SSH accounts and the relay service
above) that doesn't exist until you set it up. Once steps 1-4 are done:

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
