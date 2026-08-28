@echo off
setlocal enabledelayedexpansion
REM eve-capture.bat -- registered against the capture:// protocol handler
REM (same Windows registry mechanism Community's own capture:// links
REM already use). Windows passes the full URL as %1.
REM
REM ** UNTESTED end-to-end on a real Windows machine as of writing --
REM ** confirmed live so far: the & query separator (see below) broke
REM ** parsing under cmd.exe; not yet confirmed whether the rest of this
REM ** script (curl/relay path, plink fallback, community path) works.
REM
REM Two link shapes, distinguished by PATH PATTERN, not a query field --
REM EVE-NG has no "mode" concept of its own; that was this project's own
REM invention and turned out to be an unnecessary point of failure
REM (see the note on & below). Community's own device-name shapes,
REM confirmed live, are the actual signal:
REM   Community (unmodified, existing behaviour):
REM     capture://<eveng-host>/vunl<N>_<node>_<if>   (no query string)
REM     capture://<eveng-host>/pnet<N>                (no query string)
REM   This project's relay path (anything else in the path position):
REM     capture://<relay-host>/<container>?token=...;relay_port=...;eveng_host=...
REM
REM Query fields are separated by ";", NOT "&" -- confirmed live that &
REM broke parsing here. cmd.exe (always the interpreter for a .bat file,
REM however it's invoked) treats an unescaped & as a command separator;
REM Community's own links never hit this since they never had a query
REM string at all, but this project's multi-field query string was the
REM first capture:// link ever to include one. ; isn't one of cmd.exe's
REM special characters (& | < > ^ ( ) % !).
REM
REM CONFIGURE THESE FOR YOUR ENVIRONMENT:
set WIRESHARK=C:\Program Files\Wireshark\Wireshark.exe
set PLINK=C:\Path\To\plink.exe
set COMMUNITY_SSH_USER=eve-capture-user
REM Community's plink invocation below is reconstructed from a prose
REM description of an existing working setup, not copied from the real
REM file -- replace this block with your actual existing Community
REM .bat's plink command if it differs at all.

set "FULLURL=%~1"

REM Strip the capture:// scheme.
set "REST=%FULLURL:capture://=%"

REM Split on "?" -- HOSTPATH is always present; QUERY is only present
REM for this project's own relay-path links.
set "HOSTPATH="
set "QUERY="
for /f "tokens=1,* delims=?" %%A in ("%REST%") do (
    set "HOSTPATH=%%A"
    set "QUERY=%%B"
)

REM HOSTPATH is <host>/<path> -- host up to the first slash, everything
REM after is the device name (Community) or container name (this project).
set "URLHOST="
set "URLPATH="
for /f "tokens=1,* delims=/" %%A in ("%HOSTPATH%") do (
    set "URLHOST=%%A"
    set "URLPATH=%%B"
)

REM Detect Community's own device-name shapes by their first 4
REM characters -- "vunl" and "pnet" are both exactly 4 characters, so a
REM plain substring compare (case-insensitive via /I) is enough; no
REM regex needed.
set "PATHPREFIX=%URLPATH:~0,4%"
if /I "%PATHPREFIX%"=="vunl" goto :community_mode
if /I "%PATHPREFIX%"=="pnet" goto :community_mode

REM ---------------------------------------------------------------------
REM This project's relay path: parse token/relay_port/eveng_host out of
REM the query string (split on ";", each piece split on "=").
REM ---------------------------------------------------------------------
set "TOKEN="
set "RELAYPORT="
set "EVENGHOST="

for %%Q in ("%QUERY:;=" "%") do (
    for /f "tokens=1,* delims==" %%K in (%%Q) do (
        if /I "%%K"=="token" set "TOKEN=%%L"
        if /I "%%K"=="relay_port" set "RELAYPORT=%%L"
        if /I "%%K"=="eveng_host" set "EVENGHOST=%%L"
    )
)

if "%TOKEN%"=="" (
    echo Could not parse a token out of this capture:// URL. Aborting.
    echo URL was: %FULLURL%
    pause
    exit /b 1
)

set "CONTAINER=%URLPATH%"
set "RELAYHOST=%URLHOST%"

REM --- Primary path: curl against the relay (no SSH creds needed) ---
where curl.exe >nul 2>nul
if %ERRORLEVEL%==0 (
    curl.exe -s -N "http://%RELAYHOST%:%RELAYPORT%/capture/stream?token=%TOKEN%" | "%WIRESHARK%" -k -i -
    if !ERRORLEVEL!==0 (
        exit /b 0
    )
    echo curl/relay path failed -- falling back to plink.
)

REM --- Fallback path: plink straight into the EVE-NG host, requires the
REM     user's own SSH access (via the sudoers-scoped group) -- no
REM     password is ever passed on the command line; plink prompts
REM     interactively or uses a saved Pageant/session, same as the
REM     original fully-manual flow this replaces. ---
if not exist "%PLINK%" (
    echo Neither curl nor plink is available -- cannot stream this capture.
    pause
    exit /b 1
)
"%PLINK%" -ssh %COMMUNITY_SSH_USER%@%EVENGHOST% -no-antispoof "sudo docker exec %CONTAINER% dumpcap -i eth0 -w -" | "%WIRESHARK%" -k -i -
if %ERRORLEVEL% neq 0 (
    echo plink/dumpcap path also failed.
    pause
)
exit /b %ERRORLEVEL%

:community_mode
REM ---------------------------------------------------------------------
REM Community mode: existing, unmodified behaviour. URLHOST is the
REM EVE-NG host; URLPATH is the vunl-/pnet-style device name. Reconstructed
REM from a prose description of an existing working setup -- replace this
REM block with the real, already-working Community .bat command if this
REM doesn't match it exactly.
REM ---------------------------------------------------------------------
"%PLINK%" -ssh %COMMUNITY_SSH_USER%@%URLHOST% -no-antispoof "sudo tcpdump -i %URLPATH% -w -" | "%WIRESHARK%" -k -i -
if %ERRORLEVEL% neq 0 (
    echo Community capture path failed.
    pause
)
exit /b %ERRORLEVEL%
