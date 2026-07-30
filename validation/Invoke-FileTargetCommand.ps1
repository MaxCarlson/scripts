[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ManifestPath,

    [Parameter(Mandatory)]
    [string]$TargetName,

    [Parameter(Mandatory)]
    [string]$CommandName,

    [Parameter()]
    [string]$PythonExecutable
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

function ConvertTo-NormalizedExtension {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$Extension
    )

    $Value = $Extension.Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw 'File-target extensions cannot be empty.'
    }

    if (-not $Value.StartsWith('.')) {
        $Value = ".${Value}"
    }

    return $Value
}

function Get-RelativeDepth {
    [CmdletBinding()]
    [OutputType([int])]
    param(
        [Parameter(Mandatory)]
        [string]$Root,

        [Parameter(Mandatory)]
        [string]$Path
    )

    $RelativePath = [System.IO.Path]::GetRelativePath($Root, $Path)
    if ($RelativePath -eq '.') {
        return 0
    }

    return @(
        $RelativePath.Split(
            [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar),
            [System.StringSplitOptions]::RemoveEmptyEntries
        )
    ).Count
}

function Resolve-FileTargetRule {
    [CmdletBinding()]
    [OutputType([string[]])]
    param(
        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$Rule,

        [Parameter(Mandatory)]
        [string]$TargetRoot,

        [Parameter(Mandatory)]
        [hashtable]$Tokens
    )

    if (-not $Rule.Contains('path')) {
        throw "A file-target rule for '$CommandName' does not define 'path'."
    }

    $RelativeRoot = Convert-TokenText -Text ([string]$Rule['path']) -Tokens $Tokens
    $SearchRoot = if ([System.IO.Path]::IsPathRooted($RelativeRoot)) {
        [System.IO.Path]::GetFullPath($RelativeRoot)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $TargetRoot $RelativeRoot))
    }

    if (-not (Test-Path -LiteralPath $SearchRoot)) {
        throw "File-target path does not exist: $SearchRoot"
    }

    $MaxDepth = 1
    if ($Rule.Contains('max_depth')) {
        $MaxDepth = [int]$Rule['max_depth']
    }
    if ($MaxDepth -lt 0) {
        throw "File-target max_depth must be zero or greater: $RelativeRoot"
    }

    $ExtensionValues = @()
    if ($Rule.Contains('extensions')) {
        $ExtensionValues = @(Get-ManifestItems -Container $Rule -Name 'extensions')
    }
    elseif ($Rule.Contains('extension')) {
        $ExtensionValues = @($Rule['extension'])
    }

    if ($ExtensionValues.Count -eq 0) {
        throw "File-target rule must define 'extension' or 'extensions': $RelativeRoot"
    }

    $Extensions = @(
        $ExtensionValues |
            ForEach-Object { ConvertTo-NormalizedExtension -Extension ([string]$_) } |
            Sort-Object -Unique
    )

    $Candidates = if (Test-Path -LiteralPath $SearchRoot -PathType Leaf) {
        @(Get-Item -LiteralPath $SearchRoot -Force)
    }
    else {
        @(Get-ChildItem -LiteralPath $SearchRoot -File -Force -Recurse -ErrorAction Stop)
    }

    $Matches = @(
        foreach ($Candidate in $Candidates) {
            $Depth = if ($Candidate.FullName -eq $SearchRoot) {
                0
            }
            else {
                Get-RelativeDepth -Root $SearchRoot -Path $Candidate.FullName
            }

            if ($Depth -gt $MaxDepth) {
                continue
            }

            if ($Extensions -notcontains $Candidate.Extension.ToLowerInvariant()) {
                continue
            }

            [System.IO.Path]::GetRelativePath($TargetRoot, $Candidate.FullName)
        }
    )

    if ($Matches.Count -eq 0) {
        throw (
            "File-target rule matched no files: path='{0}', max_depth={1}, extensions={2}" -f
            $RelativeRoot,
            $MaxDepth,
            ($Extensions -join ',')
        )
    }

    return @($Matches | Sort-Object -Unique)
}

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Validation manifest not found: $ManifestPath"
}

$ResolvedManifestPath = (Resolve-Path -LiteralPath $ManifestPath).Path
$RepoRoot = Split-Path -Parent $ResolvedManifestPath
$Manifest = Get-Content -LiteralPath $ResolvedManifestPath -Raw | ConvertFrom-Json -AsHashtable

if (-not $Manifest.Contains('targets') -or -not $Manifest['targets'].Contains($TargetName)) {
    throw "Validation target '$TargetName' was not found in $ResolvedManifestPath"
}

$TargetSpec = $Manifest['targets'][$TargetName]
if (-not $TargetSpec.Contains('working_directory')) {
    throw "Validation target '$TargetName' does not define 'working_directory'."
}

$TargetRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $RepoRoot ([string]$TargetSpec['working_directory']))
)
if (-not (Test-Path -LiteralPath $TargetRoot -PathType Container)) {
    throw "Validation target working directory does not exist: $TargetRoot"
}

$MatchingCommands = @(
    Get-ManifestItems -Container $TargetSpec -Name 'commands' |
        Where-Object { [string]$_['name'] -eq $CommandName }
)
if ($MatchingCommands.Count -ne 1) {
    throw "Expected exactly one command named '$CommandName' for target '$TargetName'; found $($MatchingCommands.Count)."
}

$CommandSpec = $MatchingCommands[0]
if (-not $CommandSpec.Contains('file_command')) {
    throw "Validation command '$CommandName' does not define 'file_command'."
}

$FileCommand = $CommandSpec['file_command']
if (-not $FileCommand.Contains('executable')) {
    throw "Validation command '$CommandName' file_command does not define 'executable'."
}

$ResolvedPython = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    'python'
}
else {
    [System.IO.Path]::GetFullPath($PythonExecutable)
}

$Tokens = @{
    '{repo_root}' = $RepoRoot
    '{target_root}' = $TargetRoot
    '{python}' = $ResolvedPython
}

$Executable = Convert-TokenText -Text ([string]$FileCommand['executable']) -Tokens $Tokens
$BaseArguments = @(
    foreach ($Argument in (Get-ManifestItems -Container $FileCommand -Name 'arguments')) {
        Convert-TokenText -Text ([string]$Argument) -Tokens $Tokens
    }
)

$FileTargets = @(Get-ManifestItems -Container $CommandSpec -Name 'file_targets')
if ($FileTargets.Count -eq 0) {
    throw "Validation command '$CommandName' does not define any file_targets."
}

$DiscoveredFiles = @(
    foreach ($Rule in $FileTargets) {
        Resolve-FileTargetRule -Rule $Rule -TargetRoot $TargetRoot -Tokens $Tokens
    }
) | Sort-Object -Unique

Write-Output "Discovered $($DiscoveredFiles.Count) file(s) for '$CommandName':"
foreach ($Path in $DiscoveredFiles) {
    Write-Output "  $Path"
}

Push-Location -LiteralPath $TargetRoot
try {
    & $Executable @BaseArguments @DiscoveredFiles
    $ExitCode = $LASTEXITCODE
    if ($null -eq $ExitCode) {
        $ExitCode = 0
    }
}
finally {
    Pop-Location
}

exit $ExitCode
