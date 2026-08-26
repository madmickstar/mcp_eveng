@echo off
setlocal enabledelayedexpansion
REM eve-capture.bat -- registered against the capture:// protocol handler
REM (same Windows registry mechanism Community's own capture:// links
REM already use). Windows passes the full URL as %1.
REM
REM ** UNTESTED on a real Windows machine as of writing -- this batch
REM ** file was written and reasoned through carefully, but this
REM ** project has no way to execute cmd.exe/batch syntax to verify it.
REM ** Test this directly before relying on it, the same caution this
REM ** project applies to the untested SSH layer in ssh_client.py.
REM
REM Two link shapes:
REM   Community (unmodified, existing behaviour):
REM     capture://<eveng-host>/<device-name>                    (no query string)
REM   PRO (new, this project):
REM     capture://<relay-host>/<container>?mode=pro&token=...
REM         &relay_port=...&eveng_host=...
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
REM for a PRO-mode link.
set "HOSTPATH="
set "QUERY="
for /f "tokens=1,* delims=?" %%A in ("%REST%") do (
    set "HOSTPATH=%%A"
    set "QUERY=%%B"
)

REM HOSTPATH is <host>/<path> -- host up to the first slash, everything
REM after is the device name (Community) or container name (PRO).
set "URLHOST="
set "URLPATH="
for /f "tokens=1,* delims=/" %%A in ("%HOSTPATH%") do (
    set "URLHOST=%%A"
    set "URLPATH=%%B"
)

if "%QUERY%"=="" goto :community_mode

REM ---------------------------------------------------------------------
REM PRO mode: parse mode/token/relay_port/eveng_host out of the query
REM string (split on "&", each piece split on "=").
REM ---------------------------------------------------------------------
set "MODE="
set "TOKEN="
set "RELAYPORT="
set "EVENGHOST="

for %%Q in ("%QUERY:&=" "%") do (
    for /f "tokens=1,* delims==" %%K in (%%Q) do (
        if /I "%%K"=="mode" set "MODE=%%L"
        if /I "%%K"=="token" set "TOKEN=%%L"
        if /I "%%K"=="relay_port" set "RELAYPORT=%%L"
        if /I "%%K"=="eveng_host" set "EVENGHOST=%%L"
    )
)

if /I not "%MODE%"=="pro" (
    echo Unrecognized capture:// mode "%MODE%" -- expected "pro". Aborting.
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
    exit /b 1
)
"%PLINK%" -ssh %COMMUNITY_SSH_USER%@%EVENGHOST% -no-antispoof "sudo docker exec %CONTAINER% dumpcap -i eth0 -w -" | "%WIRESHARK%" -k -i -
exit /b %ERRORLEVEL%

:community_mode
REM ---------------------------------------------------------------------
REM Community mode: existing, unmodified behaviour. URLHOST is the
REM EVE-NG host; URLPATH is the vunl-style device name (e.g.
REM "vunl1_6_2"). Reconstructed from a prose description of an existing
REM working setup -- replace this block with the real, already-working
REM Community .bat command if this doesn't match it exactly.
REM ---------------------------------------------------------------------
"%PLINK%" -ssh %COMMUNITY_SSH_USER%@%URLHOST% -no-antispoof "sudo tcpdump -i %URLPATH% -w -" | "%WIRESHARK%" -k -i -
exit /b %ERRORLEVEL%
