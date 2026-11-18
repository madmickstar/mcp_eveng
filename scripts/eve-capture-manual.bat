@echo off
setlocal EnableDelayedExpansion
REM ======================================================================
REM eve-capture-manual.bat   (100% cmd.exe + curl, no PowerShell)
REM
REM Calls list_captures on your mcp-eveng server, shows the running
REM captures as a numbered list, asks which one you want, calls
REM get_capture for it, and prints the capture:// URL to paste into
REM your browser.
REM
REM Needs: Windows 10/11 (curl.exe is built in). Server must be running
REM with --http. JSON is read with plain string handling, so this relies
REM on the server's current reply layout (structuredContent block).
REM LIMIT: cmd.exe caps a line at ~8191 characters, which is roughly 17
REM captures at once. More than that and the list may be cut off.
REM ======================================================================

REM ---------------- CONFIGURE THESE ----------------
REM Use "localhost", not 127.0.0.1, unless MCP_ALLOWED_HOSTS includes the IP.
set "MCP_URL=http://localhost:8000/mcp"
REM Only if MCP_API_KEY is set on the server, otherwise leave empty.
set "API_KEY="
set "CURL=%SystemRoot%\System32\curl.exe"
REM list_captures does an SSH + docker ps round trip, so allow some time.
set "CURL_MAX_TIME=60"
REM -------------------------------------------------

set "T=%TEMP%\eve_cap_%RANDOM%%RANDOM%"
set "REQ=%T%.req"
set "HDR=%T%.hdr"
set "BODY=%T%.body"
set "SID="
set "SIDHDR="
set "AUTH="
set /a REQID=1

if not exist "%CURL%" (
    echo curl.exe not found at %CURL%
    goto :fail
)
if defined API_KEY set AUTH=-H "Authorization: Bearer %API_KEY%"
set CCOPTS=-s -S -k --max-time %CURL_MAX_TIME% -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream"

REM ---------- 1. initialize the MCP session ----------
>"%REQ%" echo {"jsonrpc":"2.0","id":%REQID%,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"eve-capture-manual","version":"1.0"}}}
call :post
if not "%POSTOK%"=="1" goto :fail

REM Stateful servers return a session id; stateless ones return none (fine).
for /f "tokens=2 delims=: " %%S in ('findstr /i /b "mcp-session-id" "%HDR%"') do set "SID=%%S"
if defined SID set SIDHDR=-H "Mcp-Session-Id: !SID!"

REM ---------- 2. initialized notification ----------
>"%REQ%" echo {"jsonrpc":"2.0","method":"notifications/initialized"}
call :post
REM (a 202 here is normal; result ignored)

:refresh
REM ---------- 3. list_captures ----------
set /a REQID+=1
>"%REQ%" echo {"jsonrpc":"2.0","id":!REQID!,"method":"tools/call","params":{"name":"list_captures","arguments":{}}}
call :post
if not "%POSTOK%"=="1" goto :fail

call :load_structured
if errorlevel 1 goto :fail

set "X=!X:*captures:[=!"
set COUNT=0
echo.
echo Running captures:
echo.

:next_item
if not defined X goto :list_done
for /f "tokens=1* delims=}" %%A in ("!X!") do (
    set "ITEM=%%A"
    set "X=%%B"
)
if not defined ITEM goto :list_done
if "!ITEM:~0,1!"=="]" goto :list_done
set "ITEM=!ITEM:*{=!"
set "NAME="
set "CREATED="
set "STATUS="
for /f "tokens=1-5 delims=," %%a in ("!ITEM!") do (
    call :kv "%%a"
    call :kv "%%b"
    call :kv "%%c"
    call :kv "%%d"
    call :kv "%%e"
)
if defined NAME (
    set /a COUNT+=1
    set "CAP_!COUNT!=!NAME!"
    echo   [!COUNT!] !NAME!    started: !CREATED!    status: !STATUS!
)
set "ITEM="
goto :next_item

:list_done
if !COUNT!==0 (
    echo No captures are running on the EVE-NG server.
    echo Start one in EVE-NG ^(right-click an interface ^> Capture^), then refresh.
)

:choose
echo.
set "CHOICE="
set /p "CHOICE=Enter capture number (r = refresh, q = quit): "
if "!CHOICE!"=="" goto :choose
if /i "!CHOICE!"=="q" goto :done
if /i "!CHOICE!"=="r" goto :refresh
if !COUNT!==0 goto :choose

REM digits only?
for /f "delims=0123456789" %%X in ("!CHOICE!") do goto :badchoice
REM strip leading zeros (08 would otherwise be read as octal)
for /f "tokens=* delims=0" %%Z in ("!CHOICE!") do set "CHOICE=%%Z"
if "!CHOICE!"=="" goto :badchoice
set /a N=!CHOICE!
if !N! lss 1 goto :badchoice
if !N! gtr !COUNT! goto :badchoice

set "CHOSEN="
for %%I in (!N!) do set "CHOSEN=!CAP_%%I!"
if "!CHOSEN!"=="" goto :badchoice

REM ---------- 4. get_capture (by container name, so a list shift can't pick the wrong one) ----------
set /a REQID+=1
>"%REQ%" echo {"jsonrpc":"2.0","id":!REQID!,"method":"tools/call","params":{"name":"get_capture","arguments":{"container":"!CHOSEN!"}}}
call :post
if not "%POSTOK%"=="1" goto :fail

call :load_structured
if errorlevel 1 goto :fail

set "Y=!X:*capture_url:=!"
if "!Y!"=="!X!" (
    echo get_capture returned no capture_url. Raw reply:
    echo !X!
    goto :fail
)
set "URL="
for /f "delims=," %%U in ("!Y!") do set "URL=%%U"
set "EXPIRES=?"
set "Y=!Y:*expires_in_seconds:=!"
for /f "delims=}," %%E in ("!Y!") do set "EXPIRES=%%E"

echo.
echo ----------------------------------------------------------------------
echo Capture: !CHOSEN!      (URL expires in !EXPIRES! seconds)
echo.
echo   !URL!
echo.
echo Paste this into your browser's address bar.
echo ----------------------------------------------------------------------
<nul set /p "=!URL!"| clip
echo (Also copied to your clipboard.)
echo.
set "AGAIN="
set /p "AGAIN=Pick another capture? (y/N): "
if /i "!AGAIN!"=="y" goto :refresh
goto :done

:badchoice
echo Please enter a number between 1 and !COUNT!.
goto :choose

:fail
echo.
echo Aborted.
del "%T%.*" >nul 2>nul
endlocal
pause
exit /b 1

:done
del "%T%.*" >nul 2>nul
endlocal
exit /b 0

REM ----------------------------------------------------------------------
REM :post -- sends %REQ% to the MCP server, reply body -> %BODY%, headers -> %HDR%
REM sets POSTOK=1 if curl worked and the HTTP status was 2xx
REM ----------------------------------------------------------------------
:post
set "POSTOK=0"
del "%HDR%" "%BODY%" >nul 2>nul
"%CURL%" %CCOPTS% %AUTH% %SIDHDR% -X POST "%MCP_URL%" -d "@%REQ%" -D "%HDR%" -o "%BODY%"
if errorlevel 1 (
    echo.
    echo Could not reach the MCP server at %MCP_URL%
    echo Is mcp-eveng running with --http, and is MCP_URL above correct?
    exit /b 1
)
findstr /r /c:"^HTTP/[0-9.]* 2" "%HDR%" >nul 2>nul
if errorlevel 1 (
    echo.
    echo The MCP server rejected the request:
    type "%HDR%" | findstr /b /i "HTTP/"
    type "%BODY%"
    echo.
    echo   401 = set API_KEY above to match MCP_API_KEY on the server
    echo   421 = use "localhost" in MCP_URL, or add this host to MCP_ALLOWED_HOSTS
    exit /b 1
)
set "POSTOK=1"
exit /b 0

REM ----------------------------------------------------------------------
REM :load_structured -- reads the tool reply in %BODY% into X: the
REM "structuredContent" part of the JSON with all double quotes removed.
REM Returns errorlevel 1 (after printing why) if the server reported an error.
REM ----------------------------------------------------------------------
:load_structured
set "LINE="
set "X="
for /f "usebackq delims=" %%L in (`findstr /b /c:"data:" "%BODY%"`) do set "LINE=%%L"
if not defined LINE for /f "usebackq delims=" %%L in ("%BODY%") do set "LINE=%%L"
if not defined LINE (
    echo The server sent an empty reply.
    exit /b 1
)
set "X=!LINE:"=!"
findstr /c:"\"isError\":true" "%BODY%" >nul 2>nul && (
    echo Server reported an error:
    echo !X!
    exit /b 1
)
findstr /c:"\"error\":{" "%BODY%" >nul 2>nul && (
    echo MCP error:
    echo !X!
    exit /b 1
)
set "Y=!X:*structuredContent:=!"
if "!Y!"=="!X!" (
    echo Unexpected reply from the server ^(no structuredContent^):
    echo !X!
    exit /b 1
)
set "X=!Y!"
if "!X:~0,14!"=="{status:error," (
    echo Server error: !X!
    exit /b 1
)
exit /b 0

REM ----------------------------------------------------------------------
REM :kv -- picks name / created_at / status out of one "key:value" token
REM ----------------------------------------------------------------------
:kv
set "KV=%~1"
if "!KV:~0,5!"=="name:" set "NAME=!KV:~5!"
if "!KV:~0,11!"=="created_at:" set "CREATED=!KV:~11!"
if "!KV:~0,7!"=="status:" set "STATUS=!KV:~7!"
exit /b 0
