# Capture relay (PRO/Corporate only)

Streams an EVE-NG PRO capture (started from the GUI's right-click
"Capture" menu, same as always) to a local Wireshark, without every
analyst needing their own personal SSH+sudo account on the EVE-NG host.

**Status: `list_captures`/`get_capture` confirmed working live (v0.3.8).
The curl/relay path has now delivered a real, confirmed-successful
capture to Wireshark end-to-end (v0.3.14 test)** -- URL parsing, the
relay reaching the EVE-NG host over SSH, the relay running `dumpcap`,
and streaming real capture data all confirmed live, including a
successful preflight with real bytes received before its own timeout
cutoff (the expected, benign success case -- see the `### Fixed`
entries for the earlier ambiguity this cleared up). Bugs found and
fixed along the way: two in the `.bat`'s URL parsing, one in the relay
itself (`asyncssh` UTF-8 text-mode default), one in the preflight's
timeout window (too tight, widened), and most recently a missing
`plink -i` key flag plus a missing `-batch` flag -- the latter
confirmed live via a decoded Wireshark error (`magic = 0x6b63696d`
decodes to the literal text `mick`, the tester's own Windows username,
meaning an unconfirmed-host-key prompt was leaking into the piped
stream instead of real capture data). See `CHANGELOG.md`'s `### Fixed`
entries for full details on all of these. Test suite covers the token
scheme, `docker ps` parsing, URL building, the relay's HTTP/streaming
logic, and the exact arguments `streaming_process` passes to
`asyncssh`. What's still unverified live: the plink fallback and
Community mode end-to-end with the `-batch`/separate-credentials
fixes just made.

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
   `docker ps`/`docker exec`/`tcpdump` (see step 3).** This one goes
   through `sshd`, which *does* invoke the account's shell to execute
   the command -- `nologin` here breaks everything (see the fix
   below), and it needs a real home directory for `authorized_keys`
   to live in.

If everything's on one machine, these could be the literal same Unix
account. If the EVE-NG host is a separate machine from wherever
`mcp-eveng`/`mcp-relay` run (the more common setup, and the one this
doc assumes), they're two *different* accounts that happen to share a
name for consistency -- with different requirements each, per above.

Role 2's actual sudo rights (step 3) are granted to a dedicated group
(`capture_relay`), not to the `mcp-eveng` username directly -- so
adding another account with the same rights later (a second machine's
account, a human's own account, whatever) only needs adding it to
that group, not another sudoers edit.

## 1. The account on the EVE-NG host (SSH target) -- role 2 above

```bash
sudo groupadd capture_relay
sudo useradd --system --create-home --shell /bin/bash --groups capture_relay mcp-eveng
```

**The `capture_relay` group is what sudo access is actually granted
to (step 3 below), not the `mcp-eveng` username directly** -- so
adding another account that needs the same `docker ps`/`docker exec`/
`tcpdump` rights later (a second EVE-NG-side account, a human
analyst's own account, whatever) is just adding it to this group, not
editing sudoers again. `mcp-eveng` is simply the first (and so far
only) member.

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

**If you store this key under `/home/mcp-eveng/...` (as the examples
below do) and run either process under the systemd units in this doc
or `install-linux.md`, make sure `ProtectHome=read-only`, not `true`,
in both** -- `true` makes `/home` completely invisible to the service,
which looks exactly like a permissions problem on the key file (a
misleading `Permission denied`) but isn't one at all. See step 5's
unit file below.

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

`/etc/sudoers.d/capture_relay` (edit with `visudo -f` to get syntax
validation):

```
# Allow EVE-NG PRO commands
%capture_relay  ALL=(root) NOPASSWD: /usr/bin/docker ps --filter ancestor\=eve-wireshark --format *
%capture_relay  ALL=(root) NOPASSWD: /usr/bin/docker exec * dumpcap -i eth0 -w -

# Allow EVE-NG Community commands
%capture_relay  ALL=(root) NOPASSWD: /usr/bin/tcpdump -U -i * -s 0 -w -*
```

Granted to the **`%capture_relay` group** (the `%` prefix is sudoers'
own syntax for "this is a group, not a username") -- any current or
future member of that group can run any of these, without another
sudoers edit. `mcp-eveng` gets these rights by being a member (step 1),
not by being named here directly.

The Community rule is needed even though `mcp-eveng`'s primary purpose
is the PRO/relay path -- the same account also runs the `.bat`'s
Community-mode `tcpdump` command via plink when a link turns out to be
one of Community's own (see step 7). Unlike a real Community
deployment's own SSH account (which is commonly root, needing no
`sudo` at all for this), this one is deliberately non-root, so `sudo`
is required here.

**Note the trailing `*` after `-w -` on the tcpdump rule specifically**
-- sudoers matches a command exactly unless its own spec ends in a
wildcard, and the Community `.bat` command conditionally appends
`not port 22` after `-w -` for one specific interface (`pnet0`). The
two PRO rules don't need this: `docker exec ... dumpcap -i eth0 -w -`
never has anything appended after it in this project's own design, so
matching it exactly (no trailing `*`) is intentional, not an oversight.

Confirm the exact path to `docker`/`tcpdump` on your EVE-NG host first
(`which docker`, `which tcpdump`) -- sudoers command matching is
exact-path, not `$PATH`-aware. The `*` wildcards elsewhere are broader
than ideal (sudoers doesn't support matching "any container name" or
"any interface name" more precisely without a wrapper script), but
each rule is still restricted to exactly one specific command shape,
not arbitrary `docker`/`tcpdump` access.

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

# Safety net on top of uvicorn's own timeout_graceful_shutdown (5s, set
# in __main__.py) -- that's what actually cancels any still-running
# capture stream cleanly (letting the SSH-channel-close chain that
# terminates the remote dumpcap process run), but if it somehow doesn't
# complete in time, this bounds how long `systemctl stop` waits before
# escalating to SIGKILL, rather than systemd's own default of 90s. Kept
# comfortably longer than uvicorn's 5s, not equal to it, so uvicorn's own
# graceful path is what normally handles this, with SIGKILL only as a
# last resort.
TimeoutStopSec=20

StandardOutput=journal
StandardError=journal

# --- Light sandboxing -- relax/remove any of these if they cause problems ---
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
# read-only, not "true" -- "true" makes /home (including the SSH private
# key from step 2 above, if stored under it) completely INVISIBLE to
# this service regardless of file permissions, not just permission-
# checked. Confirmed live: this was a real bug, producing a misleading
# "Permission denied" that looked like a file-ownership problem but
# wasn't. read-only still blocks this service from writing anywhere
# under /home.
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

`scripts/eve-capture.bat` -- distinguishes Community's own links from
this project's by the **first path segment**, not a query field
(confirmed live: Community's device names always start `vunl` or
`pnet`; this project's own container names never do, and EVE-NG has no
"mode" concept of its own -- an earlier version of this script relied
on an invented `mode=pro` query field instead, which turned out to be
an unnecessary point of failure). A `vunl*`/`pnet*` first segment
skips everything below entirely and runs Community's existing,
unmodified flow. Anything else tries curl against the relay first (no
SSH credentials needed on the client at all), falling back to plink
straight into `eveng_host` only if curl or the relay is unreachable
(using the user's own already-configured SSH access via the
sudoers-scoped group from your *original* setup -- no password ever
appears in the URL either way).

**No query string at all -- plain `/`-separated path segments
instead.** Confirmed live, twice: first `&` (a command separator in
`cmd.exe`, always the interpreter for a `.bat` file however it's
invoked) broke parsing outright; after switching the separator to `;`,
the argument still came through truncated right after the first field
name (exact mechanism unconfirmed -- somewhere between the browser's
handling of a non-standard scheme and Windows' own URL dispatch,
outside what this project can directly instrument). Rather than find
one more special character to work around, the URL format now avoids
the whole class of problem: `capture://<relay-host>/<container>/
<token>/<relay-port>/<eveng-host>` -- no `?`, `=`, `&`, or `;`
anywhere. Every one of those fields is guaranteed free of `/` itself
(container names are docker-safe, `token` is base64url -- no `/` in
that alphabet, `eveng_host` is an IP/hostname, `relay_port` is
numeric), so there's no remaining ambiguity about where one field ends
and the next begins. The curl request the `.bat` makes *to the relay*
still uses ordinary `?token=...` query syntax (a single field, so `&`
never comes up) -- that's a separate HTTP request curl constructs
directly, not something passed through `cmd.exe`'s own command-line
parsing the same way the `capture://` URL itself is.

**The curl step also runs a short preflight before committing to the
real (indefinite) stream**, rather than checking `%ERRORLEVEL%` after
piping straight into Wireshark -- that would reflect Wireshark's own
exit code, not curl's, since `cmd.exe` has no equivalent to a shell's
`pipefail`/`PIPESTATUS` for seeing an earlier pipeline stage's exit
code. Without a preflight, a curl failure (bad token, relay
unreachable) piped straight into Wireshark could go unnoticed if
Wireshark itself still exits `0` after being closed normally with
nothing to show.

**The preflight checks the actual response headers, not curl's exit
code.** Confirmed live: curl's exit code alone can't distinguish
"genuinely couldn't connect" from "connected fine, was streaming, got
cut off by our own `--max-time` before the indefinite body ever
finishes" -- both produce exit code `28` ("Operation timeout"),
including the literal message `Connection timed out` for a real
connection failure, which an earlier version of this script wrongly
treated as success (launching Wireshark with nothing to actually
show). `--connect-timeout` bounds just the TCP handshake separately
from `--max-time` (which still bounds the overall request, cutting the
indefinite body off after a few seconds regardless of outcome); `-D`
dumps whatever headers were actually received to a temp file, checked
afterward with `findstr` for a `200` status line -- present only if
the relay genuinely accepted the token and started responding,
regardless of which timeout curl's own exit code happens to reflect.

**Edit the top of the script before deploying it:**

```bat
set WIRESHARK=C:\Program Files\Wireshark\Wireshark.exe
set PLINK=C:\Program Files\PuTTY\plink.exe
set PRO_SSH_USER=eve-pro-user
set PRO_SSH_KEY=%HOMEPATH%\.ssh\eve-pro.ppk
set COMMUNITY_SSH_USER=eve-comm-user
set COMMUNITY_SSH_KEY=%HOMEPATH%\.ssh\eve-comm.ppk
```

Separate username/key pairs for the two plink paths -- don't assume
they're the same account. `PRO_SSH_*` authenticates against this
project's own dedicated relay-fallback account (step 1/3, `sudo docker
exec ... dumpcap`); `COMMUNITY_SSH_*` is whatever account your existing,
separate Community setup already uses.

`plink` has no single flag for "use this key automatically" the way
`ssh` does -- it needs an explicit `-i` pointing at a private key file
in PuTTY's own `.ppk` format (convert an OpenSSH-format key with
`puttygen` first if that's what you generated in step 2). Both plink
calls in the script default to key-based auth; a commented-out
password-based alternative (`-pw`, matching the pattern of the
original Community `.bat`) is included at each one if you'd rather use
that instead -- uncomment one line, leave the other commented.

**Every plink call uses `-batch`, deliberately.** Without it, plink
prompts interactively for anything it can't resolve non-interactively
-- most commonly an unconfirmed host key on a first-time connection
(not suppressed by `-no-antispoof`, a different, unrelated flag) -- and
since the whole command's stdout is piped straight into Wireshark
expecting pure pcap/pcapng bytes, prompt text corrupts that stream
instead of failing cleanly. Confirmed live: Wireshark's own error
(`File type is neither a supported pcap nor pcapng format... magic =
0x6b63696d`) decodes byte-for-byte to the literal ASCII text `mick` --
the tester's own Windows username -- as the first four bytes actually
received, consistent with exactly this kind of prompt/banner text
leaking into the pipe rather than real capture data ever arriving.
`-batch` makes plink fail outright instead of prompting, which is the
correct behavior for a piped, scripted invocation regardless of the
exact root cause. If this recurs even with `-batch`, run the same
plink command directly (drop the final `| Wireshark.exe -k -i -` and
redirect to a file instead) to see its raw output rather than guessing
further.

**The Community-mode command block is copied from a real, working
Community `.bat`, not reconstructed** -- confirmed correct: `-U`/`-s 0`
on `tcpdump`, and a `not port 22` filter specifically when the
interface is exactly `pnet0`. One deliberate difference from that real
original: it authenticated as root (no `sudo` needed for `tcpdump`'s
raw-capture privileges); this deployment authenticates as a non-root
account via the `capture_relay` group instead (step 1/3), so `sudo` IS
required here, unlike the original script it's otherwise copied from.
The PRO-fallback plink command (used when curl or the relay isn't
reachable) uses this project's own `sudo docker exec ... dumpcap` --
confirm both sudo rules still match your actual sudoers setup from
step 3.

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
- **If the `.bat`'s curl preflight reports `Connection timed out` (or
  falls back to plink without an obvious reason), check three things
  in order** before assuming it's a script bug: (1) is
  `mcp-relay.service` actually running (`systemctl status
  mcp-relay.service` on whatever machine it's deployed on)? (2) do
  `CAPTURE_RELAY_ADVERTISE_HOST`/`_PORT` in the main process's `.env`
  actually match `CAPTURE_RELAY_LISTEN_HOST`/`_PORT` in the relay's own,
  separate `.env` -- these are two different settings in two different
  files (see step 4) and a mismatch here means `get_capture` is handing
  out a URL that points somewhere the relay isn't actually listening;
  (3) is there a firewall (on the relay's host, or on the Windows
  client's own network) blocking that port between the two machines?
