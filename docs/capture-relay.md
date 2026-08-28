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

## Contents

- [Why this exists](#why-this-exists)
- [Architecture](#architecture)
- [Two roles, one account name, possibly two different actual accounts](#two-roles-one-account-name-possibly-two-different-actual-accounts)
- [1. The account on the EVE-NG host (SSH target)](#1-the-account-on-the-eve-ng-host-ssh-target----role-2-above)
- [2. A keypair](#2-a-keypair----role-1s-machines-not-the-eve-ng-host)
- [3. Scope sudo rights to exactly what's needed](#3-scope-sudo-rights-to-exactly-whats-needed)
- [4. Configure two SEPARATE `.env` files](#4-configure-two-separate-env-files)
- [5. Install and enable the relay as its own systemd service](#5-install-and-enable-the-relay-as-its-own-systemd-service)
- [6. Enable the tools on the main mcp-eveng process](#6-enable-the-tools-on-the-main-mcp-eveng-process)
- [7. The `.bat` companion and Windows registration](#7-the-bat-companion-and-windows-registration)
- [Known limitations](#known-limitations)

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
                    mcp-relay.service (own systemd unit, verifies
                    token, SSHes into EVE-NG, docker exec ... dumpcap,
                    streams the result back over plain chunked HTTP)
                    ──▶ Wireshark (-k -i -)
```

`list_captures`/`get_capture` (in the main `mcp-eveng` process) and the
relay authenticate as the **same** SSH account -- see below -- but for
two different purposes: the main process only ever runs `docker ps`
(discovery), the relay is the only thing that ever runs `docker exec`.

## Two roles, one account name, possibly two different actual accounts

`mcp-eveng` gets used as an account name in two genuinely different
roles here -- worth keeping straight, since conflating them is an easy
way to get confused:

1. **The account systemd uses to *run* `mcp-eveng.service` and
   `mcp-relay.service` locally**, on whichever machine(s) those
   processes are deployed on. systemd `exec`s the process directly as
   this account -- it never invokes a shell to do it, so `nologin` (no
   real shell) is completely fine here, and a home directory isn't
   required either (though see the private-key note in step 2 below).
2. **The account those processes SSH *into*, on the EVE-NG host, to run
   `docker ps`/`docker exec`.** This one goes through `sshd`, which
   *does* invoke the account's shell to execute the command --
   `nologin` here breaks everything (see the fix below), and it needs a
   real home directory for `authorized_keys` to live in.

If everything's on one machine, these could be the literal same Unix
account. If the EVE-NG host is a separate machine from wherever
`mcp-eveng`/`mcp-relay` run (the more common setup, and the one this
doc assumes), they're two *different* accounts that happen to share a
name for consistency -- with different requirements each, per above.

## 1. The account on the EVE-NG host (SSH target) -- role 2 above

```bash
sudo useradd --system --create-home --shell /bin/bash mcp-eveng
```

**A real shell (`/bin/bash`), not `/usr/sbin/nologin`.** `nologin`
doesn't just block interactive sessions -- it refuses to execute *any*
command handed to it over SSH at all, including the one-off `docker
ps`/`docker exec` calls both `list_captures` and the relay need.
Authenticating with a key still succeeds either way (auth and
shell-invocation are separate steps), so a `nologin` shell won't stop
you from *connecting* -- it fails right after, with `"This account is
currently not available"` -- OpenSSH's own message for exactly this
shell, not a permissions or key problem. Restricting what this account
can actually do is sudo's job (step 3 below), not the shell's.

`--create-home` sets up `/home/mcp-eveng` and (once you generate a key
in step 2) its `.ssh` directory, avoiding a manual `mkdir`/`chmod` --
if you already created this manually, double-check ownership:

```bash
sudo chown -R mcp-eveng:mcp-eveng /home/mcp-eveng/.ssh
sudo chmod 700 /home/mcp-eveng/.ssh
sudo chmod 600 /home/mcp-eveng/.ssh/*   # every file directly inside it, keys included
```

A directory or key file left owned by `root` (e.g. from `sudo mkdir`
without a follow-up `chown`) is a common cause of `[Errno 13]
Permission denied` when the process actually tries to read the key --
worth checking with `ls -la /home/mcp-eveng/.ssh/` if you hit that.

## 2. A keypair -- role 1's machine(s), NOT the EVE-NG host

**Generate this on whichever machine(s) run `mcp-eveng`/`mcp-relay`**,
not by SSHing into the EVE-NG host and running `ssh-keygen` there --
the private key needs to live wherever the connection originates
*from*. Only the **public** half ever needs to reach the EVE-NG host.

Linux/macOS:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mcp-eveng-capture -N ""
```

Windows (PowerShell, using OpenSSH's client -- included by default on
Windows 10 1803+/11):

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\mcp-eveng-capture -N '""'
```

If role 1's account (running the systemd services) has no home
directory of its own to hold this key persistently, create one and
point `CAPTURE_SSH_KEY_PATH` at a file inside it -- and make sure it's
actually owned by that account, not left owned by `root` from a `sudo
mkdir`:

```bash
sudo mkdir -p /home/mcp-eveng/.ssh
sudo chown -R mcp-eveng:mcp-eveng /home/mcp-eveng/.ssh
sudo chmod 700 /home/mcp-eveng/.ssh
# then generate the key (or copy an existing one) into it, owned by mcp-eveng:
sudo -u mcp-eveng ssh-keygen -t ed25519 -f /home/mcp-eveng/.ssh/mcp-eveng-capture -N ""
sudo chmod 600 /home/mcp-eveng/.ssh/mcp-eveng-capture
```

Then, back **on the EVE-NG host**, append the resulting *public* key
(the `.pub` file's contents -- one line) to `mcp-eveng`'s own
`authorized_keys` there:

```bash
sudo -u mcp-eveng bash -c 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo "PASTE_THE_PUBLIC_KEY_LINE_HERE" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

If `mcp-eveng` and `mcp-relay` (the relay) run on the same machine as
each other, one keypair covers both -- point both `.env` files'
`CAPTURE_SSH_KEY_PATH` at the same file. If they run on genuinely
different machines, generate one keypair per machine and append each
public half to the same `authorized_keys` file on the EVE-NG host (one
line per key -- multiple keys can coexist there).

## 3. Scope sudo rights to exactly what's needed

`/etc/sudoers.d/mcp-eveng-capture-relay` (edit with `visudo -f` to get
syntax validation):

```
mcp-eveng ALL=(root) NOPASSWD: /usr/bin/docker ps --filter ancestor\=eve-wireshark --format *, /usr/bin/docker exec * dumpcap -i eth0 -w -
```

One rule, both commands, for the `mcp-eveng` account on the EVE-NG
host (role 2 above).

Confirm the exact path to `docker` on your EVE-NG host first (`which
docker`) -- sudoers command matching is exact-path, not `$PATH`-aware.
The `*` wildcards are broader than ideal (sudoers doesn't support
matching "any container name" more precisely without a wrapper script),
but this is still restricted to exactly these two specific docker
subcommand shapes, not arbitrary docker access.

## 4. Configure two SEPARATE `.env` files

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
  systemd unit uses (e.g. `/opt/mcp_relay/.env`) -- a
  different location from the main process's `.env`, even if you keep
  both checkouts under the same parent directory.

`CAPTURE_SSH_HOST`/`_PORT`/`_USERNAME` are now **identical** in both
files -- the same `mcp-eveng` account (role 2, step 1). `CAPTURE_SSH_KEY_PATH`
is NOT necessarily identical -- it's a local path on whichever machine
each process actually runs on (see step 2), so it only matches if
`mcp-eveng` and `mcp-relay` happen to run on the same machine as each
other.

`CAPTURE_TOKEN_SECRET` **must be the exact same value** in both files --
generate it once (`openssl rand -hex 32`) and copy it into both, don't
generate it twice.

## 5. Install and enable the relay as its own systemd service

**There is only ONE source checkout** (wherever you cloned this repo,
e.g. `/opt/mcp_eveng`) -- the relay does NOT need its own separate copy
of the code, just its own separate *venv* and *`.env`*, in whatever
directory you want that deployment to live (e.g. `/opt/mcp_relay`).
Every `pip install` below points at the same source path
(`/opt/mcp_eveng[capture-relay]`) regardless of which venv it's
installing into.

```bash
sudo mkdir -p /opt/mcp_relay
cd /opt/mcp_relay
sudo python3 -m venv .venv
sudo chown -R mcp-eveng:mcp-eveng /opt/mcp_relay

# Run the venv's own pip directly as the mcp-eveng account, rather than
# `source .venv/bin/activate` -- activation doesn't reliably carry
# through `sudo -u` the way directly invoking the venv's binary does.
sudo -u mcp-eveng /opt/mcp_relay/.venv/bin/pip install "/opt/mcp_eveng[capture-relay]"
```

This installs the `mcp_eveng` package -- built from `/opt/mcp_eveng`'s
source -- into `/opt/mcp_relay`'s own venv. That package's
`pyproject.toml` defines *two* console scripts, so BOTH `mcp-eveng` and
`mcp-eveng-capture-relay` end up in `/opt/mcp_relay/.venv/bin/`
regardless of which one you actually meant to run there -- **the relay
service must run `mcp-eveng-capture-relay`, not `mcp-eveng`.** Running
`mcp-eveng --http` out of the relay's own venv starts a second copy of
the *main* MCP tool server instead of the actual relay -- it'll listen
on a port, but it's the wrong application entirely, and won't touch
the capture-streaming code at all.

The exact same install pattern applies to `mcp-eveng.service`'s own
venv too (e.g. `/opt/mcp_eveng`, or wherever its `WorkingDirectory`
is) -- `[capture-relay]` needs to be installed into **both** venvs
separately, since they're independent Python environments and nothing
installed into one is visible to the other:

```bash
sudo -u mcp-eveng /opt/mcp_eveng/.venv/bin/pip install "/opt/mcp_eveng[capture-relay]"
```

```bash
sudo vi /etc/systemd/system/mcp-relay.service
```

```ini
# /etc/systemd/system/mcp-relay.service

[Unit]
Description=Standalone relay for EVE-NG PRO capture streaming (mcp-eveng)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

# Role 1's account (see the callout above) -- the one systemd uses to
# run this process locally, not the SSH-target account on the EVE-NG
# host (even though they may share this same name).
User=mcp-eveng
Group=mcp-eveng

WorkingDirectory=/opt/mcp_relay

# The RELAY's own binary -- NOT mcp-eveng, and no --http flag (this
# entrypoint takes no CLI flags at all; it reads CAPTURE_RELAY_LISTEN_*
# from .env instead). See the note above this unit file.
ExecStart=/opt/mcp_relay/.venv/bin/mcp-eveng-capture-relay

Restart=on-failure
RestartSec=5

StandardOutput=journal
StandardError=journal

# --- Light sandboxing -- relax/remove any of these if they cause problems ---
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/mcp_relay

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl start mcp-relay.service
sudo systemctl status mcp-relay.service
sudo systemctl enable mcp-relay.service
```

Independent of `mcp-eveng.service` entirely -- a crash or hang in the
relay can't take the main MCP tool server down, and vice versa.

## 6. Enable the tools on the main mcp-eveng process

`list_captures`/`get_capture` ship **disabled by default even on PRO**
(unlike most PRO-only tools in this project) -- deliberately, since
they depend on infrastructure (the SSH account/group and the relay
service above) that doesn't exist until you set it up. Once steps 1-5
are done:

```bash
# in /opt/mcp_eveng/tools.env
list_captures=enabled
get_capture=enabled
```

## 7. The `.bat` companion and Windows registration

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
