#Requires -Version 7.0

function Read-VmLabPromptWithDefault {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Default = ''
    )
    $label = if ([string]::IsNullOrEmpty($Default)) { $Prompt } else { "$Prompt [$Default]" }
    $inputVal = Read-Host -Prompt $label
    if ([string]::IsNullOrWhiteSpace($inputVal)) {
        return $Default
    }
    return $inputVal.Trim()
}

function Invoke-VmLabWizard {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [string]$DefaultTemplate = 'windows11-dev',
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    if (-not (Test-VmLabInteractiveDesktop)) {
        throw 'Interactive setup wizard requires an interactive terminal/desktop session. Use non-interactive parameters with -o plan or -o quickstart.'
    }

    $templates = @(Get-VmLabTemplates)
    Write-Host '=== vm_lab Interactive VM Setup Assistant ===' -ForegroundColor Cyan
    Write-Host 'Available templates:'
    foreach ($t in $templates) {
        Write-Host ("  - {0} ({1} vCPU, {2} GiB RAM, {3} GiB {4} VHDX): {5}" -f `
            $t.template_id, $t.cpu_count, $t.memory_startup_gib, $t.vhdx_size_gib, $t.vhdx_format, $t.description)
    }

    $tplId = Read-VmLabPromptWithDefault -Prompt 'Template ID' -Default $DefaultTemplate
    $cfg = Get-VmLabTemplate -TemplateName $tplId

    $cfg.vm_name = Read-VmLabPromptWithDefault -Prompt 'VM Name' -Default $cfg.vm_name
    $defaultRoot = "C:\VMs\$($cfg.vm_name)"
    $cfg.vm_root = Read-VmLabPromptWithDefault -Prompt 'VM Storage Root' -Default $defaultRoot
    $cfg.iso_path = Read-VmLabPromptWithDefault -Prompt 'Windows Installation ISO path (optional)' -Default $cfg.iso_path

    $memInfo = Get-VmLabHostMemoryInfo
    Write-Host ("Host RAM: {0:N2} GiB free / {1:N2} GiB total" -f ($memInfo.FreePhysicalBytes / 1GB), ($memInfo.TotalPhysicalBytes / 1GB))

    $cpuStr = Read-VmLabPromptWithDefault -Prompt 'vCPU count (1-64)' -Default ([string]$cfg.cpu_count)
    $cfg.cpu_count = [int]$cpuStr

    $startRamGib = Read-VmLabPromptWithDefault -Prompt 'Startup RAM (GiB)' -Default ([string][math]::Round($cfg.memory_startup_bytes / 1GB))
    $cfg.memory_startup_bytes = [int64]([int]$startRamGib * 1GB)
    if ($cfg.memory_minimum_bytes -gt $cfg.memory_startup_bytes) {
        $cfg.memory_minimum_bytes = $cfg.memory_startup_bytes
    }
    if ($cfg.memory_maximum_bytes -lt $cfg.memory_startup_bytes) {
        $cfg.memory_maximum_bytes = $cfg.memory_startup_bytes
    }

    $diskGib = Read-VmLabPromptWithDefault -Prompt 'VHDX size (GiB, >= 20)' -Default ([string][math]::Round($cfg.vhdx_size_bytes / 1GB))
    $cfg.vhdx_size_bytes = [int64]([int]$diskGib * 1GB)
    $cfg.vhdx_format = Read-VmLabPromptWithDefault -Prompt 'VHDX format (Dynamic/Fixed)' -Default $cfg.vhdx_format

    Write-Host 'Networking: Disconnected by default (recommended during Windows OOBE or for isolated PowerShell Direct labs).'
    $cfg.switch_name = Read-VmLabPromptWithDefault -Prompt 'Virtual Switch name (leave blank for disconnected)' -Default $cfg.switch_name

    Write-Host ("Security & Checkpoints: SecureBoot={0} ({1}), vTPM={2}, CheckpointType={3}" -f `
        $cfg.secure_boot.enabled, $cfg.secure_boot.template, $cfg.vtpm_enabled, $cfg.checkpoint_type)

    $plan = Test-VmLabPlan -Config $cfg -ManifestRoot $ManifestRoot
    Write-Host '--- Dry-Run Plan Summary ---' -ForegroundColor Green
    Write-Host ("  VM:       {0} at {1}" -f $plan.vm_name, $plan.vm_root)
    Write-Host ("  VHDX:     {0} ({1} GiB {2})" -f $plan.vhdx_path, [math]::Round($plan.vhdx_size_bytes / 1GB), $plan.vhdx_format)
    Write-Host ("  DiskFree: {0:N2} GiB | HostFreeRAM: {1:N2} GiB" -f ($plan.free_disk_bytes / 1GB), ($plan.free_ram_bytes / 1GB))

    if ($WhatIfPreference) {
        return $plan
    }

    $confirmCreate = Read-VmLabPromptWithDefault -Prompt 'Authorize VM creation now? (y/N)' -Default 'N'
    if ($confirmCreate -notmatch '^(y|yes)$') {
        return [pscustomobject]@{
            status  = 'cancelled'
            plan    = $plan
            message = 'Wizard completed dry-run plan without mutations.'
        }
    }

    $created = New-VmLabMachine -Config $cfg -Apply -ManifestRoot $ManifestRoot
    $confirmStart = Read-VmLabPromptWithDefault -Prompt 'Start VM now? (y/N)' -Default 'N'
    $started = $null
    if ($confirmStart -match '^(y|yes)$') {
        $started = Start-VmLabMachine -Name $cfg.vm_name -Apply -ManifestRoot $ManifestRoot
    }
    return [pscustomobject]@{
        status  = if ($started) { 'created_and_started' } else { 'created' }
        created = $created
        started = $started
    }
}
