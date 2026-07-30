Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ValidationManifestItems {
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

function Convert-ValidationTokenText {
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

function Resolve-ValidationPythonExecutable {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$RepoRoot
    )

    $Candidates = @(
        (Join-Path $RepoRoot '.venv\Scripts\python.exe'),
        (Join-Path $RepoRoot '.venv\bin\python'),
        'python'
    )
    foreach ($Candidate in $Candidates) {
        if ([System.IO.Path]::IsPathRooted($Candidate)) {
            if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                return [System.IO.Path]::GetFullPath($Candidate)
            }
            continue
        }

        $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
        if ($Command) {
            return $Command.Source
        }
    }

    throw 'Unable to resolve a Python executable. Create the repository virtual environment or install Python.'
}

function ConvertTo-ValidationExtension {
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

function Get-ValidationRelativeDepth {
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

function Resolve-ValidationFileTargetRule {
    [CmdletBinding()]
    [OutputType([string[]])]
    param(
        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$Rule,

        [Parameter(Mandatory)]
        [string]$TargetRoot,

        [Parameter(Mandatory)]
        [hashtable]$Tokens,

        [Parameter(Mandatory)]
        [string]$CommandName
    )

    if (-not $Rule.Contains('path')) {
        throw "A file-target rule for '$CommandName' does not define 'path'."
    }
    $RelativeRoot = Convert-ValidationTokenText -Text ([string]$Rule['path']) -Tokens $Tokens
    $SearchRoot = if ([System.IO.Path]::IsPathRooted($RelativeRoot)) {
        [System.IO.Path]::GetFullPath($RelativeRoot)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $TargetRoot $RelativeRoot))
    }
    if (-not (Test-Path -LiteralPath $SearchRoot)) {
        throw "File-target path does not exist: $SearchRoot"
    }

    $MaxDepth = if ($Rule.Contains('max_depth')) { [int]$Rule['max_depth'] } else { 1 }
    if ($MaxDepth -lt 0) {
        throw "File-target max_depth must be zero or greater: $RelativeRoot"
    }
    $ExtensionValues = if ($Rule.Contains('extensions')) {
        @(Get-ValidationManifestItems -Container $Rule -Name 'extensions')
    }
    elseif ($Rule.Contains('extension')) {
        @($Rule['extension'])
    }
    else {
        @()
    }
    if ($ExtensionValues.Count -eq 0) {
        throw "File-target rule must define 'extension' or 'extensions': $RelativeRoot"
    }
    $Extensions = @(
        $ExtensionValues |
            ForEach-Object { ConvertTo-ValidationExtension -Extension ([string]$_) } |
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
                Get-ValidationRelativeDepth -Root $SearchRoot -Path $Candidate.FullName
            }
            if ($Depth -le $MaxDepth -and $Extensions -contains $Candidate.Extension.ToLowerInvariant()) {
                [System.IO.Path]::GetRelativePath($TargetRoot, $Candidate.FullName)
            }
        }
    ) | Sort-Object -Unique
    if ($Matches.Count -eq 0) {
        throw "File-target rule matched no files: path='$RelativeRoot', max_depth=$MaxDepth, extensions=$($Extensions -join ',')"
    }
    return $Matches
}

function Resolve-ValidationCommandSpec {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$CommandSpec,

        [Parameter(Mandatory)]
        [string]$TargetRoot,

        [Parameter(Mandatory)]
        [hashtable]$Tokens
    )

    if (-not $CommandSpec.Contains('name')) {
        throw "Validation command is missing 'name'."
    }
    $Name = Convert-ValidationTokenText -Text ([string]$CommandSpec['name']) -Tokens $Tokens
    $EffectiveSpec = $CommandSpec
    $DiscoveredFiles = @()
    if ($CommandSpec.Contains('file_targets')) {
        if (-not $CommandSpec.Contains('file_command')) {
            throw "File-target validation command '$Name' is missing 'file_command'."
        }
        $EffectiveSpec = $CommandSpec['file_command']
        $DiscoveredFiles = @(
            foreach ($Rule in (Get-ValidationManifestItems -Container $CommandSpec -Name 'file_targets')) {
                Resolve-ValidationFileTargetRule -Rule $Rule -TargetRoot $TargetRoot -Tokens $Tokens -CommandName $Name
            }
        ) | Sort-Object -Unique
    }
    if (-not $EffectiveSpec.Contains('executable')) {
        throw "Validation command '$Name' is missing 'executable'."
    }
    $Arguments = @(
        foreach ($Argument in (Get-ValidationManifestItems -Container $EffectiveSpec -Name 'arguments')) {
            Convert-ValidationTokenText -Text ([string]$Argument -as [string]) -Tokens $Tokens
        }
    ) + $DiscoveredFiles
    return @{
        Name = $Name
        Executable = Convert-ValidationTokenText -Text ([string]$EffectiveSpec['executable']) -Tokens $Tokens
        Arguments = $Arguments
        DiscoveredFiles = $DiscoveredFiles
    }
}

function Resolve-ValidationTempRoot {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$TargetSpec,

        [Parameter(Mandatory)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory)]
        [hashtable]$Tokens,

        [Parameter(Mandatory)]
        [string]$Timestamp
    )

    $Tokens['{timestamp}'] = $Timestamp
    $Tokens['{system_temp}'] = [System.IO.Path]::GetTempPath().TrimEnd('\', '/')
    $Configured = if ($TargetSpec.Contains('temp_root')) {
        Convert-ValidationTokenText -Text ([string]$TargetSpec['temp_root']) -Tokens $Tokens
    }
    else {
        Join-Path $WorkingDirectory ('.pytest_tmp_root\validation-{0}' -f $Timestamp)
    }
    if (-not [System.IO.Path]::IsPathRooted($Configured)) {
        $Configured = Join-Path $WorkingDirectory $Configured
    }
    return [System.IO.Path]::GetFullPath($Configured)
}

Export-ModuleMember -Function @(
    'Get-ValidationManifestItems',
    'Convert-ValidationTokenText',
    'Resolve-ValidationPythonExecutable',
    'Resolve-ValidationCommandSpec',
    'Resolve-ValidationTempRoot'
)
