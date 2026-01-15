# File: scripts/Start-LMStudioServer.ps1 (Complete File)
<#
.SYNOPSIS
Starts/stops/checks the LM Studio local server from PowerShell 7.

.DESCRIPTION
Wraps LM Studio's `lms` CLI to manage the local server:
- Start: `lms server start` (optionally with --port and --cors)
- Status: `lms server status` (optionally JSON)
- Stop: `lms server stop`

Optionally:
- Adds a Windows Firewall rule for inbound TCP on the chosen port (admin required)
- Waits for the OpenAI-compatible endpoint to respond at /v1/models

References:
- CLI overview and server commands: https://lmstudio.ai/docs/cli
- server start flags (--port, --cors): https://lmstudio.ai/docs/cli/serve/server-start
- server status flags (--json, --quiet, --log-level): https://lmstudio.ai/docs/cli/serve/server-status
- OpenAI compatibility (/v1): https://lmstudio.ai/docs/developer/openai-compat

.PARAMETER Port
Port to run the server on (passed to `lms server start --port`). If omitted, LM Studio uses the last used port.

.PARAMETER Cors
Enables CORS (passed to `lms server start --cors`).

.PARAMETER Status
Prints server status and exits.

.PARAMETER Stop
Stops the server and exits.

.PARAMETER Json
When used with -Status, outputs status as JSON (passes `--json --quiet`).

.PARAMETER WaitSeconds
After starting, wait up to N seconds for the server to respond at /v1/models.

.PARAMETER BaseUrl
Base URL for readiness checks. Defaults to http://localhost:<port>/v1 if -Port provided,
otherwise falls back to http://localhost:1234/v1.

.PARAMETER AddFirewallRule
Adds a Windows Firewall inbound rule for the server port (admin required).

.PARAMETER ListModels
After server is running, lists models via GET /v1/models.

.EXAMPLE
.\Start-LMStudioServer.ps1 -p 1234 -c -w 20 -f

.EXAMPLE
.\Start-LMStudioServer.ps1 -s -j

.EXAMPLE
.\Start-LMStudioServer.ps1 -x
#>

[CmdletBinding()]
param(
    [Alias("p")]
    [int]$Port,

    [Alias("c")]
    [switch]$Cors,

    [Alias("s")]
    [switch]$Status,

    [Alias("x")]
    [switch]$Stop,

    [Alias("j")]
    [switch]$Json,

    [Alias("w")]
    [int]$WaitSeconds = 0,

    [Alias("b")]
    [string]$BaseUrl,

    [Alias("f")]
    [switch]$AddFirewallRule,

    [Alias("l")]
    [switch]$ListModels
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-LmsPath {
    [CmdletBinding()]
    param()

    $cmd = Get-Command -Name "lms" -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }

    # Common Windows location (best-effort). If you installed LM Studio normally, lms may not be on PATH.
    $candidates = @(
        (Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"),
        (Join-Path $env:USERPROFILE ".lmstudio\bin\lms")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

    if ($candidates.Count -gt 0) {
        return $candidates[0]
    }

    throw "Could not find 'lms' on PATH or under '${env:USERPROFILE}\.lmstudio\bin'. Add lms to PATH or install/update LM Studio so lms is available."
}

function Invoke-Lms {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    $lmsPath = Resolve-LmsPath
    & $lmsPath @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit=$LASTEXITCODE): $lmsPath $($Args -join ' ')"
    }
}

function Ensure-FirewallRule {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [int]$RulePort
    )

    $ruleName = "LM Studio Local Server (${RulePort})"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Write-Verbose "Firewall rule already exists: $ruleName"
        return
    }

    try {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort $RulePort `
            -Profile Any `
            -Program Any | Out-Null

        Write-Host "Added firewall rule: $ruleName"
    } catch {
        Write-Warning "Failed to add firewall rule (admin likely required). Error: $($_.Exception.Message)"
    }
}

function Get-DefaultBaseUrl {
    [CmdletBinding()]
    param(
        [int]$ChosenPort
    )

    if ($ChosenPort -gt 0) {
        return "http://localhost:${ChosenPort}/v1"
    }

    # LM Studio commonly uses 1234 by default; if user didn't supply port, use 1234 for readiness checks.
    return "http://localhost:1234/v1"
}

function Wait-ForServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $modelsUrl = "${Url}/models"

    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Uri $modelsUrl -Method Get -TimeoutSec 3
            return $resp
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    throw "Timed out waiting for LM Studio server to respond at ${modelsUrl} (waited ${TimeoutSeconds}s)."
}

# --- Main ---

if ($Status) {
    if ($Json) {
        Invoke-Lms -Args @("server", "status", "--json", "--quiet")
    } else {
        Invoke-Lms -Args @("server", "status")
    }
    exit 0
}

if ($Stop) {
    Invoke-Lms -Args @("server", "stop")
    exit 0
}

# Start server
$startArgs = @("server", "start")
if ($Port -gt 0) {
    $startArgs += @("--port", "$Port")
}
if ($Cors) {
    $startArgs += "--cors"
}

if ($AddFirewallRule) {
    if ($Port -le 0) {
        Write-Warning "AddFirewallRule requested but no -Port provided. Start may reuse last-used port. Consider specifying -Port."
    } else {
        Ensure-FirewallRule -RulePort $Port
    }
}

Invoke-Lms -Args $startArgs

# Determine base URL for readiness checks
if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = Get-DefaultBaseUrl -ChosenPort $Port
}

if ($WaitSeconds -gt 0 -or $ListModels) {
    $timeout = $WaitSeconds
    if ($timeout -le 0) {
        $timeout = 10
    }

    $models = Wait-ForServer -Url $BaseUrl -TimeoutSeconds $timeout

    if ($ListModels) {
        $models | ConvertTo-Json -Depth 8
    } else {
        Write-Host "LM Studio server is responding at ${BaseUrl}"
    }
}
# End of File: scripts/Start-LMStudioServer.ps1
