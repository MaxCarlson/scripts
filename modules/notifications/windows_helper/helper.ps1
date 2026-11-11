<#
.SYNOPSIS
    Forwarding launcher for authoritative Windows toast helper.
#>
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    $RemainingArgs
)

$target = Join-Path $PSScriptRoot "..\notifications\windows_helper\helper.ps1"
if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "Authoritative helper script not found at: $target"
    exit 1
}

& $target @RemainingArgs
exit $LASTEXITCODE
