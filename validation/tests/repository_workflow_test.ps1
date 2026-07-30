[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$RepoRoot,
    [Parameter(Mandatory)] [string]$PythonExecutable,
    [Parameter(Mandatory)] [string]$ResultPath,
    [Parameter(Mandatory)] [string]$TempRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$Repo = [System.IO.Path]::GetFullPath($RepoRoot)
$Python = [System.IO.Path]::GetFullPath($PythonExecutable)
$ResultFile = [System.IO.Path]::GetFullPath($ResultPath)
$Temp = [System.IO.Path]::GetFullPath($TempRoot)
$Checks = [System.Collections.Generic.List[hashtable]]::new()

function Test-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-Check([string]$Id, [string]$Name, [string[]]$ItemIds, [scriptblock]$Body) {
    $Timer = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $Body
        $Status = 'passed'
        $Message = ''
    }
    catch {
        $Status = 'failed'
        $Message = $_.Exception.Message
    }
    finally {
        $Timer.Stop()
        $Checks.Add(@{
            id = $Id
            name = $Name
            status = $Status
            duration_seconds = [Math]::Round($Timer.Elapsed.TotalSeconds, 6)
            message = $Message
            item_ids = @($ItemIds)
        })
    }
}

function Test-Text([string]$Path, [string[]]$Patterns) {
    Test-Condition (Test-Path -LiteralPath $Path -PathType Leaf) "Missing file: $Path"
    $Text = Get-Content -LiteralPath $Path -Raw
    foreach ($Pattern in $Patterns) {
        Test-Condition $Text.Contains($Pattern) "Expected '$Pattern' in $Path"
    }
}

$Plan = Join-Path $Repo 'docs/plans/20260729-2000_unified-hybrid-workflow/00_implementation-plan.md'
$Bridge = Join-Path $Repo 'validation/Invoke-DevelopmentLedger.ps1'
$RootManifestPath = Join-Path $Repo 'validation-targets.json'
$Manifest = Join-Path $Temp 'validation-targets.json'
$Transcript = Join-Path $Temp 'LATEST.txt'
$Evidence = Join-Path $Temp 'evidence.json'
$Ledger = Join-Path $Temp 'ledger'
$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source

New-Item -ItemType Directory -Path $Temp -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $ResultFile) -Force | Out-Null

try {
    Invoke-Check 'powershell:repository-workflow::policy' 'Branch and ledger policy is discoverable' @('AC-S1-001') {
        Test-Text (Join-Path $Repo 'docs/agent/BRANCH_INTEGRATION_WORKFLOW.md') @('agent/unified', 'agent/<work>', 'Integration-Branch Loop')
        Test-Text (Join-Path $Repo 'REPO_LLM_INSTRUCTIONS.md') @('## Branch Topology', '## Development Ledger')
        Test-Text (Join-Path $Repo 'AGENTS.md') @('ledger/PROGRESS.md', 'BRANCH_INTEGRATION_WORKFLOW.md')
    }

    Invoke-Check 'powershell:repository-workflow::plan' 'Unified workflow plan is valid' @('AC-S1-001', 'AC-S2-001', 'AC-S2-002') {
        $Output = & $Python -m development_ledger validate-plan -p $Plan 2>&1
        Test-Condition ($LASTEXITCODE -eq 0) "Plan validation failed: $($Output -join ' ')"
        Test-Condition (($Output -join "`n") -match 'VALID: unified-hybrid-workflow') "Unexpected plan output: $($Output -join ' ')"
    }

    Invoke-Check 'powershell:repository-workflow::native-dispatcher' 'Root dispatcher owns file discovery and ledger ordering' @('AC-S2-001', 'AC-S2-002') {
        Test-Text (Join-Path $Repo 'Invoke-Tests.ps1') @('ValidationDispatcher.psm1', 'Invoke-RepositoryValidation')
        Test-Text (Join-Path $Repo 'validation/ValidationCommon.psm1') @('Resolve-ValidationFileTargetRule', 'Resolve-ValidationCommandSpec')
        Test-Text (Join-Path $Repo 'validation/ValidationTarget.psm1') @('Invoke-ValidationLedgerPhase', 'Invoke-ValidationPowerShellGroups')
        $RootManifest = Get-Content -LiteralPath $RootManifestPath -Raw | ConvertFrom-Json -AsHashtable
        $Target = $RootManifest.targets['repository-workflow']
        Test-Condition $Target.Contains('ledger') 'repository-workflow does not define ledger metadata.'
        Test-Condition $Target.Contains('temp_root') 'repository-workflow does not define an external temp_root.'
        $ExplicitLedgerCommands = @($Target.commands | Where-Object { [string]$_['name'] -match '^Record .* ledger' })
        Test-Condition ($ExplicitLedgerCommands.Count -eq 0) 'Ledger recording still appears as an explicit command.'
        $FileTargetCommands = @($Target.commands | Where-Object { $_.Contains('file_targets') })
        Test-Condition ($FileTargetCommands.Count -eq 1) "Expected one native file_targets command; found $($FileTargetCommands.Count)."
    }

    @{
        schema_version = 1
        source = 'powershell'
        suite = 'repository-workflow'
        tests = @(@{
            id = 'powershell:repository-workflow::bridge-evidence'
            name = 'Synthetic bridge evidence'
            status = 'passed'
            item_ids = @('AC-S1-002')
        })
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Evidence -Encoding utf8
    Set-Content -LiteralPath $Transcript -Value 'Synthetic transcript.' -Encoding utf8
    @{
        targets = @{
            synthetic = @{
                ledger = @{
                    enabled = $true
                    required = $true
                    active_plan = '{repo_root}/docs/plans/20260729-2000_unified-hybrid-workflow/00_implementation-plan.md'
                    output_directory = '{temp_root}/ledger'
                    script_result_outputs = @('{temp_root}/evidence.json')
                    transcript_outputs = @('{report_path}')
                    actor = 'remote_llm'
                    mode = 'hybrid'
                }
            }
        }
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Manifest -Encoding utf8

    Invoke-Check 'powershell:repository-workflow::bridge' 'Ledger bridge previews and writes projections' @('AC-S1-002', 'AC-S2-002') {
        Remove-Item -LiteralPath $Ledger -Recurse -Force -ErrorAction SilentlyContinue
        $Common = @('-NoLogo', '-NoProfile', '-File', $Bridge, '-ManifestPath', $Manifest, '-TargetName', 'synthetic', '-RepoRoot', $Repo, '-TargetRoot', $Temp, '-TempRoot', $Temp, '-ReportPath', $Transcript, '-PythonExecutable', $Python)
        $Preview = & $Pwsh @Common 2>&1
        Test-Condition ($LASTEXITCODE -eq 0) "Preview failed: $($Preview -join ' ')"
        Test-Condition (-not (Test-Path -LiteralPath (Join-Path $Ledger 'RUNS.jsonl'))) 'Preview wrote RUNS.jsonl.'
        $WriteOutput = & $Pwsh @Common -Write '-Confirm:$false' 2>&1
        Test-Condition ($LASTEXITCODE -eq 0) "Write failed: $($WriteOutput -join ' ')"
        foreach ($Name in @('RUNS.jsonl', 'LATEST.json', 'PROGRESS.md', 'TRACEABILITY.md', 'MANUAL_CHECKS.md')) {
            Test-Condition (Test-Path -LiteralPath (Join-Path $Ledger $Name) -PathType Leaf) "Missing projection: $Name"
        }
    }

    Invoke-Check 'powershell:repository-workflow::missing-evidence' 'Required evidence fails clearly' @('AC-S1-002', 'AC-S2-002') {
        $Data = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json -AsHashtable
        $Data.targets.synthetic.ledger.script_result_outputs = @('{temp_root}/missing.json')
        $Data | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Manifest -Encoding utf8
        $Output = & $Pwsh -NoLogo -NoProfile -File $Bridge -ManifestPath $Manifest -TargetName synthetic -RepoRoot $Repo -TargetRoot $Temp -TempRoot $Temp -ReportPath $Transcript -PythonExecutable $Python 2>&1
        Test-Condition ($LASTEXITCODE -ne 0) 'Missing evidence unexpectedly succeeded.'
        Test-Condition (($Output -join "`n") -match 'Required ledger evidence is missing') "Unexpected missing-evidence output: $($Output -join ' ')"
    }
}
finally {
    @{ schema_version = 1; source = 'powershell'; suite = 'repository-workflow'; tests = @($Checks) } |
        ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $ResultFile -Encoding utf8
}

$Failures = @($Checks | Where-Object status -in @('failed', 'error'))
$Checks | ForEach-Object { Write-Output ("{0,-7} {1} - {2}" -f $_.status.ToUpperInvariant(), $_.id, $_.name) }
if ($Failures.Count -gt 0) {
    Write-Error "$($Failures.Count) repository-workflow check(s) failed."
    exit 1
}
Write-Output "Repository-workflow checks passed: $($Checks.Count)."
exit 0
