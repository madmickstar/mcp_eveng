<#
.SYNOPSIS
    List the running captures on an mcp-eveng server, pick one by number,
    and print the capture:// URL to paste into your browser.

.DESCRIPTION
    Talks to the mcp-eveng server's Streamable HTTP endpoint directly
    (no MCP host needed): initialize -> list_captures -> get_capture.
    The server must be running with --http. Works in Windows PowerShell 5.1
    and PowerShell 7+.

    Companion to eve-capture-manual.bat (same behaviour, cmd.exe + curl only).

.PARAMETER McpUrl
    MCP endpoint. Use "localhost", not 127.0.0.1, unless the server's
    MCP_ALLOWED_HOSTS includes the IP.

.PARAMETER ApiKey
    Only needed if MCP_API_KEY is set on the server. Defaults to the
    MCP_API_KEY environment variable if present.

.PARAMETER SkipCertCheck
    Accept a self-signed HTTPS certificate on the MCP server.

.EXAMPLE
    .\eve-capture-manual.ps1
    .\eve-capture-manual.ps1 -McpUrl https://mcp.lab.local:8000/mcp -SkipCertCheck
#>
[CmdletBinding()]
param(
    [string]$McpUrl  = 'http://localhost:8000/mcp',
    [string]$ApiKey  = $env:MCP_API_KEY,
    [int]$TimeoutSec = 60,
    [switch]$SkipCertCheck
)

$ErrorActionPreference = 'Stop'
# Older Windows PowerShell defaults to TLS 1.0/1.1; make sure 1.2 is allowed.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$script:SessionId = $null
$script:ReqId     = 0

function Send-Mcp {
    <# POSTs one JSON-RPC message. Returns the parsed JSON-RPC reply, or $null
       for notifications (HTTP 202, no body). #>
    param([hashtable]$Message, [switch]$WantHeaders)

    $headers = @{ 'Accept' = 'application/json, text/event-stream' }
    if ($ApiKey)            { $headers['Authorization'] = "Bearer $ApiKey" }
    if ($script:SessionId)  { $headers['Mcp-Session-Id'] = $script:SessionId }

    $iwr = @{
        Uri             = $McpUrl
        Method          = 'Post'
        Headers         = $headers
        ContentType     = 'application/json'
        Body            = ($Message | ConvertTo-Json -Depth 10 -Compress)
        TimeoutSec      = $TimeoutSec
        UseBasicParsing = $true
    }
    if ($SkipCertCheck -and $PSVersionTable.PSVersion.Major -ge 6) { $iwr['SkipCertificateCheck'] = $true }

    try {
        $resp = Invoke-WebRequest @iwr
    }
    catch {
        $status = $null
        if ($_.Exception.Response) { try { $status = [int]$_.Exception.Response.StatusCode } catch {} }
        if ($status) {
            Write-Host ''
            Write-Host "The MCP server rejected the request (HTTP $status)." -ForegroundColor Red
            switch ($status) {
                401 { Write-Host '  Set -ApiKey (or MCP_API_KEY) to match MCP_API_KEY on the server.' }
                421 { Write-Host '  Use "localhost" in -McpUrl, or add this host to MCP_ALLOWED_HOSTS.' }
            }
        } else {
            Write-Host ''
            Write-Host "Could not reach the MCP server at $McpUrl" -ForegroundColor Red
            Write-Host '  Is mcp-eveng running with --http, and is -McpUrl correct?'
            Write-Host "  ($($_.Exception.Message))"
        }
        throw 'ABORT'
    }

    if ($WantHeaders) {
        $sid = $resp.Headers['Mcp-Session-Id']
        if ($sid) { $script:SessionId = @($sid)[0] }   # PS7 returns string[], PS5 a string
    }

    $text = $resp.Content
    if ($text -is [byte[]]) { $text = [Text.Encoding]::UTF8.GetString($text) }
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }

    # Replies are either plain JSON or SSE ("event: message" / "data: {json}").
    $m = [regex]::Matches($text, '(?m)^data:\s*(.+?)\s*$')
    if ($m.Count -gt 0) { $text = $m[$m.Count - 1].Groups[1].Value }
    return ($text | ConvertFrom-Json)
}

function Invoke-Tool {
    <# Calls an MCP tool and returns the tool's result dict (structuredContent),
       or throws 'ABORT' after printing why. #>
    param([string]$Name, [hashtable]$Arguments = @{})

    $script:ReqId++
    $reply = Send-Mcp @{
        jsonrpc = '2.0'; id = $script:ReqId; method = 'tools/call'
        params  = @{ name = $Name; arguments = $Arguments }
    }

    if ($reply.error) {
        Write-Host "MCP error: $($reply.error.message)" -ForegroundColor Red
        throw 'ABORT'
    }
    $r = $reply.result
    if ($r.isError) {
        Write-Host "Server error: $($r.content[0].text)" -ForegroundColor Red
        throw 'ABORT'
    }
    if ($r.structuredContent) { $d = $r.structuredContent }
    else                      { $d = $r.content[0].text | ConvertFrom-Json }

    if ($d.status -eq 'error') {
        Write-Host "Server error: $($d.message)" -ForegroundColor Red
        throw 'ABORT'
    }
    return $d
}

try {
    # ---- 1. initialize the MCP session -------------------------------------
    $script:ReqId++
    $null = Send-Mcp -WantHeaders @{
        jsonrpc = '2.0'; id = $script:ReqId; method = 'initialize'
        params  = @{
            protocolVersion = '2025-06-18'
            capabilities    = @{}
            clientInfo      = @{ name = 'eve-capture-manual'; version = '1.0' }
        }
    }
    # ---- 2. initialized notification (a 202 with no body is normal) --------
    $null = Send-Mcp @{ jsonrpc = '2.0'; method = 'notifications/initialized' }

    while ($true) {
        # ---- 3. list_captures ----------------------------------------------
        $d = Invoke-Tool 'list_captures'
        $caps = @($d.data.captures)

        Write-Host ''
        if ($caps.Count -eq 0) {
            Write-Host 'No captures are running on the EVE-NG server.'
            Write-Host 'Start one in EVE-NG (right-click an interface > Capture), then refresh.'
        } else {
            Write-Host 'Running captures:'
            Write-Host ''
            for ($i = 0; $i -lt $caps.Count; $i++) {
                '  [{0}] {1}    started: {2}    status: {3}' -f ($i + 1), $caps[$i].name, $caps[$i].created_at, $caps[$i].status | Write-Host
            }
        }

        # ---- choose ---------------------------------------------------------
        $chosen = $null
        while (-not $chosen) {
            Write-Host ''
            $in = (Read-Host 'Enter capture number (r = refresh, q = quit)').Trim()
            if ($in -eq '')      { continue }
            if ($in -ieq 'q')    { return }
            if ($in -ieq 'r')    { break }
            if ($caps.Count -eq 0) { continue }
            $n = 0
            if ([int]::TryParse($in, [ref]$n) -and $n -ge 1 -and $n -le $caps.Count) {
                $chosen = $caps[$n - 1].name
            } else {
                Write-Host "Please enter a number between 1 and $($caps.Count)."
            }
        }
        if (-not $chosen) { continue }   # refresh requested

        # ---- 4. get_capture (by container name, so a list shift can't pick the wrong one)
        $g = Invoke-Tool 'get_capture' @{ container = $chosen }
        $url = $g.data.capture_url
        if (-not $url) {
            Write-Host 'get_capture returned no capture_url.' -ForegroundColor Red
            throw 'ABORT'
        }

        Write-Host ''
        Write-Host ('-' * 70)
        Write-Host "Capture: $chosen      (URL expires in $($g.data.expires_in_seconds) seconds)"
        Write-Host ''
        Write-Host "  $url" -ForegroundColor Green
        Write-Host ''
        Write-Host "Paste this into your browser's address bar."
        Write-Host ('-' * 70)
        try { Set-Clipboard -Value $url; Write-Host '(Also copied to your clipboard.)' } catch {}
        Write-Host ''
        if ((Read-Host 'Pick another capture? (y/N)') -ine 'y') { return }
    }
}
catch {
    if ($_.Exception.Message -ne 'ABORT') { Write-Host $_.Exception.Message -ForegroundColor Red }
    Write-Host ''
    Write-Host 'Aborted.'
    exit 1
}
