#!/usr/bin/env pwsh
<#
Thin PowerShell wrapper for Windows users; forwards args to the Python CLI.
#>
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Rest
)
$python = "python"
& $python "$PSScriptRoot/uocs_v2.py" @Rest
exit $LASTEXITCODE
