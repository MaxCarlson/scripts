#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

$moduleManifest = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\vm_lab.psd1'))
Import-Module $moduleManifest -Force

Describe 'vm_lab module' {
    $testTemp = Join-Path $PSScriptRoot '..\..\resource_coordinator\.pytest_tmp_root\pester_vm_lab'
    if (Test-Path -LiteralPath $testTemp) {
        Remove-Item -LiteralPath $testTemp -Recurse -Force
    }
    New-Item -ItemType Directory -Path $testTemp -Force | Out-Null

    It 'parses module files cleanly with zero syntax errors' {
        foreach ($file in @('vm_lab.psm1', 'Invoke-VmLab.ps1')) {
            $full = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$file"))
            $tokens = $null
            $errors = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$tokens, [ref]$errors)
            $errors.Count | Should Be 0
        }
    }

    It 'validates windows11-h4 template and rejects invalid configs' {
        $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
        $res = Test-VmLabConfig -Config $cfg
        $res.valid | Should Be $true
        $cfg.vm_name | Should Be 'RC-H4-Windows-Acceptance'
        $cfg.generation | Should Be 2
        $cfg.cpu_count | Should Be 4

        $bad = $cfg | ConvertTo-Json -Depth 5 | ConvertFrom-Json
        $bad.generation = 1
        $threw = $false
        try { $null = Test-VmLabConfig -Config $bad } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'creates, reads, and verifies ownership manifests by VM ID and config path' {
        $manifestRoot = Join-Path $testTemp 'manifests_own'
        $vmId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        $cfgPath = Join-Path $testTemp 'vm_own\vm'
        $mod = Get-Module vm_lab
        & $mod {
            param($mRoot, $id, $cPath)
            $m = [pscustomobject]@{
                schema_version  = 1
                vm_name         = 'Lab-VM-1'
                vm_id           = $id
                created_at      = '2026-11-15T00:00:00Z'
                vm_config_path  = $cPath
                vhdx_path       = 'C:\lab\vhdx\Lab-VM-1.vhdx'
                template_id     = 'windows11-h4'
                owner_namespace = 'test.ns'
                operation_id    = 'op123'
            }
            $null = Write-VmLabOwnershipManifest -Manifest $m -ManifestRoot $mRoot
        } $manifestRoot $vmId $cfgPath

        $loaded = Get-VmLabOwnershipManifest -VmName 'Lab-VM-1' -ManifestRoot $manifestRoot
        $loaded.vm_id | Should Be $vmId

        $goodVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]$vmId; ConfigurationLocation = $cfgPath }
        (Test-VmLabOwnership -Vm $goodVm -ManifestRoot $manifestRoot).owned | Should Be $true

        $wrongIdVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]'99999999-9999-9999-9999-999999999999'; ConfigurationLocation = $cfgPath }
        (Test-VmLabOwnership -Vm $wrongIdVm -ManifestRoot $manifestRoot).owned | Should Be $false

        $wrongPathVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]$vmId; ConfigurationLocation = 'C:\other\path' }
        (Test-VmLabOwnership -Vm $wrongPathVm -ManifestRoot $manifestRoot).owned | Should Be $false

        $unmanagedVm = [pscustomobject]@{ Name = 'Other-VM'; Id = [guid]$vmId; ConfigurationLocation = $cfgPath }
        (Test-VmLabOwnership -Vm $unmanagedVm -ManifestRoot $manifestRoot).owned | Should Be $false
    }

    Context 'with mocked Hyper-V operations' {
        BeforeEach {
            $Global:vmLabLog = [System.Collections.Generic.List[string]]::new()
            $Global:vmLabManifestRoot = Join-Path $testTemp ("m_" + [guid]::NewGuid().ToString('N'))
            $Global:vmLabVmRoot = Join-Path $testTemp ("r_" + [guid]::NewGuid().ToString('N'))
            $Global:vmLabVms = @(
                [pscustomobject]@{
                    Name                  = 'Unmanaged-VM'
                    Id                    = [guid]'22222222-2222-2222-2222-222222222222'
                    State                 = 'Off'
                    Generation            = 2
                    ProcessorCount        = 2
                    MemoryStartup         = 4GB
                    MemoryMinimum         = 2GB
                    MemoryMaximum         = 4GB
                    CheckpointType        = 'Standard'
                    ConfigurationLocation = 'C:\unmanaged\vm'
                },
                [pscustomobject]@{
                    Name                  = 'Managed-VM'
                    Id                    = [guid]'33333333-3333-3333-3333-333333333333'
                    State                 = 'Off'
                    Generation            = 2
                    ProcessorCount        = 4
                    MemoryStartup         = 6GB
                    MemoryMinimum         = 4GB
                    MemoryMaximum         = 8GB
                    CheckpointType        = 'Standard'
                    ConfigurationLocation = (Join-Path $Global:vmLabVmRoot 'vm')
                }
            )
            $mod = Get-Module vm_lab
            & $mod {
                param($mRoot, $vRoot)
                $null = Write-VmLabOwnershipManifest -ManifestRoot $mRoot -Manifest ([pscustomobject]@{
                    schema_version  = 1
                    vm_name         = 'Managed-VM'
                    vm_id           = '33333333-3333-3333-3333-333333333333'
                    created_at      = '2026-11-15T00:00:00Z'
                    vm_config_path  = (Join-Path $vRoot 'vm')
                    vhdx_path       = (Join-Path $vRoot 'vhdx\Managed-VM.vhdx')
                    template_id     = 'windows11-h4'
                    owner_namespace = 'test.ns'
                    operation_id    = 'op-managed'
                })
            } $Global:vmLabManifestRoot $Global:vmLabVmRoot

            Mock -ModuleName vm_lab Test-VmLabAdministrator { return $true }
            Mock -ModuleName vm_lab Get-VmLabDriveFreeBytes { return [int64]200GB }
            Mock -ModuleName vm_lab Get-VmLabHostMemoryInfo {
                return [pscustomobject]@{ TotalPhysicalBytes = [int64]64GB; FreePhysicalBytes = [int64]16GB }
            }
            Mock -ModuleName vm_lab Get-VMHost { return [pscustomobject]@{ ComputerName = 'XERES' } }
            Mock -ModuleName vm_lab Get-VM { return $Global:vmLabVms }
            Mock -ModuleName vm_lab Get-VMSwitch { return @() }
            Mock -ModuleName vm_lab New-VM {
                param($Name, $Generation, $MemoryStartupBytes, $Path, $NewVHDPath, $NewVHDSizeBytes)
                $Global:vmLabLog.Add("New-VM:$Name")
                return [pscustomobject]@{ Name = $Name; Id = [guid]'44444444-4444-4444-4444-444444444444' }
            }
            Mock -ModuleName vm_lab Get-VMNetworkAdapter { return @([pscustomobject]@{ Name = 'NIC' }) }
            Mock -ModuleName vm_lab Remove-VMNetworkAdapter { $Global:vmLabLog.Add('Remove-VMNetworkAdapter') }
            Mock -ModuleName vm_lab Set-VM { $Global:vmLabLog.Add('Set-VM') }
            Mock -ModuleName vm_lab Set-VMFirmware { $Global:vmLabLog.Add('Set-VMFirmware') }
            Mock -ModuleName vm_lab Set-VMKeyProtector { $Global:vmLabLog.Add('Set-VMKeyProtector') }
            Mock -ModuleName vm_lab Enable-VMTPM { $Global:vmLabLog.Add('Enable-VMTPM') }
            Mock -ModuleName vm_lab Start-VM { param($Name) $Global:vmLabLog.Add("Start-VM:$Name") }
            Mock -ModuleName vm_lab Stop-VM { param($Name) $Global:vmLabLog.Add("Stop-VM:$Name") }
            Mock -ModuleName vm_lab Checkpoint-VM { param($Name, $SnapshotName) $Global:vmLabLog.Add("Checkpoint-VM:$Name`:$SnapshotName") }
            Mock -ModuleName vm_lab Get-VMSnapshot {
                param($VMName)
                return @([pscustomobject]@{ Name = 'clean-base'; Id = [guid]'55555555-5555-5555-5555-555555555555'; CreationTime = [datetime]'2026-11-15'; SnapshotType = 'Standard' })
            }
        }

        It 'refuses to modify unmanaged VMs' {
            foreach ($act in @(
                { Start-VmLabMachine -Name 'Unmanaged-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot },
                { Stop-VmLabMachine -Name 'Unmanaged-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot },
                { New-VmLabCheckpoint -Name 'Unmanaged-VM' -CheckpointName 'cp1' -Apply -ManifestRoot $Global:vmLabManifestRoot }
            )) {
                $err = $null
                try { $null = & $act } catch { $err = $_.Exception.Message }
                $err | Should Match 'unmanaged VM'
            }
        }

        It 'performs no mutations in dry-run and -WhatIf modes' {
            $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg.vm_name = 'New-DryRun-VM'
            $cfg.vm_root = Join-Path $testTemp 'dryrun_vm'

            $null = New-VmLabMachine -Config $cfg -ManifestRoot $Global:vmLabManifestRoot
            $null = New-VmLabMachine -Config $cfg -Apply -WhatIf -ManifestRoot $Global:vmLabManifestRoot
            $null = Start-VmLabMachine -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $null = Stop-VmLabMachine -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $null = New-VmLabCheckpoint -Name 'Managed-VM' -CheckpointName 'cp1' -ManifestRoot $Global:vmLabManifestRoot

            $Global:vmLabLog.Count | Should Be 0
        }

        It 'creates a new lab VM and writes ownership manifest on -Apply' {
            $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg.vm_name = 'Created-Lab-VM'
            $cfg.vm_root = Join-Path $testTemp 'created_lab_vm'

            $res = New-VmLabMachine -Config $cfg -Apply -ManifestRoot $Global:vmLabManifestRoot
            $res.status | Should Be 'created'
            ($Global:vmLabLog -contains 'New-VM:Created-Lab-VM') | Should Be $true
            (Test-Path -LiteralPath $res.manifest_path) | Should Be $true
        }

        It 'enforces host RAM reserve on start and starts when safe' {
            Mock -ModuleName vm_lab Get-VmLabHostMemoryInfo {
                return [pscustomobject]@{ TotalPhysicalBytes = [int64]64GB; FreePhysicalBytes = [int64]7GB }
            }
            $err = $null
            try { $null = Start-VmLabMachine -Name 'Managed-VM' -MinHostReserveBytes 4GB -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $err = $_.Exception.Message }
            $err | Should Match 'free host RAM'

            Mock -ModuleName vm_lab Get-VmLabHostMemoryInfo {
                return [pscustomobject]@{ TotalPhysicalBytes = [int64]64GB; FreePhysicalBytes = [int64]16GB }
            }
            $res = Start-VmLabMachine -Name 'Managed-VM' -MinHostReserveBytes 4GB -Apply -ManifestRoot $Global:vmLabManifestRoot
            $res.status | Should Be 'started'
            ($Global:vmLabLog -contains 'Start-VM:Managed-VM') | Should Be $true
        }

        It 'performs graceful stop and checkpoint create/list' {
            $stopRes = Stop-VmLabMachine -Name 'Managed-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot
            $stopRes.graceful | Should Be $true
            ($Global:vmLabLog -contains 'Stop-VM:Managed-VM') | Should Be $true

            $cpRes = New-VmLabCheckpoint -Name 'Managed-VM' -CheckpointName 'pre-h4' -Apply -ManifestRoot $Global:vmLabManifestRoot
            $cpRes.status | Should Be 'checkpoint_created'
            ($Global:vmLabLog -contains 'Checkpoint-VM:Managed-VM:pre-h4') | Should Be $true

            $snaps = Get-VmLabCheckpoint -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $snaps.Count | Should Be 1
            $snaps[0].name | Should Be 'clean-base'
        }

        It 'produces valid JSON contracts via Invoke-VmLab' {
            $listJson = Invoke-VmLab -Operation list -Json -ManifestRoot $Global:vmLabManifestRoot | ConvertFrom-Json
            $listJson.Count | Should Be 2
            ($listJson | Where-Object { $_.name -eq 'Managed-VM' }).owned | Should Be $true
            ($listJson | Where-Object { $_.name -eq 'Unmanaged-VM' }).owned | Should Be $false

            $statusJson = Invoke-VmLab -Operation status -Name 'Managed-VM' -Json -ManifestRoot $Global:vmLabManifestRoot | ConvertFrom-Json
            $statusJson.owned | Should Be $true

            $cpJson = Invoke-VmLab -Operation checkpoints -Name 'Managed-VM' -Json -ManifestRoot $Global:vmLabManifestRoot | ConvertFrom-Json
            $cpJson.name | Should Be 'clean-base'
        }

        It 'detects existing VM name collision and propagates Get-VM errors' {
            $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg.vm_name = 'Managed-VM'
            $cfg.vm_root = Join-Path $testTemp 'collide_vm'
            $err1 = $null
            try { $null = Test-VmLabPlan -Config $cfg -ManifestRoot $Global:vmLabManifestRoot } catch { $err1 = $_.Exception.Message }
            $err1 | Should Match 'already exists'

            Mock -ModuleName vm_lab Get-VM { throw 'Access denied to Hyper-V' }
            $err2 = $null
            try { $null = Get-VmLabList -ManifestRoot $Global:vmLabManifestRoot } catch { $err2 = $_.Exception.Message }
            $err2 | Should Match 'Access denied'
        }
    }
}
