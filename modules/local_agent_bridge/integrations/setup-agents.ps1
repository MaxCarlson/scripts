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
        try {
            $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
            if ($receipt.modes -and ($receipt.modes.PSObject.Properties.Value -contains 'local')) {
                $Mode = 'local'
            }
        } catch {
            $Mode = 'generic'
        }
    }
}

$localAgentCmd = Get-Command local_agent -ErrorAction SilentlyContinue
$repoWrapper = Join-Path $repoRoot 'bin\local_agent.cmd'
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

function Invoke-LocalAgent {
    param([string[]]$Arguments)
    if ($localAgentCmd) {
        & $localAgentCmd.Source @Arguments
    } elseif (Test-Path -LiteralPath $repoWrapper -PathType Leaf) {
        & $repoWrapper @Arguments
    } elseif (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        & $venvPython -m local_agent_bridge.commands @Arguments
    } else {
        throw 'local_agent is missing. Install scripts/modules/local_agent_bridge and refresh the scripts wrappers.'
    }
}

if ($WhatIfPreference) {
    Invoke-LocalAgent -Arguments (@('setup', 'plan', '-c') + $Clients + @('-m', $Mode))
} elseif ($PSCmdlet.ShouldProcess(($Clients -join ', '), "Apply $Mode agent setup")) {
    Invoke-LocalAgent -Arguments (@('setup', 'apply', '-c') + $Clients + @('-m', $Mode))
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }
