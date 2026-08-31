@echo off
setlocal enabledelayedexpansion
REM eve-capture.bat -- registered against the capture:// protocol handler
REM (same Windows registry mechanism Community's own capture:// links
REM already use). Windows passes the full URL as %1.
REM
REM ** Confirmed working end-to-end, live: stopping the relay mid-stream
REM ** (cleanly breaks the stream), curl-based streaming on PRO,
REM ** plink-based streaming on PRO (the fallback path), and plink-based
REM ** streaming on Community -- see CHANGELOG.md's [0.3.17] entry for
REM ** the full history of what was found and fixed getting here.
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
set PLINK=C:\Program Files\PuTTY\plink.exe
REM "http" (default) or "https" -- must match whatever CAPTURE_RELAY_TLS_*
REM is set to in the relay's own .env (see docs/capture-relay.md step 5).
REM Every curl call below always passes -k/--insecure regardless of this
REM setting -- a no-op on plain http, but needed for https against a
REM self-signed cert, which is the realistic case for a relay on a
REM private/lab network. Use a CA-signed cert instead if you want that
REM checked for real.
set RELAY_SCHEME=http
REM Preflight timeout, in seconds -- see the longer comment further down
REM at the actual curl call for what each one bounds and why. Widen both
REM if your own relay's real round-trip is slower than this.
set RELAY_CONNECT_TIMEOUT=5
set RELAY_MAX_TIME=5
REM Separate username/key pairs for the two plink paths -- don't assume
REM they're the same account, since they authenticate against
REM genuinely different things: PRO_SSH_* is this project's own
REM dedicated relay-fallback account (sudo docker exec ... dumpcap --
REM see docs/capture-relay.md step 1/4); COMMUNITY_SSH_* is whatever
REM account your existing, separate Community setup already uses.
set PRO_SSH_USER=eve-pro-user
set PRO_SSH_KEY=%HOMEPATH%\.ssh\eve-pro.ppk
set COMMUNITY_SSH_USER=eve-comm-user
set COMMUNITY_SSH_KEY=%HOMEPATH%\.ssh\eve-comm.ppk
REM plink has no single flag that means "use this OpenSSH-format key
REM automatically" the way ssh does -- it needs an explicit -i pointing
REM at a private key file (PuTTY's own .ppk format; convert an
REM OpenSSH-format key with puttygen first if that's what you generated
REM in docs/capture-relay.md step 2). Key-based auth is the default
REM below; a commented-out password-based alternative (matching the
REM original Community .bat's own approach) is included at each plink
REM call if you'd rather use that instead -- uncomment ONE line, leave
REM the other commented, don't run both.
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
    REM has no such tight deadline). Widened once already; RELAY_CONNECT_TIMEOUT/
    REM RELAY_MAX_TIME above are set back to 5s/5s by request -- widen
    REM them again if your own environment's round-trip is consistently
    REM slower than that.
    set "HDRFILE=%TEMP%\eve_capture_preflight_%RANDOM%.tmp"
    curl.exe -s -S -k --connect-timeout %RELAY_CONNECT_TIMEOUT% --max-time %RELAY_MAX_TIME% -D "!HDRFILE!" -o nul "%RELAY_SCHEME%://%RELAYHOST%:%RELAYPORT%/capture/stream?token=%TOKEN%"
    if exist "!HDRFILE!" (
        findstr /C:" 200 " "!HDRFILE!" >nul 2>nul
        if !ERRORLEVEL!==0 set "CURLOK=1"
        del "!HDRFILE!" >nul 2>nul
    )
    if "!CURLOK!"=="0" echo curl preflight did not get a 200 response from the relay -- falling back to plink.
)

if "%CURLOK%"=="1" (
    curl.exe -s -N -k "%RELAY_SCHEME%://%RELAYHOST%:%RELAYPORT%/capture/stream?token=%TOKEN%" | "%WIRESHARK%" -k -i -
    exit /b 0
)

REM --- Fallback path: plink straight into the EVE-NG host, requires the
REM     user's own SSH access (via the sudoers-scoped group) -- no
REM     password is ever passed on the command line by default (key-
REM     based auth is the default below). Reached whenever curl wasn't
REM     available or its preflight didn't succeed. ---
REM
REM -batch is deliberate, not optional: without it, plink prompts
REM interactively for anything it can't resolve non-interactively (an
REM unconfirmed host key on a first-time connection, most commonly --
REM not suppressed by -no-antispoof, which is a different, unrelated
REM flag) -- and since this whole command's stdout is piped straight
REM into Wireshark expecting pure pcap/pcapng bytes, any such prompt
REM text corrupts that stream instead of just failing cleanly. Confirmed
REM live: Wireshark's own error ("File type is neither a supported pcap
REM nor pcapng format... magic = 0x6b63696d") decodes byte-for-byte to
REM the literal ASCII text "mick" -- the local Windows username -- as
REM the first four bytes actually received, consistent with exactly
REM this kind of prompt/banner text leaking into the pipe rather than
REM real capture data ever arriving at all. -batch makes plink fail
REM outright instead of prompting when it can't proceed non-
REM interactively, which is the correct behavior for a piped, scripted
REM invocation like this one regardless of the exact root cause. If
REM this error recurs even with -batch, run the same plink command
REM directly (drop the `| "%WIRESHARK%" -k -i -` and redirect to a file
REM instead) to see its raw output directly rather than guessing further.
if not exist "%PLINK%" (
    echo Neither curl nor plink is available -- cannot stream this capture.
    pause
    exit /b 1
)
"%PLINK%" -ssh -batch -i "%PRO_SSH_KEY%" %PRO_SSH_USER%@%EVENGHOST% -no-antispoof "sudo docker exec %CONTAINER% dumpcap -i eth0 -w -" | "%WIRESHARK%" -k -i -
REM Password-based alternative -- uncomment this line and comment out
REM the one above if you'd rather authenticate this way instead:
REM "%PLINK%" -ssh -batch -pw %PASSWORD% %PRO_SSH_USER%@%EVENGHOST% -no-antispoof "sudo docker exec %CONTAINER% dumpcap -i eth0 -w -" | "%WIRESHARK%" -k -i -
if %ERRORLEVEL% neq 0 (
    echo plink/dumpcap path also failed.
    pause
)
exit /b %ERRORLEVEL%

:community_mode
REM ---------------------------------------------------------------------
REM Community mode: tcpdump/flags/filter logic copied from a real,
REM working Community .bat, not reconstructed. URLHOST is the EVE-NG
REM host; URLPATH is the vunl-/pnet-style device name. `-U` (unbuffered
REM output -- important for a live stream, not a completed capture) and
REM `-s 0` (snaplen 0, capture the full packet, no truncation) on
REM tcpdump; a `not port 22` filter specifically when the interface is
REM exactly "pnet0" -- presumably to exclude the SSH session's own
REM traffic from a capture on an interface that happens to carry it
REM too, avoiding a feedback loop.
REM
REM One deliberate difference from that real original: it authenticated
REM as root (so no sudo needed for tcpdump's raw-capture privileges);
REM this deployment authenticates as a non-root account via the
REM capture_relay group instead (step 1/4), so sudo IS required here.
REM Matches the sudoers rule from step 4:
REM     %capture_relay ALL=(root) NOPASSWD: /usr/bin/tcpdump -U -i * -s 0 -w -*
REM (note the trailing * after "-w -" -- needed because of %FILTER%
REM below: sudoers matches a command exactly unless its own spec ends in
REM a wildcard, and the pnet0 case appends " not port 22" after "-w -".)
REM ---------------------------------------------------------------------
set "FILTER="
if "%URLPATH%"=="pnet0" set "FILTER= not port 22"

"%PLINK%" -ssh -batch -i "%COMMUNITY_SSH_KEY%" %COMMUNITY_SSH_USER%@%URLHOST% -no-antispoof "sudo tcpdump -U -i %URLPATH% -s 0 -w -%FILTER%" | "%WIRESHARK%" -k -i -
REM Password-based alternative -- uncomment this line and comment out
REM the one above if you'd rather authenticate this way instead:
REM "%PLINK%" -ssh -batch -pw %PASSWORD% %COMMUNITY_SSH_USER%@%URLHOST% -no-antispoof "sudo tcpdump -U -i %URLPATH% -s 0 -w -%FILTER%" | "%WIRESHARK%" -k -i -
if %ERRORLEVEL% neq 0 (
    echo Community capture path failed.
    pause
)
exit /b %ERRORLEVEL%
