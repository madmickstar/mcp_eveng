# Capture relay (PRO only)

Streams an EVE-NG PRO capture to a local Wireshark, without a personal
SSH+sudo account on the EVE-NG host. Community doesn't need this — its
own GUI already generates working `capture://` links.

## Contents

- [Architecture](#architecture)
- [1. Create the account + group (EVE-NG host)](#1-create-the-account--group-eve-ng-host)
- [2. Generate a key pair (MCP Server)](#2-generate-a-key-pair-mcp-server)
- [3. Append the public key (EVE-NG host)](#3-append-the-public-key-eve-ng-host)
- [4. Sudoers (EVE-NG host)](#4-sudoers-eve-ng-host)
- [5. Add capture-relay settings to your .env](#5-add-capture-relay-settings-to-your-env)
- [6. Create and start the systemd service (MCP server)](#6-create-and-start-the-systemd-service-mcp-server)
- [7. Enable the tools on the main mcp-eveng process](#7-enable-the-tools-on-the-main-mcp-eveng-process)
- [8. The `.bat` companion and Windows registration](#8-the-bat-companion-and-windows-registration)
- [Known limitations](#known-limitations)

## Architecture

`mcp-eveng` and `mcp-relay` are two different **entrypoints of the same
package** (`mcp-eveng` and `mcp-eveng-capture-relay`, both installed by
the same `pip install`), sharing ONE venv and ONE `.env` file — not two
separate installs. Each process reads only the settings it cares about
from that shared `.env` (confirmed directly: every settings class here
uses `extra="ignore"`), so nothing needs duplicating or kept in sync
across files anymore.

```
 EVE-NG GUI                Windows client                 Linux host
┌───────────┐  starts    ┌───────────────┐   capture://  ┌──────────────────┐
│ right-click│ ─────────▶│ eve-wireshark │──────────────▶│ .bat companion   │
│ > Capture  │  container │  container   │   URL (from   │ (registered      │
└───────────┘             └───────────────┘   get_capture)│ against capture://)│
                                                            └─────────┬────────┘
                                              vunl*/pnet*? no │ yes
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

`list_captures`/`get_capture` (main process) and the relay authenticate
as the same SSH account, for two different purposes: the main process
only runs `docker ps`; the relay is the only thing that runs `docker
exec`.

## 1. Create the account + group (EVE-NG host)

```bash
sudo groupadd capture_relay
sudo useradd --system --create-home --shell /bin/bash --groups capture_relay mcp-eveng
```

## 2. Generate a key pair (MCP Server)

Not on the EVE-NG host — on whichever machine runs `mcp-eveng`/`mcp-relay`.

Linux/macOS:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mcp-eveng-capture -N ""
```

If the local account has no home directory:

```bash
sudo mkdir -p /home/mcp-eveng/.ssh
sudo chown -R mcp-eveng:mcp-eveng /home/mcp-eveng/.ssh
sudo chmod 700 /home/mcp-eveng/.ssh
sudo -u mcp-eveng ssh-keygen -t ed25519 -f /home/mcp-eveng/.ssh/mcp-eveng-capture -N ""
sudo chmod 600 /home/mcp-eveng/.ssh/mcp-eveng-capture
```

Windows (PowerShell):

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\mcp-eveng-capture -N '""'
```

PowerShell permission fix (private keys must not be readable by other
local accounts):

```powershell
# 1. Remove inherited permissions from the file
icacls "$env:USERPROFILE\.ssh\mcp-eveng-capture" /inheritance:r
# 2. Grant explicit full control only to your active Windows username
icacls "$env:USERPROFILE\.ssh\mcp-eveng-capture" /grant:r "$($env:USERNAME):F"
# Alternative do to all files at same time
icacls "$env:USERPROFILE\.ssh" /T /C /inheritance:r
icacls "$env:USERPROFILE\.ssh" /T /C /grant:r "$($env:USERNAME):F"
```

## 3. Append the public key (EVE-NG host)

```bash
sudo -u mcp-eveng bash -c 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo "PASTE_THE_PUBLIC_KEY_LINE_HERE" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

One keypair covers both `mcp-eveng` and `mcp-relay`, since they share
one machine and one account now.

## 4. Sudoers (EVE-NG host)

`/etc/sudoers.d/capture_relay` (edit with `visudo -f`):

```
# Allow EVE-NG PRO commands
%capture_relay  ALL=(root) NOPASSWD: /usr/bin/docker ps --filter ancestor\=eve-wireshark --format *
%capture_relay  ALL=(root) NOPASSWD: /usr/bin/docker exec * dumpcap -i eth0 -w -

# Allow EVE-NG Community commands
%capture_relay  ALL=(root) NOPASSWD: /usr/bin/tcpdump -U -i * -s 0 -w -*
```

Confirm `docker`/`tcpdump` paths match your host (`which docker`,
`which tcpdump`) — sudoers matching is exact-path.

## 5. Add capture-relay settings to your .env

Nothing new to install — `asyncssh`/`starlette`/`uvicorn` (what both
`list_captures`/`get_capture` and the standalone relay need) are base
dependencies of `mcp-eveng` itself, already included if you set this up
via `install-linux.md`'s systemd section. If you haven't installed
`mcp-eveng` yet, do that first.

Your `/opt/mcp_eveng/.env` already exists from that install — this step
just adds the capture-relay section to it (copy the relevant block from
`.env.example`, which has it as its own clearly-labeled section):

- `CAPTURE_SSH_HOST`/`_PORT`/`_USERNAME`/`_KEY_PATH`, `CAPTURE_SSH_KNOWN_HOSTS`,
  and `CAPTURE_TOKEN_SECRET` are read by BOTH processes — one shared
  value each, no keeping two files in sync.
- `CAPTURE_SSH_TIMEOUT_SECONDS`, `CAPTURE_TOKEN_TTL_SECONDS`, and
  `CAPTURE_RELAY_ADVERTISE_HOST`/`_PORT` are read only by `mcp-eveng`
  (`list_captures`/`get_capture`).
- `CAPTURE_RELAY_LISTEN_HOST`/`_PORT`, `CAPTURE_RELAY_LOG_LEVEL`, and
  `CAPTURE_RELAY_TLS_*` are read only by the standalone relay.

If you're using `CAPTURE_SSH_KNOWN_HOSTS` or either `*_TLS_*` pair, see
`install-linux.md`'s systemd section step 5 for creating
`/etc/mcp-eveng` with the right ownership/permissions to put the actual
files in.

## 6. Create and start the systemd service (MCP server)

A ready-to-use unit ships in the repo — `systemd/mcp-relay.service`:

```bash
sudo cp /opt/mcp_eveng/systemd/mcp-relay.service /etc/systemd/system/mcp-relay.service
```

Same `WorkingDirectory`/`ReadWritePaths` as `mcp-eveng.service` itself
— both processes share the one venv and one `.env` under
`/opt/mcp_eveng`, only `ExecStart` differs between the two units.

```bash
sudo systemctl daemon-reload
sudo systemctl start mcp-relay.service
sudo systemctl status mcp-relay.service
sudo systemctl enable mcp-relay.service
```

### Start app manually (any OS, including Windows)

```
python -m mcp_eveng.capture_relay
```

or the installed console script directly: `mcp-eveng-capture-relay`.
No `--http` flag — reads `CAPTURE_RELAY_LISTEN_HOST`/`_PORT` from
`.env` in the current working directory.

## 7. Enable the tools on the main mcp-eveng process

```bash
# in tools.env
list_captures=enabled
get_capture=enabled
```

## 8. The `.bat` companion and Windows registration

Edit the top of `scripts/eve-capture.bat`:

```bat
set WIRESHARK=C:\Program Files\Wireshark\Wireshark.exe
set PLINK=C:\Program Files\PuTTY\plink.exe
set PRO_SSH_USER=eve-pro-user
set PRO_SSH_KEY=%HOMEPATH%\.ssh\eve-pro.ppk
set COMMUNITY_SSH_USER=eve-comm-user
set COMMUNITY_SSH_KEY=%HOMEPATH%\.ssh\eve-comm.ppk
```

`PRO_SSH_*` authenticates against the relay-fallback account (step 1/4).
`COMMUNITY_SSH_*` is your existing Community setup's account. Both
default to key-based (`-i`, PuTTY `.ppk` format — convert an
OpenSSH-format key with `puttygen` if needed); a commented-out
password-based (`-pw`) alternative is included at each call.

Windows registration (skip if `capture://` is already registered):

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

Adjust the path to wherever `eve-capture.bat` lives, then import the
`.reg` file (double-click it, or via `regedit`).

See [Upgrading](upgrading.md) for updating an existing install of
either app.

## Known limitations

- **One relay per EVE-NG host** — `get_capture`'s URL always points at
  a single fixed `CAPTURE_RELAY_ADVERTISE_HOST`/`_PORT`.
- **No revocation beyond token expiry** — a leaked `capture://` URL is
  valid for `CAPTURE_TOKEN_TTL_SECONDS` (60s default).
- **`docker`/`tcpdump` paths in sudoers are hardcoded** — confirm they
  match your EVE-NG host.
- **If the `.bat`'s curl preflight fails or falls back to plink
  unexpectedly**, check: (1) is `mcp-relay.service` running? (2) do
  `CAPTURE_RELAY_ADVERTISE_HOST`/`_PORT` match `CAPTURE_RELAY_LISTEN_HOST`/
  `_PORT` (same `.env`, both read from it)? (3) firewall between the
  relay's host and the Windows client?
