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
    [Parameter(Mandatory, Position = 0)]
    [Alias('o')]
    [ValidateSet('list', 'status', 'plan', 'quickstart', 'wizard', 'templates', 'template-info', 'create', 'start', 'stop', 'connect', 'start-connect', 'boot-diagnostics', 'guest-status', 'guest-copy', 'guest-bootstrap', 'guest-verify', 'checkpoint', 'checkpoints')]
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
    [string]$WheelhousePath,
    [string]$VenvPath = 'C:\venvs\dev'
)

$ErrorActionPreference = 'Stop'

try {
    if ($Json) {
        Import-Module (Join-Path $PSScriptRoot 'vm_lab.psd1') -Force -WarningAction SilentlyContinue -Verbose:$false -InformationAction SilentlyContinue
    } else {
        Import-Module (Join-Path $PSScriptRoot 'vm_lab.psd1') -Force
    }
    $output = Invoke-VmLab @PSBoundParameters
    if ($null -ne $output) {
        $output
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
