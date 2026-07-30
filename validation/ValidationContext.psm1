Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module -Name (Join-Path $PSScriptRoot 'ValidationCommon.psm1') -Force

function Write-ValidationTargetContextSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$RepoRoot,

        [Parameter(Mandatory)]
        [string]$TargetName,

        [Parameter(Mandatory)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$TargetSpec,

        [Parameter(Mandatory)]
        [string]$ReportPath,

        [Parameter(Mandatory)]
        [string]$ContextPath
    )

    $Lines = [System.Collections.Generic.List[string]]::new()
    $Lines.Add("# Validation Context: $TargetName") | Out-Null
    $Lines.Add('') | Out-Null
    $Lines.Add("Generated: $(Get-Date -Format o)") | Out-Null
    $Lines.Add("Branch: $(& git -C $RepoRoot branch --show-current 2>$null)") | Out-Null
    $Lines.Add("Commit: $(& git -C $RepoRoot rev-parse HEAD 2>$null)") | Out-Null
    $Lines.Add("Validation report: $([System.IO.Path]::GetRelativePath($RepoRoot, $ReportPath))") | Out-Null
    $Lines.Add('') | Out-Null
    $Lines.Add('## Validation Highlights') | Out-Null
    $Lines.Add('') | Out-Null

    $HighlightLines = @(
        Get-Content -LiteralPath $ReportPath -ErrorAction SilentlyContinue |
            Where-Object {
                $_ -match '^(?:TARGET RESULT|OVERALL RESULT|Failure count|RESULT: (?:PASS|FAIL))' -or
                $_ -match '(?i)\b(?:passed|failed|skipped|errors?)\b.*\bin\s+[0-9.]+s\b'
            } |
            Select-Object -Last 30
    )
    if ($HighlightLines.Count -eq 0) {
        $Lines.Add('- No summary lines were detected in the validation report.') | Out-Null
    }
    else {
        foreach ($HighlightLine in $HighlightLines) {
            $Lines.Add("- $HighlightLine") | Out-Null
        }
    }

    $Lines.Add('') | Out-Null
    $Lines.Add('## Working Tree') | Out-Null
    $Lines.Add('') | Out-Null
    $GitStatus = @(& git -C $RepoRoot status --short 2>$null)
    $Lines.Add('```text') | Out-Null
    if ($GitStatus.Count -eq 0) {
        $Lines.Add('(clean)') | Out-Null
    }
    else {
        foreach ($StatusLine in $GitStatus) {
            $Lines.Add([string]$StatusLine) | Out-Null
        }
    }
    $Lines.Add('```') | Out-Null

    $Lines.Add('') | Out-Null
    $Lines.Add('## Project Status Sources') | Out-Null
    $Lines.Add('') | Out-Null
    $ContextFiles = @(Get-ValidationManifestItems -Container $TargetSpec -Name 'context_files')
    if ($ContextFiles.Count -eq 0) {
        $Lines.Add('No context files are configured for this target.') | Out-Null
    }
    else {
        foreach ($RelativePathObject in $ContextFiles) {
            $RelativePath = [string]$RelativePathObject
            $SourcePath = if ([System.IO.Path]::IsPathRooted($RelativePath)) {
                $RelativePath
            }
            else {
                Join-Path $WorkingDirectory $RelativePath
            }
            $Lines.Add(('### `{0}`' -f $RelativePath)) | Out-Null
            $Lines.Add('') | Out-Null
            if (Test-Path -LiteralPath $SourcePath -PathType Leaf) {
                $SourceText = Get-Content -LiteralPath $SourcePath -Raw
                $Lines.Add($SourceText.TrimEnd()) | Out-Null
            }
            else {
                $Lines.Add(('_Missing at validation time: `{0}`_' -f $SourcePath)) | Out-Null
            }
            $Lines.Add('') | Out-Null
        }
    }

    Set-Content -LiteralPath $ContextPath -Value $Lines -Encoding utf8
}

function Write-ValidationContextProgressDiff {
    [CmdletBinding()]
    param(
        [Parameter()]
        [AllowNull()]
        [string]$PreviousContextPath,

        [Parameter(Mandatory)]
        [string]$CurrentContextPath,

        [Parameter(Mandatory)]
        [string]$ProgressPath
    )

    if ([string]::IsNullOrWhiteSpace($PreviousContextPath) -or -not (Test-Path -LiteralPath $PreviousContextPath)) {
        Set-Content -LiteralPath $ProgressPath -Value 'No previous context snapshot is available. This validation establishes the baseline.' -Encoding utf8
        return
    }

    $DiffOutput = @(
        & git -c core.quotepath=false diff --no-index --no-ext-diff --unified=3 -- $PreviousContextPath $CurrentContextPath 2>&1
    )
    $DiffExitCode = $LASTEXITCODE
    if ($DiffExitCode -eq 0) {
        Set-Content -LiteralPath $ProgressPath -Value 'No project-status changes were detected since the previous validation context.' -Encoding utf8
        return
    }
    if ($DiffExitCode -eq 1) {
        Set-Content -LiteralPath $ProgressPath -Value $DiffOutput -Encoding utf8
        return
    }
    Set-Content -LiteralPath $ProgressPath -Value @(
        "Unable to generate context diff. git diff --no-index exited with code $DiffExitCode.",
        $DiffOutput
    ) -Encoding utf8
}

Export-ModuleMember -Function @(
    'Write-ValidationTargetContextSnapshot',
    'Write-ValidationContextProgressDiff'
)
