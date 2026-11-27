#Requires -Version 7.0

function Get-VmLabEvidencePlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$GuestRoots,
        [Parameter(Mandatory)][string]$HostDestination,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $Name
    $hostDestFull = Test-VmLabSafePath -Path $HostDestination -Label 'HostDestination' -CheckReparsePoints
    $validatedRoots = @()
    foreach ($gr in $GuestRoots) {
        $validatedRoots += Resolve-VmLabGuestPath -Path $gr -Label 'GuestRoot'
    }
    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) { throw "VM '$Name' was not found." }
    Assert-VmLabTargetNotProtected -VmName $vm.Name -VmId ([string]$vm.Id)
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    if (-not $own.owned) { throw "VM '$Name' is not owned by vm_lab: $($own.reason)" }

    return [pscustomobject]@{
        status           = 'PLANNED'
        reason_code      = 'evidence_plan_ready'
        vm_name          = $vm.Name
        vm_id            = [string]$vm.Id
        guest_roots      = @($validatedRoots)
        host_destination = $hostDestFull
    }
}

function Receive-VmLabGuestEvidence {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$GuestRoots,
        [Parameter(Mandatory)][string]$HostDestination,
        [string]$OperationId = ([guid]::NewGuid().ToString('N').Substring(0, 12)),
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [switch]$Apply,
        [int]$MaxConnectAttempts = 1,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $plan = Get-VmLabEvidencePlan -Name $Name -GuestRoots $GuestRoots -HostDestination $HostDestination -ManifestRoot $ManifestRoot
    if (-not $Apply -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($plan.vm_name, "Collect guest evidence to '$($plan.host_destination)'")) {
        return $plan
    }

    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) { throw "VM '$Name' was not found." }
    if ([string]$vm.State -ne 'Running') {
        return [pscustomobject]@{
            status      = 'EVIDENCE_FAILED'
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

    if (-not (Test-Path -LiteralPath $plan.host_destination -PathType Container)) {
        New-Item -ItemType Directory -Path $plan.host_destination -Force | Out-Null
    }
    $hostRootFull = Test-VmLabSafePath -Path $plan.host_destination -Label 'HostDestination' -CheckReparsePoints

    $collected = [System.Collections.Generic.List[object]]::new()
    $missing = [System.Collections.Generic.List[object]]::new()
    $rootErrors = [System.Collections.Generic.List[object]]::new()

    $null = Invoke-VmLabGuestSession -VmId $vm.Id -VmName $vm.Name -Credential $cred -MaxConnectAttempts $MaxConnectAttempts -ScriptBlock {
        param($session)
        $rootIndex = 0
        foreach ($gr in $plan.guest_roots) {
            $rootIndex++
            $inv = Invoke-VmLabPSSessionCommand -Session $session -ArgumentList @($gr) -ScriptBlock {
                param($rootPath)
                if (-not (Test-Path -LiteralPath $rootPath)) {
                    return [pscustomobject]@{ exists = $false; files = @(); error = "Guest evidence root not found: $rootPath" }
                }
                $item = Get-Item -LiteralPath $rootPath -Force
                if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                    return [pscustomobject]@{ exists = $true; files = @(); error = "Refusing reparse-point evidence root: $rootPath" }
                }
                $files = @()
                if (-not $item.PSIsContainer) {
                    $sha = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                    $files += [pscustomobject]@{
                        full_path     = $item.FullName
                        relative_path = $item.Name
                        sha256        = $sha
                        length        = [int64]$item.Length
                    }
                } else {
                    $baseFull = [System.IO.Path]::GetFullPath($item.FullName).TrimEnd('\', '/')
                    foreach ($f in @(Get-ChildItem -LiteralPath $baseFull -Recurse -File -Force | Sort-Object FullName)) {
                        if ($f.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { continue }
                        $rel = [System.IO.Path]::GetRelativePath($baseFull, $f.FullName).Replace('\', '/')
                        $sha = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                        $files += [pscustomobject]@{
                            full_path     = $f.FullName
                            relative_path = $rel
                            sha256        = $sha
                            length        = [int64]$f.Length
                        }
                    }
                }
                return [pscustomobject]@{ exists = $true; files = @($files); error = $null }
            }

            if (-not $inv.exists -or $inv.error) {
                $rootErrors.Add([pscustomobject]@{ guest_root = $gr; error = $inv.error })
                continue
            }

            $rootFolderName = if ($plan.guest_roots.Count -gt 1) { "root_$rootIndex" } else { '' }
            foreach ($gf in @($inv.files)) {
                $relWin = ([string]$gf.relative_path).Replace('/', '\')
                $relTarget = if ($rootFolderName) { Join-Path $rootFolderName $relWin } else { $relWin }
                $destPath = Test-VmLabSafePath -Path (Join-Path $hostRootFull $relTarget) -Label 'evidence_dest' -WithinRoot $hostRootFull -CheckReparsePoints
                $destParent = Split-Path -Parent $destPath
                if (-not (Test-Path -LiteralPath $destParent -PathType Container)) {
                    New-Item -ItemType Directory -Path $destParent -Force | Out-Null
                }

                # Idempotent skip if already collected with matching hash and length
                if (Test-Path -LiteralPath $destPath -PathType Leaf) {
                    $curLen = [int64](Get-Item -LiteralPath $destPath -Force).Length
                    $curSha = (Get-FileHash -LiteralPath $destPath -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($curLen -eq [int64]$gf.length -and $curSha -eq [string]$gf.sha256) {
                        $collected.Add([pscustomobject]@{
                            guest_path    = $gf.full_path
                            host_path     = $destPath
                            relative_path = $gf.relative_path
                            sha256        = $curSha
                            length        = $curLen
                            status        = 'skipped_verified'
                        })
                        continue
                    }
                }

                $tmpHost = "$destPath.vm_lab_tmp.$OperationId"
                try {
                    Copy-VmLabPSSessionItem -Session $session -SourcePath $gf.full_path -DestinationPath $tmpHost -Direction 'FromGuest' -Overwrite
                    if (-not (Test-Path -LiteralPath $tmpHost -PathType Leaf)) {
                        throw "Staged host evidence missing: $tmpHost"
                    }
                    $actualLen = [int64](Get-Item -LiteralPath $tmpHost -Force).Length
                    $actualSha = (Get-FileHash -LiteralPath $tmpHost -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($actualLen -ne [int64]$gf.length -or $actualSha -ne [string]$gf.sha256) {
                        Remove-Item -LiteralPath $tmpHost -Force -ErrorAction SilentlyContinue
                        throw "Evidence hash/length mismatch for '$($gf.relative_path)'."
                    }
                    Move-Item -LiteralPath $tmpHost -Destination $destPath -Force
                    $collected.Add([pscustomobject]@{
                        guest_path    = $gf.full_path
                        host_path     = $destPath
                        relative_path = $gf.relative_path
                        sha256        = $actualSha
                        length        = $actualLen
                        status        = 'collected'
                    })
                } catch {
                    if (Test-Path -LiteralPath $tmpHost -PathType Leaf) {
                        Remove-Item -LiteralPath $tmpHost -Force -ErrorAction SilentlyContinue
                    }
                    $missing.Add([pscustomobject]@{
                        guest_path    = $gf.full_path
                        relative_path = $gf.relative_path
                        error         = $_.Exception.Message
                    })
                }
            }
        }
    }

    $evStatus = if ($missing.Count -eq 0 -and $rootErrors.Count -eq 0) {
        'EVIDENCE_COMPLETE'
    } elseif ($collected.Count -gt 0) {
        'EVIDENCE_PARTIAL'
    } else {
        'EVIDENCE_FAILED'
    }

    return [pscustomobject]@{
        status           = $evStatus
        reason_code      = $evStatus.ToLowerInvariant()
        vm_name          = $vm.Name
        vm_id            = [string]$vm.Id
        host_destination = $hostRootFull
        collected_count  = $collected.Count
        missing_count    = $missing.Count
        root_error_count = $rootErrors.Count
        collected        = @($collected.ToArray())
        missing          = @($missing.ToArray())
        root_errors      = @($rootErrors.ToArray())
    }
}
