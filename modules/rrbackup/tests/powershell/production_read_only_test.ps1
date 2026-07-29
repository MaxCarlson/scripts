[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot,

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$IncludeProductionReadOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-True {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [bool]$Condition,

        [Parameter(Mandatory)]
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Assert-KnownSnapshots {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [object[]]$Snapshots,

        [Parameter(Mandatory)]
        [string]$SourceName
    )

    Assert-True -Condition ($Snapshots.Count -ge 2) -Message "$SourceName expected at least two snapshots, found $($Snapshots.Count)."

    foreach ($ExpectedId in $ExpectedSnapshotIds) {
        $Match = $Snapshots | Where-Object {
            ([string]$_.id).StartsWith($ExpectedId, [System.StringComparison]::OrdinalIgnoreCase) -or
            ([string]$_.short_id).Equals($ExpectedId, [System.StringComparison]::OrdinalIgnoreCase)
        }
        Assert-True -Condition ([bool]$Match) -Message "$SourceName did not include expected snapshot: $ExpectedId"
    }

    $KnownSnapshots = $Snapshots | Where-Object {
        $Id = [string]$_.id
        $ShortId = [string]$_.short_id
        $ExpectedSnapshotIds | Where-Object {
            $Id.StartsWith($_, [System.StringComparison]::OrdinalIgnoreCase) -or
            $ShortId.Equals($_, [System.StringComparison]::OrdinalIgnoreCase)
        }
    }

    foreach ($Snapshot in $KnownSnapshots) {
        Assert-True -Condition (@($Snapshot.tags) -contains $ExpectedTag) -Message "$SourceName snapshot $($Snapshot.short_id) is missing tag $ExpectedTag."
        foreach ($ExpectedPath in $ExpectedPaths) {
            Assert-True -Condition (@($Snapshot.paths) -contains $ExpectedPath) -Message "$SourceName snapshot $($Snapshot.short_id) is missing path $ExpectedPath."
        }
    }
}

if (-not $IncludeProductionReadOnly) {
    Write-Output 'SKIP: Production read-only checks were not explicitly enabled.'
    exit 0
}

$Repository = 'B:\ResticRepos\PC-Local'
$PasswordFile = 'C:\BackupConfig\restic-local-password.txt'
$ExpectedSnapshotIds = @('a1609113', '022aad5b')
$ExpectedTag = 'local-main'
$ExpectedPaths = @(
    'C:\',
    'D:\Pictures',
    'D:\Torrents\Movies',
    'D:\Torrents\TV',
    'D:\Torrents\anime'
)

Assert-True -Condition (Test-Path -LiteralPath $Repository -PathType Container) -Message "Production repository is missing: $Repository"
Assert-True -Condition (Test-Path -LiteralPath $PasswordFile -PathType Leaf) -Message "Production password file is missing: $PasswordFile"

$ResticCommand = Get-Command restic -ErrorAction SilentlyContinue
Assert-True -Condition ([bool]$ResticCommand) -Message 'restic is not available on PATH.'

Write-Output "Repository=$Repository"
Write-Output "PasswordFile=$PasswordFile"
Write-Output "Restic=$($ResticCommand.Source)"
Write-Output 'Operation=raw restic snapshots --json (read-only)'

$RawSnapshots = & $ResticCommand.Source `
    --repo $Repository `
    --password-file $PasswordFile `
    snapshots `
    --json 2>&1

Assert-True -Condition ($LASTEXITCODE -eq 0) -Message "Restic snapshot listing failed: $($RawSnapshots -join ' ')"

try {
    $ResticSnapshots = @(($RawSnapshots -join [Environment]::NewLine) | ConvertFrom-Json)
}
catch {
    throw "Unable to parse Restic snapshot JSON: $($_.Exception.Message)"
}

Assert-KnownSnapshots -Snapshots $ResticSnapshots -SourceName 'Raw Restic'

$ScriptsRoot = Split-Path -Parent $PythonExecutable
$BackupCommand = Join-Path $ScriptsRoot 'backup.exe'
if (-not (Test-Path -LiteralPath $BackupCommand -PathType Leaf)) {
    $BackupCommand = Join-Path $ScriptsRoot 'backup'
}
Assert-True -Condition (Test-Path -LiteralPath $BackupCommand -PathType Leaf) -Message "Canonical backup entry point is missing: $BackupCommand"

Write-Output "BackupCommand=$BackupCommand"
Write-Output 'Operation=backup view snapshots --json (read-only)'

$CanonicalOutput = & $BackupCommand `
    --repository $Repository `
    --password-file $PasswordFile `
    view `
    snapshots `
    --json 2>&1

Assert-True -Condition ($LASTEXITCODE -eq 0) -Message "Canonical snapshot listing failed: $($CanonicalOutput -join ' ')"

try {
    $CanonicalSnapshots = @(($CanonicalOutput -join [Environment]::NewLine) | ConvertFrom-Json)
}
catch {
    throw "Unable to parse canonical snapshot JSON: $($_.Exception.Message)"
}

Assert-KnownSnapshots -Snapshots $CanonicalSnapshots -SourceName 'Canonical backup CLI'

$CanonicalSnapshots |
    Sort-Object { [datetimeoffset]$_.time } |
    Select-Object @{Name='Id'; Expression={ if ($_.short_id) { $_.short_id } else { ([string]$_.id).Substring(0, 8) } }}, time, hostname, @{Name='Tags'; Expression={ @($_.tags) -join ',' }}, @{Name='Paths'; Expression={ @($_.paths) -join ' | ' }} |
    Format-Table -AutoSize |
    Out-String -Width 1200 |
    Write-Output

Write-Output 'Production read-only compatibility test completed successfully.'
Write-Output 'No backup, restore, init, unlock, forget, prune, cache cleanup, or retention command was executed.'
