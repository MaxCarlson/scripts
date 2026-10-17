#Requires -Version 7.0
<#
.SYNOPSIS
    Select, hard-link (when multi-variant), estimate, and start the local coding model used by Codex through OpenCode.
.DESCRIPTION
    Configures LM Studio, the OpenCode provider, and the Codex MCP bridge, then
    starts and checks both local HTTP services by default. Existing unrelated
    OpenCode configuration and Codex MCP servers are preserved.

    Includes all LM Studio CLI (lms) workflows for multi-variant models like Qwen3.8-27B:
      - Automatic `lms import --hard-link` workaround for LM Studio Issue #1462 when
        selecting between installed quantizations (e.g., Q4_K_M vs. Q6_K) from the CLI
        without duplicating GGUF disk storage or requiring manual GUI switching.
      - Fixed `lms ls --variants` parser supporting both `-` and `*` selected-variant markers.
      - Pre-load VRAM resource estimation (`lms load --estimate-only`) and side-by-side
        Q4_K_M vs. Q6_K variant comparison (`-CompareVariants`).
      - Safe unloading (`lms unload <alias>`) before reloading or switching models/variants.
      - Post-load verification via `lms ps --json` / `lms ps` (checking actual GGUF path and
        size: ~16.52 GiB for Q4_K_M vs. ~21.75 GiB for Q6_K) plus `nvidia-smi` VRAM headroom.

    The LM Studio loaded-model identifier stays constant between switches (default: qwen-local).
    Native Windows / PowerShell 7+ only.
.PARAMETER Model
    Installed LM Studio model key, optionally with @quantization (default: 'qwen/qwen3.8-27b@q6_k').
.PARAMETER Quantization
    Optional explicit quantization override (e.g., 'Q6_K' or 'Q4_K_M'). Overrides any @suffix on -Model.
.PARAMETER ModelAlias
    Stable inference API ID shared by OpenCode and Codex (default: 'qwen-local').
.PARAMETER ContextLength
    Context length used for model loads and memory estimates (default: 32768).
.PARAMETER Gpu
    Offload setting accepted by lms load: max, off, or fraction 0 through 1 (default: 'max').
.PARAMETER Reload
    Force a model unload/reload even when the requested model and quantization are already loaded.
.PARAMETER NoServers
    Configure and load the model but DO NOT start either HTTP server or check their network endpoints.
.PARAMETER EstimateOnly
    Run `lms load --estimate-only` for the target model/quantization and exit without loading.
.PARAMETER CompareVariants
    Run `lms load --estimate-only` side by side for both Q4_K_M and Q6_K at -ContextLength and exit.
.PARAMETER UnloadOnly
    Unload the current -ModelAlias instance from LM Studio memory (`lms unload`) and exit.
.PARAMETER UseGuiSelection
    Option 1 mode: rely strictly on the variant selected in the LM Studio GUI (`-` or `*` in `lms ls --variants`)
    instead of creating/using an `lms import --hard-link` repository for @quantization.
.PARAMETER DryRunImport
    Preview the `lms import --hard-link --dry-run` command and memory estimate without importing or loading.
.PARAMETER ModelsDir
    Optional override for the LM Studio models directory (auto-detected from settings.json or ~/.lmstudio/models).
.PARAMETER GgufPath
    Optional explicit path to a .gguf file to use when creating a hard-linked variant repository.
.EXAMPLE
    .\LoadLMSCodexBridge.ps1
.EXAMPLE
    .\LoadLMSCodexBridge.ps1 -Quantization Q4_K_M
.EXAMPLE
    .\LoadLMSCodexBridge.ps1 -m 'qwen/qwen3.8-27b@q6_k'
.EXAMPLE
    .\LoadLMSCodexBridge.ps1 -m 'qwen3.8-27b-uncensored' -c 65536 -r
.EXAMPLE
    .\LoadLMSCodexBridge.ps1 -CompareVariants -c 65536
.EXAMPLE
    .\LoadLMSCodexBridge.ps1 -m 'qwen/qwen3.8-27b@q4_k_m' -NoServers
#>
[CmdletBinding()]
param(
    [Alias('m')][ValidateNotNullOrEmpty()][string]$Model = 'qwen/qwen3.8-27b@q6_k',
    [Alias('q')][string]$Quantization = '',
    [Alias('a', 'Identifier')][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')][string]$ModelAlias = 'qwen-local',
    [Alias('c')][ValidateRange(1024, 262144)][int]$ContextLength = 32768,
    [Alias('g', 'GpuOffload')][ValidateNotNullOrEmpty()][string]$Gpu = 'max',
    [Alias('r')][switch]$Reload,
    [Alias('ns')][switch]$NoServers,
    [Alias('e')][switch]$EstimateOnly,
    [Alias('cmp')][switch]$CompareVariants,
    [Alias('u')][switch]$UnloadOnly,
    [Alias('UseGuiSelectedVariant')][switch]$UseGuiSelection,
    [Alias('DryRun')][switch]$DryRunImport,
    [string]$ModelsDir = '',
    [string]$GgufPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$LmsUrl = 'http://127.0.0.1:1234'
$OpenCodeUrl = 'http://127.0.0.1:4096'
$ProviderId = 'lmstudio'
$BridgeName = 'opencode_worker'
$BridgePackage = 'opencode-mcp@3.0.0'
$OpenCodeConfig = Join-Path $HOME '.config/opencode/opencode.json'
$CodexConfig = Join-Path $HOME '.codex/config.toml'
$script:CurrentStep = ''
$script:StepStarted = [datetime]::UtcNow

function Start-Step {
    param([Parameter(Mandatory)][string]$Description)
    $script:CurrentStep = $Description
    $script:StepStarted = [datetime]::UtcNow
    Write-Host "… $Description" -ForegroundColor Yellow
    Write-Debug "Starting: $Description"
}
function Complete-Step {
    param([Parameter(Mandatory)][string]$Description)
    Write-Host "✓ $Description" -ForegroundColor Green
    Write-Debug "Completed: $Description"
    $script:CurrentStep = ''
}
function Report-Failure {
    param([string]$Description)
    Write-Host "✗ $Description" -ForegroundColor Red
}
function Write-Notice {
    param([string]$Description)
    Write-Host "! $Description" -ForegroundColor Yellow
}

# Uses a worker runspace so even a slow lms load emits heartbeat messages.
function Invoke-External {
    param(
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 300
    )
    Write-Debug ("Executing: {0} {1}" -f $Command, ($Arguments -join ' '))
    $spec = @{ Command = $Command; Arguments = @($Arguments) }
    $job = Start-ThreadJob -ArgumentList $spec -ScriptBlock {
        param($item)
        $ErrorActionPreference = 'Continue'
        $result = & $item.Command @($item.Arguments) 2>&1 | Out-String
        [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $result }
    }
    try {
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        while (-not (Wait-Job -Job $job -Timeout 5)) {
            $seconds = [int]$watch.Elapsed.TotalSeconds
            if ($seconds -ge $TimeoutSeconds) {
                Stop-Job -Job $job -ErrorAction SilentlyContinue
                throw "Timed out after ${seconds}s: $Command $($Arguments -join ' ')"
            }
            Write-Host "… $($script:CurrentStep) (${seconds}s elapsed)" -ForegroundColor Yellow
        }
        if ($job.State -ne 'Completed') {
            $details = ($job.ChildJobs[0].JobStateInfo.Reason | Out-String).Trim()
            throw "Command failed to execute: $Command. $details"
        }
        $response = @(Receive-Job -Job $job -ErrorAction Stop)[-1]
        if ($null -eq $response -or $response.ExitCode -ne 0) {
            throw "Command failed ($($response.ExitCode)): $Command $($Arguments -join ' ')`n$($response.Output)"
        }
        return [string]$response.Output.Trim()
    } finally {
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
}

function Get-HttpJson {
    param([Parameter(Mandatory)][string]$Url, [int]$TimeoutSeconds = 4)
    try { return Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSeconds -ErrorAction Stop }
    catch { Write-Debug "HTTP unavailable: ${Url}: $_"; return $null }
}

function Wait-HttpJson {
    param([Parameter(Mandatory)][string]$Url, [int]$MaxSeconds = 30)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt $MaxSeconds) {
        $result = Get-HttpJson -Url $Url -TimeoutSeconds 2
        if ($null -ne $result) { return $result }
        Start-Sleep -Seconds 2
        $elapsed = [int]$watch.Elapsed.TotalSeconds
        if ($elapsed % 10 -lt 2) {
            Write-Host "… Waiting for $Url (${elapsed}s elapsed)" -ForegroundColor Yellow
        }
    }
    return $null
}

# Converts a string like 'qwen3.8-27b' or 'q4_k_m' into a flexible token regex 'qwen3[-_.]?8[-_.]?27b'
function Get-TokenRegex {
    param([Parameter(Mandatory)][string]$Text)
    $tokens = @($Text -split '[-_.]+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { [regex]::Escape($_) })
    return ($tokens -join '[-_.]?')
}

function Resolve-ModelsDirectory {
    param([string]$ExplicitDir)
    if (-not [string]::IsNullOrWhiteSpace($ExplicitDir)) {
        if (-not (Test-Path -LiteralPath $ExplicitDir)) {
            throw "Provided -ModelsDir '$ExplicitDir' does not exist."
        }
        return (Resolve-Path -LiteralPath $ExplicitDir).Path
    }
    $settingsCandidates = @(
        (Join-Path $HOME '.lmstudio/settings.json'),
        (Join-Path $env:APPDATA 'LM Studio/settings.json')
    )
    foreach ($cfg in $settingsCandidates) {
        if (Test-Path -LiteralPath $cfg) {
            try {
                $json = Get-Content -LiteralPath $cfg -Raw | ConvertFrom-Json -ErrorAction Stop
                if ($json.PSObject.Properties['downloadsFolder'] -and
                    -not [string]::IsNullOrWhiteSpace($json.downloadsFolder) -and
                    (Test-Path -LiteralPath $json.downloadsFolder)) {
                    return (Resolve-Path -LiteralPath $json.downloadsFolder).Path
                }
            } catch {}
        }
    }
    foreach ($candidate in @(
        (Join-Path $HOME '.lmstudio/models'),
        (Join-Path $HOME '.cache/lm-studio/models')
    )) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ''
}

function Find-VariantGguf {
    param(
        [Parameter(Mandatory)][string]$Base,
        [Parameter(Mandatory)][string]$Quant,
        [string]$ModelsRoot,
        [string]$ExplicitFile
    )
    if (-not [string]::IsNullOrWhiteSpace($ExplicitFile)) {
        if (-not (Test-Path -LiteralPath $ExplicitFile)) {
            throw "Provided -GgufPath '$ExplicitFile' does not exist."
        }
        return (Resolve-Path -LiteralPath $ExplicitFile).Path
    }
    if ([string]::IsNullOrWhiteSpace($ModelsRoot) -or -not (Test-Path -LiteralPath $ModelsRoot)) {
        throw "Could not determine LM Studio models directory. Pass -ModelsDir or -GgufPath."
    }

    $baseLeaf = ($Base -split '/')[-1]
    $baseRegex = '(?i)' + (Get-TokenRegex -Text $baseLeaf)
    $quantRegex = '(?i)(^|[-_.])' + (Get-TokenRegex -Text $Quant) + '(?=[-_.]|\.gguf$)'
    $wantUncensored = $Base -match '(?i)uncensored'

    $candidates = @(Get-ChildItem -LiteralPath $ModelsRoot -Recurse -File -Filter '*.gguf' -ErrorAction SilentlyContinue |
        Where-Object {
            $fileName = $_.Name
            $fullPath = $_.FullName
            $isMmproj = $fileName -match '(?i)^mmproj'
            $isLocalHardLink = $fullPath -match '(?i)[\\/]local[\\/]'
            $hasUncensored = $fullPath -match '(?i)uncensored'

            (-not $isMmproj) -and
            (-not $isLocalHardLink) -and
            ($wantUncensored -eq $hasUncensored) -and
            ($fullPath -match $baseRegex) -and
            ($fileName -match $quantRegex)
        } | Sort-Object Length -Descending)

    if ($candidates.Count -eq 0) {
        throw "Could not auto-locate the $Quant .gguf file for '$Base' under '$ModelsRoot'. Pass -GgufPath 'C:\path\to\model.gguf'."
    }
    return $candidates[0].FullName
}

function Get-HardLinkRepoNames {
    param(
        [Parameter(Mandatory)][string]$Base,
        [Parameter(Mandatory)][string]$Quant
    )
    $baseLeaf = (($Base -split '/')[-1].ToLowerInvariant() -replace '\.', '')
    $quantClean = ($Quant.ToLowerInvariant() -replace '[_-]+', '')
    $repoLeaf = "$baseLeaf-$quantClean"
    return [pscustomobject]@{
        UserRepo = "local/$repoLeaf"
        RepoLeaf = $repoLeaf
    }
}

function Find-RegisteredRepoKey {
    param(
        [Parameter(Mandatory)][string]$UserRepo,
        [Parameter(Mandatory)][string]$RepoLeaf
    )
    # 1. Check `lms ls --json` if available
    try {
        $jsonRaw = Invoke-External -Command 'lms' -Arguments @('ls', '--json')
        if ($jsonRaw -and $jsonRaw.StartsWith('[')) {
            $models = @($jsonRaw | ConvertFrom-Json -ErrorAction Stop)
            foreach ($m in $models) {
                $key = if ($m.PSObject.Properties['modelKey']) { [string]$m.modelKey }
                       elseif ($m.PSObject.Properties['key']) { [string]$m.key }
                       else { '' }
                $path = if ($m.PSObject.Properties['path']) { [string]$m.path } else { '' }
                if ($key -ieq $UserRepo -or $key -ieq $RepoLeaf -or
                    $path -match "(?i)(^|[\\/])$([regex]::Escape($RepoLeaf))([\\/]|$)") {
                    if ($key) { return $key }
                }
            }
        }
    } catch {}

    # 2. Check `lms ls --variants` text output
    $lsText = Invoke-External -Command 'lms' -Arguments @('ls', '--variants')
    $m = [regex]::Match($lsText, "(?im)^\s*(?:[\*\-]\s+)?(?<key>(?:local/)?$([regex]::Escape($RepoLeaf)))(?=\s|@|$)")
    if ($m.Success) {
        return $m.Groups['key'].Value.Trim()
    }
    return $null
}

function Ensure-HardLinkedVariant {
    param(
        [Parameter(Mandatory)][string]$Base,
        [Parameter(Mandatory)][string]$Quant
    )
    $names = Get-HardLinkRepoNames -Base $Base -Quant $Quant
    $existingKey = Find-RegisteredRepoKey -UserRepo $names.UserRepo -RepoLeaf $names.RepoLeaf
    if ($existingKey -and -not $DryRunImport) {
        Write-Notice "Using registered hard-link repo '$existingKey' for $Base@$Quant"
        return $existingKey
    }

    $modelsRoot = Resolve-ModelsDirectory -ExplicitDir $ModelsDir
    $ggufFile = Find-VariantGguf -Base $Base -Quant $Quant -ModelsRoot $modelsRoot -ExplicitFile $GgufPath

    if ($modelsRoot) {
        $srcDrive = (Split-Path -Path $ggufFile -Qualifier).ToUpperInvariant()
        $dstDrive = (Split-Path -Path $modelsRoot -Qualifier).ToUpperInvariant()
        if ($srcDrive -and $dstDrive -and ($srcDrive -cne $dstDrive)) {
            throw "Hard-link import requires '$ggufFile' ($srcDrive) and '$modelsRoot' ($dstDrive) to be on the same volume."
        }
    }

    Write-Notice "Previewing hard-link import (--dry-run): $ggufFile -> $($names.UserRepo)"
    $dryRunOut = Invoke-External -Command 'lms' -Arguments @(
        'import', $ggufFile, '--user-repo', $names.UserRepo, '--hard-link', '--dry-run'
    )
    if ($dryRunOut) { Write-Debug $dryRunOut }

    if ($DryRunImport) {
        Write-Notice "DryRunImport enabled: skipping 'lms import -y' execution."
        return $names.UserRepo
    }

    Write-Notice "Importing hard-linked variant '$($names.UserRepo)' (zero extra disk space)"
    Invoke-External -Command 'lms' -Arguments @(
        'import', $ggufFile, '--user-repo', $names.UserRepo, '--hard-link', '-y'
    ) | Out-Null

    $registeredKey = Find-RegisteredRepoKey -UserRepo $names.UserRepo -RepoLeaf $names.RepoLeaf
    if ($registeredKey) {
        return $registeredKey
    }
    return $names.UserRepo
}

function Get-LoadedModel {
    param([Parameter(Mandatory)][string]$Identifier)
    # Prefer machine-readable `lms ps --json` when supported, with fallback to `lms ps` text parsing
    try {
        $jsonRaw = Invoke-External -Command 'lms' -Arguments @('ps', '--json')
        if ($jsonRaw -and $jsonRaw.StartsWith('[')) {
            $items = @($jsonRaw | ConvertFrom-Json -ErrorAction Stop)
            foreach ($item in $items) {
                $id = if ($item.PSObject.Properties['identifier']) { [string]$item.identifier } else { '' }
                if ($id -cne $Identifier) { continue }
                $p = if ($item.PSObject.Properties['path']) { [string]$item.path }
                     elseif ($item.PSObject.Properties['modelKey']) { [string]$item.modelKey }
                     else { '' }
                $sz = if ($item.PSObject.Properties['sizeBytes'] -and $item.sizeBytes) {
                    "{0:N2} GiB" -f ([double]$item.sizeBytes / 1GB)
                } elseif ($item.PSObject.Properties['size']) {
                    [string]$item.size
                } else { '' }
                if ($p) {
                    return [pscustomobject]@{
                        Identifier = $Identifier
                        Path       = $p.Trim()
                        Size       = $sz
                    }
                }
            }
        }
    } catch {}

    $output = Invoke-External -Command 'lms' -Arguments @('ps')
    foreach ($block in [regex]::Matches($output,
        '(?ms)^\s*Identifier:\s*(?<id>[^\r\n]+)\r?\n(?<details>.*?)(?=^\s*Identifier:|\z)')) {
        if ($block.Groups['id'].Value.Trim() -cne $Identifier) { continue }
        $path = [regex]::Match($block.Groups['details'].Value,
            '(?m)^\s*[^\w\r\n]*Path:\s*(?<value>[^\r\n]+)')
        $size = [regex]::Match($block.Groups['details'].Value,
            '(?m)^\s*[^\w\r\n]*Size:\s*(?<value>[^\r\n]+)')
        return [pscustomobject]@{
            Identifier = $Identifier
            Path       = if ($path.Success) { $path.Groups['value'].Value.Trim() } else { '' }
            Size       = if ($size.Success) { $size.Groups['value'].Value.Trim() } else { '' }
        }
    }
    return $null
}

function Test-LoadedSelection {
    param($Loaded, $Selection)
    if ($null -eq $Loaded -or [string]::IsNullOrWhiteSpace($Loaded.Path)) { return $false }
    $path = $Loaded.Path.Replace('\', '/').ToLowerInvariant()
    $basename = ($Selection.Base -split '/')[-1].ToLowerInvariant()
    $baseRegex = '(^|/)' + (Get-TokenRegex -Text $basename) + '(?=/|[-_.]|$)'

    $loadKeyLeaf = if ($Selection.PSObject.Properties['LoadKey'] -and $Selection.LoadKey) {
        ($Selection.LoadKey -split '/')[-1].ToLowerInvariant()
    } else { '' }
    $loadKeyRegex = if ($loadKeyLeaf) {
        '(^|/)' + (Get-TokenRegex -Text $loadKeyLeaf) + '(?=/|[-_.]|$)'
    } else { '' }

    $matchesBaseOrRepo = ($path -match $baseRegex) -or ($loadKeyRegex -and ($path -match $loadKeyRegex))
    if (-not $matchesBaseOrRepo) { return $false }

    if ($basename -notmatch 'uncensored' -and $path -match 'uncensored') { return $false }
    if ($basename -match 'uncensored' -and $path -notmatch 'uncensored') { return $false }

    if ($Selection.Quant) {
        $quantRegex = '(?i)(^|[-_./])' + (Get-TokenRegex -Text $Selection.Quant.ToLowerInvariant()) + '(?=[-_./]|$)'
        if ($path -notmatch $quantRegex) { return $false }
    }
    return $true
}

function Resolve-Selection {
    param([string]$Requested)
    $split = $Requested.Split('@', 2)
    $base = $split[0]
    $quant = if ($split.Count -gt 1) { $split[1].ToLowerInvariant() } else { '' }
    if (-not $base -or ($split.Count -gt 1 -and -not $quant)) {
        throw "Invalid model key: '$Requested'"
    }

    $output = Invoke-External -Command 'lms' -Arguments @('ls', '--variants')
    # Matches both `- model@quant` and `* model@quant` selected indicators in `lms ls --variants`
    $rows = @([regex]::Matches($output,
        '(?m)^\s*(?:(?<selected>[\*\-])\s+)?(?<key>[^\s@]+@[^\s]+)\s+') |
        ForEach-Object {
            [pscustomobject]@{
                Key      = $_.Groups['key'].Value
                Selected = $_.Groups['selected'].Success
            }
        } | Where-Object { $_.Key.StartsWith("$base@", [StringComparison]::OrdinalIgnoreCase) })

    if ($rows.Count -eq 0) {
        if ($quant) {
            # If user requested @quant on a model that isn't grouped under @variants, try hard-link or check lms ls
            if ($output -notmatch "(?im)^\s*(?:[\*\-]\s+)?$([regex]::Escape($base))(?=\s|$)") {
                throw "Cannot find model '$base' or variant '$Requested' in 'lms ls --variants'."
            }
        } elseif ($output -notmatch "(?im)^\s*(?:[\*\-]\s+)?$([regex]::Escape($base))(?=\s|$)") {
            throw "Model '$base' is not installed (lms ls)."
        }
        return [pscustomobject]@{
            Base         = $base
            LoadKey      = $base
            Quant        = $quant
            Display      = if ($quant) { "$base@$quant" } else { $base }
            UsedHardLink = $false
        }
    }

    if ($quant) {
        $matchingRow = @($rows | Where-Object { $_.Key -ieq "$base@$quant" })
        if ($matchingRow.Count -eq 0) {
            $available = ($rows | ForEach-Object Key) -join ', '
            throw "Variant '$base@$quant' is not installed. Installed variants: $available"
        }
    }

    $selected = @($rows | Where-Object Selected)

    # Single-variant model: base key unambiguously loads the only installed variant
    if ($rows.Count -eq 1) {
        $choice = $rows[0].Key
        $resolvedQuant = $choice.Split('@', 2)[1]
        return [pscustomobject]@{
            Base         = $base
            LoadKey      = $base
            Quant        = $resolvedQuant
            Display      = $choice
            UsedHardLink = $false
        }
    }

    # Multi-variant model (e.g., qwen/qwen3.8-27b with @q4_k_m and @q6_k)
    if (-not $quant) {
        if ($selected.Count -eq 1) {
            $choice = $selected[0].Key
            $quant = $choice.Split('@', 2)[1]
        } else {
            throw "Multiple variants of '$base' exist. Specify a quantization (e.g., -m '$($rows[0].Key)' or -Quantization Q6_K)."
        }
    }

    $guiMatchesRequest = ($selected.Count -eq 1) -and ($selected[0].Key -ieq "$base@$quant")

    if ($UseGuiSelection) {
        if (-not $guiMatchesRequest) {
            $currentGui = if ($selected.Count -eq 1) { $selected[0].Key } else { '<none>' }
            throw "Requested '$base@$quant', but LM Studio GUI currently selects '$currentGui'. Select '$base@$quant' in the GUI or omit -UseGuiSelection to auto-register a hard-linked CLI repo."
        }
        return [pscustomobject]@{
            Base         = $base
            LoadKey      = $base
            Quant        = $quant
            Display      = "$base@$quant"
            UsedHardLink = $false
        }
    }

    # Option 2 (Default for multi-variant CLI control): Ensure a dedicated hard-linked repo exists
    # so CLI loads are 100% deterministic regardless of GUI state.
    $hardLinkKey = Ensure-HardLinkedVariant -Base $base -Quant $quant
    return [pscustomobject]@{
        Base         = $base
        LoadKey      = $hardLinkKey
        Quant        = $quant
        Display      = "$base@$quant"
        UsedHardLink = $true
    }
}

function Invoke-MemoryEstimate {
    param(
        [Parameter(Mandatory)][string]$LoadKey,
        [Parameter(Mandatory)][string]$DisplayLabel
    )
    $estOut = Invoke-External -Command 'lms' -Arguments @(
        'load', $LoadKey, '--gpu', $Gpu, '--context-length', "$ContextLength", '--estimate-only'
    )
    $cleanLines = @($estOut -split '\r?\n' | Where-Object { $_ -match '(?i)Model:|Estimated|Estimate:' })
    if ($cleanLines.Count -gt 0) {
        Write-Notice "Memory estimate for $DisplayLabel (GPU=$Gpu, context=$ContextLength): $($cleanLines -join ' | ')"
    } else {
        Write-Notice "Memory estimate for $DisplayLabel`: $estOut"
    }
}

function Show-GpuHeadroom {
    $nvidiaCmd = Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue
    if (-not $nvidiaCmd) { return }
    try {
        $csv = Invoke-External -Command 'nvidia-smi' -Arguments @(
            '--query-gpu=name,memory.used,memory.free,memory.total',
            '--format=csv,noheader,nounits'
        ) -TimeoutSeconds 15
        foreach ($line in ($csv -split '\r?\n')) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            $parts = @($line -split ',\s*')
            if ($parts.Count -ge 4) {
                $gpuName  = $parts[0]
                $usedGiB  = "{0:N2}" -f ([double]$parts[1] / 1024)
                $freeGiB  = "{0:N2}" -f ([double]$parts[2] / 1024)
                $totalGiB = "{0:N2}" -f ([double]$parts[3] / 1024)
                Write-Notice "GPU VRAM ($gpuName): $usedGiB GiB used, $freeGiB GiB free headroom (of $totalGiB GiB)"
            }
        }
    } catch {
        Write-Debug "nvidia-smi check skipped: $_"
    }
}

function Set-OpenCodeConfiguration {
    $settings = @{}
    if (Test-Path -LiteralPath $OpenCodeConfig) {
        try {
            $settings = Get-Content -LiteralPath $OpenCodeConfig -Raw |
                ConvertFrom-Json -AsHashtable -ErrorAction Stop
        } catch { throw "Invalid existing OpenCode JSON: $OpenCodeConfig. $_" }
    }
    if ($null -eq $settings) { $settings = @{} }
    if (-not ($settings -is [System.Collections.IDictionary])) {
        throw 'OpenCode JSON root must be an object.'
    }
    $before = ConvertTo-Json -InputObject $settings -Depth 100 -Compress
    if (-not $settings.Contains('$schema')) { $settings['$schema'] = 'https://opencode.ai/config.json' }
    if (-not $settings.Contains('provider')) { $settings['provider'] = @{} }
    if (-not ($settings['provider'] -is [System.Collections.IDictionary])) {
        throw 'OpenCode provider must be a JSON object.'
    }
    $providers = $settings['provider']
    if (-not $providers.Contains($ProviderId)) { $providers[$ProviderId] = @{} }
    $provider = $providers[$ProviderId]
    if (-not ($provider -is [System.Collections.IDictionary])) {
        throw 'Existing lmstudio provider must be an object.'
    }
    foreach ($field in @('options', 'models')) {
        if (-not $provider.Contains($field)) { $provider[$field] = @{} }
        if (-not ($provider[$field] -is [System.Collections.IDictionary])) {
            throw "Existing lmstudio.$field must be an object."
        }
    }
    $provider['npm'] = '@ai-sdk/openai-compatible'
    $provider['name'] = 'LM Studio Local'
    $provider['options']['baseURL'] = "$LmsUrl/v1"
    if (-not $provider['models'].Contains($ModelAlias)) {
        $provider['models'][$ModelAlias] = @{}
    }
    if (-not ($provider['models'][$ModelAlias] -is [System.Collections.IDictionary])) {
        throw "Existing lmstudio model '$ModelAlias' must be an object."
    }
    $provider['models'][$ModelAlias]['name'] = "Local worker: $($selection.Display)"
    $settings['model'] = "$ProviderId/$ModelAlias"
    $after = ConvertTo-Json -InputObject $settings -Depth 100 -Compress
    if ($after -ceq $before) { return $false }

    $folder = Split-Path -Parent $OpenCodeConfig
    New-Item -Path $folder -ItemType Directory -Force | Out-Null
    if (Test-Path -LiteralPath $OpenCodeConfig) {
        $backup = "$OpenCodeConfig.bak-$(Get-Date -Format yyyyMMdd-HHmmss-fff)"
        Copy-Item -LiteralPath $OpenCodeConfig -Destination $backup -ErrorAction Stop
        Write-Notice "Backed up OpenCode settings: $backup"
    }
    $temp = Join-Path $folder ("opencode-$(New-Guid).tmp")
    try {
        Set-Content -LiteralPath $temp -Value ($settings | ConvertTo-Json -Depth 100) -Encoding utf8
        Move-Item -LiteralPath $temp -Destination $OpenCodeConfig -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
    return $true
}

function Register-McpBridge {
    $wanted = [ordered]@{
        OPENCODE_BASE_URL         = $OpenCodeUrl
        OPENCODE_AUTO_SERVE       = 'false'
        OPENCODE_TOOL_PROFILE     = 'essential'
        OPENCODE_DEFAULT_PROVIDER = $ProviderId
        OPENCODE_DEFAULT_MODEL    = $ModelAlias
    }
    $entries = @(Invoke-External -Command 'codex' -Arguments @('mcp', 'list', '--json') |
        ConvertFrom-Json)
    $existing = @($entries | Where-Object { $_.name -eq $BridgeName })
    $isCurrent = $false
    if ($existing.Count -gt 0) {
        $bridge = $existing[0]
        $envs = $bridge.transport.env
        $isCurrent = $bridge.enabled -and $bridge.transport.type -eq 'stdio' -and
            $bridge.transport.command -eq 'npx.cmd' -and
            (@($bridge.transport.args) -join '|') -eq "-y|$BridgePackage"
        foreach ($key in $wanted.Keys) {
            if ($null -eq $envs -or $envs.$key -cne $wanted[$key]) { $isCurrent = $false }
        }
    }
    if ($isCurrent) { return $false }

    $backup = $null
    if ($existing.Count -gt 0) {
        if (-not (Test-Path -LiteralPath $CodexConfig)) {
            throw "Cannot update existing '$BridgeName': Codex config not found at $CodexConfig"
        }
        $backup = "$CodexConfig.bak-$(Get-Date -Format yyyyMMdd-HHmmss-fff)"
        Copy-Item -LiteralPath $CodexConfig -Destination $backup -ErrorAction Stop
        Write-Notice "Backing up Codex configuration: $backup"
    }
    try {
        if ($existing.Count -gt 0) {
            Invoke-External -Command 'codex' -Arguments @('mcp', 'remove', $BridgeName) | Out-Null
        }
        $arguments = @('mcp', 'add', $BridgeName)
        foreach ($key in $wanted.Keys) { $arguments += @('--env', "$key=$($wanted[$key])") }
        $arguments += @('--', 'npx.cmd', '-y', $BridgePackage)
        Invoke-External -Command 'codex' -Arguments $arguments | Out-Null
    } catch {
        if ($backup) {
            Copy-Item -LiteralPath $backup -Destination $CodexConfig -Force
            Write-Notice 'Restored the previous Codex config after registration failure.'
        }
        throw
    }
    return $true
}

function Test-OpenCodeModel {
    $config = Get-HttpJson "$OpenCodeUrl/config"
    if ($null -eq $config) { throw 'OpenCode server responds to health checks but /config is unavailable.' }
    if ($config.model -cne "$ProviderId/$ModelAlias") {
        throw "OpenCode server uses '$($config.model)' instead of '$ProviderId/$ModelAlias'. Restart the existing OpenCode server to reload its config."
    }
    $catalog = Get-HttpJson "$OpenCodeUrl/config/providers"
    if ($null -eq $catalog) { throw 'OpenCode provider catalog is unavailable.' }
    $providers = @($catalog.providers)
    $lmProvider = @($providers | Where-Object { $_.id -eq $ProviderId })
    if ($lmProvider.Count -eq 0) { throw 'OpenCode server has not loaded its lmstudio provider.' }
    $models = $lmProvider[0].models
    if ($null -eq $models) { throw 'OpenCode lmstudio provider lists no models.' }
    if ($models -is [System.Collections.IDictionary]) {
        if (-not $models.Contains($ModelAlias)) { throw "OpenCode does not list '$ModelAlias'." }
    } elseif ($models.PSObject.Properties.Name -cnotcontains $ModelAlias) {
        throw "OpenCode does not list '$ModelAlias'."
    }
}

try {
    # If -Quantization was passed (e.g. -Quantization Q4_K_M), apply it onto $Model
    if (-not [string]::IsNullOrWhiteSpace($Quantization)) {
        $baseOnly = ($Model -split '@', 2)[0]
        $Model = "$baseOnly@$($Quantization.ToLowerInvariant())"
    }

    Start-Step 'Checking PowerShell, Node.js, LM Studio, and Codex'
    if (-not $IsWindows) { throw 'This script is for native Windows PowerShell 7, not WSL2.' }
    foreach ($command in @('lms', 'codex', 'node', 'npm.cmd', 'npx.cmd')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Missing command: $command" }
    }
    $node = (Invoke-External -Command 'node' -Arguments @('--version')).Trim().TrimStart('v')
    if ([version]$node -lt [version]'22.0.0') { throw "Node.js 22+ required (found $node)." }
    if ($Gpu -notmatch '^(max|off|0(?:\.\d+)?|1(?:\.0+)?)$') {
        throw "Invalid -Gpu '$Gpu'. Choose max, off, or a number from 0 through 1."
    }
    Complete-Step "Prerequisites available (Node.js $node)"

    if ($UnloadOnly) {
        Start-Step "Unloading model alias '$ModelAlias'"
        $existingLoad = Get-LoadedModel -Identifier $ModelAlias
        if ($null -ne $existingLoad) {
            Invoke-External -Command 'lms' -Arguments @('unload', $ModelAlias) | Out-Null
            Complete-Step "Unloaded '$ModelAlias' ($($existingLoad.Path))"
        } else {
            Complete-Step "Model alias '$ModelAlias' is not currently loaded"
        }
        exit 0
    }

    if ($CompareVariants) {
        $baseModel = ($Model -split '@', 2)[0]
        Start-Step "Comparing Q4_K_M and Q6_K memory estimates for '$baseModel' (context=$ContextLength)"
        $q4Sel = Resolve-Selection -Requested "$baseModel@q4_k_m"
        $q6Sel = Resolve-Selection -Requested "$baseModel@q6_k"
        if (-not $DryRunImport) {
            Invoke-MemoryEstimate -LoadKey $q4Sel.LoadKey -DisplayLabel $q4Sel.Display
            Invoke-MemoryEstimate -LoadKey $q6Sel.LoadKey -DisplayLabel $q6Sel.Display
        }
        Show-GpuHeadroom
        Complete-Step "Completed variant comparison for '$baseModel'"
        exit 0
    }

    Start-Step "Selecting LM Studio model '$Model'"
    $selection = Resolve-Selection -Requested $Model
    Complete-Step "Selected '$($selection.Display)' (load key: '$($selection.LoadKey)')"

    if ($EstimateOnly -or $DryRunImport) {
        Start-Step "Estimating memory requirements for '$($selection.Display)'"
        if (-not $DryRunImport) {
            Invoke-MemoryEstimate -LoadKey $selection.LoadKey -DisplayLabel $selection.Display
        }
        Show-GpuHeadroom
        Complete-Step "Completed estimate/dry-run for '$($selection.Display)'"
        exit 0
    }

    Start-Step "Checking loaded model alias '$ModelAlias'"
    $loaded = Get-LoadedModel -Identifier $ModelAlias
    if ($Reload -or -not (Test-LoadedSelection -Loaded $loaded -Selection $selection)) {
        if ($null -ne $loaded) {
            Write-Notice "Replacing $ModelAlias ($($loaded.Path)): running local inference requests may be interrupted."
            Invoke-External -Command 'lms' -Arguments @('unload', $ModelAlias) | Out-Null
        }
        try { Invoke-MemoryEstimate -LoadKey $selection.LoadKey -DisplayLabel $selection.Display } catch { Write-Debug "Estimate skipped: $_" }
        Write-Notice "Loading $($selection.Display) via '$($selection.LoadKey)' with GPU=$Gpu and context=$ContextLength"
        Invoke-External -Command 'lms' -Arguments @(
            'load', $selection.LoadKey,
            '--identifier', $ModelAlias,
            '--gpu', $Gpu,
            '--context-length', "$ContextLength",
            '-y'
        ) -TimeoutSeconds 600 | Out-Null
    } else {
        Write-Notice "Reusing $ModelAlias; use -Reload to reapply GPU/context settings."
    }
    $loaded = Get-LoadedModel -Identifier $ModelAlias
    if (-not (Test-LoadedSelection -Loaded $loaded -Selection $selection)) {
        $observed = if ($null -eq $loaded) { '<not loaded>' } else { $loaded.Path }
        throw "LM Studio returned '$observed', which doesn't match the requested model/quantization '$($selection.Display)'. Check 'lms ps'."
    }
    $sizeInfo = if ($loaded.Size) { ", size: $($loaded.Size)" } else { '' }
    Complete-Step "Model ready as '$ModelAlias' ($($loaded.Path)$sizeInfo)"
    Show-GpuHeadroom

    Start-Step 'Installing or checking OpenCode'
    if (-not (Get-Command 'opencode' -ErrorAction SilentlyContinue)) {
        Write-Notice 'OpenCode is missing; installing opencode-ai via npm.'
        Invoke-External -Command 'npm.cmd' -Arguments @('install', '-g', 'opencode-ai') -TimeoutSeconds 300 | Out-Null
    }
    $openCodeVersion = (Invoke-External -Command 'opencode' -Arguments @('--version')).Trim()
    Complete-Step "OpenCode available (version $openCodeVersion)"

    Start-Step 'Updating OpenCode LM Studio provider without replacing other settings'
    $changed = Set-OpenCodeConfiguration
    Complete-Step $(if ($changed) { 'OpenCode configuration updated' } else { 'OpenCode configuration already correct' })

    Start-Step 'Registering Codex MCP bridge (preserving other servers)'
    $bridgeChanged = Register-McpBridge
    Complete-Step $(if ($bridgeChanged) { "Codex MCP '$BridgeName' registered/updated" } else { "Codex MCP '$BridgeName' already correct" })

    if ($NoServers) {
        Complete-Step 'Server startup skipped (-NoServers): configuration and model load completed'
        Write-Notice 'LM Studio HTTP and OpenCode HTTP were not started or verified.'
    } else {
        Start-Step 'Starting/verifying LM Studio API on 127.0.0.1:1234'
        $status = Invoke-External -Command 'lms' -Arguments @('server', 'status', '--json', '--quiet') |
            ConvertFrom-Json
        if ($status.running -and [int]$status.port -ne 1234) {
            throw "LM Studio is serving port $($status.port), not 1234. Stop it or restore port 1234."
        }
        if (-not $status.running) {
            Invoke-External -Command 'lms' -Arguments @('server', 'start', '--port', '1234', '--bind', '127.0.0.1') | Out-Null
        }
        $api = Wait-HttpJson -Url "$LmsUrl/v1/models" -MaxSeconds 35
        if ($null -eq $api) { throw 'LM Studio API failed readiness check at /v1/models.' }
        if (@($api.data | ForEach-Object id) -cnotcontains $ModelAlias) {
            throw "LM Studio API is reachable but '$ModelAlias' is not advertised."
        }
        Complete-Step "LM Studio API running, advertising '$ModelAlias'"

        Start-Step 'Starting/verifying OpenCode HTTP server on 127.0.0.1:4096'
        $health = Get-HttpJson "$OpenCodeUrl/global/health"
        if ($null -eq $health) {
            $folder = Split-Path -Parent $OpenCodeConfig
            New-Item -ItemType Directory -Path $folder -Force | Out-Null
            $stdout = Join-Path $folder 'serve.stdout.log'
            $stderr = Join-Path $folder 'serve.stderr.log'
            # Start through cmd.exe so npm's Windows .cmd shim is resolved.
            Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c',
                'opencode serve --hostname 127.0.0.1 --port 4096') -WorkingDirectory $HOME `
                -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden | Out-Null
            $health = Wait-HttpJson -Url "$OpenCodeUrl/global/health" -MaxSeconds 40
            if ($null -eq $health) {
                throw "OpenCode failed to start. Check logs: $stdout and $stderr"
            }
        }
        if (-not $health.healthy) { throw 'OpenCode returned unhealthy status.' }
        Test-OpenCodeModel
        Complete-Step "OpenCode healthy (v$($health.version)); lmstudio/$ModelAlias available"
    }
    Start-Step 'Verifying Codex MCP registration'
    $entries = @(Invoke-External -Command 'codex' -Arguments @('mcp', 'list', '--json') |
        ConvertFrom-Json)
    if (@($entries | Where-Object { $_.name -eq $BridgeName -and $_.enabled }).Count -ne 1) {
        throw "Codex MCP '$BridgeName' is missing or disabled."
    }
    Complete-Step "Codex MCP '$BridgeName' enabled (launched by Codex on demand)"

    Write-Host ''
    if ($NoServers) {
        Write-Host "✓ CONFIGURED: Codex -> $BridgeName -> OpenCode -> LM Studio/$ModelAlias ($($selection.Display))" -ForegroundColor Green
        Write-Notice 'Services were intentionally not started (-NoServers).'
    } else {
        Write-Host "✓ READY: Codex -> $BridgeName -> OpenCode -> LM Studio/$ModelAlias ($($selection.Display))" -ForegroundColor Green
    }
    Write-Notice 'GUI settings reminder: Flash Attention=On, KV Offload=GPU, K/V=F16 (Q8_0 for 64K+), Thinking=On (xhigh, Preserve Thinking=On).'
    Write-Notice 'Open a new Codex session if the MCP tool list has not refreshed.'
} catch {
    $description = if ($script:CurrentStep) { $script:CurrentStep } else { 'Setup' }
    Report-Failure "$description failed: $($_.Exception.Message)"
    Write-Debug ($_ | Out-String)
    exit 1
}
