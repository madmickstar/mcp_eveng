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
- [5. Install and config mcp-relay App (MCP server)](#5-install-and-config-mcp-relay-app-mcp-server)
- [6. Install and config mcp-eveng App (MCP server)](#6-install-and-config-mcp-eveng-app-mcp-server)
- [7. Create and start the systemd service (MCP server)](#7-create-and-start-the-systemd-service-mcp-server)
- [8. Enable the tools on the main mcp-eveng process](#8-enable-the-tools-on-the-main-mcp-eveng-process)
- [9. The `.bat` companion and Windows registration](#9-the-bat-companion-and-windows-registration)
- [Known limitations](#known-limitations)

## Architecture

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

Not on the EVE-NG host — on whichever machine(s) run `mcp-eveng`/`mcp-relay`.

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

One keypair covers both `mcp-eveng` and `mcp-relay` if they run on the
same machine. Otherwise generate one per machine and append each
public half to the same `authorized_keys` file.

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

## 5. Install and config mcp-relay App (MCP server)

```bash
sudo git clone https://github.com/madmickstar/mcp_eveng.git /opt/mcp_eveng
# skip the line above if you already have /opt/mcp_eveng from
# install-linux.md's systemd setup

sudo mkdir -p /opt/mcp_relay
cd /opt/mcp_relay
sudo python3 -m venv .venv
sudo chown -R mcp-eveng:mcp-eveng /opt/mcp_relay
sudo -u mcp-eveng /opt/mcp_relay/.venv/bin/pip install "/opt/mcp_eveng[capture-relay]"
```

The clone target is `/opt/mcp_eveng`, not `/opt/mcp_relay` — there is
only ONE shared source checkout (used by both apps); `/opt/mcp_relay`
is just this app's own separate venv + `.env`, installed *from* that
shared source above.

Copy **`.env.capture-relay.example`** (project root) to `/opt/mcp_relay/.env`
and configure it. Includes optional `CAPTURE_RELAY_TLS_CERT_PATH`/
`_KEY_PATH` to serve this relay over HTTPS instead of plain HTTP — see
the comments in that file.

## 6. Install and config mcp-eveng App (MCP server)

```bash
sudo -u mcp-eveng /opt/mcp_eveng/.venv/bin/pip install "/opt/mcp_eveng[capture-relay]"
```

This upgrades the existing `mcp-eveng` install to add the `[capture-relay]`
extra (`asyncssh`) it needs for `list_captures`/`get_capture` to SSH into
the EVE-NG host directly.

Your `.env` here already exists from setting up `mcp-eveng` itself (see
`install-linux.md`/`install-windows.md`) — this step only needs a few
fields added or updated in that existing file, not a fresh copy of
`.env.example`:

- `CAPTURE_SSH_HOST`/`_PORT`/`_USERNAME` are identical in both `.env` files.
- `CAPTURE_SSH_KEY_PATH` is a local path per machine — only identical
  if both processes run on the same machine.
- `CAPTURE_TOKEN_SECRET` **must be the exact same value** in both —
  generate once (`openssl rand -hex 32`) and copy into both.

## 7. Create and start the systemd service (MCP server)

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

User=mcp-eveng
Group=mcp-eveng

WorkingDirectory=/opt/mcp_relay
ExecStart=/opt/mcp_relay/.venv/bin/mcp-eveng-capture-relay

Restart=on-failure
RestartSec=5
TimeoutStopSec=20

StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
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

### Start app manually (any OS, including Windows)

```
python -m mcp_eveng.capture_relay
```

or the installed console script directly: `mcp-eveng-capture-relay`.
No `--http` flag — reads `CAPTURE_RELAY_LISTEN_HOST`/`_PORT` from
`.env` in the current working directory.

## 8. Enable the tools on the main mcp-eveng process

```bash
# in tools.env
list_captures=enabled
get_capture=enabled
```

## 9. The `.bat` companion and Windows registration

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
  `CAPTURE_RELAY_ADVERTISE_HOST`/`_PORT` (main `.env`) match
  `CAPTURE_RELAY_LISTEN_HOST`/`_PORT` (relay's `.env`)? (3) firewall
  between the relay's host and the Windows client?
