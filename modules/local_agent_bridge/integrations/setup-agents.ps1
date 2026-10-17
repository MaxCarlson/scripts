<# Module-owned replacement hook for a later dotfiles setup migration. #>
[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('generic', 'local')][string]$Mode = 'generic',
    [ValidateSet('codex', 'agy')][string[]]$Clients = @('codex', 'agy')
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command local_agent -ErrorAction SilentlyContinue)) {
    throw 'local_agent is missing. Install scripts/modules/local_agent_bridge and refresh the scripts wrappers.'
}
if ($WhatIfPreference) {
    & local_agent setup plan -c $Clients -m $Mode
} elseif ($PSCmdlet.ShouldProcess(($Clients -join ', '), "Apply $Mode agent setup")) {
    & local_agent setup apply -c $Clients -m $Mode
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }
