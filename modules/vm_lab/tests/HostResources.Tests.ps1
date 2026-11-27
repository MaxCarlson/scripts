#Requires -Version 7.0

$moduleRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force

Describe 'Get-VmLabHostResources' {
    It 'reports accurate structured host resources when memory and storage succeed' {
        Mock -ModuleName vm_lab Get-VmLabHostMemoryInfo {
            [pscustomobject]@{
                TotalPhysicalBytes = [int64]32GB
                FreePhysicalBytes  = [int64]12GB
            }
        }
        Mock -ModuleName vm_lab Get-VmLabDriveFreeBytes {
            return [int64]150GB
        }

        $res = Get-VmLabHostResources -MinReserveBytes ([int64]4GB) -TargetPath 'C:\VMs'
        $res.status | Should Be 'OK'
        $res.reason_code | Should Be 'host_resources_ok'
        $res.operation | Should Be 'host-resources'
        $res.hostname | Should Not BeNullOrEmpty
        $res.logical_cpu_count | Should BeGreaterThan 0
        $res.total_physical_bytes | Should Be ([int64]32GB)
        $res.available_physical_bytes | Should Be ([int64]12GB)
        $res.used_physical_bytes | Should Be ([int64]20GB)
        $res.min_reserve_bytes | Should Be ([int64]4GB)
        $res.reserve_satisfied | Should Be $true
        $res.storage_available_bytes | Should Be ([int64]150GB)
        @($res.diagnostics).Count | Should Be 0
    }

    It 'distinguishes insufficient memory reserve from collection failure' {
        Mock -ModuleName vm_lab Get-VmLabHostMemoryInfo {
            [pscustomobject]@{
                TotalPhysicalBytes = [int64]16GB
                FreePhysicalBytes  = [int64]2GB
            }
        }
        Mock -ModuleName vm_lab Get-VmLabDriveFreeBytes {
            return [int64]80GB
        }

        $res = Get-VmLabHostResources -MinReserveBytes ([int64]4GB)
        $res.status | Should Be 'OK'
        $res.reason_code | Should Be 'host_memory_below_reserve'
        $res.reserve_satisfied | Should Be $false
        $res.available_physical_bytes | Should Be ([int64]2GB)
    }

    It 'fails explicitly when host memory counters throw and never treats failure as zero memory' {
        Mock -ModuleName vm_lab Get-VmLabHostMemoryInfo {
            throw 'CIM Win32_OperatingSystem unavailable'
        }
        Mock -ModuleName vm_lab Get-VmLabDriveFreeBytes {
            return [int64]100GB
        }

        $res = Get-VmLabHostResources -MinReserveBytes ([int64]4GB)
        $res.status | Should Be 'ERROR'
        $res.reason_code | Should Be 'host_resource_collection_failed'
        $res.total_physical_bytes | Should BeNullOrEmpty
        $res.available_physical_bytes | Should BeNullOrEmpty
        $res.used_physical_bytes | Should BeNullOrEmpty
        $res.reserve_satisfied | Should BeNullOrEmpty
        $res.error | Should Match 'CIM Win32_OperatingSystem unavailable'
    }

    It 'records storage diagnostic when drive free-space lookup fails' {
        Mock -ModuleName vm_lab Get-VmLabHostMemoryInfo {
            [pscustomobject]@{
                TotalPhysicalBytes = [int64]32GB
                FreePhysicalBytes  = [int64]16GB
            }
        }
        Mock -ModuleName vm_lab Get-VmLabDriveFreeBytes {
            throw 'Drive Z:\ not ready'
        }

        $res = Get-VmLabHostResources -MinReserveBytes ([int64]4GB) -TargetPath 'Z:\Missing'
        $res.status | Should Be 'OK'
        $res.reason_code | Should Be 'host_resources_partial'
        $res.reserve_satisfied | Should Be $true
        $res.storage_available_bytes | Should BeNullOrEmpty
        ($res.diagnostics -join ' ') | Should Match 'Drive Z:\\ not ready'
    }

    It 'dispatches host-resources through Invoke-VmLab -Json without elevation' {
        $json = Invoke-VmLab -Operation host-resources -Json
        $parsed = $json | ConvertFrom-Json -ErrorAction Stop
        $parsed.status | Should Be 'OK'
        $parsed.operation | Should Be 'host-resources'
        $parsed.logical_cpu_count | Should BeGreaterThan 0
        $parsed.total_physical_bytes | Should BeGreaterThan 0
        $parsed.available_physical_bytes | Should BeGreaterThan 0
    }
}
