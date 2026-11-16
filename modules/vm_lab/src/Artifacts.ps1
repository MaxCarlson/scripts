#Requires -Version 7.0

function New-VmLabArtifactManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$DestinationRoot,
        [string]$ManifestId = ('manifest-' + [guid]::NewGuid().ToString('N').Substring(0, 8)),
        [string]$TrustedRootDigest
    )
    $srcFull = Test-VmLabSafePath -Path $SourceRoot -Label 'SourceRoot' -CheckReparsePoints
    if (-not (Test-Path -LiteralPath $srcFull -PathType Container)) {
        throw "SourceRoot directory not found: '$srcFull'."
    }
    $destNorm = Resolve-VmLabGuestPath -Path $DestinationRoot -Label 'DestinationRoot'

    $items = @()
    $files = @(Get-ChildItem -LiteralPath $srcFull -Recurse -File -Force | Sort-Object FullName)
    foreach ($f in $files) {
        if ($f.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Refusing reparse-point artifact '$($f.FullName)'."
        }
        $rel = [System.IO.Path]::GetRelativePath($srcFull, $f.FullName).Replace('\', '/')
        if ($rel -match '(^|/)\.\.(/|$)' -or $rel.StartsWith('/')) {
            throw "Invalid relative artifact path '$rel'."
        }
        $sha = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $items += [pscustomobject]@{
            relative_path = $rel
            sha256        = $sha
            length        = [int64]$f.Length
        }
    }
    $manifest = [pscustomobject]@{
        schema_version      = 1
        manifest_id         = $ManifestId
        trusted_root_digest = $TrustedRootDigest
        destination_root    = $destNorm
        artifacts           = @($items)
    }
    $null = Test-VmLabArtifactManifestSchema -Manifest $manifest
    return $manifest
}

function Publish-VmLabArtifactBundle {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][object]$Manifest,
        [string]$OperationId = ([guid]::NewGuid().ToString('N').Substring(0, 12)),
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [switch]$Apply,
        [switch]$AuthorizeGuestMutation,
        [int]$MaxConnectAttempts = 1,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $Name
    $srcFull = Test-VmLabSafePath -Path $SourceRoot -Label 'SourceRoot' -CheckReparsePoints
    $schemaInfo = Test-VmLabArtifactManifestSchema -Manifest $Manifest
    $destRoot = Resolve-VmLabGuestPath -Path ([string]$Manifest.destination_root) -Label 'manifest.destination_root'

    # Verify all host source files match manifest SHA-256 and byte lengths before touching VM
    $verifiedSources = @()
    foreach ($item in @($Manifest.artifacts)) {
        $relWin = ([string]$item.relative_path).Replace('/', '\')
        $localPath = Test-VmLabSafePath -Path (Join-Path $srcFull $relWin) -Label "artifact($relWin)" -WithinRoot $srcFull -CheckReparsePoints
        if (-not (Test-Path -LiteralPath $localPath -PathType Leaf)) {
            throw "Manifest artifact missing on host: '$localPath'."
        }
        $fi = Get-Item -LiteralPath $localPath -Force
        if ([int64]$fi.Length -ne [int64]$item.length) {
            throw "Host artifact length mismatch for '$($item.relative_path)': expected $($item.length), actual $($fi.Length)."
        }
        $sha = (Get-FileHash -LiteralPath $localPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($sha -ne ([string]$item.sha256).ToLowerInvariant()) {
            throw "Host artifact SHA-256 mismatch for '$($item.relative_path)': expected $($item.sha256), actual $sha."
        }
        $verifiedSources += [pscustomobject]@{
            relative_path = [string]$item.relative_path
            local_path    = $localPath
            guest_path    = (Join-Path $destRoot $relWin)
            sha256        = $sha
            length        = [int64]$item.length
        }
    }

    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) { throw "VM '$Name' was not found." }
    Assert-VmLabTargetNotProtected -VmName $vm.Name -VmId ([string]$vm.Id)
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    if (-not $own.owned) { throw "VM '$Name' is not owned by vm_lab: $($own.reason)" }

    $authorized = Test-VmLabCapabilityAuthorized -Capability 'guest_mutation' -Apply:$Apply -AuthorizeGuestMutation:$AuthorizeGuestMutation
    if (-not $authorized -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($vm.Name, "Deploy $($verifiedSources.Count) verified artifacts to '$destRoot'")) {
        $reason = if (-not $Apply -or $WhatIfPreference) { 'dry_run_not_applied' } else { 'guest_mutation_authorization_required' }
        return [pscustomobject]@{
            status           = if ($reason -eq 'dry_run_not_applied') { 'PLANNED' } else { 'BLOCKED' }
            reason_code      = $reason
            dry_run          = $true
            vm_name          = $vm.Name
            vm_id            = [string]$vm.Id
            manifest_digest  = $schemaInfo.manifest_digest
            destination_root = $destRoot
            artifact_count   = $verifiedSources.Count
            items            = @($verifiedSources | Select-Object relative_path, guest_path, sha256, length)
        }
    }

    if ([string]$vm.State -ne 'Running') {
        return [pscustomobject]@{
            status      = 'BLOCKED'
            reason_code = 'vm_not_running'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
        }
    }

    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        return [pscustomobject]@{
            status      = 'AWAITING_INTERACTION'
            reason_code = 'guest_credentials_required'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
        }
    }

    $itemResults = [System.Collections.Generic.List[object]]::new()
    $stats = @{ bytes_transferred = [int64]0; failed_count = 0 }

    $null = Invoke-VmLabGuestSession -VmId $vm.Id -VmName $vm.Name -Credential $cred -MaxConnectAttempts $MaxConnectAttempts -ScriptBlock {
        param($session)
        foreach ($art in $verifiedSources) {
            # Re-probe guest destination hash for idempotent resume
            $existing = Invoke-VmLabPSSessionCommand -Session $session -ArgumentList @($art.guest_path) -ScriptBlock {
                param($gp)
                if (Test-Path -LiteralPath $gp -PathType Leaf) {
                    return [pscustomobject]@{
                        exists = $true
                        sha256 = (Get-FileHash -LiteralPath $gp -Algorithm SHA256).Hash.ToLowerInvariant()
                        length = [int64](Get-Item -LiteralPath $gp -Force).Length
                    }
                }
                return [pscustomobject]@{ exists = $false; sha256 = $null; length = 0 }
            }

            if ($existing.exists -and $existing.sha256 -eq $art.sha256 -and $existing.length -eq $art.length) {
                $itemResults.Add([pscustomobject]@{
                    relative_path = $art.relative_path
                    guest_path    = $art.guest_path
                    status        = 'skipped_verified'
                    sha256        = $art.sha256
                    length        = $art.length
                })
                continue
            }

            $stagePath = "$($art.guest_path).vm_lab_tmp.$OperationId"
            $parentGuest = Split-Path -Parent $art.guest_path
            Invoke-VmLabPSSessionCommand -Session $session -ArgumentList @($parentGuest) -ScriptBlock {
                param($pg)
                if (-not (Test-Path -LiteralPath $pg -PathType Container)) {
                    New-Item -ItemType Directory -Path $pg -Force | Out-Null
                }
            }

            try {
                Copy-VmLabPSSessionItem -Session $session -SourcePath $art.local_path -DestinationPath $stagePath -Direction 'ToGuest' -Overwrite
                $staged = Invoke-VmLabPSSessionCommand -Session $session -ArgumentList @($stagePath, $art.guest_path, $art.sha256) -ScriptBlock {
                    param($sp, $gp, $expSha)
                    if (-not (Test-Path -LiteralPath $sp -PathType Leaf)) {
                        throw "Staged guest artifact missing: $sp"
                    }
                    $actualSha = (Get-FileHash -LiteralPath $sp -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($actualSha -ne $expSha) {
                        throw "Guest staged SHA-256 mismatch for '$gp': expected $expSha, actual $actualSha"
                    }
                    Move-Item -LiteralPath $sp -Destination $gp -Force
                    return $actualSha
                }
                $stats.bytes_transferred += $art.length
                $itemResults.Add([pscustomobject]@{
                    relative_path = $art.relative_path
                    guest_path    = $art.guest_path
                    status        = 'deployed'
                    sha256        = $staged
                    length        = $art.length
                })
            } catch {
                $stats.failed_count++
                $itemResults.Add([pscustomobject]@{
                    relative_path = $art.relative_path
                    guest_path    = $art.guest_path
                    status        = 'failed'
                    error         = $_.Exception.Message
                })
            }
        }
    }

    $overallStatus = if ($stats.failed_count -eq 0) { 'SUCCEEDED' } elseif ($itemResults | Where-Object { $_.status -in @('deployed', 'skipped_verified') }) { 'PARTIAL' } else { 'FAILED' }
    return [pscustomobject]@{
        status            = $overallStatus
        reason_code       = if ($stats.failed_count -eq 0) { 'artifacts_deployed_verified' } else { 'artifact_deploy_incomplete' }
        dry_run           = $false
        vm_name           = $vm.Name
        vm_id             = [string]$vm.Id
        manifest_digest   = $schemaInfo.manifest_digest
        destination_root  = $destRoot
        artifact_count    = $verifiedSources.Count
        bytes_transferred = $stats.bytes_transferred
        failed_count      = $stats.failed_count
        items             = @($itemResults.ToArray())
    }
}

function Expand-VmLabGuestArchive {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$GuestArchivePath,
        [Parameter(Mandatory)][string]$ExpectedArchiveSha256,
        [Parameter(Mandatory)][string]$GuestExtractRoot,
        [int]$MaxEntries = 5000,
        [int64]$MaxUncompressedBytes = 536870912,
        [pscredential]$Credential,
        [switch]$Apply,
        [switch]$AuthorizeGuestMutation,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $Name
    $arch = Resolve-VmLabGuestPath -Path $GuestArchivePath -Label 'GuestArchivePath'
    $dest = Resolve-VmLabGuestPath -Path $GuestExtractRoot -Label 'GuestExtractRoot'
    if ($ExpectedArchiveSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Invalid ExpectedArchiveSha256 '$ExpectedArchiveSha256'."
    }

    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) { throw "VM '$Name' was not found." }
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    if (-not $own.owned) { throw "VM '$Name' is not owned by vm_lab: $($own.reason)" }

    $authorized = Test-VmLabCapabilityAuthorized -Capability 'guest_mutation' -Apply:$Apply -AuthorizeGuestMutation:$AuthorizeGuestMutation
    if (-not $authorized -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($vm.Name, "Safely extract '$arch' to '$dest'")) {
        return [pscustomobject]@{
            status      = if (-not $Apply -or $WhatIfPreference) { 'PLANNED' } else { 'BLOCKED' }
            reason_code = if (-not $Apply -or $WhatIfPreference) { 'dry_run_not_applied' } else { 'guest_mutation_authorization_required' }
            dry_run     = $true
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
        }
    }

    $res = Invoke-VmLabGuestSession -VmId $vm.Id -VmName $vm.Name -Credential $Credential -ScriptBlock {
        param($session)
        Invoke-VmLabPSSessionCommand -Session $session -ArgumentList @($arch, $ExpectedArchiveSha256.ToLowerInvariant(), $dest, $MaxEntries, $MaxUncompressedBytes) -ScriptBlock {
            param($ap, $expSha, $dp, $maxCnt, $maxBytes)
            if (-not (Test-Path -LiteralPath $ap -PathType Leaf)) {
                throw "Guest archive not found: $ap"
            }
            $actualSha = (Get-FileHash -LiteralPath $ap -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualSha -ne $expSha) {
                throw "Guest archive SHA-256 mismatch: expected $expSha, actual $actualSha"
            }
            if ((Test-Path -LiteralPath $dp) -and @(Get-ChildItem -LiteralPath $dp -Force).Count -gt 0) {
                throw "Refusing to extract into non-empty guest directory '$dp'."
            }
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $zip = [System.IO.Compression.ZipFile]::OpenRead($ap)
            try {
                if ($zip.Entries.Count -gt $maxCnt) {
                    throw "Archive entry count $($zip.Entries.Count) exceeds limit $maxCnt."
                }
                $totalBytes = [int64]0
                $dpFull = [System.IO.Path]::GetFullPath($dp).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
                foreach ($entry in $zip.Entries) {
                    if ($entry.FullName -match '(^|[\\/])\.\.([\\/]|$)' -or $entry.FullName.StartsWith('/') -or $entry.FullName -match '^[A-Za-z]:') {
                        throw "Archive contains unsafe entry path '$($entry.FullName)'."
                    }
                    $target = [System.IO.Path]::GetFullPath((Join-Path $dp $entry.FullName))
                    if (-not $target.StartsWith($dpFull, [System.StringComparison]::OrdinalIgnoreCase)) {
                        throw "Archive entry escapes target root: '$($entry.FullName)'."
                    }
                    $totalBytes += [int64]$entry.Length
                    if ($totalBytes -gt $maxBytes) {
                        throw "Archive uncompressed size exceeds limit $maxBytes bytes."
                    }
                }
                New-Item -ItemType Directory -Path $dp -Force | Out-Null
                [System.IO.Compression.ZipFile]::ExtractToDirectory($ap, $dp)
                return [pscustomobject]@{
                    status          = 'SUCCEEDED'
                    reason_code     = 'archive_extracted_verified'
                    archive_sha256  = $actualSha
                    entry_count     = $zip.Entries.Count
                    extracted_bytes = $totalBytes
                    extract_root    = $dp
                }
            } finally {
                $zip.Dispose()
            }
        }
    }
    return $res
}
