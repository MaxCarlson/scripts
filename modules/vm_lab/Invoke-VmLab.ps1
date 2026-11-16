#Requires -Version 7.0
<#
.SYNOPSIS
    CLI entry point for the vm_lab disposable Hyper-V lab manager.
.DESCRIPTION
    Imports the local vm_lab module and invokes Invoke-VmLab with short and long flags.
    Mutating operations (create, start, stop, checkpoint) are dry-run by default and require -Apply (-a).
.PARAMETER Operation
    Operation to perform: list, status, plan, create, start, stop, checkpoint, checkpoints.
.PARAMETER Name
    Target VM name.
.PARAMETER ConfigPath
    Path to a JSON VM configuration file.
.PARAMETER TemplateName
    Built-in template name (default: windows11-h4).
.PARAMETER IsoPath
    Installation ISO path override.
.PARAMETER VmRoot
    Target VM storage root directory override.
.PARAMETER SwitchName
    Existing Hyper-V virtual switch name override.
.PARAMETER CheckpointName
    Checkpoint name for the checkpoint operation.
.PARAMETER Apply
    Authorize mutating Hyper-V operations.
.PARAMETER Json
    Emit a single valid JSON document on stdout.
.PARAMETER OwnedOnly
    Filter list results to vm_lab-owned VMs only.
.PARAMETER MinReserveBytes
    Minimum free host RAM reserve required before start (default: 4GB).
.PARAMETER ShutdownTimeoutSeconds
    Bounded wait timeout in seconds for graceful guest shutdown (default: 30).
.PARAMETER ManifestRoot
    Override directory for vm_lab ownership manifests.
.EXAMPLE
    ./Invoke-VmLab.ps1 -Operation list -OwnedOnly -Json
.EXAMPLE
    ./Invoke-VmLab.ps1 -o plan -t windows11-h4 -n Lab-Test-01 -r "C:\Lab\Lab Test 01" -j
.EXAMPLE
    ./Invoke-VmLab.ps1 -o start -n Lab-Test-01 -Apply
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Position = 0)]
    [Alias('o')]
    [ValidateSet('list', 'status', 'plan', 'quickstart', 'wizard', 'templates', 'template-info', 'create', 'start', 'stop', 'connect', 'start-connect', 'boot-diagnostics', 'guest-status', 'guest-copy', 'guest-bootstrap', 'guest-verify', 'guest-command-plan', 'guest-exec', 'artifact-plan', 'artifact-deploy', 'evidence-plan', 'evidence-collect', 'lifecycle-transaction', 'workflow-plan', 'workflow-status', 'workflow-apply', 'workflow-resume', 'workflow-doctor', 'checkpoint', 'baseline', 'checkpoints', 'recovery-plan', 'doctor', 'unattend-xml')]
    [string]$Operation,

    [Alias('n')][string]$Name,
    [Alias('c')][string]$ConfigPath,
    [Alias('t')][string]$TemplateName = 'windows11-h4',
    [Alias('i')][string]$IsoPath,
    [Alias('r')][string]$VmRoot,
    [Alias('s')][string]$SwitchName,
    [Alias('m')][string]$CheckpointName,
    [Alias('a')][switch]$Apply,
    [Alias('j')][switch]$Json,
    [Alias('oo')][switch]$OwnedOnly,
    [Alias('rb')][int64]$MinReserveBytes = 4GB,
    [Alias('st')][int]$ShutdownTimeoutSeconds = 30,
    [Alias('mr')][string]$ManifestRoot,
    [switch]$Start,
    [switch]$Connect,
    [pscredential]$Credential,
    [switch]$PromptCredential,
    [string]$SourcePath,
    [string]$DestinationPath,
    [ValidateSet('ToGuest', 'FromGuest')][string]$Direction = 'ToGuest',
    [switch]$Overwrite,
    [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$GuestProfile = 'windows-minimal',
    [string]$InstallerPath,
    [string]$ExpectedInstallerSha256,
    [string]$PythonPath,
    [string]$WheelhousePath,
    [string]$RequirementsPath,
    [string[]]$Packages,
    [string]$VenvPath = 'C:\venvs\dev',
    [switch]$Offline,
    [switch]$AllowOnlineInstall,
    [switch]$RequireGuestVerified,
    [int]$MaxConnectAttempts = 1,
    [string]$OutputPath,
    [string]$Locale = 'en-US',
    [string]$KeyboardLayout = 'en-US',
    [string]$ImageEdition,
    [string]$ExecutablePath,
    [string[]]$ArgumentList = @(),
    [string]$WorkingDirectory = 'C:\Windows\Temp',
    [string]$ExpectedSha256,
    [Alias('am')][string]$ArtifactManifestPath,
    [string[]]$GuestRoots,
    [Alias('er')][string]$EvidenceRoot,
    [Alias('op')][string]$OperationId,
    [switch]$AuthorizeHostMutation,
    [switch]$AuthorizeVmLifecycle,
    [switch]$AuthorizeGuestMutation,
    [switch]$AuthorizeGuestExec,
    [switch]$RestartAfter,
    [Alias('f')][string]$WorkflowPath,
    [Alias('or')][string]$OperationRoot = 'C:\VM-Lab-Operations',
    [switch]$AuthorizeElevation,
    [Alias('h')][switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help -or [string]::IsNullOrWhiteSpace($Operation)) {
    Get-Help $PSCommandPath -Detailed
    if ($Help) { exit 0 }
    exit 1
}

try {
    if (-not (Get-Module -Name vm_lab)) {
        if ($Json) {
            Import-Module (Join-Path $PSScriptRoot 'vm_lab.psd1') -Force -WarningAction SilentlyContinue -Verbose:$false -InformationAction SilentlyContinue
        } else {
            Import-Module (Join-Path $PSScriptRoot 'vm_lab.psd1') -Force
        }
    }
    $output = Invoke-VmLab @PSBoundParameters
    if ($null -ne $output) {
        $output
    }
    if ($Operation -eq 'guest-verify' -and $null -ne $output) {
        $verifyStatus = if ($Json) {
            ($output | ConvertFrom-Json).status
        } else {
            $output.status
        }
        if ($verifyStatus -ne 'verified') {
            exit 1
        }
    }
    exit 0
} catch {
    $msg = $_.Exception.Message
    if ($Json) {
        $errObj = [pscustomobject]@{
            status    = 'error'
            operation = $Operation
            error     = $msg
        }
        [Console]::Error.WriteLine(($errObj | ConvertTo-Json -Compress -Depth 4))
    } else {
        [Console]::Error.WriteLine("vm_lab error ($Operation): $msg")
    }
    exit 1
}
