@echo off
setlocal enabledelayedexpansion
REM eve-capture.bat -- registered against the capture:// protocol handler
REM (same mechanism Community's own capture:// links use). Windows
REM passes the full URL as %1.
REM
REM Two link shapes, distinguished by the first path segment:
REM   Community: capture://<eveng-host>/vunl<N>_<node>_<if>   (1 segment)
REM              capture://<eveng-host>/pnet<N>                (1 segment)
REM   This project's relay path (anything else in the first segment):
REM     capture://<relay-host>/<container>/<token>/<relay-port>/<eveng-host>

REM CONFIGURE THESE FOR YOUR ENVIRONMENT:
set WIRESHARK=C:\Program Files\Wireshark\Wireshark.exe
set PLINK=C:\Program Files\PuTTY\plink.exe

REM Path to curl.exe. Default: Windows' own bundled copy. If HTTPS
REM connections fail with a "schannel" error, first check your relay's
REM TLS certificate -- Windows' Schannel has a known incompatibility
REM with ECDSA P-521 (secp521r1) certs specifically; use RSA or ECDSA
REM P-256/P-384 instead. If that's not an option, point this at the
REM official curl.se Windows build instead (https://curl.se/windows/).
set CURL=C:\Windows\System32\curl.exe

REM Scheme the relay is reachable on: "http" or "https". Must match
REM CAPTURE_RELAY_TLS_* in the relay's own .env. Every curl call below
REM always passes -k/--insecure (no-op on http; needed for https
REM against a self-signed cert -- use a CA-signed cert if you want
REM certificate verification enforced).
set RELAY_SCHEME=http

REM Preflight timeout, in seconds, for confirming the relay responds
REM before starting the real capture stream. Widen both if your relay's
REM SSH+sudo+docker round-trip is slower than this.
set RELAY_CONNECT_TIMEOUT=5
set RELAY_MAX_TIME=5

REM Separate username/key pairs for the two plink paths. PRO_SSH_* is
REM this project's own relay-fallback account (docs/capture-relay.md
REM step 1/4); COMMUNITY_SSH_* is your existing Community setup's
REM account -- these are not necessarily the same account.
set PRO_SSH_USER=eve-pro-user
set PRO_SSH_KEY=%HOMEPATH%\.ssh\eve-pro.ppk
set COMMUNITY_SSH_USER=eve-comm-user
set COMMUNITY_SSH_KEY=%HOMEPATH%\.ssh\eve-comm.ppk

REM plink needs an explicit -i pointing at a private key in PuTTY's own
REM .ppk format (convert an OpenSSH-format key with puttygen if needed).
REM Key-based auth is the default below. To use password auth instead,
REM set PASSWORD here and swap which plink line is commented out at
REM each of the two call sites further down -- uncomment ONE, not both.
REM set PASSWORD=your-password-here

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

REM Detect Community's own device-name shapes ("vunl.../pnet...") by
REM the first segment's first 4 characters. Anything else is treated
REM as this project's relay path.
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

title %CONTAINER%

set "RELAYHOST=%URLHOST%"

REM --- Primary path: curl against the relay (no SSH creds needed) ---
set "HAVECURL=0"
if exist "%CURL%" set "HAVECURL=1"

set "CURLOK=0"
if "%HAVECURL%"=="1" (
    REM Preflight: confirm the relay actually returns a 200 for this
    REM token before committing to the real (indefinite) stream. Checks
    REM the response headers for a "200" status line, not curl's own
    REM exit code -- exit code 28 ("Operation timeout") means either
    REM "couldn't connect" or "connected fine, cut off by --max-time",
    REM and the response headers are the only way to tell those apart.
    set "HDRFILE=%TEMP%\eve_capture_preflight_%RANDOM%.tmp"
    "%CURL%" -s -S -k --connect-timeout %RELAY_CONNECT_TIMEOUT% --max-time %RELAY_MAX_TIME% -D "!HDRFILE!" -o nul "%RELAY_SCHEME%://%RELAYHOST%:%RELAYPORT%/capture/stream?token=%TOKEN%"
    if exist "!HDRFILE!" (
        findstr /C:" 200 " "!HDRFILE!" >nul 2>nul
        if !ERRORLEVEL!==0 set "CURLOK=1"
        del "!HDRFILE!" >nul 2>nul
    )
    if "!CURLOK!"=="0" echo curl preflight did not get a 200 response from the relay -- falling back to plink.
)

if "%CURLOK%"=="1" (
    "%CURL%" -s -N -k "%RELAY_SCHEME%://%RELAYHOST%:%RELAYPORT%/capture/stream?token=%TOKEN%" | "%WIRESHARK%" -k -i -
    exit /b 0
)

REM --- Fallback path: plink straight into the EVE-NG host, via the
REM     sudoers-scoped group. Reached whenever curl wasn't available or
REM     its preflight didn't succeed. -batch prevents plink from
REM     prompting interactively for anything it can't resolve
REM     non-interactively (e.g. an unconfirmed host key) -- since this
REM     command's stdout is piped straight into Wireshark expecting raw
REM     pcap/pcapng bytes, any such prompt text would corrupt the
REM     stream instead of failing cleanly. ---
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
REM Community mode. URLHOST is the EVE-NG host; URLPATH is the
REM vunl-/pnet-style device name. `-U` (unbuffered output, needed for a
REM live stream) and `-s 0` (capture full packets, no truncation) on
REM tcpdump; a `not port 22` filter when the interface is exactly
REM "pnet0", to exclude the SSH session's own traffic from the capture.
REM Matches the sudoers rule:
REM     %capture_relay ALL=(root) NOPASSWD: /usr/bin/tcpdump -U -i * -s 0 -w -*
REM (the trailing * after "-w -" is required for the pnet0 filter to
REM match -- sudoers matches a command exactly unless its own spec ends
REM in a wildcard).
REM ---------------------------------------------------------------------
set "FILTER="
if "%URLPATH%"=="pnet0" set "FILTER= not port 22"

title %URLPATH%

"%PLINK%" -ssh -batch -i "%COMMUNITY_SSH_KEY%" %COMMUNITY_SSH_USER%@%URLHOST% -no-antispoof "sudo tcpdump -U -i %URLPATH% -s 0 -w -%FILTER%" | "%WIRESHARK%" -k -i -
REM Password-based alternative -- uncomment this line and comment out
REM the one above if you'd rather authenticate this way instead:
REM "%PLINK%" -ssh -batch -pw %PASSWORD% %COMMUNITY_SSH_USER%@%URLHOST% -no-antispoof "sudo tcpdump -U -i %URLPATH% -s 0 -w -%FILTER%" | "%WIRESHARK%" -k -i -
if %ERRORLEVEL% neq 0 (
    echo Community capture path failed.
    pause
)
exit /b %ERRORLEVEL%
