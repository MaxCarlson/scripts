# Requires: Pester v5
BeforeAll {
  $here = Split-Path -Parent $PSCommandPath
  $repo = Join-Path $here "..\..\"
  $env:HOME = Join-Path $repo "fakehome"
  New-Item -Force -ItemType Directory $env:HOME | Out-Null
  $profilePath = Join-Path $env:HOME "Documents\PowerShell\Microsoft.PowerShell_profile.ps1"
  New-Item -Force -ItemType Directory (Split-Path $profilePath) | Out-Null
  Set-Content -Path $profilePath -Value "# test profile"
  $bin = Join-Path $repo "scripts\bin"
  New-Item -Force -ItemType Directory $bin | Out-Null

  # Path to your pwsh wrapper script (adjust if needed)
  $Wrapper = Join-Path $repo "scripts\pwsh\script.ps1"
}

Describe "pwsh wrapper" {
  It "passes recognized options through 1:1" {
    $result = & $Wrapper -i -t "C:\tmp\scripts\bin" -s powershell -n
    $LASTEXITCODE | Should -Be 0
  }

  It "rejects nonconforming options" {
    & $Wrapper -install 2>$null
    $LASTEXITCODE | Should -Not -Be 0
  }

  It "modifies the PowerShell profile for --install" {
    & $Wrapper -i -s powershell -t (Join-Path $PWD "scripts\bin")
    $LASTEXITCODE | Should -Be 0
    (Get-Content $profilePath -Raw) | Should -Match 'BEGIN pathctl'
  }

  It "uninstalls cleanly" {
    & $Wrapper -u -s powershell -t (Join-Path $PWD "scripts\bin")
    $LASTEXITCODE | Should -Be 0
    (Get-Content $profilePath -Raw) | Should -Not -Match 'pathctl'
  }
}
