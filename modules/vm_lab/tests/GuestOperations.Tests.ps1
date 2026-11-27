#Requires -Version 7.0

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Split-Path -Parent $here
Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force

Describe 'vm_lab Phase 1 generic guest execution, artifacts, and evidence' {
    $tmpRoot = Join-Path $moduleRoot '.pytest_tmp_root\pester_guest_ops'
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

    InModuleScope vm_lab {
        $script:p1TmpRoot = Join-Path (Split-Path -Parent $PSScriptRoot) '.pytest_tmp_root\pester_guest_ops'
        if (-not (Test-Path -LiteralPath $script:p1TmpRoot)) {
            $script:p1TmpRoot = Join-Path (Get-Location) 'modules\vm_lab\.pytest_tmp_root\pester_guest_ops'
        }
        $secPwd = ConvertTo-SecureString 'DummyPass123!' -AsPlainText -Force
        $script:p1Cred = [pscredential]::new('Administrator', $secPwd)
        $script:p1Vm = [pscustomobject]@{
            Name                  = 'Disp-Phase1-VM'
            Id                    = [guid]'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            State                 = 'Running'
            ConfigurationLocation = 'C:\VMs\Disp-Phase1-VM'
        }
        Mock Get-VM { return @($script:p1Vm) }
        Mock Test-VmLabOwnership { return [pscustomobject]@{ owned = $true; reason = 'ok' } }
        Mock New-VmLabPSSession { return [pscustomobject]@{ Id = 1; ComputerName = 'Guest' } }
        Mock Remove-VmLabPSSession { }
    }

    It 'validates guest identity policy and fails closed on non-admin or forbidden processes' {
        InModuleScope vm_lab {
            Mock Invoke-VmLabPSSessionCommand {
                return [pscustomobject]@{
                    hostname            = 'DISP-GUEST'
                    os_caption          = 'Microsoft Windows 11 Pro'
                    os_version          = '10.0.26100'
                    os_architecture     = '64-bit'
                    manufacturer        = 'Microsoft Corporation'
                    model               = 'Virtual Machine'
                    user_name           = 'DISP-GUEST\mcarls'
                    is_admin            = $true
                    forbidden_processes = @()
                }
            }
            $ok = Test-VmLabGuestIdentityPolicy -Name 'Disp-Phase1-VM' -Credential $script:p1Cred -Policy @{
                require_local_admin = $true
                expected_hostname   = 'DISP-GUEST'
                os_caption_match    = 'Windows 11'
                architecture        = '64-bit'
            }
            $ok.status | Should Be 'SUCCEEDED'

            Mock Invoke-VmLabPSSessionCommand {
                return [pscustomobject]@{
                    hostname            = 'DISP-GUEST'
                    os_caption          = 'Microsoft Windows 11 Pro'
                    os_version          = '10.0.26100'
                    os_architecture     = '64-bit'
                    manufacturer        = 'Microsoft Corporation'
                    model               = 'Virtual Machine'
                    user_name           = 'DISP-GUEST\user'
                    is_admin            = $false
                    forbidden_processes = @('badproc')
                }
            }
            $bad = Test-VmLabGuestIdentityPolicy -Name 'Disp-Phase1-VM' -Credential $script:p1Cred -Policy @{
                require_local_admin = $true
                forbidden_processes = @('badproc')
            }
            $bad.status | Should Be 'FAILED'
            $bad.failures.Count | Should Be 2
        }
    }

    It 'enforces guest-exec authorization, rejects secret env keys, preserves exit codes, and flags non_repeatable transport loss as PARTIAL' {
        InModuleScope vm_lab {
            $plan = Invoke-VmLabGuestCommand -Name 'Disp-Phase1-VM' -ExecutablePath 'C:\Tools\runner.exe' -ArgumentList @('--profile', 'offline')
            $plan.status | Should Be 'PLANNED'
            $plan.dry_run | Should Be $true

            $blocked = Invoke-VmLabGuestCommand -Name 'Disp-Phase1-VM' -ExecutablePath 'C:\Tools\runner.exe' -Apply
            $blocked.status | Should Be 'BLOCKED'
            $blocked.reason_code | Should Be 'guest_exec_authorization_required'

            $threw = $false
            try {
                Invoke-VmLabGuestCommand -Name 'Disp-Phase1-VM' -ExecutablePath 'C:\Tools\runner.exe' -Environment @{ MY_SECRET = '123' }
            } catch { $threw = $true }
            $threw | Should Be $true

            Mock Invoke-VmLabPSSessionCommand {
                return [pscustomobject]@{
                    status        = 'FAILED'
                    reason_code   = 'guest_command_nonzero_exit'
                    actual_sha256 = ('a' * 64)
                    exit_code     = 2
                    timed_out     = $false
                    stdout        = '{"status":"failed","skipped":0}'
                    stderr        = 'acceptance failed'
                    parsed_json   = [pscustomobject]@{ status = 'failed'; skipped = 0 }
                }
            }
            $nz = Invoke-VmLabGuestCommand -Name 'Disp-Phase1-VM' -ExecutablePath 'C:\Tools\runner.exe' -ArgumentList @('--profile', 'task') -Credential $script:p1Cred -Apply -AuthorizeGuestExec
            $nz.status | Should Be 'FAILED'
            $nz.exit_code | Should Be 2
            $nz.parsed_json.status | Should Be 'failed'

            Mock New-VmLabPSSession { throw 'PowerShell Direct session transport timeout' }
            $part = Invoke-VmLabGuestCommand -Name 'Disp-Phase1-VM' -ExecutablePath 'C:\Tools\runner.exe' -IdempotencyClass 'non_repeatable' -Credential $script:p1Cred -Apply -AuthorizeGuestExec
            $part.status | Should Be 'PARTIAL'
            $part.reason_code | Should Be 'needs_reconciliation_after_transport_loss'
        }
    }

    It 'builds manifests, enforces artifact deploy auth, supports resumable verified staging, and blocks ZIP slip' {
        $srcDir = Join-Path $tmpRoot 'bundle_src'
        $subDir = Join-Path $srcDir 'wheels'
        New-Item -ItemType Directory -Path $subDir -Force | Out-Null
        $f1 = Join-Path $srcDir 'setup script.ps1'
        $f2 = Join-Path $subDir 'pkg-1.0.whl'
        [System.IO.File]::WriteAllText($f1, 'Write-Output "ok"')
        [System.IO.File]::WriteAllText($f2, 'wheel-bytes-123')

        $env:VMLAB_TEST_ROOT = $tmpRoot
        InModuleScope vm_lab {
            $tRoot = $env:VMLAB_TEST_ROOT
            $srcDirPath = Join-Path $tRoot 'bundle_src'
            $guestDest = Join-Path $tRoot 'fake_guest_dest'
            New-Item -ItemType Directory -Path (Join-Path $guestDest 'wheels') -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $srcDirPath 'wheels\pkg-1.0.whl') -Destination (Join-Path $guestDest 'wheels\pkg-1.0.whl') -Force

            $manifest = New-VmLabArtifactManifest -SourceRoot $srcDirPath -DestinationRoot $guestDest
            $manifest.artifacts.Count | Should Be 2

            $blk = Publish-VmLabArtifactBundle -Name 'Disp-Phase1-VM' -SourceRoot $srcDirPath -Manifest $manifest -Apply
            $blk.status | Should Be 'BLOCKED'
            $blk.reason_code | Should Be 'guest_mutation_authorization_required'

            Mock New-VmLabPSSession { return [pscustomobject]@{ Id = 1; ComputerName = 'Guest' } }
            Mock Invoke-VmLabPSSessionCommand {
                param($Session, $ScriptBlock, $ArgumentList)
                return (& $ScriptBlock @ArgumentList)
            }
            Mock Copy-VmLabPSSessionItem {
                param($Session, $SourcePath, $DestinationPath, $Direction, $Overwrite)
                $parent = Split-Path -Parent $DestinationPath
                if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
                Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
            }
            $dep = Publish-VmLabArtifactBundle -Name 'Disp-Phase1-VM' -SourceRoot $srcDirPath -Manifest $manifest -OperationId 'op1' -Credential $script:p1Cred -Apply -AuthorizeGuestMutation
            $dep.status | Should Be 'SUCCEEDED'
            $dep.failed_count | Should Be 0
            ($dep.items | Where-Object { $_.relative_path -eq 'wheels/pkg-1.0.whl' }).status | Should Be 'skipped_verified'
            ($dep.items | Where-Object { $_.relative_path -eq 'setup script.ps1' }).status | Should Be 'deployed'

            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $goodZip = Join-Path $tRoot 'good.zip'
            $zipIn = Join-Path $tRoot 'zip_in'
            New-Item -ItemType Directory -Path $zipIn -Force | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $zipIn 'hello.txt'), 'hello')
            [System.IO.Compression.ZipFile]::CreateFromDirectory($zipIn, $goodZip)
            $goodSha = (Get-FileHash -LiteralPath $goodZip -Algorithm SHA256).Hash.ToLowerInvariant()
            $extractOut = Join-Path $tRoot 'zip_out'
            $exRes = Expand-VmLabGuestArchive -Name 'Disp-Phase1-VM' -GuestArchivePath $goodZip -ExpectedArchiveSha256 $goodSha -GuestExtractRoot $extractOut -Credential $script:p1Cred -Apply -AuthorizeGuestMutation
            $exRes.status | Should Be 'SUCCEEDED'
            (Test-Path -LiteralPath (Join-Path $extractOut 'hello.txt')) | Should Be $true

            $slipZip = Join-Path $tRoot 'slip.zip'
            $za = [System.IO.Compression.ZipFile]::Open($slipZip, [System.IO.Compression.ZipArchiveMode]::Create)
            $entry = $za.CreateEntry('..\evil.txt')
            $sw = [System.IO.StreamWriter]::new($entry.Open())
            $sw.Write('evil')
            $sw.Dispose()
            $za.Dispose()
            $slipSha = (Get-FileHash -LiteralPath $slipZip -Algorithm SHA256).Hash.ToLowerInvariant()
            $threwSlip = $false
            try {
                Expand-VmLabGuestArchive -Name 'Disp-Phase1-VM' -GuestArchivePath $slipZip -ExpectedArchiveSha256 $slipSha -GuestExtractRoot (Join-Path $tRoot 'slip_out') -Credential $script:p1Cred -Apply -AuthorizeGuestMutation
            } catch { $threwSlip = $true }
            $threwSlip | Should Be $true
        }
    }

    It 'collects recursive guest evidence with SHA-256 verification and classifies partial vs complete' {
        $guestEvRoot = Join-Path $tmpRoot 'guest_ev'
        $guestSub = Join-Path $guestEvRoot 'nested'
        New-Item -ItemType Directory -Path $guestSub -Force | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $guestEvRoot 'summary.json'), '{"status":"passed"}')
        [System.IO.File]::WriteAllText((Join-Path $guestSub 'detail.log'), 'line1')

        $env:VMLAB_TEST_ROOT = $tmpRoot
        InModuleScope vm_lab {
            $tRoot = $env:VMLAB_TEST_ROOT
            $gRoot = Join-Path $tRoot 'guest_ev'
            $hDest = Join-Path $tRoot 'host_ev'
            Mock New-VmLabPSSession { return [pscustomobject]@{ Id = 1; ComputerName = 'Guest' } }
            Mock Invoke-VmLabPSSessionCommand {
                param($Session, $ScriptBlock, $ArgumentList)
                return (& $ScriptBlock @ArgumentList)
            }
            Mock Copy-VmLabPSSessionItem {
                param($Session, $SourcePath, $DestinationPath, $Direction, $Overwrite)
                Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
            }
            $ev1 = Receive-VmLabGuestEvidence -Name 'Disp-Phase1-VM' -GuestRoots @($gRoot) -HostDestination $hDest -OperationId 'ev1' -Credential $script:p1Cred -Apply
            $ev1.status | Should Be 'EVIDENCE_COMPLETE'
            $ev1.collected_count | Should Be 2
            $ev1.missing_count | Should Be 0

            $ev2 = Receive-VmLabGuestEvidence -Name 'Disp-Phase1-VM' -GuestRoots @($gRoot) -HostDestination $hDest -OperationId 'ev2' -Credential $script:p1Cred -Apply
            $ev2.status | Should Be 'EVIDENCE_COMPLETE'
            @($ev2.collected | Where-Object { $_.status -eq 'skipped_verified' }).Count | Should Be 2
        }
    }

    It 'supports Phase 1 plan operations via Invoke-VmLab.ps1 CLI in -Json mode' {
        $cliScript = Join-Path $moduleRoot 'Invoke-VmLab.ps1'
        $out = & pwsh -NoProfile -File $cliScript -o evidence-plan -n 'NonExistent-Check' -GuestRoots 'C:\Ev' -EvidenceRoot (Join-Path $tmpRoot 'cli_ev') -j 2>&1
        $LASTEXITCODE | Should Be 1
        ($out -join "`n") | Should Match '"status":"error"'
    }
}
