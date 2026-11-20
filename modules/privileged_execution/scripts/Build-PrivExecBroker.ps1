#Requires -Version 7.0
<#
.SYNOPSIS
    Build PrivExecBroker (.NET 10) and optionally PrivExecBroker.Tests.
.DESCRIPTION
    Uses `dotnet build` when a compatible .NET 10+ SDK is installed; otherwise
    compiles directly with Visual Studio 2022 Roslyn `csc.exe` against the
    installed Microsoft.NETCore.App 10.x runtime assemblies and emits matching
    *.runtimeconfig.json files.
#>
[CmdletBinding()]
param(
    [string]$OutDir = (Join-Path (Split-Path -Parent $PSScriptRoot) 'broker\bin'),
    [switch]$IncludeTests,
    [switch]$ForceRoslyn
)

$ErrorActionPreference = 'Stop'
$moduleRoot = Split-Path -Parent $PSScriptRoot
$brokerProjDir = Join-Path $moduleRoot 'broker\PrivExecBroker'
$testsProjDir = Join-Path $moduleRoot 'broker\PrivExecBroker.Tests'

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
Get-ChildItem -LiteralPath $OutDir -Filter 'PrivExecBroker*.dll' -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $OutDir -Filter 'PrivExecBroker*.pdb' -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

function Get-DotnetSdkVersion {
    try {
        $sdks = @(& dotnet --list-sdks 2>$null)
        if ($LASTEXITCODE -ne 0 -or $sdks.Count -eq 0) { return $null }
        foreach ($line in $sdks) {
            if ($line -match '^10\.') { return $line }
        }
        return $null
    } catch {
        return $null
    }
}

function Find-RoslynCsc {
    $candidates = @(
        'C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\Roslyn\csc.exe',
        'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe',
        'C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\Roslyn\csc.exe',
        'C:\Program Files\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\Roslyn\csc.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) { return $c }
    }
    throw 'Neither a .NET 10 SDK nor VS2022 Roslyn csc.exe was found.'
}

function Find-Net10RuntimeDir {
    $sharedRoot = 'C:\Program Files\dotnet\shared\Microsoft.NETCore.App'
    if (-not (Test-Path -LiteralPath $sharedRoot)) {
        throw "Missing .NET shared runtime directory: $sharedRoot"
    }
    $dirs = @(Get-ChildItem -LiteralPath $sharedRoot -Directory | Where-Object { $_.Name -match '^10\.' } | Sort-Object Name -Descending)
    if ($dirs.Count -eq 0) {
        throw 'No Microsoft.NETCore.App 10.x runtime found.'
    }
    return $dirs[0]
}

function Write-RuntimeConfig {
    param([string]$TargetPath, [string]$RuntimeVersion)
    $cfg = [ordered]@{
        runtimeOptions = [ordered]@{
            tfm = 'net10.0'
            framework = [ordered]@{
                name = 'Microsoft.NETCore.App'
                version = $RuntimeVersion
            }
        }
    }
    $cfg | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $TargetPath -Encoding utf8NoBOM
}

function Invoke-RoslynCompile {
    param(
        [string]$CscPath,
        [string]$RuntimeDir,
        [string[]]$SourceFiles,
        [string]$OutputDll,
        [string[]]$ExtraRefs = @(),
        [string]$TargetType = 'exe'
    )
    $refDlls = @(Get-ChildItem -LiteralPath $RuntimeDir -Filter '*.dll' -File | Where-Object {
        $_.Name -eq 'System.Private.CoreLib.dll' -or
        ($_.Name -match '^(System\.|Microsoft\.|mscorlib|netstandard)' -and $_.Name -notmatch '\.Native\.')
    } | ForEach-Object { $_.FullName })

    $rspPath = [System.IO.Path]::GetTempFileName()
    try {
        $lines = [System.Collections.Generic.List[string]]::new()
        $lines.Add('-nologo')
        $lines.Add('-nostdlib+')
        $lines.Add("-target:$TargetType")
        $lines.Add('-langversion:latest')
        $lines.Add('-nullable:enable')
        $lines.Add('-optimize+')
        $lines.Add("-out:`"$OutputDll`"")
        foreach ($r in $refDlls) {
            $lines.Add("-reference:`"$r`"")
        }
        foreach ($er in $ExtraRefs) {
            $lines.Add("-reference:`"$er`"")
        }
        foreach ($src in $SourceFiles) {
            $lines.Add("`"$src`"")
        }
        Set-Content -LiteralPath $rspPath -Value $lines -Encoding utf8NoBOM
        $out = & $CscPath -noconfig "@$rspPath" 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Roslyn compilation failed for ${OutputDll}:`n$($out -join "`n")"
        }
    } finally {
        Remove-Item -LiteralPath $rspPath -Force -ErrorAction SilentlyContinue
    }
}

$sdk = if ($ForceRoslyn) { $null } else { Get-DotnetSdkVersion }
$brokerDll = Join-Path $OutDir 'PrivExecBroker.dll'

if ($sdk) {
    Write-Host "Building PrivExecBroker using .NET SDK ($sdk)..."
    & dotnet build (Join-Path $brokerProjDir 'PrivExecBroker.csproj') -c Release -o $OutDir --nologo
    if ($LASTEXITCODE -ne 0) { throw "dotnet build failed for PrivExecBroker." }
    if ($IncludeTests -and (Test-Path -LiteralPath $testsProjDir)) {
        & dotnet build (Join-Path $testsProjDir 'PrivExecBroker.Tests.csproj') -c Release -o $OutDir --nologo
        if ($LASTEXITCODE -ne 0) { throw "dotnet build failed for PrivExecBroker.Tests." }
    }
} else {
    $csc = Find-RoslynCsc
    $rtDir = Find-Net10RuntimeDir
    Write-Host "No .NET 10 SDK found; compiling with Roslyn ($csc) against .NET $($rtDir.Name)..."

    $brokerSources = @(Get-ChildItem -LiteralPath $brokerProjDir -Filter '*.cs' -File | Sort-Object Name | ForEach-Object { $_.FullName })
    Invoke-RoslynCompile -CscPath $csc -RuntimeDir $rtDir.FullName -SourceFiles $brokerSources -OutputDll $brokerDll -TargetType 'exe'
    Write-RuntimeConfig -TargetPath (Join-Path $OutDir 'PrivExecBroker.runtimeconfig.json') -RuntimeVersion $rtDir.Name

    if ($IncludeTests -and (Test-Path -LiteralPath $testsProjDir)) {
        $testSources = @(Get-ChildItem -LiteralPath $testsProjDir -Filter '*.cs' -File | Sort-Object Name | ForEach-Object { $_.FullName })
        $testDll = Join-Path $OutDir 'PrivExecBroker.Tests.dll'
        Invoke-RoslynCompile -CscPath $csc -RuntimeDir $rtDir.FullName -SourceFiles $testSources -OutputDll $testDll -ExtraRefs @($brokerDll) -TargetType 'exe'
        Write-RuntimeConfig -TargetPath (Join-Path $OutDir 'PrivExecBroker.Tests.runtimeconfig.json') -RuntimeVersion $rtDir.Name
    }
}

Write-Host "Built PrivExecBroker -> $brokerDll"
