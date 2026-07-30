<#
.SYNOPSIS
Records one validation target through the repository development ledger.

.DESCRIPTION
Reads the selected target's `ledger` object from validation-targets.json,
resolves configured evidence paths, and invokes the dispatcher-safe
`development_ledger.dispatcher_record` adapter.

The script preserves dry-run behavior unless -Write is supplied. The adapter
maps a successfully recorded failed-test event to exit code zero because the
root validation dispatcher already owns the original validation result.
Plan, evidence, Git, duplicate-event, and write failures remain nonzero.

.PARAMETER ManifestPath
Path to validation-targets.json.

.PARAMETER TargetName
Validation target whose ledger configuration should be used.

.PARAMETER RepoRoot
Repository root used for Git provenance and {repo_root} token expansion.

.PARAMETER TargetRoot
Validation target working directory used for relative path resolution and
{target_root} token expansion.

.PARAMETER TempRoot
Current isolated validation directory used for {temp_root} token expansion.

.PARAMETER ReportPath
Current raw validation transcript used for {report_path} token expansion.

.PARAMETER PythonExecutable
Python executable containing the installed development_ledger package.

.PARAMETER Write
Append the immutable event and regenerate ledger projections. Without this
switch, preview the normalized event without modifying ledger files.

.EXAMPLE
./validation/Invoke-DevelopmentLedger.ps1 `
    -ManifestPath ./validation-targets.json `
    -TargetName repository-workflow `
    -RepoRoot . `
    -TargetRoot . `
    -TempRoot ./.pytest_tmp_root/validation-example `
    -ReportPath ./docs/test-results/repository-workflow/LATEST.txt `
    -PythonExecutable ./.venv/Scripts/python.exe `
    -Write
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory)]
    [string]$ManifestPath,

    [Parameter(Mandatory)]
    [string]$TargetName,

    [Parameter(Mandatory)]
    [string]$RepoRoot,

    [Parameter(Mandatory)]
    [string]$TargetRoot,

    [Parameter(Mandatory)]
    [string]$TempRoot,

    [Parameter(Mandatory)]
    [string]$ReportPath,

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$Write
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Get-ManifestItems {
    [CmdletBinding()]
    [OutputType([object[]])]
    param(
        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$Container,

        [Parameter(Mandatory)]
        [string]$Name
    )

    if (-not $Container.Contains($Name) -or $null -eq $Container[$Name]) {
        return @()
    }

    return @($Container[$Name])
}

function Convert-TokenText {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Text,

        [Parameter(Mandatory)]
        [hashtable]$Tokens
    )

    $Result = $Text
    foreach ($Token in $Tokens.GetEnumerator()) {
        $Result = $Result.Replace([string]$Token.Key, [string]$Token.Value)
    }

    return $Result
}

function Resolve-ConfiguredPath {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$ConfiguredPath,

        [Parameter(Mandatory)]
        [string]$DefaultRoot,

        [Parameter(Mandatory)]
        [hashtable]$Tokens
    )

    $ResolvedText = Convert-TokenText -Text $ConfiguredPath -Tokens $Tokens
    if ([string]::IsNullOrWhiteSpace($ResolvedText)) {
        throw 'Ledger evidence paths cannot be empty.'
    }

    if ([System.IO.Path]::IsPathRooted($ResolvedText)) {
        return [System.IO.Path]::GetFullPath($ResolvedText)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $DefaultRoot $ResolvedText))
}

function Add-EvidenceArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.Collections.Generic.List[string]]$Arguments,

        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$LedgerSpec,

        [Parameter(Mandatory)]
        [string]$FieldName,

        [Parameter(Mandatory)]
        [string]$ArgumentName,

        [Parameter(Mandatory)]
        [string]$DefaultRoot,

        [Parameter(Mandatory)]
        [hashtable]$Tokens,

        [Parameter(Mandatory)]
        [bool]$Required
    )

    foreach ($ConfiguredPath in (Get-ManifestItems -Container $LedgerSpec -Name $FieldName)) {
        $ResolvedPath = Resolve-ConfiguredPath `
            -ConfiguredPath ([string]$ConfiguredPath) `
            -DefaultRoot $DefaultRoot `
            -Tokens $Tokens

        if (-not (Test-Path -LiteralPath $ResolvedPath -PathType Leaf)) {
            if ($Required) {
                throw "Required ledger evidence is missing for '$FieldName': $ResolvedPath