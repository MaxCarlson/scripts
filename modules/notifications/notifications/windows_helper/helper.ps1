<#
.SYNOPSIS
    Hardened Interactive User-Session Toast Notification Helper for Scripts Notifications.

.DESCRIPTION
    Runs as a non-elevated user-session process (started at user logon via Task Scheduler).
    Listens on an authenticated loopback HTTP interface (127.0.0.1:1238) for notification requests.
    Renders and displays native Windows Toast Notifications via WinRT.
    Requires Bearer token authentication matching the shared broker token file.
    Does NOT accept arbitrary executable commands or elevated operations.
    Enforces strict cumulative byte limits, read timeouts, and robust stream safety.
#>

[CmdletBinding()]
param (
    [Parameter()]
    [int]$Port = 1238,

    [Parameter()]
    [string]$TokenPath = "",

    [Parameter()]
    [string]$ShutdownToken = "",

    [Parameter()]
    [string]$AppId = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe",

    [Parameter()]
    [switch]$SingleRequest
)

$ErrorActionPreference = "Stop"

# 1. Elevation Guard: Helper must NEVER run as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Write-Error "Security Refusal: Windows Toast Helper must NOT run as Administrator/elevated. Microsoft guidelines advise against elevated notification hosts."
    exit 3
}

# 2. Ensure WinRT types
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$CurrentSession = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
Write-Host "Starting Scripts Notifications Windows Toast Helper on PID $($PID) (Session: $CurrentSession)..."

if ($CurrentSession -eq 0) {
    Write-Warning "Running in Session 0 (non-interactive). Windows Toast Notifications cannot be displayed to users from Session 0."
}

# 3. Resolve Authoritative Token Path (aligns with notifications.config.default_token_path)
if (-not $TokenPath) {
    if ($env:NOTIFICATIONS_TOKEN_FILE) {
        $TokenPath = $env:NOTIFICATIONS_TOKEN_FILE
    } else {
        $scriptsHome = [System.IO.Path]::Combine($env:USERPROFILE, ".scripts", "notifications", "secrets")
        $TokenPath = [System.IO.Path]::Combine($scriptsHome, "broker-token")
    }
}

# Read or generate bearer token with strict ACLs
$token = ""
if (Test-Path -LiteralPath $TokenPath) {
    $token = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
} else {
    $tokenDir = [System.IO.Path]::GetDirectoryName($TokenPath)
    if (-not (Test-Path -LiteralPath $tokenDir)) {
        New-Item -ItemType Directory -Path $tokenDir -Force | Out-Null
    }
    # Generate 32-byte secure random hex token
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $token = [System.BitConverter]::ToString($bytes).Replace("-", "").ToLowerInvariant()
    Set-Content -LiteralPath $TokenPath -Value $token -NoNewline -Encoding utf8

    # Enforce strict ACL: owner and LocalSystem only
    try {
        $sid = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
        & icacls.exe $TokenPath /reset | Out-Null
        & icacls.exe $TokenPath /inheritance:r /grant:r "*${sid}:(F)" "*S-1-5-18:(F)" | Out-Null
        Write-Host "Generated new secure authentication token at: $TokenPath"
    } catch {
        Remove-Item -LiteralPath $TokenPath -Force -ErrorAction SilentlyContinue
        Write-Error "Failed to secure permissions on token file: $_"
        exit 1
    }
}

if (-not $token -or $token.Length -lt 32) {
    Write-Error "Failed to acquire valid authentication token from: $TokenPath"
    exit 1
}

# Resolve Shutdown Token (dedicated control token if available, else standard token)
if (-not $ShutdownToken) {
    if ($env:NOTIFICATIONS_SHUTDOWN_TOKEN) {
        $ShutdownToken = $env:NOTIFICATIONS_SHUTDOWN_TOKEN
    } else {
        $controlPath = [System.IO.Path]::Combine([System.IO.Path]::GetDirectoryName($TokenPath), "broker-control-token")
        if (Test-Path -LiteralPath $controlPath) {
            $ShutdownToken = (Get-Content -LiteralPath $controlPath -Raw).Trim()
        } else {
            $ShutdownToken = $token
        }
    }
}

# Setup HttpListener
$prefix = "http://127.0.0.1:$Port/"
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add($prefix)

try {
    $listener.Start()
    Write-Host "Listening for authenticated notification requests on $prefix"
} catch {
    Write-Error "Failed to bind to $prefix : $_"
    exit 2
}

$startTime = [DateTime]::UtcNow

function Escape-XmlText([string]$text) {
    if (-not $text) { return "" }
    # Strip non-printable control characters except newline and tab
    $clean = [regex]::Replace($text, "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "")
    # Standard XML escaping
    $clean = $clean.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace('"', "&quot;").Replace("'", "&apos;")
    return $clean
}

function Send-JsonResponse($response, [int]$statusCode, $obj) {
    try {
        $json = $obj | ConvertTo-Json -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        $response.StatusCode = $statusCode
        $response.ContentType = "application/json; charset=utf-8"
        $response.ContentLength64 = $bytes.Length
        $response.OutputStream.Write($bytes, 0, $bytes.Length)
        $response.OutputStream.Close()
    } catch {
        # Catch client disconnects or write failures cleanly
    }
}

try {
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response

        $urlPath = $request.Url.AbsolutePath.ToLowerInvariant()
        $method = $request.HttpMethod.ToUpperInvariant()

        # 1. Bearer Token Authentication
        $authHeader = $request.Headers["Authorization"]
        $expectedAuth = "Bearer $token"
        $expectedShutdownAuth = "Bearer $ShutdownToken"

        # Special authorization check for shutdown endpoint
        if ($urlPath -eq "/shutdown") {
            if (-not $authHeader -or ($authHeader -ne $expectedShutdownAuth -and $authHeader -ne $expectedAuth)) {
                Send-JsonResponse $response 401 @{ ok = $false; error = "unauthorized" }
                continue
            }
        } else {
            if (-not $authHeader -or $authHeader -ne $expectedAuth) {
                Send-JsonResponse $response 401 @{ ok = $false; error = "unauthorized" }
                continue
            }
        }

        # 2. Health check route
        if ($urlPath -in @("/health", "/status") -and $method -eq "GET") {
            $uptime = ([DateTime]::UtcNow - $startTime).TotalSeconds
            Send-JsonResponse $response 200 @{
                ok = $true
                status = "healthy"
                session_id = $CurrentSession
                user = $env:USERNAME
                pid = $PID
                uptime_seconds = [Math]::Round($uptime, 1)
                version = "1.1.0"
            }
            if ($SingleRequest) { break }
            continue
        }

        # 3. Shutdown route
        if ($urlPath -eq "/shutdown" -and $method -eq "POST") {
            Send-JsonResponse $response 200 @{ ok = $true; status = "shutting_down" }
            Write-Host "Shutdown requested via authenticated API."
            break
        }

        # 4. Notify route
        if ($urlPath -in @("/notify", "/toast") -and $method -eq "POST") {
            $maxBytes = 32768
            # Pre-check declared Content-Length
            if ($request.ContentLength64 -gt $maxBytes) {
                Send-JsonResponse $response 413 @{ ok = $false; error = "payload_too_large"; max_bytes = $maxBytes }
                continue
            }

            # Bounded streaming read (handles unknown-length/chunked requests and prevents slowloris)
            $stream = $request.InputStream
            $buffer = New-Object byte[] 4096
            $memStream = New-Object System.IO.MemoryStream
            $totalBytes = 0
            $timeoutMs = 5000
            $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            $streamError = $false

            while ($true) {
                if ($stopwatch.ElapsedMilliseconds -gt $timeoutMs) {
                    Send-JsonResponse $response 408 @{ ok = $false; error = "request_timeout" }
                    $streamError = $true
                    break
                }

                $bytesRead = 0
                try {
                    $asyncResult = $stream.BeginRead($buffer, 0, $buffer.Length, $null, $null)
                    $remainingMs = [Math]::Max(100, $timeoutMs - $stopwatch.ElapsedMilliseconds)
                    if (-not $asyncResult.AsyncWaitHandle.WaitOne($remainingMs)) {
                        Send-JsonResponse $response 408 @{ ok = $false; error = "request_timeout" }
                        $streamError = $true
                        break
                    }
                    $bytesRead = $stream.EndRead($asyncResult)
                } catch {
                    Send-JsonResponse $response 400 @{ ok = $false; error = "stream_read_error" }
                    $streamError = $true
                    break
                }

                if ($bytesRead -le 0) {
                    break # Reached end of stream
                }

                $totalBytes += $bytesRead
                if ($totalBytes -gt $maxBytes) {
                    Send-JsonResponse $response 413 @{ ok = $false; error = "payload_too_large"; max_bytes = $maxBytes }
                    $streamError = $true
                    break
                }

                $memStream.Write($buffer, 0, $bytesRead)
            }

            if ($streamError) {
                continue
            }

            $rawBody = [System.Text.Encoding]::UTF8.GetString($memStream.ToArray())
            try {
                $payload = $rawBody | ConvertFrom-Json
            } catch {
                Send-JsonResponse $response 400 @{ ok = $false; error = "invalid_json" }
                continue
            }

            $title = [string]$payload.title
            $body = [string]$payload.body
            $severity = if ($payload.severity) { [string]$payload.severity } else { "info" }
            $incidentId = [string]$payload.incident_id
            $dashboardUrl = [string]$payload.dashboard_url

            if (-not $title -or -not $body) {
                Send-JsonResponse $response 400 @{ ok = $false; error = "missing_required_fields" }
                continue
            }

            # Enforce max lengths
            if ($title.Length -gt 128) { $title = $title.Substring(0, 125) + "..." }
            if ($body.Length -gt 512) { $body = $body.Substring(0, 509) + "..." }

            # Safe XML escaping
            $escTitle = Escape-XmlText $title
            $escBody = Escape-XmlText $body
            $escSeverity = (Escape-XmlText $severity).ToUpperInvariant()

            # Scenario selection: critical breaks through Focus Assist
            $scenario = if ($severity -eq "critical") { "urgent" } else { "default" }

            # Safe action: ONLY allow dashboard navigation via verified https:// protocol
            $actionXml = ""
            if ($dashboardUrl -and $dashboardUrl.StartsWith("https://") -and -not $dashboardUrl.Contains("@")) {
                $escUrl = Escape-XmlText $dashboardUrl
                $actionXml = @"
    <actions>
        <action content="Open Dashboard" activationType="protocol" arguments="$escUrl" />
    </actions>
"@
            }

            $toastXmlString = @"
<toast scenario="$scenario">
    <visual>
        <binding template="ToastGeneric">
            <text>[$escSeverity] $escTitle</text>
            <text>$escBody</text>
            <text placement="attribution">Scripts Notifications</text>
        </binding>
    </visual>
$actionXml
</toast>
"@

            $toastId = "toast-" + [Guid]::NewGuid().ToString("N").Substring(0, 12)

            try {
                if ($CurrentSession -eq 0) {
                    # Explicit session 0 reporting
                    Send-JsonResponse $response 200 @{
                        ok = $false
                        status = "session_unavailable"
                        error = "Interactive user session not active (Session 0)"
                        toast_id = $toastId
                    }
                    if ($SingleRequest) { break }
                    continue
                }

                $xmlDoc = New-Object Windows.Data.Xml.Dom.XmlDocument
                $xmlDoc.LoadXml($toastXmlString)
                $toast = [Windows.UI.Notifications.ToastNotification]::new($xmlDoc)
                $toast.Tag = $toastId
                $toast.Group = "scripts_notifications"

                $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId)
                $notifier.Show($toast)

                Send-JsonResponse $response 200 @{
                    ok = $true
                    status = "display_requested"
                    toast_id = $toastId
                }
            } catch {
                Write-Warning "Toast display exception: $_"
                Send-JsonResponse $response 200 @{
                    ok = $false
                    status = "display_failed"
                    error = $_.Exception.Message
                    toast_id = $toastId
                }
            }

            if ($SingleRequest) { break }
            continue
        }

        # 5. Fallback 404
        Send-JsonResponse $response 404 @{ ok = $false; error = "not_found" }
    }
} finally {
    $listener.Stop()
    $listener.Close()
    Write-Host "Helper listener stopped."
}
