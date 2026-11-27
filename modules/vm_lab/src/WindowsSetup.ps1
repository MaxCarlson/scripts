#Requires -Version 7.0

function New-VmLabAnswerMediaStaging {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$StagingDirectory,
        [string]$Locale = 'en-US',
        [string]$KeyboardLayout = 'en-US',
        [string]$ImageEdition,
        [switch]$Overwrite,
        [switch]$Apply
    )
    $dirFull = Test-VmLabSafePath -Path $StagingDirectory -Label 'StagingDirectory' -CheckReparsePoints
    $xmlPath = Join-Path $dirFull 'Autounattend.xml'
    $metaPath = Join-Path $dirFull 'answer-media-manifest.json'

    if (-not $Apply -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($dirFull, 'Stage Windows Setup answer media')) {
        return [pscustomobject]@{
            status      = 'PLANNED'
            reason_code = 'dry_run_not_applied'
            staging_dir = $dirFull
            xml_path    = $xmlPath
            meta_path   = $metaPath
        }
    }

    if (-not (Test-Path -LiteralPath $dirFull -PathType Container)) {
        New-Item -ItemType Directory -Path $dirFull -Force | Out-Null
    }
    $xmlRes = New-VmLabUnattendXml -OutputPath $xmlPath -Locale $Locale -KeyboardLayout $KeyboardLayout -ImageEdition $ImageEdition -Overwrite:$Overwrite -Apply
    $xmlSha = (Get-FileHash -LiteralPath $xmlPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $meta = [ordered]@{
        schema_version      = 1
        autounattend_path   = $xmlPath
        autounattend_sha256 = $xmlSha
        locale              = $Locale
        keyboard_layout     = $KeyboardLayout
        contains_passwords  = $false
        created_at          = [DateTimeOffset]::UtcNow.ToString('o')
    }
    Write-VmLabJsonAtomic -Path $metaPath -Data $meta
    return [pscustomobject]@{
        status              = 'SUCCEEDED'
        reason_code         = 'answer_media_staged'
        staging_dir         = $dirFull
        xml_path            = $xmlPath
        autounattend_sha256 = $xmlSha
        meta_path           = $metaPath
        xml_result          = $xmlRes
    }
}

function Get-VmLabSetupProgressReport {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [pscredential]$Credential,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $Name
    $boot = Get-VmLabBootDiagnostics -Name $Name -ManifestRoot $ManifestRoot
    $guest = Get-VmLabGuestStatus -Name $Name -Credential $Credential -ManifestRoot $ManifestRoot
    $guidance = @()
    if ($boot.dvd_first_in_boot_order -eq $false) {
        $guidance += 'UEFI boot order does not place DVD first; inspect firmware boot order before Windows Setup.'
    }
    if ($guest.guest_state -eq 'windows_booted_account_unavailable') {
        $guidance += 'Guest booted into OOBE/Setup; complete local account setup via VMConnect.'
    } elseif ($guest.guest_state -eq 'ps_direct_auth_unavailable') {
        $guidance += 'Supply -Credential to probe PowerShell Direct readiness.'
    } elseif ($guest.guest_state -eq 'guest_ready') {
        $guidance += 'Guest PowerShell Direct is ready.'
    } else {
        $guidance += 'If Windows Setup DVD prompt timed out, open VMConnect and press any key on reset.'
    }
    return [pscustomobject]@{
        status      = if ($guest.guest_state -eq 'guest_ready') { 'SUCCEEDED' } else { 'AWAITING_INTERACTION' }
        reason_code = $guest.guest_state
        vm_name     = $Name
        boot        = $boot
        guest       = $guest
        guidance    = @($guidance)
    }
}

function Test-VmLabPreparedImagePolicy {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VhdxPath,
        [switch]$SysprepGeneralized,
        [switch]$LicensingAcknowledged
    )
    $vhdxFull = Test-VmLabSafePath -Path $VhdxPath -Label 'VhdxPath' -CheckReparsePoints
    if (-not $SysprepGeneralized) {
        throw 'Reusable prepared VHDX image requires -SysprepGeneralized confirmation (Sysprep /generalize /oobe /shutdown).'
    }
    if (-not $LicensingAcknowledged) {
        throw 'Reusable prepared VHDX image requires -LicensingAcknowledged.'
    }
    return [pscustomobject]@{
        valid                  = $true
        vhdx_path              = $vhdxFull
        sysprep_generalized    = $true
        licensing_acknowledged = $true
    }
}
