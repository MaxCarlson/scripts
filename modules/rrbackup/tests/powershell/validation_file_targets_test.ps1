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

$null = $IncludeProductionReadOnly
$HelperPath = Join-Path $RepoRoot 'validation\Invoke-FileTargetCommand.ps1'
Assert-True -Condition (Test-Path -LiteralPath $HelperPath -PathType Leaf) -Message "Validation helper is missing: $HelperPath"

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("validation-file-targets-{0}" -f [Guid]::NewGuid().ToString('N'))
$ProjectRoot = Join-Path $TempRoot 'project'
$SourceRoot = Join-Path $ProjectRoot 'source'
$TestsRoot = Join-Path $ProjectRoot 'tests'
$CaptureScript = Join-Path $TempRoot 'capture_args.py'
$CaptureOutput = Join-Path $TempRoot 'captured.json'
$ManifestPath = Join-Path $TempRoot 'validation-targets.json'

try {
    New-Item -ItemType Directory -Path (Join-Path $SourceRoot 'nested') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $TestsRoot 'nested') -Force | Out-Null

    Set-Content -LiteralPath (Join-Path $SourceRoot 'alpha.py') -Value 'VALUE = 1' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $SourceRoot 'ignored.md') -Value '# ignored' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $SourceRoot 'nested\too_deep.py') -Value 'VALUE = 2' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $TestsRoot 'alpha_test.py') -Value 'def test_alpha(): pass' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $TestsRoot 'nested\too_deep_test.py') -Value 'def test_nested(): pass' -Encoding utf8

    Set-Content -LiteralPath $CaptureScript -Encoding utf8 -Value @'
import json
import pathlib
import sys

output = pathlib.Path(sys.argv[1])
output.write_text(json.dumps(sys.argv[2:]), encoding="utf-8")
'@

    $Manifest = @{
        default_targets = @('sample')
        targets = @{
            sample = @{
                description = 'Synthetic file-target discovery test.'
                working_directory = 'project'
                commands = @(
                    @{
                        name = 'Discover Python files'
                        executable = 'pwsh'
                        arguments = @()
                        file_command = @{
                            executable = '{python}'
                            arguments = @('{repo_root}/capture_args.py', '{repo_root}/captured.json')
                        }
                        file_targets = @(
                            @{
                                path = 'source'
                                max_depth = 1
                                extensions = @('.py')
                            },
                            @{
                                path = 'tests'
                                max_depth = 1
                                extension = 'py'
                            }
                        )
                    }
                )
            }
        }
    }
    $Manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ManifestPath -Encoding utf8

    $Output = & pwsh -NoLogo -NoProfile -File $HelperPath `
        -ManifestPath $ManifestPath `
        -TargetName sample `
        -CommandName 'Discover Python files' `
        -PythonExecutable $PythonExecutable 2>&1
    $ExitCode = $LASTEXITCODE

    Assert-True -Condition ($ExitCode -eq 0) -Message "File-target helper failed: $($Output -join ' ')"
    Assert-True -Condition (Test-Path -LiteralPath $CaptureOutput -PathType Leaf) -Message 'Capture output was not created.'

    $Captured = @(Get-Content -LiteralPath $CaptureOutput -Raw | ConvertFrom-Json)
    $Expected = @('source\alpha.py', 'tests\alpha_test.py')
    Assert-True -Condition ($Captured.Count -eq $Expected.Count) -Message "Expected $($Expected.Count) files; got $($Captured.Count): $($Captured -join ', ')"
    for ($Index = 0; $Index -lt $Expected.Count; $Index++) {
        Assert-True -Condition ($Captured[$Index] -eq $Expected[$Index]) -Message "Unexpected discovered file order/content: $($Captured -join ', ')"
    }

    Assert-True -Condition (-not ($Captured -contains 'source\nested\too_deep.py')) -Message 'max_depth=1 incorrectly included a nested source file.'
    Assert-True -Condition (-not ($Captured -contains 'tests\nested\too_deep_test.py')) -Message 'max_depth=1 incorrectly included a nested test file.'
    Assert-True -Condition (-not ($Captured -contains 'source\ignored.md')) -Message 'Extension filtering incorrectly included a Markdown file.'

    $Manifest.targets.sample.commands[0].file_targets = @(
        @{
            path = 'source'
            max_depth = 1
            extensions = @('.ps1')
        }
    )
    $Manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ManifestPath -Encoding utf8

    $NoMatchOutput = & pwsh -NoLogo -NoProfile -File $HelperPath `
        -ManifestPath $ManifestPath `
        -TargetName sample `
        -CommandName 'Discover Python files' `
        -PythonExecutable $PythonExecutable 2>&1
    $NoMatchExitCode = $LASTEXITCODE

    Assert-True -Condition ($NoMatchExitCode -ne 0) -Message 'A file-target rule with no matches should fail.'
    Assert-True -Condition (($NoMatchOutput -join "`n") -match 'matched no files') -Message "No-match failure was not actionable: $($NoMatchOutput -join ' ')"

    Write-Output 'Validation file-target discovery completed successfully.'
}
finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
