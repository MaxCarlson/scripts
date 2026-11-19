#Requires -Version 7.0
<#
.SYNOPSIS
    Fail-closed PowerShell Direct recovery wrapper for failed H4 Windows guest installations.
.DESCRIPTION
    Safely inspects and optionally recovers a failed H4 guest installation (such as the
    disabled v8 task ResourceCoordinator-H4-9ea7312c8c-install-logon) by invoking the
    Python guest harness `windows_acceptance.py --profile recover` rather than the
    host qualification orchestrator.

    Default invocation is a strictly read-only recovery dry run (`--profile recover`).
    Staging an unextracted verified recovery bundle requires `-StageBundle`.
    Guest task/launcher removal requires both `-Apply` (`-a`) and `-AuthorizeGuestMutation`.
    `-WhatIf` suppresses all host and guest mutations.
    `-PostInventory` runs a standalone read-only verification proving protected task
    removal, clean inventories, and preserved phase/test-root evidence.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Alias('a')][switch]$Apply,
    [switch]$AuthorizeGuestMutation,
    [switch]$StageBundle,
    [switch]$PostInventory,
    [Alias('j')][switch]$Json,
    [string]$OperationId,
    [string]$VmId = 'd8483f98-8884-4758-abd1-cd6107c83c03',
    [string]$VmName = 'RC-H4-Windows-Acceptance',
    [string]$ProtectedCheckpointId = '9f45b469-382c-4be0-a50e-7a71384c7922',
    [string]$ExpectedGuestHost = 'DESKTOP-1ITSJV0',
    [pscredential]$Credential,
    [string]$GuestTestRoot = 'C:\H4-Guest-Work\runs\h4-rc-install-v8-install-20261115-194217-a283bd',
    [string]$ExpectedSourceTreeSha256 = '27764f44b7311072b62b0dbf8d8faa96260f3deb8a0f09bf0bef969368599989',
    [string[]]$ExpectedManifestTasks = @(
        'ResourceCoordinator-H4-9ea7312c8c-install-boot',
        'ResourceCoordinator-H4-9ea7312c8c-install-logon',
        'ResourceCoordinator-H4-9ea7312c8c-install-viewer'
    ),
    [string]$HostCleanupManifest = 'C:\H4-VM-Staging\evidence-v8-install-only\v8-install-20261115-194217-a283bd\cleanup-manifest.json',
    [string]$BundleZip = 'C:\H4-VM-Staging\bundle-rc1-v9\h4-windows-acceptance.zip',
    [string]$ExpectedBundleSha256 = '16912bab41ddb1d2be7c23f89c5caf70cdb94d84e6cf08e8e24ca0aa16c74017',
    [string]$BootstrapScript = (Join-Path $PSScriptRoot 'Bootstrap-H4GuestBundle.ps1'),
    [string]$ExpectedBootstrapSha256 = '5EFACFAFCECC45DF5459D53B75A999B21574C83D0A2F5339F0A4AB1AB5D01DE9',
    [string]$GuestBundleRoot = 'C:\H4-Guest-Work\recovery-bundles\v9-16912bab',
    [string]$GuestVenvPython = 'C:\H4-Guest-Work\venv\Scripts\python.exe',
    [string]$EvidenceRoot = 'C:\H4-VM-Staging\evidence-recovery'
)

$ErrorActionPreference = 'Stop'
$H4AuthorizationPhrase = 'I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION'

if (-not (Get-Command -Name Get-H4HostVm -ErrorAction SilentlyContinue)) {
    function Get-H4HostVm {
        param([Parameter(Mandatory)][string]$Id)
        $vmGuid = [guid]$Id
        $vms = @(Get-VM -Id $vmGuid -ErrorAction Stop)
        if ($vms.Count -ne 1) {
            throw "Expected exactly 1 Hyper-V VM for ID '$Id', found $($vms.Count)."
        }
        return $vms[0]
    }
}
if (-not (Get-Command -Name Get-H4HostCheckpoints -ErrorAction SilentlyContinue)) {
    function Get-H4HostCheckpoints {
        param([Parameter(Mandatory)][string]$Id)
        $vmObj = Get-H4HostVm -Id $Id
        return @(Get-VMSnapshot -VM $vmObj -ErrorAction Stop)
    }
}
if (-not (Get-Command -Name Open-H4GuestSession -ErrorAction SilentlyContinue)) {
    function Open-H4GuestSession {
        param([Parameter(Mandatory)][string]$Id, [Parameter(Mandatory)][pscredential]$Cred)
        return New-PSSession -VMId $Id -Credential $Cred -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Close-H4GuestSession -ErrorAction SilentlyContinue)) {
    function Close-H4GuestSession {
        param($Session)
        if ($Session) { Remove-PSSession -Session $Session -ErrorAction SilentlyContinue }
    }
}
if (-not (Get-Command -Name Invoke-H4GuestScript -ErrorAction SilentlyContinue)) {
    function Invoke-H4GuestScript {
        param($Session, [Parameter(Mandatory)][scriptblock]$ScriptBlock, [object[]]$ArgumentList = @())
        return Invoke-Command -Session $Session -ScriptBlock $ScriptBlock -ArgumentList $ArgumentList -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Copy-H4ToGuest -ErrorAction SilentlyContinue)) {
    function Copy-H4ToGuest {
        param($Session, [Parameter(Mandatory)][string]$SourcePath, [Parameter(Mandatory)][string]$DestinationPath)
        Copy-Item -ToSession $Session -LiteralPath $SourcePath -Destination $DestinationPath -Force -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Copy-H4FromGuest -ErrorAction SilentlyContinue)) {
    function Copy-H4FromGuest {
        param($Session, [Parameter(Mandatory)][string]$SourcePath, [Parameter(Mandatory)][string]$DestinationPath)
        if ($SourcePath -match '^(.*)\\\*$') {
            $baseDir = $Matches[1]
            $stagedDir = Invoke-Command -Session $Session -ArgumentList @($baseDir) -ScriptBlock {
                param($srcRoot)
                $ErrorActionPreference = 'Stop'
                $tmp = Join-Path $env:TEMP ('h4-ev-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
                New-Item -ItemType Directory -Path $tmp -Force | Out-Null
                $allowExt = @('.json', '.xml', '.log', '.yaml', '.txt')
                $files = @(Get-ChildItem -LiteralPath $srcRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
                    ($allowExt -contains $_.Extension.ToLowerInvariant()) -and
                    ($_.Name -ne 'request.json') -and
                    ($_.Extension.ToLowerInvariant() -ne '.token')
                })
                foreach ($f in $files) {
                    $rel = $f.FullName.Substring($srcRoot.TrimEnd('\').Length).TrimStart('\')
                    $dst = Join-Path $tmp $rel
                    $parent = Split-Path -Parent $dst
                    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
                    Copy-Item -LiteralPath $f.FullName -Destination $dst -Force
                }
                return $tmp
            } -ErrorAction Stop
            try {
                Copy-Item -FromSession $Session -Path "$stagedDir\*" -Destination $DestinationPath -Recurse -Force -ErrorAction Stop
            } finally {
                Invoke-Command -Session $Session -ArgumentList @($stagedDir) -ScriptBlock {
                    param($tmp)
                    if ($tmp -and (Test-Path -LiteralPath $tmp)) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
                } -ErrorAction SilentlyContinue
            }
        } else {
            Copy-Item -FromSession $Session -Path $SourcePath -Destination $DestinationPath -Recurse -Force -ErrorAction Stop
        }
    }
}
if (-not (Get-Command -Name Request-H4GuestCredential -ErrorAction SilentlyContinue)) {
    function Request-H4GuestCredential {
        param([string]$UserHint = 'DESKTOP-1ITSJV0\mcarls')
        return Get-Credential -UserName $UserHint -Message 'Enter Windows 11 guest local admin credentials for PowerShell Direct'
    }
}

function Assert-H4NoReparsePoint {
    param([Parameter(Mandatory)][string]$FullPath, [Parameter(Mandatory)][string]$Label)
    $root = [System.IO.Path]::GetPathRoot($FullPath)
    $current = $FullPath
    while (-not [string]::IsNullOrWhiteSpace($current) -and $current -ne $root) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label path traverses a reparse point at '$current'."
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Assert-H4FileDigest {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ExpectedSha256, [Parameter(Mandatory)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedSha256) -or $ExpectedSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "$Label expected SHA-256 must be a 64-character hex digest, got '$ExpectedSha256'"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path -ErrorAction Stop).Hash
    if ($actual.ToLowerInvariant() -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "$Label SHA-256 mismatch: expected $ExpectedSha256, got $actual"
    }
    return $actual
}

function Get-H4RecoveryCommandSpec {
    param(
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][string]$BundleRoot,
        [Parameter(Mandatory)][string]$TestRoot,
        [switch]$ApplyMutation,
        [string]$AuthorizationPhrase = 'I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION'
    )
    $runner = Join-Path $BundleRoot 'harness\windows_acceptance.py'
    $srcNew = Join-Path $BundleRoot 'sources\rc-1.0.0'
    $manifest = Join-Path $BundleRoot 'manifest.json'
    $modRoot = Join-Path $srcNew 'modules\resource_coordinator'
    $args = [System.Collections.Generic.List[string]]::new()
    $args.Add($runner)
    $args.Add('--test-root')
    $args.Add($TestRoot)
    if ($ApplyMutation) {
        $args.Add('--apply')
    }
    $args.Add('--profile')
    $args.Add('recover')
    if ($ApplyMutation) {
        $args.Add('--authorization')
        $args.Add($AuthorizationPhrase)
        $args.Add('--authorize-guest-mutation')
    }
    $args.Add('--source-root')
    $args.Add($srcNew)
    $args.Add('--source-manifest')
    $args.Add($manifest)
    $args.Add('--json')

    return [pscustomobject]@{
        python      = $PythonExe
        module_root = $modRoot
        runner      = $runner
        source_root = $srcNew
        manifest    = $manifest
        apply       = [bool]$ApplyMutation
        arguments   = $args.ToArray()
        rendered    = "$PythonExe -B " + (($args.ToArray() | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' ')
    }
}

function Save-H4JsonArtifact {
    param([string]$Dir, [string]$FileName, $Data)
    if ($Dir -and (Test-Path -LiteralPath $Dir)) {
        $Data | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $Dir $FileName) -Encoding utf8
    }
}

function Invoke-H4GuestRecoveryInspection {
    param(
        $Session,
        [Parameter(Mandatory)][string]$ExpectedHost,
        [Parameter(Mandatory)][string]$TestRoot,
        [Parameter(Mandatory)][string]$ExpectedSourceDigest,
        [string[]]$ExpectedTasks = @(),
        [switch]$RequirePostClean
    )
    $expTasksJson = ConvertTo-Json -Compress -InputObject @($ExpectedTasks)
    $insp = Invoke-H4GuestScript -Session $Session -ArgumentList @($TestRoot, $ExpectedSourceDigest, $expTasksJson) -ScriptBlock {
        param($tRoot, $expSha, $expTasksRaw)
        $ErrorActionPreference = 'Stop'

        $cs = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

        $tasks = @(Get-ScheduledTask -ErrorAction Stop)
        $rcTaskObjs = @($tasks | Where-Object { $_.TaskName -like '*ResourceCoordinator*' -or $_.TaskName -like '*KRig*' })
        $rcTaskRows = @(foreach ($t in $rcTaskObjs) {
            $act = (@($t.Actions | ForEach-Object { ([string]$_.Execute + ' ' + [string]$_.Arguments).Trim() }) -join ';')
            [pscustomobject]@{
                name     = [string]$t.TaskName
                state    = [string]$t.State
                enabled  = [bool]$t.Settings.Enabled
                actions  = $act
            }
        })

        $services = @(Get-Service -ErrorAction Stop)
        $rcServices = @($services | Where-Object { $_.Name -like '*ResourceCoordinator*' -or $_.Name -like '*KRig*' -or $_.Name -like '*GPUCoordinator*' } | ForEach-Object {
            [pscustomobject]@{ name = [string]$_.Name; status = [string]$_.Status }
        })

        $procs = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
        $rcProcs = @($procs | Where-Object {
            $_.Name -match 'resource[-_]?coordinator|gpu[-_]?coordinator|krig-miner|srbminer' -or
            ($_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'resource_coordinator\.cli')
        } | ForEach-Object {
            [pscustomobject]@{ name = [string]$_.Name; pid = [int]$_.ProcessId }
        })

        $rootExists = Test-Path -LiteralPath $tRoot -PathType Container
        $rootHasReparse = $false
        if ($rootExists) {
            $rootFull = [IO.Path]::GetFullPath($tRoot)
            $rootPrefix = [IO.Path]::GetPathRoot($rootFull)
            $cur = $rootFull
            while ($cur -and $cur -ne $rootPrefix) {
                if (Test-Path -LiteralPath $cur) {
                    $it = Get-Item -LiteralPath $cur -Force
                    if (($it.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $rootHasReparse = $true; break }
                }
                $par = Split-Path -Parent $cur
                if ($par -eq $cur) { break }
                $cur = $par
            }
            if (-not $rootHasReparse) {
                foreach ($ch in @(Get-ChildItem -LiteralPath $tRoot -Force -ErrorAction SilentlyContinue)) {
                    if (($ch.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $rootHasReparse = $true; break }
                }
            }
        }

        $markerPath = Join-Path $tRoot '.h4-test-root.json'
        $manifestPath = Join-Path $tRoot 'cleanup-manifest.json'
        $markerExists = Test-Path -LiteralPath $markerPath -PathType Leaf
        $manifestExists = Test-Path -LiteralPath $manifestPath -PathType Leaf
        $markerObj = if ($markerExists) { Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json } else { $null }
        $manifestObj = if ($manifestExists) { Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } else { $null }

        $phaseRows = [System.Collections.Generic.List[object]]::new()
        $ports = [System.Collections.Generic.HashSet[int]]::new()
        $manifestTasks = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

        if ($manifestObj -and $manifestObj.phases) {
            foreach ($p in @($manifestObj.phases)) {
                $pRoot = [string]$p.root
                $pExists = $pRoot -and (Test-Path -LiteralPath $pRoot -PathType Container)
                $pFiles = if ($pExists) { @(Get-ChildItem -LiteralPath $pRoot -Recurse -File -ErrorAction SilentlyContinue).Count } else { 0 }
                $launcherExists = $pExists -and (Test-Path -LiteralPath (Join-Path $pRoot 'start-coordinator-managed.ps1') -PathType Leaf)
                $viewerExists = $pExists -and (Test-Path -LiteralPath (Join-Path $pRoot 'open-krig-viewer.ps1') -PathType Leaf)
                if ($null -ne $p.port) { [void]$ports.Add([int]$p.port) }
                foreach ($tn in @($p.task_names)) { if ($tn) { [void]$manifestTasks.Add([string]$tn) } }
                $phaseRows.Add([pscustomobject]@{
                    phase              = [string]$p.phase
                    run_id             = [string]$p.run_id
                    port               = [int]$p.port
                    root               = $pRoot
                    source_tree_sha256 = [string]$p.source_tree_sha256
                    task_names         = @($p.task_names)
                    root_exists        = [bool]$pExists
                    file_count         = $pFiles
                    launcher_exists    = [bool]$launcherExists
                    viewer_exists      = [bool]$viewerExists
                })
            }
        }

        $listeners = @()
        foreach ($pt in $ports) {
            $rows = @(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter ("State = 2 AND LocalPort = " + $pt) -ErrorAction Stop | ForEach-Object {
                [pscustomobject]@{ port = $pt; local_address = [string]$_.LocalAddress; pid = [int]$_.OwningProcess }
            })
            $listeners += $rows
        }

        $recoveryResPath = Join-Path $tRoot 'recovery-result.json'
        $testResPath = Join-Path $tRoot 'test-results.json'
        $recoveryResult = if (Test-Path -LiteralPath $recoveryResPath -PathType Leaf) { Get-Content -LiteralPath $recoveryResPath -Raw | ConvertFrom-Json } else { $null }

        [pscustomobject]@{
            hostname              = $env:COMPUTERNAME
            user                  = "$env:USERDOMAIN\$env:USERNAME"
            is_admin              = $isAdmin
            manufacturer          = [string]$cs.Manufacturer
            model                 = [string]$cs.Model
            hypervisor_present    = [bool]$cs.HypervisorPresent
            os_caption            = [string]$os.Caption
            os_version            = [string]$os.Version
            os_build              = [string]$os.BuildNumber
            test_root             = $tRoot
            test_root_exists      = $rootExists
            test_root_has_reparse = $rootHasReparse
            marker_exists         = $markerExists
            marker_root_id        = if ($markerObj) { [string]$markerObj.root_id } else { $null }
            manifest_exists       = $manifestExists
            manifest_schema       = if ($manifestObj) { [int]$manifestObj.schema_version } else { $null }
            phases                = @($phaseRows)
            manifest_tasks        = @($manifestTasks)
            rc_tasks              = @($rcTaskRows)
            rc_services           = @($rcServices)
            rc_processes          = @($rcProcs)
            listeners             = @($listeners)
            recovery_result_exists = [bool](Test-Path -LiteralPath $recoveryResPath -PathType Leaf)
            recovery_result_status = if ($recoveryResult) { [string]$recoveryResult.status } else { $null }
            test_results_preserved = [bool](Test-Path -LiteralPath $testResPath -PathType Leaf)
        }
    }

    if (-not $insp -or $insp.hostname -ne $ExpectedHost -or $insp.hostname -eq 'XERES') {
        throw "Guest hostname verification failed: got '$($insp.hostname)', expected '$ExpectedHost' (must not be XERES)."
    }
    if ($insp.manufacturer -notmatch 'Microsoft' -or $insp.model -notmatch 'Virtual Machine' -or -not $insp.hypervisor_present) {
        throw "Guest hardware is not an active Hyper-V VM: $($insp.manufacturer) / $($insp.model)."
    }
    if ($insp.os_caption -notmatch 'Windows 11') {
        throw "Guest OS is not Windows 11: $($insp.os_caption)"
    }
    if (-not $insp.is_admin) {
        throw "Guest session user '$($insp.user)' does not have guest Administrator privileges."
    }
    if (-not $insp.test_root_exists) {
        throw "Original H4 test root not found on guest: '$TestRoot'."
    }
    if ($insp.test_root_has_reparse) {
        throw "Guest H4 test root contains or traverses a reparse point: '$TestRoot'."
    }
    if (-not $insp.marker_exists -or [string]::IsNullOrWhiteSpace($insp.marker_root_id) -or $insp.marker_root_id.Length -lt 10) {
        throw "Guest .h4-test-root.json marker is missing or invalid under '$TestRoot'."
    }
    if (-not $insp.manifest_exists -or $insp.manifest_schema -ne 1 -or @($insp.phases).Count -eq 0) {
        throw "Guest cleanup-manifest.json is missing or invalid under '$TestRoot'."
    }

    $rootPrefix = $insp.marker_root_id.Substring(0, 10)
    $allowedTaskSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $phaseActionPrefixes = [System.Collections.Generic.Dictionary[string, string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($p in @($insp.phases)) {
        if ($p.phase -notin @('install', 'upgrade', 'rollback')) {
            throw "Cleanup manifest phase '$($p.phase)' is invalid."
        }
        if ($p.run_id -ne $rootPrefix) {
            throw "Cleanup manifest run_id '$($p.run_id)' does not match .h4-test-root.json prefix '$rootPrefix'."
        }
        if ([string]$p.source_tree_sha256 -ne $ExpectedSourceDigest.ToLowerInvariant()) {
            throw "Cleanup manifest source_tree_sha256 mismatch for phase '$($p.phase)': expected '$ExpectedSourceDigest', got '$($p.source_tree_sha256)'."
        }
        $expectedPhaseRoot = [System.IO.Path]::GetFullPath((Join-Path (Join-Path $TestRoot 'runs') "$rootPrefix-$($p.phase)"))
        $actualPhaseRoot = [System.IO.Path]::GetFullPath([string]$p.root)
        if ($actualPhaseRoot.ToLowerInvariant() -ne $expectedPhaseRoot.ToLowerInvariant()) {
            throw "Cleanup manifest phase root '$actualPhaseRoot' does not match expected '$expectedPhaseRoot'."
        }
        if (-not $p.root_exists) {
            throw "Phase root directory is missing (evidence not preserved): '$actualPhaseRoot'."
        }
        if ($p.port -in @(0, 1235) -or $p.port -lt 1024 -or $p.port -gt 65535) {
            throw "Cleanup manifest listener port '$($p.port)' is invalid."
        }
        if (@($p.task_names).Count -ne 3 -or (@($p.task_names | Select-Object -Unique).Count -ne 3)) {
            throw "Cleanup manifest task_names must contain 3 distinct task names for phase '$($p.phase)'."
        }
        $prefix = $actualPhaseRoot.TrimEnd('\') + '\'
        foreach ($tn in @($p.task_names)) {
            if ($tn -notlike 'ResourceCoordinator-H4-*') {
                throw "Cleanup manifest task '$tn' is not H4-scoped."
            }
            [void]$allowedTaskSet.Add($tn)
            $phaseActionPrefixes[$tn] = $prefix
        }
    }

    if ($ExpectedTasks.Count -gt 0) {
        $missingExp = @($ExpectedTasks | Where-Object { -not $allowedTaskSet.Contains($_) })
        $extraExp = @($allowedTaskSet | Where-Object { $ExpectedTasks -notcontains $_ })
        if ($missingExp.Count -gt 0 -or $extraExp.Count -gt 0) {
            throw "Manifest task set mismatch against expected v8 tasks (missing=$($missingExp -join ','), extra=$($extraExp -join ','))."
        }
    }

    if (@($insp.rc_services).Count -gt 0 -or @($insp.rc_processes).Count -gt 0 -or @($insp.listeners).Count -gt 0) {
        throw "Live RC services ($((@($insp.rc_services).name -join ','))), processes ($(@($insp.rc_processes).Count)), or manifest-port listeners ($(@($insp.listeners).Count)) detected; refusing offline recovery."
    }

    foreach ($t in @($insp.rc_tasks)) {
        if (-not $allowedTaskSet.Contains([string]$t.name)) {
            throw "Unexpected RC/KRig scheduled task present outside cleanup manifest: '$($t.name)'."
        }
        $expectedPrefix = $phaseActionPrefixes[[string]$t.name]
        if ([string]::IsNullOrWhiteSpace([string]$t.actions) -or ([string]$t.actions).IndexOf($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw "Manifest task '$($t.name)' action '$($t.actions)' does not reference owned phase root '$expectedPrefix'."
        }
    }

    if ($RequirePostClean) {
        if (@($insp.rc_tasks).Count -gt 0) {
            throw "Post-recovery check failed: RC tasks still remain: $((@($insp.rc_tasks) | ForEach-Object { $_.name }) -join ', ')."
        }
        if (-not $insp.test_root_exists -or -not $insp.manifest_exists -or -not $insp.marker_exists) {
            throw "Post-recovery check failed: original test-root evidence is missing."
        }
        foreach ($p in @($insp.phases)) {
            if ($p.launcher_exists -or $p.viewer_exists) {
                throw "Post-recovery check failed: marked launcher/viewer script still exists in '$($p.root)'."
            }
        }
    }

    return $insp
}

if ([string]::IsNullOrWhiteSpace($OperationId)) {
    $OperationId = 'recover-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
}
if ($OperationId -notmatch '^[A-Za-z0-9_-]{4,64}$') {
    throw "Invalid OperationId '$OperationId'."
}

$isMutatingApply = [bool]($Apply -and -not $WhatIfPreference)
$isMutatingStage = [bool](($StageBundle -or $Apply) -and -not $WhatIfPreference)
$mode = if ($PostInventory) { 'post_inventory' } elseif ($Apply) { 'apply' } else { 'dry_run' }

$summary = [ordered]@{
    schema_version          = 1
    operation_id            = $OperationId
    mode                    = $mode
    apply_requested         = [bool]$Apply
    whatif                  = [bool]$WhatIfPreference
    guest_authorized        = [bool]$AuthorizeGuestMutation
    stage_bundle_requested  = [bool]$StageBundle
    vm_id                   = $VmId
    vm_name                 = $VmName
    protected_checkpoint_id = $ProtectedCheckpointId
    guest_test_root         = $GuestTestRoot
    guest_bundle_root       = $GuestBundleRoot
    evidence_dir            = $null
    python_command          = $null
    python_status           = 'not_run'
    evidence_preserved      = $null
    pre_inventory           = $null
    dry_run_result          = $null
    apply_result            = $null
    post_inventory          = $null
    error_category          = $null
    error                   = $null
}

$hostEvidenceDir = [System.IO.Path]::GetFullPath((Join-Path $EvidenceRoot $OperationId))
$session = $null
$overallExit = 0

try {
    if ($PostInventory -and ($Apply -or $StageBundle)) {
        $summary['error_category'] = 'argument_conflict'
        $overallExit = 2
        throw '-PostInventory is strictly read-only and cannot be combined with -Apply or -StageBundle.'
    }
    if ($Apply -and -not $WhatIfPreference -and -not $AuthorizeGuestMutation) {
        $summary['error_category'] = 'authorization'
        $overallExit = 3
        throw 'Recovery mutation requires both -Apply and -AuthorizeGuestMutation.'
    }

    # 1. Exact host VM + protected baseline checkpoint + host bundle verification
    $vm = Get-H4HostVm -Id $VmId
    if (-not $vm -or $vm.Name -ne $VmName) {
        throw "Hyper-V VM verification failed for ID '$VmId' (found name='$($vm.Name)', expected '$VmName')."
    }
    if ($vm.State -ne 'Running') {
        throw "VM '$VmName' ($VmId) state is '$($vm.State)'; expected 'Running' for PowerShell Direct."
    }

    $checkpoints = @(Get-H4HostCheckpoints -Id $VmId)
    $protectedCp = $checkpoints | Where-Object { [string]$_.Id -eq $ProtectedCheckpointId } | Select-Object -First 1
    if (-not $protectedCp) {
        throw "Protected baseline checkpoint '$ProtectedCheckpointId' was not found on VM '$VmName' ($VmId)."
    }

    $bundleSha = Assert-H4FileDigest -Path $BundleZip -ExpectedSha256 $ExpectedBundleSha256 -Label 'Recovery v9 bundle'
    $bootstrapSha = Assert-H4FileDigest -Path $BootstrapScript -ExpectedSha256 $ExpectedBootstrapSha256 -Label 'Standalone Bootstrap-H4GuestBundle.ps1'

    if ($isMutatingApply) {
        Assert-H4NoReparsePoint -FullPath $hostEvidenceDir -Label 'Host recovery evidence root'
        if (-not $PSCmdlet.ShouldProcess($VmName, "Execute H4 recovery '$mode' (OperationId=$OperationId)")) {
            if ($Json) { $summary | ConvertTo-Json -Depth 10 } else { Write-Host 'Operation declined by ShouldProcess; no changes made.' }
            exit 0
        }
        if ((Test-Path -LiteralPath $hostEvidenceDir) -and @(Get-ChildItem -LiteralPath $hostEvidenceDir -Force -ErrorAction SilentlyContinue).Count -gt 0) {
            throw "Host evidence directory already exists and is non-empty: '$hostEvidenceDir'. Supply a distinct -OperationId or -EvidenceRoot."
        }
        New-Item -ItemType Directory -Path $hostEvidenceDir -Force -ErrorAction Stop | Out-Null
        $summary['evidence_dir'] = $hostEvidenceDir
    } elseif ($WhatIfPreference) {
        $null = $PSCmdlet.ShouldProcess($VmName, "Execute H4 recovery '$mode' (OperationId=$OperationId)")
    }

    if (-not $Credential) {
        $Credential = Request-H4GuestCredential -UserHint "$ExpectedGuestHost\mcarls"
    }
    $session = Open-H4GuestSession -Id $VmId -Cred $Credential

    # 2. Read-only guest pre-recovery or post-recovery inspection
    $preInsp = Invoke-H4GuestRecoveryInspection `
        -Session $session `
        -ExpectedHost $ExpectedGuestHost `
        -TestRoot $GuestTestRoot `
        -ExpectedSourceDigest $ExpectedSourceTreeSha256 `
        -ExpectedTasks $ExpectedManifestTasks `
        -RequirePostClean:$PostInventory
    $summary['pre_inventory'] = $preInsp
    $summary['evidence_preserved'] = [bool]($preInsp.test_root_exists -and $preInsp.manifest_exists -and $preInsp.marker_exists)

    if (-not [string]::IsNullOrWhiteSpace($HostCleanupManifest) -and (Test-Path -LiteralPath $HostCleanupManifest -PathType Leaf)) {
        $hostManifest = Get-Content -LiteralPath $HostCleanupManifest -Raw | ConvertFrom-Json -ErrorAction Stop
        $hostPhases = @($hostManifest.phases)
        $guestPhases = @($preInsp.phases)
        if ($hostPhases.Count -ne $guestPhases.Count) {
            throw "Host cleanup-manifest.json phase count ($($hostPhases.Count)) differs from guest ($($guestPhases.Count))."
        }
        for ($i = 0; $i -lt $hostPhases.Count; $i++) {
            $hp = $hostPhases[$i]; $gp = $guestPhases[$i]
            $hTasks = (@($hp.task_names) | ForEach-Object { [string]$_ } | Sort-Object) -join '|'
            $gTasks = (@($gp.task_names) | ForEach-Object { [string]$_ } | Sort-Object) -join '|'
            if ([string]$hp.phase -ne [string]$gp.phase -or
                [string]$hp.run_id -ne [string]$gp.run_id -or
                [int]$hp.port -ne [int]$gp.port -or
                [string]$hp.source_tree_sha256 -ne [string]$gp.source_tree_sha256 -or
                ([string]$hp.root).ToLowerInvariant() -ne ([string]$gp.root).ToLowerInvariant() -or
                $hTasks -ne $gTasks) {
                throw "Host cleanup-manifest.json does not match live guest cleanup-manifest.json for phase '$($gp.phase)'."
            }
        }
    }

    Save-H4JsonArtifact -Dir $summary['evidence_dir'] -FileName 'pre-recovery-inventory.json' -Data $preInsp

    if ($PostInventory) {
        $summary['post_inventory'] = $preInsp
        $summary['python_status'] = 'skipped_post_inventory'
        if ($Json) { $summary | ConvertTo-Json -Depth 10 } else { Write-Host "POST-RECOVERY INVENTORY PASSED ($OperationId)." }
        exit 0
    }

    # 3. Verify or explicitly stage immutable v9 recovery bundle on guest
    $bundleState = Invoke-H4GuestScript -Session $session -ArgumentList @($GuestBundleRoot, $GuestVenvPython, $ExpectedSourceTreeSha256) -ScriptBlock {
        param($bRoot, $pyExe, $expSrcSha)
        $ErrorActionPreference = 'Stop'
        $pyOk = Test-Path -LiteralPath $pyExe -PathType Leaf
        $manifestPath = Join-Path $bRoot 'manifest.json'
        $verifyPs1 = Join-Path $bRoot 'scripts\Verify-H4GuestBundle.ps1'
        $runnerPy = Join-Path $bRoot 'harness\windows_acceptance.py'
        $srcNew = Join-Path $bRoot 'sources\rc-1.0.0'
        if (-not $pyOk) { return [pscustomobject]@{ ready = $false; reason = "Guest venv Python missing: $pyExe" } }
        if (-not ((Test-Path -LiteralPath $manifestPath -PathType Leaf) -and (Test-Path -LiteralPath $verifyPs1 -PathType Leaf) -and (Test-Path -LiteralPath $runnerPy -PathType Leaf) -and (Test-Path -LiteralPath $srcNew -PathType Container))) {
            return [pscustomobject]@{ ready = $false; reason = "Recovery bundle not staged at '$bRoot'" }
        }
        $m = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $newSrc = @($m.sources | Where-Object { $_.source_role -eq 'new_1_0_0' } | Select-Object -First 1)
        if ($newSrc.Count -ne 1 -or ([string]$newSrc[0].source_tree_sha256).ToLowerInvariant() -ne $expSrcSha.ToLowerInvariant()) {
            return [pscustomobject]@{ ready = $false; reason = 'Bundle manifest new_1_0_0 digest mismatch' }
        }
        $env:PYTHONDONTWRITEBYTECODE = '1'
        $pwshExe = 'C:\Program Files\PowerShell\7\pwsh.exe'
        $vOut = @(& $pwshExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $verifyPs1 -BundleRoot $bRoot -Python $pyExe *>&1)
        if ($LASTEXITCODE -ne 0) {
            return [pscustomobject]@{ ready = $false; reason = ("Verify-H4GuestBundle failed: " + (($vOut | ForEach-Object { [string]$_ }) -join "`n")) }
        }
        return [pscustomobject]@{ ready = $true; reason = 'verified' }
    }

    if (-not $bundleState.ready) {
        if (-not $isMutatingStage) {
            $drySpec = Get-H4RecoveryCommandSpec -PythonExe $GuestVenvPython -BundleRoot $GuestBundleRoot -TestRoot $GuestTestRoot
            $summary['python_command'] = $drySpec.rendered
            $summary['python_status'] = 'bundle_not_staged'
            $summary['error_category'] = 'bundle_not_staged'
            $overallExit = 2
            throw "$($bundleState.reason). Re-run with -StageBundle once to verify and extract the immutable v9 recovery bundle into '$GuestBundleRoot' (no task or test-root changes)."
        }
        $stageDir = "C:\H4-Guest-Work\recovery-bundles\stage-$OperationId"
        Invoke-H4GuestScript -Session $session -ArgumentList @($stageDir, $GuestBundleRoot) -ScriptBlock {
            param($sDir, $bRoot)
            $ErrorActionPreference = 'Stop'
            if (Test-Path -LiteralPath $bRoot) {
                throw "Target recovery bundle directory already exists and failed verification: '$bRoot'."
            }
            New-Item -ItemType Directory -Path $sDir -Force | Out-Null
            New-Item -ItemType Directory -Path (Split-Path -Parent $bRoot) -Force | Out-Null
        }
        Copy-H4ToGuest -Session $session -SourcePath $BundleZip -Destination "$stageDir\h4-windows-acceptance.zip"
        Copy-H4ToGuest -Session $session -SourcePath $BootstrapScript -Destination "$stageDir\Bootstrap-H4GuestBundle.ps1"
        Invoke-H4GuestScript -Session $session -ArgumentList @($stageDir, $GuestBundleRoot, $bundleSha, $bootstrapSha, $GuestVenvPython) -ScriptBlock {
            param($sDir, $bRoot, $expBundle, $expBoot, $pyExe)
            $ErrorActionPreference = 'Stop'
            $actBundle = (Get-FileHash -Algorithm SHA256 -LiteralPath "$sDir\h4-windows-acceptance.zip").Hash
            if ($actBundle.ToLowerInvariant() -ne $expBundle.ToLowerInvariant()) { throw "Guest recovery bundle SHA-256 mismatch: $actBundle" }
            $actBoot = (Get-FileHash -Algorithm SHA256 -LiteralPath "$sDir\Bootstrap-H4GuestBundle.ps1").Hash
            if ($actBoot.ToLowerInvariant() -ne $expBoot.ToLowerInvariant()) { throw "Guest Bootstrap-H4GuestBundle.ps1 SHA-256 mismatch: $actBoot" }
            $env:PYTHONDONTWRITEBYTECODE = '1'
            $pwshExe = 'C:\Program Files\PowerShell\7\pwsh.exe'
            & $pwshExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$sDir\Bootstrap-H4GuestBundle.ps1" `
                -ArchivePath "$sDir\h4-windows-acceptance.zip" `
                -ExpectedSha256 $expBundle `
                -DestinationRoot $bRoot `
                -Python $pyExe
            if ($LASTEXITCODE -ne 0) { throw "Bootstrap-H4GuestBundle.ps1 exited $LASTEXITCODE" }
            $vOut = @(& $pwshExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$bRoot\scripts\Verify-H4GuestBundle.ps1" -BundleRoot $bRoot -Python $pyExe *>&1)
            if ($LASTEXITCODE -ne 0) {
                throw ("Verify-H4GuestBundle.ps1 exited ${LASTEXITCODE}: " + (($vOut | ForEach-Object { [string]$_ }) -join "`n"))
            }
        }
    }

    # 4. Always execute read-only Python --profile recover dry-run first
    $drySpec = Get-H4RecoveryCommandSpec -PythonExe $GuestVenvPython -BundleRoot $GuestBundleRoot -TestRoot $GuestTestRoot
    $summary['python_command'] = $drySpec.rendered
    $dryRes = Invoke-H4GuestScript -Session $session -ArgumentList @($drySpec.python, $drySpec.module_root, ($drySpec.arguments | ConvertTo-Json -Compress)) -ScriptBlock {
        param($py, $modRoot, $argsJson)
        $ErrorActionPreference = 'Continue'
        $env:PYTHONPATH = $modRoot
        $env:PYTHONDONTWRITEBYTECODE = '1'
        Remove-Item Env:\RC_H4_DISPOSABLE_GUEST_AUTHORIZED -ErrorAction SilentlyContinue
        Set-Location $modRoot
        $argList = @($argsJson | ConvertFrom-Json)
        $out = & $py -B @argList 2>&1
        [pscustomobject]@{ exit_code = $LASTEXITCODE; output = ($out -join "`n") }
    }
    $dryParsed = $null
    try { $dryParsed = $dryRes.output | ConvertFrom-Json -ErrorAction Stop } catch { $dryParsed = $null }
    $summary['dry_run_result'] = $dryParsed
    Save-H4JsonArtifact -Dir $summary['evidence_dir'] -FileName 'dry-run-plan.json' -Data $dryRes

    if ($dryRes.exit_code -ne 0 -or -not $dryParsed -or $dryParsed.status -ne 'planned') {
        $summary['python_status'] = 'dry_run_failed'
        $summary['error_category'] = 'recovery_dry_run_failed'
        $overallExit = if ($dryRes.exit_code -ne 0) { [int]$dryRes.exit_code } else { 4 }
        throw "Python --profile recover dry-run failed (exit=$($dryRes.exit_code)): $($dryRes.output)"
    }
    $summary['python_status'] = 'planned'

    if (-not $isMutatingApply) {
        if ($Json) { $summary | ConvertTo-Json -Depth 10 } else {
            Write-Host "READ-ONLY RECOVERY DRY-RUN PASSED (OperationId=$OperationId)."
            Write-Host "  Command: $($drySpec.rendered)"
            Write-Host "  Re-run with -Apply -AuthorizeGuestMutation to remove only owned v8 tasks/launchers while preserving evidence."
        }
        exit 0
    }

    # 5. Explicitly gated Python --profile recover --apply mutation
    $applySpec = Get-H4RecoveryCommandSpec `
        -PythonExe $GuestVenvPython `
        -BundleRoot $GuestBundleRoot `
        -TestRoot $GuestTestRoot `
        -ApplyMutation `
        -AuthorizationPhrase $H4AuthorizationPhrase
    $summary['python_command'] = $applySpec.rendered

    $applyRes = Invoke-H4GuestScript -Session $session -ArgumentList @($applySpec.python, $applySpec.module_root, ($applySpec.arguments | ConvertTo-Json -Compress), $H4AuthorizationPhrase) -ScriptBlock {
        param($py, $modRoot, $argsJson, $authPhrase)
        $ErrorActionPreference = 'Continue'
        $env:PYTHONPATH = $modRoot
        $env:PYTHONDONTWRITEBYTECODE = '1'
        $env:RC_H4_DISPOSABLE_GUEST_AUTHORIZED = $authPhrase
        Set-Location $modRoot
        $argList = @($argsJson | ConvertFrom-Json)
        $out = & $py -B @argList 2>&1
        [pscustomobject]@{ exit_code = $LASTEXITCODE; output = ($out -join "`n") }
    }
    Save-H4JsonArtifact -Dir $summary['evidence_dir'] -FileName 'recovery-apply-raw.json' -Data $applyRes
    $applyParsed = $null
    try { $applyParsed = $applyRes.output | ConvertFrom-Json -ErrorAction Stop } catch { $applyParsed = $null }
    $summary['apply_result'] = $applyParsed

    # Always copy allowlisted guest evidence even if apply failed so failure records survive
    $guestEvHostDir = Join-Path $hostEvidenceDir 'guest-evidence'
    New-Item -ItemType Directory -Path $guestEvHostDir -Force -ErrorAction Stop | Out-Null
    try {
        Copy-H4FromGuest -Session $session -SourcePath "$GuestTestRoot\*" -DestinationPath $guestEvHostDir
    } catch {
        Save-H4JsonArtifact -Dir $hostEvidenceDir -FileName 'evidence-copy-error.json' -Data ([pscustomobject]@{ error = $_.Exception.Message })
    }

    if ($applyRes.exit_code -ne 0 -or -not $applyParsed -or $applyParsed.status -ne 'applied') {
        $summary['python_status'] = 'apply_failed'
        $summary['error_category'] = 'recovery_apply_failed'
        $overallExit = if ($applyRes.exit_code -ne 0) { [int]$applyRes.exit_code } else { 4 }
        throw "Python --profile recover --apply failed (exit=$($applyRes.exit_code)): $($applyRes.output)"
    }
    $summary['python_status'] = 'applied'

    # 6. Mandatory separate post-recovery read-only inventory
    $postInsp = Invoke-H4GuestRecoveryInspection `
        -Session $session `
        -ExpectedHost $ExpectedGuestHost `
        -TestRoot $GuestTestRoot `
        -ExpectedSourceDigest $ExpectedSourceTreeSha256 `
        -ExpectedTasks $ExpectedManifestTasks `
        -RequirePostClean
    $summary['post_inventory'] = $postInsp
    $summary['evidence_preserved'] = [bool]($postInsp.test_root_exists -and $postInsp.manifest_exists -and $postInsp.marker_exists)
    Save-H4JsonArtifact -Dir $hostEvidenceDir -FileName 'post-recovery-inventory.json' -Data $postInsp
}
catch {
    if (-not $summary['error']) {
        $summary['error_category'] = if ($summary['error_category']) { $summary['error_category'] } else { 'recovery_error' }
        $summary['error'] = $_.Exception.Message
    }
    if ($overallExit -eq 0) { $overallExit = 1 }
}
finally {
    Close-H4GuestSession -Session $session
    Save-H4JsonArtifact -Dir $summary['evidence_dir'] -FileName 'final-recovery-summary.json' -Data $summary
}

if ($Json) {
    $summary | ConvertTo-Json -Depth 10
} elseif ($overallExit -ne 0) {
    Write-Error $summary['error'] -ErrorAction Continue
} else {
    Write-Host "H4 guest recovery completed cleanly (Mode=$mode, OperationId=$OperationId)."
}
exit $overallExit
