@echo off
setlocal enabledelayedexpansion
REM eve-capture.bat -- registered against the capture:// protocol handler
REM (same Windows registry mechanism Community's own capture:// links
REM already use). Windows passes the full URL as %1.
REM
REM ** UNTESTED end-to-end on a real Windows machine as of writing --
REM ** confirmed live so far: (1) the & query separator broke parsing
REM ** under cmd.exe, (2) even after switching to ;, the argument still
REM ** came through truncated. Both fixed by dropping the query string
REM ** entirely for plain /-separated path segments (see below). (3) A
REM ** binary encoding bug in the relay itself (fixed separately, see
REM ** capture_relay/ssh_client.py). A real capture has now reached
REM ** Wireshark successfully at least once -- which of curl/relay vs.
REM ** the plink fallback actually delivered it is still being confirmed
REM ** (see docs/capture-relay.md); plink was also missing its -i key
REM ** flag entirely until just now, so if it WAS the fallback that
REM ** delivered it, that specific run must have used a different auth
REM ** method (e.g. Pageant) than what this script explicitly passed.
REM ** Community mode's actual command block below is copied from a
REM ** real, working Community .bat (not reconstructed) but hasn't been
REM ** exercised through THIS wrapper script live yet.
REM
REM Two link shapes, distinguished by the FIRST path segment, not a
REM query field -- EVE-NG has no "mode" concept of its own; that was
REM this project's own invention and turned out to be an unnecessary
REM point of failure. Community's own device-name shapes, confirmed
REM live, are the actual signal:
REM   Community (unmodified, existing behaviour):
REM     capture://<eveng-host>/vunl<N>_<node>_<if>   (one path segment)
REM     capture://<eveng-host>/pnet<N>                (one path segment)
REM   This project's relay path (anything else in the first segment):
REM     capture://<relay-host>/<container>/<token>/<relay-port>/<eveng-host>
REM
REM CONFIGURE THESE FOR YOUR ENVIRONMENT:
set WIRESHARK=C:\Program Files\Wireshark\Wireshark.exe
set PLINK=C:\Path\To\plink.exe
set COMMUNITY_SSH_USER=eve-capture-user
REM plink has no single flag that means "use this OpenSSH-format key
REM automatically" the way ssh does -- it needs an explicit -i pointing
REM at a private key file (PuTTY's own .ppk format; convert an
REM OpenSSH-format key with puttygen first if that's what you generated
REM in docs/capture-relay.md step 2). Key-based auth is the default
REM below; a commented-out password-based alternative (matching the
REM original Community .bat's own approach) is included at each plink
REM call if you'd rather use that instead -- uncomment ONE line, leave
REM the other commented, don't run both.
set COMMUNITY_SSH_KEY=C:\Path\To\private-key.ppk
REM set PASSWORD=your-password-here
REM
REM Community's plink invocation below is copied from a real, working
REM Community .bat (tcpdump, not docker -- Community's own SSH account
REM apparently doesn't need sudo for this, unlike this project's own
REM dedicated relay-fallback account above).

set "FULLURL=%~1"

REM Strip the capture:// scheme.
set "REST=%FULLURL:capture://=%"

REM Split into host and everything-after-the-host on the first "/".
set "URLHOST="
set "URLPATH="
for /f "tokens=1,* delims=/" %%A in ("%REST%") do (
    set "URLHOST=%%A"
    set "URLPATH=%%B"
)

REM URLPATH is now either:
REM   - one segment (Community: the device name itself), or
REM   - four segments, /-separated (this project: container/token/
REM     relay_port/eveng_host)
REM Detect Community's own device-name shapes by the FIRST segment's
REM first 4 characters -- "vunl" and "pnet" are both exactly 4
REM characters, so a plain substring compare (case-insensitive via /I)
REM is enough; no regex needed. This works whether URLPATH has 1 segment
REM or 4, since it only ever looks at the very first one.
set "PATHPREFIX=%URLPATH:~0,4%"
if /I "%PATHPREFIX%"=="vunl" goto :community_mode
if /I "%PATHPREFIX%"=="pnet" goto :community_mode

REM ---------------------------------------------------------------------
REM This project's relay path: split URLPATH on "/" into its 4 segments.
REM ---------------------------------------------------------------------
set "CONTAINER="
set "TOKEN="
set "RELAYPORT="
set "EVENGHOST="
for /f "tokens=1,2,3,4 delims=/" %%A in ("%URLPATH%") do (
    set "CONTAINER=%%A"
    set "TOKEN=%%B"
    set "RELAYPORT=%%C"
    set "EVENGHOST=%%D"
)

if "%TOKEN%"=="" (
    echo Could not parse a token out of this capture:// URL. Aborting.
    echo URL was: %FULLURL%
    pause
    exit /b 1
)

set "RELAYHOST=%URLHOST%"

REM --- Primary path: curl against the relay (no SSH creds needed) ---
REM
REM Deliberately NOT using goto/labels inside a parenthesized if-block
REM here (a well-known cmd.exe fragility trap -- jumping into or out of
REM a block that's already been tokenized as one unit can behave
REM unpredictably) -- flag variables and straight-line if-blocks instead.
set "HAVECURL=0"
where curl.exe >nul 2>nul
if %ERRORLEVEL%==0 set "HAVECURL=1"

set "CURLOK=0"
if "%HAVECURL%"=="1" (
    REM Preflight: verify the relay actually returns a 200 for this
    REM token BEFORE committing to the real (indefinite) stream. This is
    REM deliberately a separate request -- %ERRORLEVEL% after a
    REM `curl | wireshark` pipe reflects WIRESHARK's exit code, not
    REM curl's (cmd.exe has no equivalent to a shell's pipefail/
    REM PIPESTATUS to see an earlier pipeline stage's exit code), so a
    REM curl failure piped straight into Wireshark could go unnoticed if
    REM Wireshark itself still exits 0 after being closed normally with
    REM nothing to show.
    REM
    REM Confirmed live: curl's own exit code alone can't tell "genuinely
    REM couldn't connect" apart from "connected fine, was streaming,
    REM got cut off by our own --max-time before the indefinite body
    REM ever finishes" -- BOTH produce exit code 28 ("Operation
    REM timeout"), including the literal message "Connection timed out"
    REM for a real connection failure, which an earlier version of this
    REM script wrongly treated as success. Checking the actual response
    REM headers instead of inferring from the exit code sidesteps this
    REM entirely: --connect-timeout bounds just the TCP handshake
    REM (should be near-instant on a LAN -- a real failure to connect
    REM shows up here, fast, with no headers ever captured);
    REM --max-time bounds the OVERALL request, so it still cuts the
    REM (indefinite, on success) body off after a few seconds regardless
    REM of outcome; -D dumps whatever headers WERE received (if any) to
    REM a temp file, checked below with findstr for an actual "200"
    REM status line -- present only if the relay genuinely accepted the
    REM token and started responding, regardless of which timeout
    REM curl's own exit code reflects.
    REM
    REM Confirmed live that 3s/5s was too tight: the relay's full
    REM round-trip (SSH connect + sudo + docker exec + dumpcap startup)
    REM took long enough that a genuinely-working relay still missed
    REM this window -- observed a preflight timeout at ~3004ms followed
    REM immediately by Wireshark receiving a real, successful capture
    REM moments later (via the real, unbounded stream call below, which
    REM has no such tight deadline). Widened accordingly; adjust further
    REM if your own environment's round-trip is consistently slower or
    REM faster than this.
    set "HDRFILE=%TEMP%\eve_capture_preflight_%RANDOM%.tmp"
    curl.exe -s -S --connect-timeout 5 --max-time 10 -D "!HDRFILE!" -o nul "http://%RELAYHOST%:%RELAYPORT%/capture/stream?token=%TOKEN%"
    if exist "!HDRFILE!" (
        findstr /C:" 200 " "!HDRFILE!" >nul 2>nul
        if !ERRORLEVEL!==0 set "CURLOK=1"
        del "!HDRFILE!" >nul 2>nul
    )
    if "!CURLOK!"=="0" echo curl preflight did not get a 200 response from the relay -- falling back to plink.
)

if "%CURLOK%"=="1" (
    curl.exe -s -N "http://%RELAYHOST%:%RELAYPORT%/capture/stream?token=%TOKEN%" | "%WIRESHARK%" -k -i -
    exit /b 0
)

REM --- Fallback path: plink straight into the EVE-NG host, requires the
REM     user's own SSH access (via the sudoers-scoped group) -- no
REM     password is ever passed on the command line; plink prompts
REM     interactively or uses a saved Pageant/session, same as the
REM     original fully-manual flow this replaces. Reached whenever curl
REM     wasn't available or its preflight didn't succeed. ---
if not exist "%PLINK%" (
    echo Neither curl nor plink is available -- cannot stream this capture.
    pause
    exit /b 1
)
"%PLINK%" -ssh -i "%COMMUNITY_SSH_KEY%" %COMMUNITY_SSH_USER%@%EVENGHOST% -no-antispoof "sudo docker exec %CONTAINER% dumpcap -i eth0 -w -" | "%WIRESHARK%" -k -i -
REM Password-based alternative -- uncomment this line and comment out
REM the one above if you'd rather authenticate this way instead:
REM "%PLINK%" -ssh -pw %PASSWORD% %COMMUNITY_SSH_USER%@%EVENGHOST% -no-antispoof "sudo docker exec %CONTAINER% dumpcap -i eth0 -w -" | "%WIRESHARK%" -k -i -
if %ERRORLEVEL% neq 0 (
    echo plink/dumpcap path also failed.
    pause
)
exit /b %ERRORLEVEL%

:community_mode
REM ---------------------------------------------------------------------
REM Community mode: existing, unmodified behaviour -- this block is
REM copied from a real, working Community .bat, not reconstructed.
REM URLHOST is the EVE-NG host; URLPATH is the vunl-/pnet-style device
REM name. Confirmed detail from that real script: no sudo (Community's
REM SSH account apparently doesn't need it for this, unlike this
REM project's own dedicated relay-fallback account above); `-U`
REM (unbuffered output -- important for a live stream, not a completed
REM capture) and `-s 0` (snaplen 0, capture the full packet, no
REM truncation) on tcpdump; and a `not port 22` filter specifically
REM when the interface is exactly "pnet0" -- presumably to exclude the
REM SSH session's own traffic from a capture on an interface that
REM happens to carry it too, avoiding a feedback loop.
REM ---------------------------------------------------------------------
set "FILTER="
if "%URLPATH%"=="pnet0" set "FILTER= not port 22"

"%PLINK%" -ssh -i "%COMMUNITY_SSH_KEY%" %COMMUNITY_SSH_USER%@%URLHOST% -no-antispoof "tcpdump -U -i %URLPATH% -s 0 -w -%FILTER%" | "%WIRESHARK%" -k -i -
REM Password-based alternative -- uncomment this line and comment out
REM the one above if you'd rather authenticate this way instead:
REM "%PLINK%" -ssh -pw %PASSWORD% %COMMUNITY_SSH_USER%@%URLHOST% -no-antispoof "tcpdump -U -i %URLPATH% -s 0 -w -%FILTER%" | "%WIRESHARK%" -k -i -
if %ERRORLEVEL% neq 0 (
    echo Community capture path failed.
    pause
)
exit /b %ERRORLEVEL%
