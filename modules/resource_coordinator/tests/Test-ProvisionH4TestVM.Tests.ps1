#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

$scriptPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\tools\h4_qualification\Provision-H4TestVM.ps1'))

Describe 'Provision-H4TestVM.ps1' {
    $testTemp = Join-Path $PSScriptRoot '..\.pytest_tmp_root\pester_provision_h4'
    if (Test-Path -LiteralPath $testTemp) {
        Remove-Item -LiteralPath $testTemp -Recurse -Force
    }
    New-Item -ItemType Directory -Path $testTemp -Force | Out-Null

    $dummyIso = Join-Path $testTemp 'Windows11_dummy.iso'
    $fs = [System.IO.File]::Create($dummyIso)
    $fs.SetLength(3GB)
    $fs.Dispose()

    function Test-IsAdministrator { $false }
    function Get-H4DriveFreeBytes { param([string]$TargetPath) 0 }
    function Get-H4HostMemoryInfo { [pscustomobject]@{ TotalPhysicalBytes = 0; FreePhysicalBytes = 0 } }
    function Set-VMFirmware { param($VMName, $EnableSecureBoot, $SecureBootTemplate, [object[]]$BootOrder) }

    function Initialize-HappyHyperVMocks {
        param(
            [string]$VmRoot,
            [string]$VmName = 'RC-H4-Windows-Acceptance',
            [switch]$VmExists,
            [switch]$ThrowOnGetVm,
            [switch]$ThrowOnSetVm,
            [switch]$ThrowOnEnableTpm,
            [switch]$ThrowOnAddDvd,
            [switch]$EmptyBootOrder
        )
        $Global:h4CallLog = [System.Collections.Generic.List[string]]::new()
        $Global:h4VmCreated = [bool]$VmExists

        Mock Test-IsAdministrator { return $true }
        Mock Get-H4DriveFreeBytes { return [int64]200GB }
        Mock Get-H4HostMemoryInfo {
            return [pscustomobject]@{
                TotalPhysicalBytes = [int64]64GB
                FreePhysicalBytes  = [int64]16GB
            }
        }
        Mock Get-FileHash {
            return [pscustomobject]@{
                Algorithm = 'SHA256'
                Hash      = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
            }
        }
        Mock Get-VMHost {
            return [pscustomobject]@{
                ComputerName        = 'XERES'
                VirtualMachinePath  = $VmRoot
                VirtualHardDiskPath = $VmRoot
            }
        }
        if ($ThrowOnGetVm) {
            Mock Get-VM { throw 'You do not have the required permission to complete this task.' }
        } else {
            Mock Get-VM {
                if ($Global:h4VmCreated) {
                    return @([pscustomobject]@{
                        Name           = $VmName
                        Id             = [guid]'11111111-1111-1111-1111-111111111111'
                        Generation     = 2
                        State          = 'Off'
                        ProcessorCount = 4
                        MemoryStartup  = 6GB
                        MemoryMinimum  = 4GB
                        MemoryMaximum  = 8GB
                        CheckpointType = 'Standard'
                    })
                }
                return @()
            }
        }
        Mock Get-VMSwitch {
            return @([pscustomobject]@{ Name = 'ExistingSwitch'; SwitchType = 'Internal' })
        }
        Mock New-VM {
            param($Name, $Generation, $MemoryStartupBytes, $Path, $NewVHDPath, $NewVHDSizeBytes)
            $Global:h4CallLog.Add("New-VM:$Name`:$Generation`:$NewVHDPath`:$NewVHDSizeBytes")
            $Global:h4VmCreated = $true
            $vhdParent = Split-Path -Parent $NewVHDPath
            if (-not (Test-Path -LiteralPath $vhdParent)) {
                New-Item -ItemType Directory -Path $vhdParent -Force | Out-Null
            }
            Set-Content -LiteralPath $NewVHDPath -Value 'mock-vhdx'
            return [pscustomobject]@{
                Name = $Name
                Id   = [guid]'11111111-1111-1111-1111-111111111111'
            }
        }
        Mock Get-VMNetworkAdapter {
            $Global:h4CallLog.Add('Get-VMNetworkAdapter')
            return @([pscustomobject]@{ Name = 'Network Adapter' })
        }
        Mock Remove-VMNetworkAdapter {
            $Global:h4CallLog.Add('Remove-VMNetworkAdapter')
        }
        Mock Add-VMNetworkAdapter {
            param($VMName, $SwitchName)
            $Global:h4CallLog.Add("Add-VMNetworkAdapter:$SwitchName")
        }
        if ($ThrowOnSetVm) {
            Mock Set-VM {
                $Global:h4CallLog.Add('Set-VM:THROW')
                throw 'Simulated Set-VM failure'
            }
        } else {
            Mock Set-VM {
                $Global:h4CallLog.Add('Set-VM')
            }
        }
        Mock Set-VMFirmware {
            param($VMName, $EnableSecureBoot, $SecureBootTemplate, $BootOrder)
            if ($BootOrder) {
                $Global:h4CallLog.Add('Set-VMFirmware:BootOrder')
            } else {
                $Global:h4CallLog.Add("Set-VMFirmware:SecureBoot:$EnableSecureBoot`:$SecureBootTemplate")
            }
        }
        Mock Set-VMKeyProtector {
            $Global:h4CallLog.Add('Set-VMKeyProtector')
        }
        if ($ThrowOnEnableTpm) {
            Mock Enable-VMTPM {
                $Global:h4CallLog.Add('Enable-VMTPM:THROW')
                throw 'Simulated Enable-VMTPM failure'
            }
        } else {
            Mock Enable-VMTPM {
                $Global:h4CallLog.Add('Enable-VMTPM')
            }
        }
        if ($ThrowOnAddDvd) {
            Mock Add-VMDvdDrive {
                $Global:h4CallLog.Add('Add-VMDvdDrive:THROW')
                throw 'Simulated Add-VMDvdDrive failure'
            }
        } else {
            Mock Add-VMDvdDrive {
                $Global:h4CallLog.Add('Add-VMDvdDrive')
                return [pscustomobject]@{ BootType = 'Dvd' }
            }
        }
        Mock Get-VMHardDiskDrive {
            $Global:h4CallLog.Add('Get-VMHardDiskDrive')
            return [pscustomobject]@{ BootType = 'HardDrive' }
        }
        if ($EmptyBootOrder) {
            Mock Get-VMFirmware {
                return [pscustomobject]@{ BootOrder = @() }
            }
        } else {
            Mock Get-VMFirmware {
                return [pscustomobject]@{ BootOrder = @([pscustomobject]@{ BootType = 'Dvd' }, [pscustomobject]@{ BootType = 'HardDrive' }) }
            }
        }
        Mock Remove-VM {
            $Global:h4CallLog.Add('Remove-VM:UNEXPECTED')
        }
    }

    It 'parses cleanly with zero PowerShell syntax errors' {
        $tokens = $null
        $errors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
        $errors.Count | Should Be 0
    }

    It 'performs no writes in default dry-run mode' {
        $vmRoot = Join-Path $testTemp 'case_dryrun'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot *>&1
        $LASTEXITCODE | Should Be 0
        (Test-Path -LiteralPath $vmRoot) | Should Be $false
        ($Global:h4CallLog | Where-Object { $_ -like 'New-VM*' }).Count | Should Be 0
        ($output -join "`n") | Should Match 'DRY-RUN'
    }

    It 'performs no writes when -WhatIf is combined with -Apply' {
        $vmRoot = Join-Path $testTemp 'case_whatif'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply -WhatIf *>&1
        $LASTEXITCODE | Should Be 0
        (Test-Path -LiteralPath $vmRoot) | Should Be $false
        ($Global:h4CallLog | Where-Object { $_ -like 'New-VM*' }).Count | Should Be 0
        ($output -join "`n") | Should Match 'DRY-RUN'
    }

    It 'fails when ISO is missing' {
        $vmRoot = Join-Path $testTemp 'case_missing_iso'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot

        $null = & $scriptPath -IsoPath (Join-Path $testTemp 'does-not-exist.iso') -VmRoot $vmRoot *>&1
        $LASTEXITCODE | Should Not Be 0
    }

    It 'fails when ISO path is invalid (too small or directory)' {
        $vmRoot = Join-Path $testTemp 'case_small_iso'
        $smallIso = Join-Path $testTemp 'small.iso'
        Set-Content -LiteralPath $smallIso -Value 'tiny'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot

        $null = & $scriptPath -IsoPath $smallIso -VmRoot $vmRoot *>&1
        $LASTEXITCODE | Should Not Be 0
        $null = & $scriptPath -IsoPath $testTemp -VmRoot $vmRoot *>&1
        $LASTEXITCODE | Should Not Be 0
    }

    It 'fails on existing VM name collision without calling New-VM' {
        $vmRoot = Join-Path $testTemp 'case_vm_collision'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot -VmExists

        $null = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply *>&1
        $LASTEXITCODE | Should Not Be 0
        ($Global:h4CallLog | Where-Object { $_ -like 'New-VM*' }).Count | Should Be 0
    }

    It 'fails on existing VHDX collision without deleting or overwriting' {
        $vmRoot = Join-Path $testTemp 'case_vhdx_collision'
        $vhdxDir = Join-Path $vmRoot 'vhdx'
        New-Item -ItemType Directory -Path $vhdxDir -Force | Out-Null
        $vhdxFile = Join-Path $vhdxDir 'RC-H4-Windows-Acceptance.vhdx'
        Set-Content -LiteralPath $vhdxFile -Value 'existing-vhdx'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot

        $null = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply *>&1
        $LASTEXITCODE | Should Not Be 0
        (Get-Content -LiteralPath $vhdxFile -Raw).Trim() | Should Be 'existing-vhdx'
        ($Global:h4CallLog | Where-Object { $_ -like 'New-VM*' }).Count | Should Be 0
    }

    It 'fails on Hyper-V permission errors during VM enumeration' {
        $vmRoot = Join-Path $testTemp 'case_perm_error'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot -ThrowOnGetVm

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot *>&1
        $LASTEXITCODE | Should Not Be 0
        ($output -join "`n") | Should Match 'permission'
    }

    It 'fails when host disk space is insufficient for 80 GiB VHDX' {
        $vmRoot = Join-Path $testTemp 'case_low_disk'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot
        Mock Get-H4DriveFreeBytes { return [int64]20GB }

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot *>&1
        $LASTEXITCODE | Should Not Be 0
        ($output -join "`n") | Should Match 'Insufficient free disk space'
    }

    Context 'when required Hyper-V cmdlets are missing' {
        It 'fails when required Hyper-V cmdlets are missing' {
            $vmRoot = Join-Path $testTemp 'case_missing_cmdlet'
            Initialize-HappyHyperVMocks -VmRoot $vmRoot
            Mock Get-Command {
                param($Name)
                if ($Name -eq 'Enable-VMTPM') { return $null }
                return [pscustomobject]@{ Name = $Name }
            }

            $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot *>&1
            $LASTEXITCODE | Should Not Be 0
            ($output -join "`n") | Should Match 'Enable-VMTPM'
        }
    }

    It 'fails when an invalid SwitchName is provided' {
        $vmRoot = Join-Path $testTemp 'case_bad_switch'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -SwitchName 'NonExistentSwitch' *>&1
        $LASTEXITCODE | Should Not Be 0
        ($output -join "`n") | Should Match 'NonExistentSwitch'
    }

    It 'rejects reparse-point target paths before any mutation' {
        $realTarget = Join-Path $testTemp 'reparse_target'
        $junctionPath = Join-Path $testTemp 'reparse_junction'
        New-Item -ItemType Directory -Path $realTarget -Force | Out-Null
        New-Item -ItemType Junction -Path $junctionPath -Target $realTarget | Out-Null
        $vmRoot = Join-Path $junctionPath 'vm_child'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply *>&1
        $LASTEXITCODE | Should Not Be 0
        ($output -join "`n") | Should Match 'reparse point'
        ($Global:h4CallLog | Where-Object { $_ -like 'New-VM*' }).Count | Should Be 0
    }

    It 'executes combined New-VM and full security/boot sequence on -Apply' {
        $vmRoot = Join-Path $testTemp 'case_apply_ok'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply *>&1
        $LASTEXITCODE | Should Be 0
        ($Global:h4CallLog -join '|') | Should Match 'New-VM:RC-H4-Windows-Acceptance:2:'
        ($Global:h4CallLog -join '|') | Should Match '85899345920'
        ($Global:h4CallLog -join '|') | Should Match 'Remove-VMNetworkAdapter'
        ($Global:h4CallLog -join '|') | Should Match 'Set-VM\|'
        ($Global:h4CallLog -join '|') | Should Match 'Set-VMFirmware:SecureBoot:On:MicrosoftWindows'
        ($Global:h4CallLog -join '|') | Should Match 'Set-VMKeyProtector'
        ($Global:h4CallLog -join '|') | Should Match 'Enable-VMTPM'
        ($Global:h4CallLog -join '|') | Should Match 'Add-VMDvdDrive'
        ($Global:h4CallLog -join '|') | Should Match 'Set-VMFirmware:BootOrder'
        ($output -join "`n") | Should Match 'Provisioned and verified isolated VM'
    }

    It 'preserves VM and VHDX and reports cleanup guidance on Set-VM failure' {
        $vmRoot = Join-Path $testTemp 'case_fail_setvm'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot -ThrowOnSetVm

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply *>&1
        $LASTEXITCODE | Should Not Be 0
        ($Global:h4CallLog -contains 'Remove-VM:UNEXPECTED') | Should Be $false
        (Test-Path -LiteralPath (Join-Path $vmRoot 'vhdx\RC-H4-Windows-Acceptance.vhdx')) | Should Be $true
        ($output -join "`n") | Should Match 'configure_vm'
        ($output -join "`n") | Should Match 'Remove-VM -Name'
    }

    It 'preserves VM and VHDX on Enable-VMTPM failure' {
        $vmRoot = Join-Path $testTemp 'case_fail_tpm'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot -ThrowOnEnableTpm

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply *>&1
        $LASTEXITCODE | Should Not Be 0
        ($Global:h4CallLog -contains 'Remove-VM:UNEXPECTED') | Should Be $false
        ($output -join "`n") | Should Match 'configure_security'
    }

    It 'preserves VM and VHDX on Add-VMDvdDrive failure' {
        $vmRoot = Join-Path $testTemp 'case_fail_dvd'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot -ThrowOnAddDvd

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply *>&1
        $LASTEXITCODE | Should Not Be 0
        ($Global:h4CallLog -contains 'Remove-VM:UNEXPECTED') | Should Be $false
        ($output -join "`n") | Should Match 'attach_iso_and_boot_order'
    }

    It 'does not print success when final verification fails' {
        $vmRoot = Join-Path $testTemp 'case_fail_verify'
        Initialize-HappyHyperVMocks -VmRoot $vmRoot -EmptyBootOrder

        $output = & $scriptPath -IsoPath $dummyIso -VmRoot $vmRoot -Apply *>&1
        $LASTEXITCODE | Should Not Be 0
        ($output -join "`n") | Should Not Match 'Provisioned and verified'
        ($output -join "`n") | Should Match 'verify_final_state'
    }
}
