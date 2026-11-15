#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

$moduleManifest = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\vm_lab.psd1'))
$cliScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\Invoke-VmLab.ps1'))
Import-Module $moduleManifest -Force

Describe 'vm_lab module' {
    $testTemp = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.pytest_tmp_root\pester_vm_lab'))
    if (Test-Path -LiteralPath $testTemp) {
        Remove-Item -LiteralPath $testTemp -Recurse -Force
    }
    New-Item -ItemType Directory -Path $testTemp -Force | Out-Null

    It 'parses module files cleanly with zero syntax errors' {
        $filesToParse = @('vm_lab.psm1', 'Invoke-VmLab.ps1') + @(
            Get-ChildItem -Path (Join-Path $PSScriptRoot '..\src') -Filter '*.ps1' -ErrorAction SilentlyContinue |
                ForEach-Object { "src\$($_.Name)" }
        )
        foreach ($file in $filesToParse) {
            $full = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$file"))
            $tokens = $null
            $errors = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$tokens, [ref]$errors)
            $errors.Count | Should Be 0
        }
    }

    It 'validates windows11-h4 template and rejects invalid schema versions, types, and paths' {
        $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
        $res = Test-VmLabConfig -Config $cfg
        $res.valid | Should Be $true
        $cfg.vm_name | Should Be 'RC-H4-Windows-Acceptance'
        $cfg.generation | Should Be 2
        $cfg.cpu_count | Should Be 4

        $invalidCases = @(
            { param($c) $c.schema_version = 2 },
            { param($c) $c.schema_version = '1' },
            { param($c) $c.generation = 1 },
            { param($c) $c.generation = '2' },
            { param($c) $c.vtpm_enabled = 'false' },
            { param($c) $c.automatic_checkpoints_enabled = 'true' },
            { param($c) $c.memory_minimum_bytes = -1 },
            { param($c) $c.memory_startup_bytes = 2GB; $c.memory_minimum_bytes = 4GB },
            { param($c) $c.memory_maximum_bytes = 4GB; $c.memory_startup_bytes = 6GB },
            { param($c) $c.vhdx_format = 'Differencing' },
            { param($c) $c.vm_root = 'relative\path' },
            { param($c) $c.vm_root = '\\server\share\vm' },
            { param($c) $c.vm_root = 'C:\Lab\..\Other' },
            { param($c) $c.vm_root = 'C:\' },
            { param($c) $c.vm_name = 'Bad:Name' },
            { param($c) $c.automatic_start_action = 'InvalidAction' },
            { param($c) $c.secure_boot | Add-Member -NotePropertyName 'unknown_flag' -NotePropertyValue $true }
        )

        foreach ($mutator in $invalidCases) {
            $bad = $cfg | ConvertTo-Json -Depth 6 | ConvertFrom-Json
            & $mutator $bad
            $threw = $false
            try { $null = Test-VmLabConfig -Config $bad } catch { $threw = $true }
            $threw | Should Be $true
        }
    }

    It 'enforces strict path-boundary ownership and rejects prefix collisions, cross-volume, missing, and corrupt manifests' {
        $manifestRoot = Join-Path $testTemp 'manifests_own'
        $vmId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        $cfgPath = Join-Path $testTemp 'Lab\VM'
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

        # Exact match and valid descendant directory are owned
        $goodVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]$vmId; ConfigurationLocation = $cfgPath }
        (Test-VmLabOwnership -Vm $goodVm -ManifestRoot $manifestRoot).owned | Should Be $true

        $descendantVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]$vmId; ConfigurationLocation = (Join-Path $cfgPath 'Virtual Machines') }
        (Test-VmLabOwnership -Vm $descendantVm -ManifestRoot $manifestRoot).owned | Should Be $true

        # Sibling path-prefix collision MUST fail (C:\...\Lab\VM vs C:\...\Lab\VM2)
        $siblingVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]$vmId; ConfigurationLocation = ($cfgPath + '2') }
        $sibRes = Test-VmLabOwnership -Vm $siblingVm -ManifestRoot $manifestRoot
        $sibRes.owned | Should Be $false
        $sibRes.ownership_state | Should Be 'mismatched'

        # Ancestor directory MUST fail
        $ancestorVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]$vmId; ConfigurationLocation = (Split-Path -Parent $cfgPath) }
        (Test-VmLabOwnership -Vm $ancestorVm -ManifestRoot $manifestRoot).owned | Should Be $false

        # Cross-volume substitution MUST fail
        $crossVolVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]$vmId; ConfigurationLocation = 'D:\Lab\VM' }
        (Test-VmLabOwnership -Vm $crossVolVm -ManifestRoot $manifestRoot).owned | Should Be $false

        # Missing live ConfigurationLocation MUST fail closed
        $emptyLocVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]$vmId; ConfigurationLocation = '' }
        (Test-VmLabOwnership -Vm $emptyLocVm -ManifestRoot $manifestRoot).owned | Should Be $false

        # VM ID mismatch MUST fail
        $wrongIdVm = [pscustomobject]@{ Name = 'Lab-VM-1'; Id = [guid]'99999999-9999-9999-9999-999999999999'; ConfigurationLocation = $cfgPath }
        (Test-VmLabOwnership -Vm $wrongIdVm -ManifestRoot $manifestRoot).owned | Should Be $false

        # Missing manifest
        $unmanagedVm = [pscustomobject]@{ Name = 'Other-VM'; Id = [guid]$vmId; ConfigurationLocation = $cfgPath }
        $missRes = Test-VmLabOwnership -Vm $unmanagedVm -ManifestRoot $manifestRoot
        $missRes.owned | Should Be $false
        $missRes.ownership_state | Should Be 'missing'

        # Corrupt JSON manifest
        [System.IO.File]::WriteAllText((Join-Path $manifestRoot 'Corrupt-VM.json'), '{not valid json')
        $corruptVm = [pscustomobject]@{ Name = 'Corrupt-VM'; Id = [guid]$vmId; ConfigurationLocation = $cfgPath }
        $corruptRes = Test-VmLabOwnership -Vm $corruptVm -ManifestRoot $manifestRoot
        $corruptRes.owned | Should Be $false
        $corruptRes.ownership_state | Should Be 'corrupt'

        # Wrong manifest schema_version -> untrusted
        [System.IO.File]::WriteAllText((Join-Path $manifestRoot 'BadSchema-VM.json'), '{"schema_version":99,"vm_name":"BadSchema-VM"}')
        $badSchemaVm = [pscustomobject]@{ Name = 'BadSchema-VM'; Id = [guid]$vmId; ConfigurationLocation = $cfgPath }
        $badSchemaRes = Test-VmLabOwnership -Vm $badSchemaVm -ManifestRoot $manifestRoot
        $badSchemaRes.owned | Should Be $false
        $badSchemaRes.ownership_state | Should Be 'untrusted'
    }

    It 'rejects reparse-point manifests and refuses concurrent/overwrite manifest writes' {
        $manifestRoot = Join-Path $testTemp 'manifests_atomic'
        $vmId = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'
        $cfgPath = Join-Path $testTemp 'atomic_vm\vm'
        $mod = Get-Module vm_lab
        $manifestObj = [pscustomobject]@{
            schema_version  = 1
            vm_name         = 'Atomic-VM'
            vm_id           = $vmId
            created_at      = '2026-11-15T00:00:00Z'
            vm_config_path  = $cfgPath
            vhdx_path       = (Join-Path $testTemp 'atomic_vm\vhdx\Atomic-VM.vhdx')
            template_id     = 'windows11-h4'
            owner_namespace = 'test.ns'
            operation_id    = 'op-atomic'
        }
        & $mod { param($m, $r) $null = Write-VmLabOwnershipManifest -Manifest $m -ManifestRoot $r } $manifestObj $manifestRoot

        # Second write to same VM name must fail (no silent overwrite)
        $threw = $false
        try {
            & $mod { param($m, $r) $null = Write-VmLabOwnershipManifest -Manifest $m -ManifestRoot $r } $manifestObj $manifestRoot
        } catch {
            $threw = $true
        }
        $threw | Should Be $true

        # Reparse-point/junction in manifest root must be rejected
        $junctionTarget = Join-Path $testTemp 'junction_target'
        New-Item -ItemType Directory -Path $junctionTarget -Force | Out-Null
        $junctionPath = Join-Path $testTemp 'manifests_junction'
        New-Item -ItemType Junction -Path $junctionPath -Target $junctionTarget | Out-Null
        $rpVm = [pscustomobject]@{ Name = 'Atomic-VM'; Id = [guid]$vmId; ConfigurationLocation = $cfgPath }
        $rpRes = Test-VmLabOwnership -Vm $rpVm -ManifestRoot $junctionPath
        $rpRes.owned | Should Be $false
        $rpRes.ownership_state | Should Be 'untrusted'
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
            $Global:vmLabSnaps = @(
                [pscustomobject]@{ Name = 'clean-base'; Id = [guid]'55555555-5555-5555-5555-555555555555'; CreationTime = [datetime]'2026-11-15T00:00:00Z'; SnapshotType = 'Standard' }
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
            Mock -ModuleName vm_lab Get-VMSwitch { return @([pscustomobject]@{ Name = 'LabSwitch' }) }
            Mock -ModuleName vm_lab New-VHD {
                param($Path, $SizeBytes, [switch]$Dynamic, [switch]$Fixed)
                $fmt = if ($Fixed) { 'Fixed' } else { 'Dynamic' }
                $Global:vmLabLog.Add("New-VHD:$fmt`:$Path")
                $dir = Split-Path -Parent $Path
                if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
                [System.IO.File]::WriteAllText($Path, "mock-vhd-$fmt")
                return [pscustomobject]@{ Path = $Path; VhdFormat = 'VHDX'; VhdType = $fmt }
            }
            Mock -ModuleName vm_lab New-VM {
                param($Name, $Generation, $MemoryStartupBytes, $Path, $VHDPath)
                $Global:vmLabLog.Add("New-VM:$Name")
                $created = [pscustomobject]@{
                    Name                  = $Name
                    Id                    = [guid]'44444444-4444-4444-4444-444444444444'
                    State                 = 'Off'
                    Generation            = $Generation
                    ProcessorCount        = 4
                    MemoryStartup         = $MemoryStartupBytes
                    MemoryMinimum         = 4GB
                    MemoryMaximum         = 8GB
                    CheckpointType        = 'Standard'
                    ConfigurationLocation = $Path
                }
                $Global:vmLabVms += $created
                return $created
            }
            Mock -ModuleName vm_lab Get-VMNetworkAdapter { return @([pscustomobject]@{ Name = 'NIC' }) }
            Mock -ModuleName vm_lab Remove-VMNetworkAdapter { $Global:vmLabLog.Add('Remove-VMNetworkAdapter') }
            Mock -ModuleName vm_lab Add-VMNetworkAdapter { param($VMName, $SwitchName) $Global:vmLabLog.Add("Add-VMNetworkAdapter:$SwitchName") }
            Mock -ModuleName vm_lab Set-VM { $Global:vmLabLog.Add('Set-VM') }
            Mock -ModuleName vm_lab Set-VMFirmware { $Global:vmLabLog.Add('Set-VMFirmware') }
            Mock -ModuleName vm_lab Set-VMKeyProtector { $Global:vmLabLog.Add('Set-VMKeyProtector') }
            Mock -ModuleName vm_lab Enable-VMTPM { $Global:vmLabLog.Add('Enable-VMTPM') }
            Mock -ModuleName vm_lab Start-VM {
                param($Name, $VM)
                $targetName = if ($VM) { $VM.Name } else { $Name }
                $Global:vmLabLog.Add("Start-VM:$targetName")
                ($Global:vmLabVms | Where-Object { $_.Name -eq $targetName }).State = 'Running'
            }
            Mock -ModuleName vm_lab Stop-VM {
                param($Name, $VM)
                $targetName = if ($VM) { $VM.Name } else { $Name }
                $Global:vmLabLog.Add("Stop-VM:$targetName")
                ($Global:vmLabVms | Where-Object { $_.Name -eq $targetName }).State = 'Off'
            }
            Mock -ModuleName vm_lab Checkpoint-VM {
                param($Name, $VM, $SnapshotName)
                $targetName = if ($VM) { $VM.Name } else { $Name }
                $Global:vmLabLog.Add("Checkpoint-VM:$targetName`:$SnapshotName")
                $Global:vmLabSnaps += [pscustomobject]@{
                    Name         = $SnapshotName
                    Id           = [guid]'66666666-6666-6666-6666-666666666666'
                    CreationTime = [datetime]'2026-11-15T01:00:00Z'
                    SnapshotType = 'Standard'
                }
            }
            Mock -ModuleName vm_lab Get-VMSnapshot {
                param($VMName)
                return $Global:vmLabSnaps
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

        It 'performs no mutations in dry-run and -WhatIf modes even with -Apply' {
            $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg.vm_name = 'New-DryRun-VM'
            $cfg.vm_root = Join-Path $testTemp 'dryrun_vm'

            $null = New-VmLabMachine -Config $cfg -ManifestRoot $Global:vmLabManifestRoot
            $null = New-VmLabMachine -Config $cfg -Apply -WhatIf -ManifestRoot $Global:vmLabManifestRoot
            $null = Start-VmLabMachine -Name 'Managed-VM' -Apply -WhatIf -ManifestRoot $Global:vmLabManifestRoot
            $null = Stop-VmLabMachine -Name 'Managed-VM' -Apply -WhatIf -ManifestRoot $Global:vmLabManifestRoot
            $null = New-VmLabCheckpoint -Name 'Managed-VM' -CheckpointName 'cp1' -Apply -WhatIf -ManifestRoot $Global:vmLabManifestRoot

            $Global:vmLabLog.Count | Should Be 0
        }

        It 'creates Dynamic and Fixed VHDX VMs and handles Unicode and spaces in paths' {
            $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg.vm_name = 'Created-Lab-VM'
            $cfg.vm_root = Join-Path $testTemp 'Ünicode Lab VM'
            $cfg.vhdx_format = 'Fixed'

            $res = New-VmLabMachine -Config $cfg -Apply -ManifestRoot $Global:vmLabManifestRoot
            $res.status | Should Be 'created'
            $res.vhdx_format | Should Be 'Fixed'
            ($Global:vmLabLog -match '^New-VHD:Fixed:').Count | Should Be 1
            ($Global:vmLabLog -contains 'New-VM:Created-Lab-VM') | Should Be $true
            (Test-Path -LiteralPath $res.manifest_path) | Should Be $true
        }

        It 'preserves partial artifacts and writes no manifest on failure after VM or vTPM creation' {
            # Failure at Set-VM after VM registration
            Mock -ModuleName vm_lab Set-VM { throw 'Simulated Set-VM failure' }
            $cfg1 = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg1.vm_name = 'Partial-SetVM-Fail'
            $cfg1.vm_root = Join-Path $testTemp 'partial_setvm'
            $err1 = $null
            try { $null = New-VmLabMachine -Config $cfg1 -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $err1 = $_.Exception.Message }
            $err1 | Should Match "stage 'configure_vm'"
            $err1 | Should Match 'vhd_created=True'
            $err1 | Should Match 'vm_created=True'
            (Test-Path -LiteralPath (Join-Path $cfg1.vm_root 'vhdx\Partial-SetVM-Fail.vhdx')) | Should Be $true
            (Test-Path -LiteralPath (Join-Path $Global:vmLabManifestRoot 'Partial-SetVM-Fail.json')) | Should Be $false

            # Failure at vTPM setup
            Mock -ModuleName vm_lab Set-VM { $Global:vmLabLog.Add('Set-VM') }
            Mock -ModuleName vm_lab Enable-VMTPM { throw 'Simulated vTPM failure' }
            $cfg2 = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg2.vm_name = 'Partial-Vtpm-Fail'
            $cfg2.vm_root = Join-Path $testTemp 'partial_vtpm'
            $err2 = $null
            try { $null = New-VmLabMachine -Config $cfg2 -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $err2 = $_.Exception.Message }
            $err2 | Should Match "stage 'configure_vtpm'"
            (Test-Path -LiteralPath (Join-Path $cfg2.vm_root 'vhdx\Partial-Vtpm-Fail.vhdx')) | Should Be $true
            (Test-Path -LiteralPath (Join-Path $Global:vmLabManifestRoot 'Partial-Vtpm-Fail.json')) | Should Be $false
        }

        It 'blocks concurrent provisioning lock and existing VHDX or non-empty directory collisions' {
            $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg.vm_name = 'Collide-VM'
            $cfg.vm_root = Join-Path $testTemp 'nonempty_root'
            New-Item -ItemType Directory -Path $cfg.vm_root -Force | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $cfg.vm_root 'existing.txt'), 'keep')

            $errDir = $null
            try { $null = Test-VmLabPlan -Config $cfg -ManifestRoot $Global:vmLabManifestRoot } catch { $errDir = $_.Exception.Message }
            $errDir | Should Match 'not empty'

            # Concurrent lock file
            $cfg.vm_root = Join-Path $testTemp 'lock_vm'
            New-Item -ItemType Directory -Path $Global:vmLabManifestRoot -Force | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $Global:vmLabManifestRoot 'Collide-VM.lock'), 'locked')
            $errLock = $null
            try { $null = New-VmLabMachine -Config $cfg -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $errLock = $_.Exception.Message }
            $errLock | Should Match 'Concurrent provisioning'
        }

        It 'enforces host RAM reserve on start and handles already-running and transitional states' {
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

            # Already running -> idempotent no-op
            $Global:vmLabLog.Clear()
            $res2 = Start-VmLabMachine -Name 'Managed-VM' -MinHostReserveBytes 4GB -Apply -ManifestRoot $Global:vmLabManifestRoot
            $res2.status | Should Be 'already_running'
            $Global:vmLabLog.Count | Should Be 0

            # Transitional state -> refuses
            $Global:vmLabVms[1].State = 'Starting'
            $errTrans = $null
            try { $null = Start-VmLabMachine -Name 'Managed-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $errTrans = $_.Exception.Message }
            $errTrans | Should Match 'transitional state'
        }

        It 'detects changed VM identity before mutation' {
            $Global:vmLabGetVmCalls = 0
            Mock -ModuleName vm_lab Get-VM {
                $Global:vmLabGetVmCalls++
                if ($Global:vmLabGetVmCalls -ge 2) {
                    $tampered = $Global:vmLabVms[1] | Select-Object *
                    $tampered.Name = 'Renamed-VM'
                    return @($Global:vmLabVms[0], $tampered)
                }
                return $Global:vmLabVms
            }
            $err = $null
            try { $null = Start-VmLabMachine -Name 'Managed-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $err = $_.Exception.Message }
            $err | Should Match 'identity changed'
        }

        It 'performs graceful stop, reports shutdown_requested on timeout, and surfaces integration service errors' {
            # Already stopped -> no-op
            $already = Stop-VmLabMachine -Name 'Managed-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot
            $already.status | Should Be 'already_stopped'
            $Global:vmLabLog.Count | Should Be 0

            # Running -> graceful stop
            $Global:vmLabVms[1].State = 'Running'
            $stopRes = Stop-VmLabMachine -Name 'Managed-VM' -ShutdownTimeoutSeconds 1 -Apply -ManifestRoot $Global:vmLabManifestRoot
            $stopRes.status | Should Be 'stopped'
            $stopRes.graceful | Should Be $true
            ($Global:vmLabLog -contains 'Stop-VM:Managed-VM') | Should Be $true

            # Timeout when guest stays Running
            $Global:vmLabVms[1].State = 'Running'
            Mock -ModuleName vm_lab Stop-VM { param($VM) $Global:vmLabLog.Add("Stop-VM-Slow:$($VM.Name)") }
            $timeoutRes = Stop-VmLabMachine -Name 'Managed-VM' -ShutdownTimeoutSeconds 0 -Apply -ManifestRoot $Global:vmLabManifestRoot
            $timeoutRes.status | Should Be 'shutdown_requested'
            $timeoutRes.timed_out | Should Be $true

            # Integration service failure
            Mock -ModuleName vm_lab Stop-VM { throw 'Guest shutdown integration service unavailable' }
            $errStop = $null
            try { $null = Stop-VmLabMachine -Name 'Managed-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $errStop = $_.Exception.Message }
            $errStop | Should Match 'hard power-off is disabled'
        }

        It 'verifies checkpoint creation, rejects duplicates and disabled policy, and returns checkpoint ID' {
            $cpRes = New-VmLabCheckpoint -Name 'Managed-VM' -CheckpointName 'pre-h4' -Apply -ManifestRoot $Global:vmLabManifestRoot
            $cpRes.status | Should Be 'checkpoint_created'
            $cpRes.checkpoint_id | Should Be '66666666-6666-6666-6666-666666666666'

            # Duplicate checkpoint name
            $errDup = $null
            try { $null = New-VmLabCheckpoint -Name 'Managed-VM' -CheckpointName 'clean-base' -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $errDup = $_.Exception.Message }
            $errDup | Should Match 'already exists'

            # Disabled checkpoint policy
            $Global:vmLabVms[1].CheckpointType = 'Disabled'
            $errDis = $null
            try { $null = New-VmLabCheckpoint -Name 'Managed-VM' -CheckpointName 'cp2' -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $errDis = $_.Exception.Message }
            $errDis | Should Match 'Disabled'
        }

        It 'produces valid single-document JSON contracts via Invoke-VmLab including empty and single-item lists' {
            $listJson = Invoke-VmLab -Operation list -Json -ManifestRoot $Global:vmLabManifestRoot | ConvertFrom-Json
            $listJson.Count | Should Be 2
            ($listJson | Where-Object { $_.name -eq 'Managed-VM' }).owned | Should Be $true
            ($listJson | Where-Object { $_.name -eq 'Unmanaged-VM' }).owned | Should Be $false

            # Empty list must still be valid JSON []
            Mock -ModuleName vm_lab Get-VM { return @() }
            $emptyRaw = Invoke-VmLab -Operation list -Json -ManifestRoot $Global:vmLabManifestRoot
            $emptyParsed = $emptyRaw | ConvertFrom-Json
            $emptyParsed.Count | Should Be 0

            # Single-item list must still be a JSON array
            Mock -ModuleName vm_lab Get-VM { return @($Global:vmLabVms[1]) }
            $singleRaw = Invoke-VmLab -Operation list -Json -ManifestRoot $Global:vmLabManifestRoot
            $singleRaw.TrimStart().StartsWith('[') | Should Be $true
        }

        It 'detects existing VM name collision, unsafe existing VM paths, and propagates Get-VM permission errors' {
            $cfg = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg.vm_name = 'Managed-VM'
            $cfg.vm_root = Join-Path $testTemp 'collide_vm'
            $err1 = $null
            try { $null = Test-VmLabPlan -Config $cfg -ManifestRoot $Global:vmLabManifestRoot } catch { $err1 = $_.Exception.Message }
            $err1 | Should Match 'already exists'

            # Unsafe/uninspectable ConfigurationLocation on an existing VM must block rather than silently pass
            $Global:vmLabUnsafeVm = $Global:vmLabVms[0] | Select-Object *
            $Global:vmLabUnsafeVm.ConfigurationLocation = '\\unc-server\share\unsafe-vm'
            Mock -ModuleName vm_lab Get-VM { return @($Global:vmLabUnsafeVm) }
            $cfg2 = Get-VmLabTemplate -TemplateName 'windows11-h4'
            $cfg2.vm_name = 'Brand-New-VM'
            $cfg2.vm_root = Join-Path $testTemp 'brand_new_vm'
            $errUnsafe = $null
            try { $null = Test-VmLabPlan -Config $cfg2 -ManifestRoot $Global:vmLabManifestRoot } catch { $errUnsafe = $_.Exception.Message }
            $errUnsafe | Should Match 'Cannot safely verify path non-conflict'

            Mock -ModuleName vm_lab Get-VM { throw 'Access denied to Hyper-V' }
            $err2 = $null
            try { $null = Get-VmLabList -ManifestRoot $Global:vmLabManifestRoot } catch { $err2 = $_.Exception.Message }
            $err2 | Should Match 'Access denied'
        }

        It 'lists and validates all built-in templates via templates and template-info' {
            $tpls = Invoke-VmLab -Operation templates -Json | ConvertFrom-Json
            $tplIds = @($tpls | ForEach-Object { $_.template_id })
            ($tplIds -contains 'windows11-h4') | Should Be $true
            ($tplIds -contains 'windows11-dev') | Should Be $true
            ($tplIds -contains 'windows11-light') | Should Be $true
            ($tplIds -contains 'windows11-empty') | Should Be $true

            $info = Invoke-VmLab -Operation template-info -TemplateName 'windows11-dev' -Json | ConvertFrom-Json
            $info.valid | Should Be $true
            $info.config.generation | Should Be 2
        }

        It 'runs quickstart dry-run, separate create/start boundaries, and resumable existing-VM inspection' {
            $qsRoot = Join-Path $testTemp 'qs_dev_vm'
            $plan = Invoke-VmLab -Operation quickstart -TemplateName 'windows11-dev' -Name 'QS-Dev-01' -VmRoot $qsRoot -ManifestRoot $Global:vmLabManifestRoot -Json | ConvertFrom-Json
            $plan.status | Should Be 'planned'
            $plan.vm_state | Should Be 'NotCreated'
            $Global:vmLabLog.Count | Should Be 0

            # -Apply without -Start creates VM only
            $created = Invoke-VmLab -Operation quickstart -TemplateName 'windows11-dev' -Name 'QS-Dev-01' -VmRoot $qsRoot -Apply -ManifestRoot $Global:vmLabManifestRoot
            $created.status | Should Be 'created'
            $created.vm_state | Should Be 'Off'
            ($Global:vmLabLog -contains 'New-VM:QS-Dev-01') | Should Be $true
            ($Global:vmLabLog -contains 'Start-VM:QS-Dev-01') | Should Be $false

            # Re-running quickstart on existing owned VM inspects it and starts when -Start -Apply is passed
            $resumed = Invoke-VmLab -Operation quickstart -TemplateName 'windows11-dev' -Name 'QS-Dev-01' -VmRoot $qsRoot -Apply -Start -ManifestRoot $Global:vmLabManifestRoot
            $resumed.status | Should Be 'started'
            $resumed.vm_state | Should Be 'Running'

            # Refuses to adopt unmanaged VM
            $errUnm = $null
            try {
                $null = Invoke-VmLab -Operation quickstart -TemplateName 'windows11-dev' -Name 'Unmanaged-VM' -VmRoot (Join-Path $testTemp 'qs_unm') -ManifestRoot $Global:vmLabManifestRoot
            } catch {
                $errUnm = $_.Exception.Message
            }
            $errUnm | Should Match 'not owned'
        }

        It 'handles VMConnect, start-connect, boot-diagnostics, and non-interactive rejection' {
            Mock -ModuleName vm_lab Test-VmLabInteractiveDesktop { return $true }
            Mock -ModuleName vm_lab Resolve-VmLabVmConnectPath { return 'C:\Windows\System32\vmconnect.exe' }
            Mock -ModuleName vm_lab Start-VmLabProcess {
                param($FilePath, $ArgumentList)
                $Global:vmLabLog.Add("VMConnect:$($ArgumentList -join ' ')")
                return [pscustomobject]@{ Id = 9999 }
            }
            Mock -ModuleName vm_lab Get-VMDvdDrive { return @([pscustomobject]@{ Path = 'C:\ISOs\Win11.iso' }) }
            Mock -ModuleName vm_lab Get-VMFirmware { return [pscustomobject]@{ SecureBoot = 'On'; BootOrder = @([pscustomobject]@{ BootType = 'Drive' }) } }

            $conn = Invoke-VmLab -Operation connect -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $conn.status | Should Be 'connected'
            ($Global:vmLabLog -contains 'VMConnect:localhost Managed-VM') | Should Be $true

            $scPlan = Invoke-VmLab -Operation start-connect -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $scPlan.status | Should Be 'planned'

            $diag = Invoke-VmLab -Operation boot-diagnostics -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $diag.secure_boot | Should Be 'On'
            $diag.attached_isos[0] | Should Be 'C:\ISOs\Win11.iso'

            Mock -ModuleName vm_lab Test-VmLabInteractiveDesktop { return $false }
            $errHeadless = $null
            try { $null = Invoke-VmLab -Operation connect -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot } catch { $errHeadless = $_.Exception.Message }
            $errHeadless | Should Match 'interactive Windows desktop'
        }

        It 'runs interactive setup wizard with mocked prompts and blocks wizard in -Json mode' {
            $errJson = $null
            try { $null = Invoke-VmLab -Operation wizard -Json -ManifestRoot $Global:vmLabManifestRoot } catch { $errJson = $_.Exception.Message }
            $errJson | Should Match '-Json mode'

            Mock -ModuleName vm_lab Test-VmLabInteractiveDesktop { return $true }
            $Global:vmLabWizardQueue = [System.Collections.Queue]::new(@(
                'windows11-light',
                'Wizard-VM-01',
                (Join-Path $testTemp 'wizard_vm_01'),
                '',
                '2',
                '4',
                '64',
                'Dynamic',
                '',
                'n'
            ))
            Mock -ModuleName vm_lab Read-Host {
                if ($Global:vmLabWizardQueue.Count -gt 0) { return $Global:vmLabWizardQueue.Dequeue() }
                return ''
            }
            $wizRes = Invoke-VmLab -Operation wizard -ManifestRoot $Global:vmLabManifestRoot
            $wizRes.status | Should Be 'cancelled'
            $wizRes.plan.vm_name | Should Be 'Wizard-VM-01'
            $Global:vmLabLog.Count | Should Be 0
        }

        It 'distinguishes guest readiness states and PowerShell Direct authentication failures' {
            # Missing VM
            $gsMissing = Get-VmLabGuestStatus -Name 'NoSuch-VM' -ManifestRoot $Global:vmLabManifestRoot
            $gsMissing.guest_state | Should Be 'vm_missing'

            # Powered off VM
            $gsOff = Get-VmLabGuestStatus -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $gsOff.guest_state | Should Be 'vm_powered_off'

            # Running VM, Heartbeat OK, no credentials
            $Global:vmLabVms[1].State = 'Running'
            Mock -ModuleName vm_lab Get-VMIntegrationService {
                return @([pscustomobject]@{ Name = 'Heartbeat'; PrimaryStatusDescription = 'OK' })
            }
            $gsNoCred = Get-VmLabGuestStatus -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $gsNoCred.guest_state | Should Be 'ps_direct_auth_unavailable'

            # Running VM with credentials -> PowerShell Direct auth & operational checks
            $secPass = ConvertTo-SecureString 'DummyPass!123' -AsPlainText -Force
            $cred = [pscredential]::new('AdminUser', $secPass)
            Mock -ModuleName vm_lab New-VmLabPSSession { throw 'The user name or password is incorrect. Logon failure.' }
            $gsAuthFail = Get-VmLabGuestStatus -Name 'Managed-VM' -Credential $cred -ManifestRoot $Global:vmLabManifestRoot
            $gsAuthFail.guest_state | Should Be 'ps_direct_auth_failed'

            Mock -ModuleName vm_lab New-VmLabPSSession { throw 'Cannot connect to PowerShell Direct endpoint.' }
            $gsOobe = Get-VmLabGuestStatus -Name 'Managed-VM' -Credential $cred -ManifestRoot $Global:vmLabManifestRoot
            $gsOobe.guest_state | Should Be 'windows_booted_account_unavailable'

            Mock -ModuleName vm_lab New-VmLabPSSession { return [pscustomobject]@{ Id = 1; Name = 'MockSess' } }
            Mock -ModuleName vm_lab Remove-VmLabPSSession { $Global:vmLabLog.Add('Remove-PSSession') }
            Mock -ModuleName vm_lab Invoke-VmLabPSSessionCommand {
                return [pscustomobject]@{
                    os_caption      = 'Microsoft Windows 11 Pro'
                    computer_name   = 'DEV-WIN11'
                    ps_version      = '5.1.26100.1'
                    bootstrap_state = 'complete'
                }
            }
            $gsOk = Get-VmLabGuestStatus -Name 'Managed-VM' -Credential $cred -ManifestRoot $Global:vmLabManifestRoot
            $gsOk.guest_state | Should Be 'guest_bootstrap_complete'
            $gsOk.ps_direct_available | Should Be $true
            ($Global:vmLabLog -contains 'Remove-PSSession') | Should Be $true
        }

        It 'performs dry-run, verified ToGuest guest-copy, and guest-bootstrap/guest-verify' {
            $Global:vmLabVms[1].State = 'Running'
            $srcFile = Join-Path $testTemp 'payload.txt'
            [System.IO.File]::WriteAllText($srcFile, 'vm-lab-payload')
            $expectedHash = (Get-FileHash -LiteralPath $srcFile -Algorithm SHA256).Hash
            $secPass = ConvertTo-SecureString 'DummyPass!123' -AsPlainText -Force
            $cred = [pscredential]::new('AdminUser', $secPass)

            # Dry-run guest-copy
            $cpPlan = Copy-VmLabGuestItem -Name 'Managed-VM' -SourcePath $srcFile -DestinationPath 'C:\Temp\payload.txt' -ManifestRoot $Global:vmLabManifestRoot
            $cpPlan.status | Should Be 'planned'
            $cpPlan.source_sha256 | Should Be $expectedHash

            # Mock PowerShell Direct session for guest-copy & guest-bootstrap
            Mock -ModuleName vm_lab New-VmLabPSSession { return [pscustomobject]@{ Id = 2; Name = 'MockSess2' } }
            Mock -ModuleName vm_lab Remove-VmLabPSSession { $Global:vmLabLog.Add('Remove-PSSession') }
            $Global:vmLabRemoteExists = $false
            $Global:vmLabRemoteHash = $expectedHash
            Mock -ModuleName vm_lab Copy-VmLabPSSessionItem { $Global:vmLabLog.Add('Copy-Item') }
            Mock -ModuleName vm_lab Invoke-VmLabPSSessionCommand {
                param($Session, $ScriptBlock, $ArgumentList)
                $text = $ScriptBlock.ToString()
                if ($text -match 'Test-Path -LiteralPath \$p') { return $Global:vmLabRemoteExists }
                if ($text -match 'Get-FileHash') { return $Global:vmLabRemoteHash }
                if ($text -match 'Invoke-VmLabGuestBootstrapLocal') {
                    return [pscustomobject]@{ schema_version = 2; completed = $true; reboot_required = $false; profile = 'windows-minimal' }
                }
                if ($text -match 'Test-VmLabGuestVerifyLocal') {
                    return [pscustomobject]@{
                        status   = 'verified'
                        checks   = [pscustomobject]@{ state_dir_present = $true; bootstrap_marker = $true }
                        failures = @()
                    }
                }
                return $null
            }

            $cpRes = Copy-VmLabGuestItem -Name 'Managed-VM' -SourcePath $srcFile -DestinationPath 'C:\Temp\payload.txt' -Credential $cred -Apply -ManifestRoot $Global:vmLabManifestRoot
            $cpRes.status | Should Be 'copied'
            $cpRes.sha256_verified | Should Be $true

            # Overwrite protection when remote file already exists
            $Global:vmLabRemoteExists = $true
            $errOvr = $null
            try { $null = Copy-VmLabGuestItem -Name 'Managed-VM' -SourcePath $srcFile -DestinationPath 'C:\Temp\payload.txt' -Credential $cred -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $errOvr = $_.Exception.Message }
            $errOvr | Should Match '-Overwrite'

            # guest-bootstrap dry-run and apply
            $bsPlan = Invoke-VmLabGuestBootstrap -Name 'Managed-VM' -Profile 'windows-minimal' -ManifestRoot $Global:vmLabManifestRoot
            $bsPlan.status | Should Be 'planned'

            $bsRes = Invoke-VmLabGuestBootstrap -Name 'Managed-VM' -Profile 'windows-minimal' -Credential $cred -Apply -ManifestRoot $Global:vmLabManifestRoot
            $bsRes.status | Should Be 'bootstrapped'

            $gvRes = Test-VmLabGuestVerify -Name 'Managed-VM' -Profile 'windows-minimal' -Credential $cred -ManifestRoot $Global:vmLabManifestRoot
            $gvRes.status | Should Be 'verified'
            $gvRes.checks.bootstrap_marker | Should Be $true
        }

        It 'creates baseline checkpoints and generates non-destructive recovery plans' {
            $blPlan = Invoke-VmLab -Operation baseline -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot
            $blPlan.status | Should Be 'planned'
            $blPlan.checkpoint_name | Should Be 'clean-baseline'

            $blRes = Invoke-VmLab -Operation baseline -Name 'Managed-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot
            $blRes.status | Should Be 'baseline_created'
            $blRes.baseline | Should Be $true
            $blRes.checkpoint_id | Should Be '66666666-6666-6666-6666-666666666666'

            # Stale lock + partial artifacts recovery-plan
            $partialRoot = Join-Path $testTemp 'partial_rec_vm'
            New-Item -ItemType Directory -Path (Join-Path $partialRoot 'vhdx') -Force | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $partialRoot 'vhdx\Interrupted-VM.vhdx'), 'partial')
            $lockFile = Join-Path $Global:vmLabManifestRoot 'Interrupted-VM.lock'
            [System.IO.File]::WriteAllText($lockFile, 'lock')

            $rec = Invoke-VmLab -Operation recovery-plan -Name 'Interrupted-VM' -VmRoot $partialRoot -ManifestRoot $Global:vmLabManifestRoot -Json | ConvertFrom-Json
            $rec.lock_present | Should Be $true
            $rec.vhdx_exists | Should Be $true
            $rec.vm_registered | Should Be $false
            (Test-Path -LiteralPath $lockFile) | Should Be $true
            (Test-Path -LiteralPath (Join-Path $partialRoot 'vhdx\Interrupted-VM.vhdx')) | Should Be $true
        }

        It 'generates bounded Autounattend.xml without passwords and enforces overwrite protection' {
            $outXml = Join-Path $testTemp 'Autounattend.xml'
            $planXml = Invoke-VmLab -Operation unattend-xml -OutputPath $outXml -ImageEdition 'Windows 11 Pro' -Json | ConvertFrom-Json
            $planXml.status | Should Be 'planned'
            ($planXml.xml -match '<AcceptEula>true</AcceptEula>') | Should Be $true
            ($planXml.xml -match 'AdministratorPassword|Password') | Should Be $false
            (Test-Path -LiteralPath $outXml) | Should Be $false

            $written = Invoke-VmLab -Operation unattend-xml -OutputPath $outXml -ImageEdition 'Windows 11 Pro' -Apply
            $written.status | Should Be 'written'
            (Test-Path -LiteralPath $outXml) | Should Be $true

            $errOvr = $null
            try { $null = Invoke-VmLab -Operation unattend-xml -OutputPath $outXml -Apply } catch { $errOvr = $_.Exception.Message }
            $errOvr | Should Match '-Overwrite'
        }

        It 'hardens Copy-VmLabGuestItem for ToGuest, FromGuest, hash mismatches, and cleanup' {
            $Global:vmLabVms[1].State = 'Running'
            $secPass = ConvertTo-SecureString 'DummyPass!123' -AsPlainText -Force
            $cred = [pscredential]::new('AdminUser', $secPass)

            $stageDir = Join-Path $testTemp ("copy_stage_" + [guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $stageDir -Force | Out-Null
            $srcLocal = Join-Path $stageDir 'unicode файл.txt'
            [System.IO.File]::WriteAllText($srcLocal, 'hello-guest')

            Mock -ModuleName vm_lab New-VmLabPSSession { return [pscustomobject]@{ Id = 10; Name = 'CopySess' } }
            Mock -ModuleName vm_lab Remove-VmLabPSSession { $Global:vmLabLog.Add('Remove-CopySess') }
            Mock -ModuleName vm_lab Copy-VmLabPSSessionItem {
                param($Session, $SourcePath, $DestinationPath, $Direction, $Overwrite)
                if ($Direction -eq 'FromGuest') {
                    [System.IO.File]::WriteAllText($DestinationPath, $Global:vmLabFromGuestContent)
                }
            }

            $Global:vmLabRemoteHash = ('F' * 64)
            $Global:vmLabCleanupCalled = $false
            Mock -ModuleName vm_lab Invoke-VmLabPSSessionCommand {
                param($Session, $ScriptBlock, $ArgumentList)
                $text = $ScriptBlock.ToString()
                if ($text -match 'Test-Path -LiteralPath \$p') { return $false }
                if ($text -match 'Get-FileHash') { return $Global:vmLabRemoteHash }
                if ($text -match 'Remove-Item') { $Global:vmLabCleanupCalled = $true; return $null }
                return $null
            }
            $errHash = $null
            try { $null = Copy-VmLabGuestItem -Name 'Managed-VM' -SourcePath $srcLocal -DestinationPath 'C:\Temp\unicode файл.txt' -Credential $cred -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $errHash = $_.Exception.Message }
            $errHash | Should Match 'SHA-256 verification failed'
            $Global:vmLabCleanupCalled | Should Be $true

            $destFrom = Join-Path $stageDir 'from_guest\out.txt'
            $Global:vmLabFromGuestContent = 'from-guest-data'
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($Global:vmLabFromGuestContent)
            $expectedFromHash = ([System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::HashData($bytes))).Replace('-', '')
            $Global:vmLabRemoteHash = $expectedFromHash
            Mock -ModuleName vm_lab Invoke-VmLabPSSessionCommand {
                param($Session, $ScriptBlock, $ArgumentList)
                $text = $ScriptBlock.ToString()
                if ($text -match 'Get-FileHash') { return $Global:vmLabRemoteHash }
                if ($text -match 'Test-Path -LiteralPath \$p') { return $true }
                return $null
            }
            $fgRes = Copy-VmLabGuestItem -Name 'Managed-VM' -SourcePath 'C:\Guest\in.txt' -DestinationPath $destFrom -Direction FromGuest -Credential $cred -Apply -ManifestRoot $Global:vmLabManifestRoot
            $fgRes.status | Should Be 'copied'
            $fgRes.sha256_verified | Should Be $true
            [System.IO.File]::ReadAllText($destFrom) | Should Be 'from-guest-data'

            $errFgOvr = $null
            try { $null = Copy-VmLabGuestItem -Name 'Managed-VM' -SourcePath 'C:\Guest\in.txt' -DestinationPath $destFrom -Direction FromGuest -Credential $cred -Apply -ManifestRoot $Global:vmLabManifestRoot } catch { $errFgOvr = $_.Exception.Message }
            $errFgOvr | Should Match '-Overwrite'
        }

        It 'reports quickstart template drift, baseline qualification, and lock uncertainty' {
            Mock -ModuleName vm_lab Get-VMNetworkAdapter { return @() }
            $qsDrift = Invoke-VmLab -Operation quickstart -TemplateName 'windows11-light' -Name 'Managed-VM' -ManifestRoot $Global:vmLabManifestRoot -Json | ConvertFrom-Json
            $qsDrift.status | Should Be 'existing_owned'
            $qsDrift.configuration_drift | Should Be $true
            $qsDrift.actual.cpu_count | Should Be 4
            $qsDrift.requested.cpu_count | Should Be 2

            $blUnq = New-VmLabBaselineCheckpoint -Name 'Managed-VM' -Apply -ManifestRoot $Global:vmLabManifestRoot
            $blUnq.guest_verified | Should Be $false
            $blUnq.baseline_qualified | Should Be $false

            $Global:vmLabVms[1].State = 'Running'
            $secPass = ConvertTo-SecureString 'DummyPass!123' -AsPlainText -Force
            $cred = [pscredential]::new('AdminUser', $secPass)
            Mock -ModuleName vm_lab New-VmLabPSSession { return [pscustomobject]@{ Id = 11; Name = 'BaseSess' } }
            Mock -ModuleName vm_lab Remove-VmLabPSSession {}
            Mock -ModuleName vm_lab Invoke-VmLabPSSessionCommand {
                return [pscustomobject]@{ status = 'incomplete'; checks = [pscustomobject]@{}; failures = @('missing marker') }
            }
            $errQual = $null
            try {
                $null = New-VmLabBaselineCheckpoint -Name 'Managed-VM' -CheckpointName 'qual-base' -RequireGuestVerified -Credential $cred -Apply -ManifestRoot $Global:vmLabManifestRoot
            } catch { $errQual = $_.Exception.Message }
            $errQual | Should Match 'guest verification failed'

            $lkFile = Join-Path $Global:vmLabManifestRoot 'Some-VM.lock'
            [System.IO.File]::WriteAllText($lkFile, 'lock')
            $recAll = Get-VmLabRecoveryPlan -ManifestRoot $Global:vmLabManifestRoot
            ($recAll.findings -join ' ') | Should Match 'may be active or stale'
            Remove-Item -LiteralPath $lkFile -Force -ErrorAction SilentlyContinue
        }
    }

    It 'imports and invokes cleanly from an isolated PowerShell session with accurate exit codes' {
        $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
        $psi.ArgumentList.Add('-NoProfile')
        $psi.ArgumentList.Add('-File')
        $psi.ArgumentList.Add($cliScript)
        $psi.ArgumentList.Add('-o')
        $psi.ArgumentList.Add('status')
        $psi.ArgumentList.Add('-j')
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false

        $proc = [System.Diagnostics.Process]::Start($psi)
        $stdout = $proc.StandardOutput.ReadToEnd()
        $stderr = $proc.StandardError.ReadToEnd()
        $proc.WaitForExit()

        # Missing -Name for status must exit 1 with structured JSON error on stderr and empty stdout
        $proc.ExitCode | Should Be 1
        [string]::IsNullOrWhiteSpace($stdout) | Should Be $true
        $errJson = $stderr | ConvertFrom-Json
        $errJson.status | Should Be 'error'
        $errJson.operation | Should Be 'status'

        # Clean import + Get-VmLabTemplate in fresh pwsh session exits 0
        $psi2 = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
        $psi2.ArgumentList.Add('-NoProfile')
        $psi2.ArgumentList.Add('-Command')
        $psi2.ArgumentList.Add("Import-Module '$moduleManifest' -Force; (Get-VmLabTemplate).template_id")
        $psi2.RedirectStandardOutput = $true
        $psi2.RedirectStandardError = $true
        $psi2.UseShellExecute = $false

        $proc2 = [System.Diagnostics.Process]::Start($psi2)
        $stdout2 = $proc2.StandardOutput.ReadToEnd().Trim()
        $proc2.WaitForExit()
        $proc2.ExitCode | Should Be 0
        $stdout2 | Should Be 'windows11-h4'
    }

    Context 'Stage A-D reliability, real bootstrap logic, file transfer, and CLI exit codes' {
        BeforeEach {
            $Global:vmLabStageTemp = Join-Path $testTemp ("stage_tests_" + [guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $Global:vmLabStageTemp -Force | Out-Null
        }

        It 'executes real guest-bootstrap and guest-verify logic across windows-minimal, python-dev, and powershell-dev' {
            InModuleScope vm_lab {
                $root = $Global:vmLabStageTemp
                $stateRoot = Join-Path $root 'ProgramData\vm_lab'

                # 1. windows-minimal writes v2 marker and verifies
                $rMin = Invoke-VmLabGuestBootstrapLocal -Profile 'windows-minimal' -StateRoot $stateRoot
                $rMin.completed | Should Be $true
                $vMin = Test-VmLabGuestVerifyLocal -Profile 'windows-minimal' -StateRoot $stateRoot
                $vMin.status | Should Be 'verified'

                # 2. python-dev fails without Python or installer
                $errNoPy = $null
                try {
                    $null = Invoke-VmLabGuestBootstrapLocal -Profile 'python-dev' -StateRoot $stateRoot -PythonSearchRoots @(Join-Path $root 'NoPython*')
                } catch { $errNoPy = $_.Exception.Message }
                $errNoPy | Should Match 'Python 3\.12\+'

                # 3. WindowsApps alias rejected, Python 3.11 rejected, Python 3.12 accepted
                $winAppsDir = Join-Path $root 'WindowsApps'
                $py311Dir = Join-Path $root 'Python311'
                $py312Dir = Join-Path $root 'Python312'
                foreach ($d in @($winAppsDir, $py311Dir, $py312Dir)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
                $winAppsPy = Join-Path $winAppsDir 'python.exe'
                $py311Exe = Join-Path $py311Dir 'python.exe'
                $py312Exe = Join-Path $py312Dir 'python.exe'
                foreach ($f in @($winAppsPy, $py311Exe, $py312Exe)) { [System.IO.File]::WriteAllText($f, 'stub') }

                $errAlias = $null
                try { $null = Resolve-VmLabGuestPythonInterpreter -PythonPath $winAppsPy } catch { $errAlias = $_.Exception.Message }
                $errAlias | Should Match 'WindowsApps'

                $runner = {
                    param([string]$Exe, [string[]]$ExeArgs)
                    if ($Exe -eq $py311Exe) {
                        return [pscustomobject]@{ exit_code = 0; output = '3.11.9|64' }
                    }
                    if ($Exe -eq $py312Exe -or $Exe -like '*\Scripts\python.exe') {
                        if ($ExeArgs -contains '-c') {
                            return [pscustomobject]@{ exit_code = 0; output = '3.12.4|64' }
                        }
                        if ($ExeArgs -contains 'venv') {
                            $targetVenv = $ExeArgs[-1]
                            $scriptsDir = Join-Path $targetVenv 'Scripts'
                            New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
                            [System.IO.File]::WriteAllText((Join-Path $scriptsDir 'python.exe'), 'venv-stub')
                            return [pscustomobject]@{ exit_code = 0; output = '' }
                        }
                        if ($ExeArgs -contains 'install') {
                            $Global:vmLabPipCalls.Add(($ExeArgs -join ' '))
                            return [pscustomobject]@{ exit_code = 0; output = 'Successfully installed' }
                        }
                        if ($ExeArgs -contains 'list') {
                            return [pscustomobject]@{ exit_code = 0; output = $Global:vmLabPipListJson }
                        }
                    }
                    if ($Exe -like '*pwsh.exe') {
                        return [pscustomobject]@{ exit_code = 0; output = '7.4.6' }
                    }
                    return [pscustomobject]@{ exit_code = 1; output = 'unexpected command' }
                }

                $err311 = $null
                try { $null = Resolve-VmLabGuestPythonInterpreter -PythonPath $py311Exe -CommandRunner $runner } catch { $err311 = $_.Exception.Message }
                $err311 | Should Match '3\.12'

                # 4. Installer refreshes and finds Python 3.12+, creates venv with no packages
                $venv1 = Join-Path $root 'venv_clean'
                $pyInst = Join-Path $root 'python-3.12.4-amd64.exe'
                [System.IO.File]::WriteAllText($pyInst, 'installer')
                $Global:vmLabInstallCount = 0
                $procRunnerOk = {
                    param($FilePath, $ArgumentList)
                    $Global:vmLabInstallCount++
                    return 0
                }
                $rPyClean = Invoke-VmLabGuestBootstrapLocal -Profile 'python-dev' -InstallerPath $pyInst -VenvPath $venv1 -StateRoot $stateRoot -PythonSearchRoots @($py312Dir) -CommandRunner $runner -ProcessRunner $procRunnerOk
                $rPyClean.completed | Should Be $true
                $rPyClean.details.python_version | Should Be '3.12.4'
                (Test-Path -LiteralPath (Join-Path $venv1 'Scripts\python.exe')) | Should Be $true

                # 5. Wheelhouse without requirements or packages must fail (no --upgrade pip fallback)
                $wheelDir = Join-Path $root 'wheelhouse'
                New-Item -ItemType Directory -Path $wheelDir -Force | Out-Null
                $errWheelOnly = $null
                try {
                    $null = Invoke-VmLabGuestBootstrapLocal -Profile 'python-dev' -PythonPath $py312Exe -WheelhousePath $wheelDir -VenvPath $venv1 -StateRoot $stateRoot -CommandRunner $runner
                } catch { $errWheelOnly = $_.Exception.Message }
                $errWheelOnly | Should Match 'requires -RequirementsPath or -Packages'

                # 6. Missing requirements file or missing wheelhouse fails
                $errMissReq = $null
                try {
                    $null = Invoke-VmLabGuestBootstrapLocal -Profile 'python-dev' -PythonPath $py312Exe -RequirementsPath (Join-Path $root 'missing-req.txt') -AllowOnlineInstall -VenvPath $venv1 -StateRoot $stateRoot -CommandRunner $runner
                } catch { $errMissReq = $_.Exception.Message }
                $errMissReq | Should Match 'Requirements file not found'

                $reqFile = Join-Path $root 'requirements.txt'
                [System.IO.File]::WriteAllText($reqFile, "# comment`npytest>=8.0`nmy_pkg[extra]==1.2.3`n")

                $errMissWheel = $null
                try {
                    $null = Invoke-VmLabGuestBootstrapLocal -Profile 'python-dev' -PythonPath $py312Exe -WheelhousePath (Join-Path $root 'no_wheels') -RequirementsPath $reqFile -VenvPath $venv1 -StateRoot $stateRoot -CommandRunner $runner
                } catch { $errMissWheel = $_.Exception.Message }
                $errMissWheel | Should Match 'Wheelhouse directory not found'

                # 7. Offline without wheelhouse fails; implicit online without -AllowOnlineInstall fails
                $errOffNoWheel = $null
                try {
                    $null = Invoke-VmLabGuestBootstrapLocal -Profile 'python-dev' -PythonPath $py312Exe -RequirementsPath $reqFile -Offline -VenvPath $venv1 -StateRoot $stateRoot -CommandRunner $runner
                } catch { $errOffNoWheel = $_.Exception.Message }
                $errOffNoWheel | Should Match 'without -WheelhousePath'

                $errImplicitOnline = $null
                try {
                    $null = Invoke-VmLabGuestBootstrapLocal -Profile 'python-dev' -PythonPath $py312Exe -RequirementsPath $reqFile -VenvPath $venv1 -StateRoot $stateRoot -CommandRunner $runner
                } catch { $errImplicitOnline = $_.Exception.Message }
                $errImplicitOnline | Should Match 'AllowOnlineInstall'

                # 8. Offline wheelhouse + requirements installs and verifies normalized names
                $Global:vmLabPipCalls = [System.Collections.Generic.List[string]]::new()
                $Global:vmLabPipListJson = '[{"name":"pytest","version":"8.3.0"},{"name":"my-pkg","version":"1.2.3"}]'
                $rPyWheel = Invoke-VmLabGuestBootstrapLocal -Profile 'python-dev' -PythonPath $py312Exe -WheelhousePath $wheelDir -RequirementsPath $reqFile -VenvPath $venv1 -StateRoot $stateRoot -CommandRunner $runner
                $rPyWheel.completed | Should Be $true
                ($Global:vmLabPipCalls[0] -match '--no-index --find-links') | Should Be $true
                $vPyOk = Test-VmLabGuestVerifyLocal -Profile 'python-dev' -VenvPath $venv1 -StateRoot $stateRoot -CommandRunner $runner
                $vPyOk.status | Should Be 'verified'

                # 9. Missing expected package fails verification
                $Global:vmLabPipListJson = '[{"name":"pytest","version":"8.3.0"}]'
                $vPyMiss = Test-VmLabGuestVerifyLocal -Profile 'python-dev' -VenvPath $venv1 -StateRoot $stateRoot -CommandRunner $runner
                $vPyMiss.status | Should Be 'failed'
                ($vPyMiss.failures -join ' ') | Should Match 'my-pkg'

                # 10. powershell-dev: non-MSI rejected, SHA256 mismatch rejected, exit 3010 persists reboot_required, 0 verifies
                $badInst = Join-Path $root 'pwsh.zip'
                [System.IO.File]::WriteAllText($badInst, 'zip')
                $errBadExt = $null
                try {
                    $null = Invoke-VmLabGuestBootstrapLocal -Profile 'powershell-dev' -InstallerPath $badInst -StateRoot $stateRoot -PwshStandardPaths @((Join-Path $root 'no_pwsh.exe')) -CommandRunner $runner
                } catch { $errBadExt = $_.Exception.Message }
                $errBadExt | Should Match '\.msi'

                $msiInst = Join-Path $root 'PowerShell-7.4.6-win-x64.msi'
                [System.IO.File]::WriteAllText($msiInst, 'msi-bytes')
                $msiSha = (Get-FileHash -LiteralPath $msiInst -Algorithm SHA256).Hash

                $errBadSha = $null
                try {
                    $null = Invoke-VmLabGuestBootstrapLocal -Profile 'powershell-dev' -InstallerPath $msiInst -ExpectedInstallerSha256 ('0' * 64) -StateRoot $stateRoot -PwshStandardPaths @((Join-Path $root 'no_pwsh.exe')) -CommandRunner $runner
                } catch { $errBadSha = $_.Exception.Message }
                $errBadSha | Should Match 'SHA-256 mismatch'

                $r3010 = Invoke-VmLabGuestBootstrapLocal -Profile 'powershell-dev' -InstallerPath $msiInst -ExpectedInstallerSha256 $msiSha -StateRoot $stateRoot -PwshStandardPaths @((Join-Path $root 'no_pwsh.exe')) -CommandRunner $runner -ProcessRunner { param($f, $a) return 3010 }
                $r3010.status | Should Be 'reboot_required'
                $r3010.reboot_required | Should Be $true
                $v3010 = Test-VmLabGuestVerifyLocal -Profile 'powershell-dev' -StateRoot $stateRoot -PwshStandardPaths @((Join-Path $root 'no_pwsh.exe')) -CommandRunner $runner
                $v3010.status | Should Be 'incomplete'

                # Complete powershell-dev and confirm all 3 profiles coexist in v2 store
                $pwshDir = Join-Path $root 'PowerShell\7'
                New-Item -ItemType Directory -Path $pwshDir -Force | Out-Null
                $pwshExe = Join-Path $pwshDir 'pwsh.exe'
                [System.IO.File]::WriteAllText($pwshExe, 'pwsh-stub')
                $rPwshOk = Invoke-VmLabGuestBootstrapLocal -Profile 'powershell-dev' -InstallerPath $msiInst -ExpectedInstallerSha256 $msiSha -StateRoot $stateRoot -PwshStandardPaths @($pwshExe) -CommandRunner $runner -ProcessRunner { param($f, $a) return 0 }
                $rPwshOk.completed | Should Be $true
                $store = Read-VmLabGuestBootstrapStore -StateRoot $stateRoot
                $store.schema_version | Should Be 2
                $store.profiles.ContainsKey('windows-minimal') | Should Be $true
                $store.profiles.ContainsKey('python-dev') | Should Be $true
                $store.profiles.ContainsKey('powershell-dev') | Should Be $true

                # 11. Corrupt JSON marker fails verification
                $corruptState = Join-Path $root 'corrupt_state'
                New-Item -ItemType Directory -Path $corruptState -Force | Out-Null
                [System.IO.File]::WriteAllText((Join-Path $corruptState 'bootstrap-state.json'), '{not-json')
                $vCorrupt = Test-VmLabGuestVerifyLocal -Profile 'windows-minimal' -StateRoot $corruptState
                $vCorrupt.status | Should Be 'failed'
            }
        }

        It 'returns exit code 1 from Invoke-VmLab.ps1 when guest-verify is not verified' {
            $script = @"
Import-Module Pester -Force
Import-Module '$moduleManifest' -Force
Describe 'gv' {
    It 'exits 1' {
        Mock -ModuleName vm_lab Assert-VmLabOwnedVm { return [pscustomobject]@{ owned = `$true; vm = [pscustomobject]@{ Name='V1'; Id=[guid]'11111111-1111-1111-1111-111111111111'; State='Running' } } }
        Mock -ModuleName vm_lab New-VmLabPSSession { return [pscustomobject]@{ Id = 1; Name = 'S1' } }
        Mock -ModuleName vm_lab Remove-VmLabPSSession {}
        Mock -ModuleName vm_lab Invoke-VmLabPSSessionCommand { return [pscustomobject]@{ status = 'incomplete'; checks = [pscustomobject]@{}; failures = @('missing') } }
        `$sec = ConvertTo-SecureString 'Dummy!123' -AsPlainText -Force
        `$cred = [pscredential]::new('u', `$sec)
        & '$cliScript' -Operation guest-verify -Name 'V1' -Credential `$cred -Json
        exit `$LASTEXITCODE
    }
}
"@
            $runnerFile = Join-Path $Global:vmLabStageTemp 'run_gv_exit.ps1'
            [System.IO.File]::WriteAllText($runnerFile, $script)
            $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
            $psi.ArgumentList.Add('-NoProfile')
            $psi.ArgumentList.Add('-File')
            $psi.ArgumentList.Add($runnerFile)
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.UseShellExecute = $false
            $proc = [System.Diagnostics.Process]::Start($psi)
            $out = $proc.StandardOutput.ReadToEnd()
            $proc.WaitForExit()
            $proc.ExitCode | Should Be 1
            $jsonStart = $out.IndexOf('{')
            ($jsonStart -ge 0) | Should Be $true
            ($out.Substring($jsonStart) | ConvertFrom-Json).status | Should Be 'incomplete'
        }
    }
}
