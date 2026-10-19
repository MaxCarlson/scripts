<# Module-owned replacement hook for dotfiles setup migration. #>
[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('generic', 'local')][string]$Mode = '',
    [ValidateSet('codex', 'agy')][string[]]$Clients = @('codex', 'agy')
)
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$receiptPath = Join-Path $HOME '.local\share\local-agent\receipt.json'
if ([string]::IsNullOrWhiteSpace($Mode)) {
    $Mode = 'generic'
    if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
        $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
        $selectedModes = @($Clients | ForEach-Object {
            $recordedMode = if ($receipt.modes) { $receipt.modes.$_ } else { $null }
            if ($recordedMode) { $recordedMode } else { 'generic' }
        } | Select-Object -Unique)
        if ($selectedModes.Count -ne 1 -or $selectedModes[0] -notin @('generic', 'local')) {
            throw 'Mixed or invalid client modes: select clients or pass an explicit -Mode.'
        }
        $Mode = $selectedModes[0]
    }
}

$localAgentCmd = Get-Command local-agent -ErrorAction SilentlyContinue
if (-not $localAgentCmd) { $localAgentCmd = Get-Command local_agent -ErrorAction SilentlyContinue }
$repoWrapper = Join-Path $repoRoot 'bin\local_agent.cmd'
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

function Invoke-LocalAgent {
    param([string[]]$Arguments)
    if ($localAgentCmd) {
        & $localAgentCmd @Arguments
    } elseif (Test-Path -LiteralPath $repoWrapper -PathType Leaf) {
        & $repoWrapper @Arguments
    } elseif (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        & $venvPython -m local_agent_bridge.commands @Arguments
    } else {
        throw 'local_agent is missing. Install scripts/modules/local_agent_bridge and refresh the scripts wrappers.'
    }
}

if ($WhatIfPreference -or $env:DOTFILES_DRY_RUN -eq '1') {
    Invoke-LocalAgent -Arguments (@('setup', 'plan', '-c') + $Clients + @('-m', $Mode))
} elseif ($PSCmdlet.ShouldProcess(($Clients -join ', '), "Apply $Mode agent setup")) {
    Invoke-LocalAgent -Arguments (@('setup', 'apply', '-c') + $Clients + @('-m', $Mode))
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }
