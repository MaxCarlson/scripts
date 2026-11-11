<#
.SYNOPSIS
    Interactive User-Session Toast Notification Helper for Scripts Notifications.

.DESCRIPTION
    Runs as a non-elevated user-session process (started at user logon via Task Scheduler).
    Listens on an authenticated loopback HTTP interface (127.0.0.1:1238) for notification requests.
    Renders and displays native Windows Toast Notifications via WinRT.
    Requires Bearer token authentication matching the shared token file.
    Does NOT accept arbitrary executable commands or elevated operations.
#>

[CmdletBinding()]
param (
    [Parameter()]
    [int]$Port = 1238,

    [Parameter()]
    [string]$TokenPath = "",

    [Parameter()]
    [string]$AppId = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe",

    [Parameter()]
    [switch]$SingleRequest
)

$ErrorActionPreference = "Stop"

# Ensure WinRT types
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$CurrentSession = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
Write-Host "Starting Scripts Notifications Windows Toast Helper on PID $($PID) (Session: $CurrentSession)..."

if ($CurrentSession -eq 0) {
    Write-Warning "Running in Session 0 (non-interactive). Windows Toast Notifications cannot be displayed to users from Session 0."
}

# Resolve token path
if (-not $TokenPath) {
    if ($env:NOTIFICATIONS_TOKEN_FILE) {
        $TokenPath = $env:NOTIFICATIONS_TOKEN_FILE
    } else {
        $localShare = [System.IO.Path]::Combine($env:USERPROFILE, ".local", "share", "scripts_notifications")
        $TokenPath = [System.IO.Path]::Combine($localShare, "token")
    }
}

# Read or generate bearer token
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
    Write-Host "Generated new authentication token at: $TokenPath"
}

if (-not $token) {
    Write-Error "Failed to acquire authentication token from: $TokenPath"
    exit 1
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
    $json = $obj | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $response.StatusCode = $statusCode
    $response.ContentType = "application/json; charset=utf-8"
    $response.ContentLength64 = $bytes.Length
    $response.OutputStream.Write($bytes, 0, $bytes.Length)
    $response.OutputStream.Close()
}

try {
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response

        # 1. Bearer Token Authentication
        $authHeader = $request.Headers["Authorization"]
        $expectedAuth = "Bearer $token"
        if (-not $authHeader -or $authHeader -ne $expectedAuth) {
            Send-JsonResponse $response 401 @{ ok = $false; error = "unauthorized" }
            continue
        }

        $urlPath = $request.Url.AbsolutePath.ToLowerInvariant()
        $method = $request.HttpMethod.ToUpperInvariant()

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
                version = "1.0.0"
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
            # Read and limit payload size (max 32KB)
            if ($request.ContentLength64 -gt 32768) {
                Send-JsonResponse $response 400 @{ ok = $false; error = "payload_too_large" }
                continue
            }

            $reader = New-Object System.IO.StreamReader($request.InputStream, [System.Text.Encoding]::UTF8)
            $rawBody = $reader.ReadToEnd()

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
