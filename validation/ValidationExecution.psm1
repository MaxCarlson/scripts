Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

Import-Module -Name (Join-Path $PSScriptRoot 'ValidationCommon.psm1') -Force
Import-Module -Name (Join-Path $PSScriptRoot 'ValidationArtifacts.psm1') -Force
Import-Module -Name (Join-Path $PSScriptRoot 'DevelopmentLedgerBridge.psm1') -Force

function Add-ValidationFailure {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$TargetName,

        [Parameter(Mandatory)]
        [string]$Failure,

        [Parameter(Mandatory)]
        [System.Collections.Generic.List[string]]$TargetFailures,

        [Parameter(Mandatory)]
        [System.Collections.Generic.List[string]]$OverallFailures
    )

    $TargetFailures.Add($Failure)
    $OverallFailures.Add("$TargetName - $Failure")
}

function Invoke-ValidationCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$TargetName,

        [Parameter(Mandatory)]
        [string]$ReportPath,

        [Parameter(Mandatory)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$CommandSpec,

        [Parameter(Mandatory)]
        [hashtable]$Tokens,

        [Parameter(Mandatory)]
        [System.Collections.Generic.List[string]]$TargetFailures,

        [Parameter(Mandatory)]
        [System.Collections.Generic.List[string]]$OverallFailures
    )

    $Name = if ($CommandSpec.Contains('name')) { [string]$CommandSpec['name'] } else { '(unnamed command)' }
    try {
        $Resolved = Resolve-ValidationCommandSpec -CommandSpec $CommandSpec -TargetRoot $WorkingDirectory -Tokens $Tokens
        $Name = [string]$Resolved.Name
        $Executable = [string]$Resolved.Executable
        $Arguments = @($Resolved.Arguments)
        Write-ValidationReportSection -ReportPath $ReportPath -Title $Name
        Write-ValidationReportLine -ReportPath $ReportPath -Text ("Working directory: {0}" -f $WorkingDirectory)
        if (@($Resolved.DiscoveredFiles).Count -gt 0) {
            Write-ValidationReportLine -ReportPath $ReportPath -Text ("Discovered files: {0}" -f @($Resolved.DiscoveredFiles).Count)
            foreach ($Path in @($Resolved.DiscoveredFiles)) {
                Write-ValidationReportLine -ReportPath $ReportPath -Text ("  {0}" -f $Path)
            }
        }
        Write-ValidationReportLine -ReportPath $ReportPath -Text ("Command: {0} {1}" -f $Executable, ($Arguments -join ' '))

        Push-Location -LiteralPath $WorkingDirectory
        try {
            & $Executable @Arguments 2>&1 | ForEach-Object {
                Write-ValidationReportLine -ReportPath $ReportPath -Text ([string]$_)
            }
            $ExitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
        }
        finally {
            Pop-Location
        }
        if ($ExitCode -ne 0) {
            throw "Command returned exit code $ExitCode."
        }
        Write-ValidationReportLine -ReportPath $ReportPath -Text "RESULT: PASS - $Name"
    }
    catch {
        $Message = $_.Exception.Message
        $Failure = "$Name`: $Message"
        Add-ValidationFailure -TargetName $TargetName -Failure $Failure -TargetFailures $TargetFailures -OverallFailures $OverallFailures
        Write-ValidationReportSection -ReportPath $ReportPath -Title $Name
        Write-ValidationReportLine -ReportPath $ReportPath -Text "RESULT: FAIL - $Name"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "ERROR: $Message"
    }
}

function Invoke-ValidationPowerShellGroups {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$TargetName,
        [Parameter(Mandatory)] [string]$ReportPath,
        [Parameter(Mandatory)] [string]$WorkingDirectory,
        [Parameter(Mandatory)] [System.Collections.IDictionary]$TargetSpec,
        [Parameter(Mandatory)] [hashtable]$Tokens,
        [Parameter(Mandatory)] [System.Collections.Generic.List[string]]$TargetFailures,
        [Parameter(Mandatory)] [System.Collections.Generic.List[string]]$OverallFailures
    )

    foreach ($ScriptGroup in (Get-ValidationManifestItems -Container $TargetSpec -Name 'powershell_tests')) {
        if (-not $ScriptGroup.Contains('glob')) {
            $Failure = "A PowerShell test group for '$TargetName' does not define a glob."
            Add-ValidationFailure -TargetName $TargetName -Failure $Failure -TargetFailures $TargetFailures -OverallFailures $OverallFailures
            continue
        }
        $Pattern = Join-Path $WorkingDirectory ([string]$ScriptGroup['glob'])
        $Scripts = @(Get-ChildItem -Path $Pattern -File -ErrorAction SilentlyContinue | Sort-Object FullName)
        if ($Scripts.Count -eq 0) {
            $Failure = "No PowerShell tests matched: $Pattern"
            Add-ValidationFailure -TargetName $TargetName -Failure $Failure -TargetFailures $TargetFailures -OverallFailures $OverallFailures
            Write-ValidationReportSection -ReportPath $ReportPath -Title 'POWERSHELL TEST DISCOVERY'
            Write-ValidationReportLine -ReportPath $ReportPath -Text "RESULT: FAIL - $Failure"
            continue
        }
        foreach ($Script in $Scripts) {
            $ScriptArguments = @(
                foreach ($Argument in (Get-ValidationManifestItems -Container $ScriptGroup -Name 'arguments')) {
                    Convert-ValidationTokenText -Text ([string]$Argument) -Tokens $Tokens
                }
            )
            $CommandSpec = @{
                name = "PowerShell test: $([System.IO.Path]::GetRelativePath($WorkingDirectory, $Script.FullName))"
                executable = 'pwsh'
                arguments = @('-NoLogo', '-NoProfile', '-File', $Script.FullName) + $ScriptArguments
            }
            Invoke-ValidationCommand `
                -TargetName $TargetName `
                -ReportPath $ReportPath `
                -WorkingDirectory $WorkingDirectory `
                -CommandSpec $CommandSpec `
                -Tokens $Tokens `
                -TargetFailures $TargetFailures `
                -OverallFailures $OverallFailures
        }
    }
}

function Invoke-ValidationLedgerPhase {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$ManifestPath,
        [Parameter(Mandatory)] [string]$TargetName,
        [Parameter(Mandatory)] [string]$RepoRoot,
        [Parameter(Mandatory)] [string]$WorkingDirectory,
        [Parameter(Mandatory)] [string]$TempRoot,
        [Parameter(Mandatory)] [string]$ReportPath,
        [Parameter(Mandatory)] [string]$PythonExecutable,
        [Parameter(Mandatory)] [System.Collections.IDictionary]$TargetSpec,
        [Parameter(Mandatory)] [System.Collections.Generic.List[string]]$TargetFailures,
        [Parameter(Mandatory)] [System.Collections.Generic.List[string]]$OverallFailures
    )

    if (-not $TargetSpec.Contains('ledger')) {
        return
    }
    $Ledger = $TargetSpec['ledger']
    if ($Ledger.Contains('enabled') -and -not [bool]$Ledger['enabled']) {
        return
    }
    $Required = $Ledger.Contains('required') -and [bool]$Ledger['required']
    Write-ValidationReportSection -ReportPath $ReportPath -Title 'DEVELOPMENT LEDGER'
    try {
        Invoke-TargetDevelopmentLedger `
            -ManifestPath $ManifestPath `
            -TargetName $TargetName `
            -RepoRoot $RepoRoot `
            -TargetRoot $WorkingDirectory `
            -TempRoot $TempRoot `
            -ReportPath $ReportPath `
            -PythonExecutable $PythonExecutable `
            -Write 2>&1 | ForEach-Object {
                Write-ValidationReportLine -ReportPath $ReportPath -Text ([string]$_)
            }
        Write-ValidationReportLine -ReportPath $ReportPath -Text 'RESULT: PASS - Development ledger'
    }
    catch {
        $Message = $_.Exception.Message
        Write-ValidationReportLine -ReportPath $ReportPath -Text 'RESULT: FAIL - Development ledger'
        Write-ValidationReportLine -ReportPath $ReportPath -Text "ERROR: $Message"
        if ($Required) {
            Add-ValidationFailure -TargetName $TargetName -Failure "Development ledger: $Message" -TargetFailures $TargetFailures -OverallFailures $OverallFailures
        }
        else {
            Write-ValidationReportLine -ReportPath $ReportPath -Text 'Ledger recording is optional for this target; validation continues.'
        }
    }
}

Export-ModuleMember -Function @(
    'Invoke-ValidationCommand',
    'Invoke-ValidationPowerShellGroups',
    'Invoke-ValidationLedgerPhase'
)
