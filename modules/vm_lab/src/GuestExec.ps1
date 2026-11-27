#Requires -Version 7.0

function Test-VmLabGuestIdentityPolicy {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][pscredential]$Credential,
        [hashtable]$Policy,
        [int]$MaxConnectAttempts = 1,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $Name
    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) {
        throw "VM '$Name' was not found."
    }
    Assert-VmLabTargetNotProtected -VmName $vm.Name -VmId ([string]$vm.Id)
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    if (-not $own.owned) {
        throw "VM '$Name' is not owned by vm_lab: $($own.reason)"
    }
    if ([string]$vm.State -ne 'Running') {
        return [pscustomobject]@{
            status      = 'BLOCKED'
            reason_code = 'vm_not_running'
            vm_id       = [string]$vm.Id
            vm_name     = $vm.Name
            vm_state    = [string]$vm.State
        }
    }

    $probe = Invoke-VmLabGuestSession -VmId $vm.Id -VmName $vm.Name -Credential $Credential -MaxConnectAttempts $MaxConnectAttempts -ScriptBlock {
        param($session)
        $forbidden = if ($Policy -and $Policy.forbidden_processes) { @($Policy.forbidden_processes) } else { @() }
        Invoke-VmLabPSSessionCommand -Session $session -ArgumentList @($forbidden) -ScriptBlock {
            param($forbiddenProcs)
            $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
            $cs = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
            $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
            $principal = [System.Security.Principal.WindowsPrincipal]::new($id)
            $isAdmin = $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
            $matchedForbidden = @()
            if ($forbiddenProcs.Count -gt 0) {
                $procs = @(Get-Process -ErrorAction Stop | Select-Object -ExpandProperty ProcessName)
                foreach ($fp in $forbiddenProcs) {
                    if ($procs -contains $fp) { $matchedForbidden += $fp }
                }
            }
            [pscustomobject]@{
                hostname            = $env:COMPUTERNAME
                os_caption          = $os.Caption
                os_version          = $os.Version
                os_architecture     = $os.OSArchitecture
                manufacturer        = $cs.Manufacturer
                model               = $cs.Model
                user_name           = $id.Name
                is_admin            = $isAdmin
                forbidden_processes = @($matchedForbidden)
            }
        }
    }

    $failures = @()
    if ($Policy) {
        if ($Policy.require_local_admin -and -not $probe.is_admin) {
            $failures += 'Guest session account does not hold local Administrator token.'
        }
        if ($Policy.expected_hostname -and $probe.hostname -ne [string]$Policy.expected_hostname) {
            $failures += "Guest hostname '$($probe.hostname)' does not match expected '$($Policy.expected_hostname)'."
        }
        if ($Policy.os_caption_match -and $probe.os_caption -notmatch [string]$Policy.os_caption_match) {
            $failures += "Guest OS '$($probe.os_caption)' does not match '$($Policy.os_caption_match)'."
        }
        if ($Policy.architecture -and $probe.os_architecture -notmatch [string]$Policy.architecture) {
            $failures += "Guest architecture '$($probe.os_architecture)' does not match '$($Policy.architecture)'."
        }
        if (@($probe.forbidden_processes).Count -gt 0) {
            $failures += "Forbidden guest processes detected: $(@($probe.forbidden_processes) -join ', ')."
        }
    }

    return [pscustomobject]@{
        status      = if ($failures.Count -eq 0) { 'SUCCEEDED' } else { 'FAILED' }
        reason_code = if ($failures.Count -eq 0) { 'guest_identity_verified' } else { 'guest_identity_mismatch' }
        vm_id       = [string]$vm.Id
        vm_name     = $vm.Name
        identity    = $probe
        failures    = @($failures)
    }
}

function Invoke-VmLabGuestCommand {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$ExecutablePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = 'C:\Windows\Temp',
        [hashtable]$Environment = @{},
        [string]$ExpectedSha256,
        [ValidateSet('read_only', 'replayable', 'non_repeatable')][string]$IdempotencyClass = 'replayable',
        [int]$TimeoutSeconds = 300,
        [int]$MaxOutputBytes = 1048576,
        [string]$RunId = ([guid]::NewGuid().ToString('N')),
        [string]$OperationId,
        [string]$StageId,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [switch]$Apply,
        [switch]$AuthorizeGuestExec,
        [int]$MaxConnectAttempts = 1,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $Name
    $guestExe = Resolve-VmLabGuestPath -Path $ExecutablePath -Label 'ExecutablePath'
    $guestCwd = Resolve-VmLabGuestPath -Path $WorkingDirectory -Label 'WorkingDirectory'

    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and $ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Invalid ExpectedSha256 format: '$ExpectedSha256'."
    }
    foreach ($k in $Environment.Keys) {
        if ($k -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw "Invalid environment variable name '$k'."
        }
        if ($k -match 'PASS|SECRET|TOKEN|CREDENTIAL') {
            throw "Refusing credential-like environment variable key '$k' in guest-exec."
        }
    }

    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) { throw "VM '$Name' was not found." }
    Assert-VmLabTargetNotProtected -VmName $vm.Name -VmId ([string]$vm.Id)
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    if (-not $own.owned) { throw "VM '$Name' is not owned by vm_lab: $($own.reason)" }

    $authorized = Test-VmLabCapabilityAuthorized -Capability 'guest_exec' -Apply:$Apply -AuthorizeGuestExec:$AuthorizeGuestExec
    if (-not $authorized -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($vm.Name, "Execute pinned guest command '$guestExe'")) {
        $reason = if (-not $Apply -or $WhatIfPreference) { 'dry_run_not_applied' } else { 'guest_exec_authorization_required' }
        return [pscustomobject]@{
            status            = if ($reason -eq 'dry_run_not_applied') { 'PLANNED' } else { 'BLOCKED' }
            reason_code       = $reason
            dry_run           = $true
            vm_name           = $vm.Name
            vm_id             = [string]$vm.Id
            run_id            = $RunId
            operation_id      = $OperationId
            stage_id          = $StageId
            executable        = $guestExe
            args              = @($ArgumentList)
            working_directory = $guestCwd
            idempotency_class = $IdempotencyClass
            exit_code         = $null
        }
    }

    if ([string]$vm.State -ne 'Running') {
        return [pscustomobject]@{
            status      = 'BLOCKED'
            reason_code = 'vm_not_running'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
            run_id      = $RunId
            exit_code   = $null
        }
    }

    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        return [pscustomobject]@{
            status      = 'AWAITING_INTERACTION'
            reason_code = 'guest_credentials_required'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
            run_id      = $RunId
            exit_code   = $null
        }
    }

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $execRes = Invoke-VmLabGuestSession -VmId $vm.Id -VmName $vm.Name -Credential $cred -MaxConnectAttempts $MaxConnectAttempts -OpenTimeoutSeconds ([Math]::Max(30, $TimeoutSeconds)) -ScriptBlock {
            param($session)
            Invoke-VmLabPSSessionCommand -Session $session -ArgumentList @($guestExe, @($ArgumentList), $guestCwd, $Environment, $ExpectedSha256, $TimeoutSeconds, $MaxOutputBytes, $RunId) -ScriptBlock {
                param($exe, $argArr, $cwd, $envMap, $expSha, $timeoutSec, $maxOutBytes, $rid)
                if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
                    return [pscustomobject]@{
                        status      = 'FAILED'
                        reason_code = 'executable_not_found'
                        exit_code   = $null
                        stdout      = ''
                        stderr      = "Executable not found: $exe"
                    }
                }
                $actualSha = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
                if (-not [string]::IsNullOrWhiteSpace($expSha) -and $actualSha -ne $expSha.ToLowerInvariant()) {
                    return [pscustomobject]@{
                        status          = 'FAILED'
                        reason_code     = 'executable_hash_mismatch'
                        actual_sha256   = $actualSha
                        expected_sha256 = $expSha.ToLowerInvariant()
                        exit_code       = $null
                        stdout          = ''
                        stderr          = "SHA-256 mismatch for $exe"
                    }
                }
                if (-not (Test-Path -LiteralPath $cwd -PathType Container)) {
                    return [pscustomobject]@{
                        status      = 'FAILED'
                        reason_code = 'working_directory_missing'
                        exit_code   = $null
                        stdout      = ''
                        stderr      = "Working directory missing: $cwd"
                    }
                }

                $psi = [System.Diagnostics.ProcessStartInfo]::new($exe)
                $psi.WorkingDirectory = $cwd
                $psi.RedirectStandardOutput = $true
                $psi.RedirectStandardError = $true
                $psi.UseShellExecute = $false
                foreach ($a in @($argArr)) {
                    $psi.ArgumentList.Add([string]$a)
                }
                foreach ($k in $envMap.Keys) {
                    $psi.Environment[[string]$k] = [string]$envMap[$k]
                }

                $proc = [System.Diagnostics.Process]::Start($psi)
                $outTask = $proc.StandardOutput.ReadToEndAsync()
                $errTask = $proc.StandardError.ReadToEndAsync()
                $finished = $proc.WaitForExit($timeoutSec * 1000)
                if (-not $finished) {
                    try { $proc.Kill($true) } catch {}
                    return [pscustomobject]@{
                        status        = 'FAILED'
                        reason_code   = 'guest_command_timeout'
                        actual_sha256 = $actualSha
                        exit_code     = $null
                        timed_out     = $true
                        stdout        = ''
                        stderr        = "Timed out after $timeoutSec seconds."
                    }
                }
                $stdout = $outTask.GetAwaiter().GetResult()
                $stderr = $errTask.GetAwaiter().GetResult()
                if ($stdout.Length -gt $maxOutBytes) { $stdout = $stdout.Substring(0, $maxOutBytes) }
                if ($stderr.Length -gt $maxOutBytes) { $stderr = $stderr.Substring(0, $maxOutBytes) }

                $parsedJson = $null
                try {
                    if ($stdout.Trim().StartsWith('{')) {
                        $parsedJson = $stdout | ConvertFrom-Json -ErrorAction Stop
                    }
                } catch {
                    $parsedJson = $null
                }

                return [pscustomobject]@{
                    status        = if ($proc.ExitCode -eq 0) { 'SUCCEEDED' } else { 'FAILED' }
                    reason_code   = if ($proc.ExitCode -eq 0) { 'guest_command_ok' } else { 'guest_command_nonzero_exit' }
                    actual_sha256 = $actualSha
                    exit_code     = $proc.ExitCode
                    timed_out     = $false
                    stdout        = $stdout
                    stderr        = $stderr
                    parsed_json   = $parsedJson
                }
            }
        }
        $sw.Stop()
        return [pscustomobject]@{
            status            = $execRes.status
            reason_code       = $execRes.reason_code
            dry_run           = $false
            vm_name           = $vm.Name
            vm_id             = [string]$vm.Id
            run_id            = $RunId
            operation_id      = $OperationId
            stage_id          = $StageId
            executable        = $guestExe
            actual_sha256     = $execRes.actual_sha256
            exit_code         = $execRes.exit_code
            timed_out         = [bool]$execRes.timed_out
            duration_ms       = [int64]$sw.ElapsedMilliseconds
            stdout            = $execRes.stdout
            stderr            = $execRes.stderr
            parsed_json       = $execRes.parsed_json
            idempotency_class = $IdempotencyClass
        }
    } catch {
        $sw.Stop()
        $msg = $_.Exception.Message
        $status = if ($IdempotencyClass -eq 'non_repeatable' -and $msg -match 'timeout|connection|session|transport') { 'PARTIAL' } else { 'FAILED' }
        $reason = if ($status -eq 'PARTIAL') { 'needs_reconciliation_after_transport_loss' } else { 'guest_exec_transport_or_host_error' }
        return [pscustomobject]@{
            status            = $status
            reason_code       = $reason
            dry_run           = $false
            vm_name           = $vm.Name
            vm_id             = [string]$vm.Id
            run_id            = $RunId
            operation_id      = $OperationId
            stage_id          = $StageId
            executable        = $guestExe
            exit_code         = $null
            duration_ms       = [int64]$sw.ElapsedMilliseconds
            detail            = $msg
            idempotency_class = $IdempotencyClass
        }
    }
}

function Get-VmLabGuestInventory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [switch]$IncludeProcesses,
        [switch]$IncludeServices,
        [switch]$IncludeTasks,
        [int]$MaxConnectAttempts = 1,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $resolved = Resolve-VmLabTargetVm -NameOrId $Name -ManifestRoot $ManifestRoot
    if (-not $resolved.ownership.owned) { throw "VM '$($resolved.vm.Name)' is not owned by vm_lab: $($resolved.ownership.reason)" }
    $vm = $resolved.vm
    if ([string]$vm.State -ne 'Running') {
        return [pscustomobject]@{ status = 'BLOCKED'; reason_code = 'vm_not_running'; vm_name = $vm.Name; vm_id = [string]$vm.Id }
    }
    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        return [pscustomobject]@{ status = 'AWAITING_INTERACTION'; reason_code = 'guest_credentials_required'; vm_name = $vm.Name; vm_id = [string]$vm.Id }
    }
    $inv = Invoke-VmLabGuestSession -VmId $vm.Id -VmName $vm.Name -Credential $cred -MaxConnectAttempts $MaxConnectAttempts -ScriptBlock {
        param($session)
        Invoke-VmLabPSSessionCommand -Session $session -ArgumentList @([bool]$IncludeProcesses, [bool]$IncludeServices, [bool]$IncludeTasks) -ScriptBlock {
            param($incProc, $incSvc, $incTask)
            $res = [ordered]@{ hostname = $env:COMPUTERNAME }
            if ($incProc) {
                $res.processes = @(Get-Process -ErrorAction SilentlyContinue | Select-Object -First 200 Name, Id)
            }
            if ($incSvc) {
                $res.services = @(Get-Service -ErrorAction SilentlyContinue | Select-Object -First 200 Name, Status, StartType | ForEach-Object { [pscustomobject]@{ name = $_.Name; status = [string]$_.Status; start_type = [string]$_.StartType } })
            }
            if ($incTask) {
                $res.scheduled_tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Select-Object -First 200 TaskName, TaskPath, State | ForEach-Object { [pscustomobject]@{ task_name = $_.TaskName; task_path = $_.TaskPath; state = [string]$_.State } })
            }
            return [pscustomobject]$res
        }
    }
    return [pscustomobject]@{
        status      = 'SUCCEEDED'
        reason_code = 'guest_inventory_collected'
        vm_name     = $vm.Name
        vm_id       = [string]$vm.Id
        inventory   = $inv
    }
}

function Resolve-VmLabGuestPowerShellPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][guid]$VmId,
        [Parameter(Mandatory)][string]$VmName,
        [Parameter(Mandatory)][pscredential]$Credential,
        [int]$MaxConnectAttempts = 1
    )
    return Invoke-VmLabGuestSession -VmId $VmId -VmName $VmName -Credential $Credential -MaxConnectAttempts $MaxConnectAttempts -ScriptBlock {
        param($session)
        Invoke-VmLabPSSessionCommand -Session $session -ScriptBlock {
            $cmd = Get-Command -Name 'pwsh.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source -PathType Leaf)) {
                return [string]$cmd.Source
            }
            $candidates = @(
                'C:\Program Files\PowerShell\7\pwsh.exe',
                'C:\Program Files\PowerShell\7-preview\pwsh.exe',
                'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
            )
            foreach ($cand in $candidates) {
                if (Test-Path -LiteralPath $cand -PathType Leaf) {
                    return $cand
                }
            }
            return $null
        }
    }
}

function Invoke-VmLabGuestScript {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$ScriptPath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = 'C:\Windows\Temp',
        [hashtable]$Environment = @{},
        [string]$ExpectedSha256,
        [int]$TimeoutSeconds = 300,
        [string]$OperationId,
        [string]$StageId,
        [switch]$Reboot3010AsRebootRequired,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [switch]$Apply,
        [switch]$AuthorizeGuestExec,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $scriptFull = Test-VmLabSafePath -Path $ScriptPath -Label 'ScriptPath' -CheckReparsePoints
    if (-not (Test-Path -LiteralPath $scriptFull -PathType Leaf)) {
        throw "Guest script not found: '$scriptFull'."
    }
    $actualSha = (Get-FileHash -LiteralPath $scriptFull -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and $actualSha -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Script SHA-256 mismatch for '$scriptFull': expected '$ExpectedSha256', actual '$actualSha'."
    }
    $resolved = Resolve-VmLabTargetVm -NameOrId $Name -ManifestRoot $ManifestRoot
    if (-not $resolved.ownership.owned) { throw "VM '$($resolved.vm.Name)' is not owned by vm_lab: $($resolved.ownership.reason)" }
    $vm = $resolved.vm

    $authorized = Test-VmLabCapabilityAuthorized -Capability 'guest_exec' -Apply:$Apply -AuthorizeGuestExec:$AuthorizeGuestExec
    if (-not $authorized -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($vm.Name, "Execute trusted script '$scriptFull'")) {
        $reason = if (-not $Apply -or $WhatIfPreference) { 'dry_run_not_applied' } else { 'guest_exec_authorization_required' }
        return [pscustomobject]@{
            status        = if ($reason -eq 'dry_run_not_applied') { 'PLANNED' } else { 'BLOCKED' }
            reason_code   = $reason
            vm_name       = $vm.Name
            vm_id         = [string]$vm.Id
            script_path   = $scriptFull
            script_sha256 = $actualSha
        }
    }
    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        return [pscustomobject]@{ status = 'AWAITING_INTERACTION'; reason_code = 'guest_credentials_required'; vm_name = $vm.Name; vm_id = [string]$vm.Id }
    }
    $guestPwsh = Resolve-VmLabGuestPowerShellPath -VmId $vm.Id -VmName $vm.Name -Credential $cred
    if ([string]::IsNullOrWhiteSpace($guestPwsh)) {
        return [pscustomobject]@{
            status        = 'FAILED'
            reason_code   = 'guest_powershell_not_found'
            vm_name       = $vm.Name
            vm_id         = [string]$vm.Id
            script_sha256 = $actualSha
        }
    }
    $guestDest = "C:\Windows\Temp\vm_lab_script_$($actualSha.Substring(0, 12)).ps1"
    $copyRes = Copy-VmLabGuestItem -Name $vm.Name -SourcePath $scriptFull -DestinationPath $guestDest -Direction ToGuest -Overwrite -Credential $cred -Apply -ManifestRoot $ManifestRoot
    if ($copyRes.status -ne 'copied') {
        return [pscustomobject]@{ status = 'FAILED'; reason_code = 'script_stage_failed'; vm_name = $vm.Name; vm_id = [string]$vm.Id; copy = $copyRes }
    }
    $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $guestDest) + @($ArgumentList)
    $execRes = Invoke-VmLabGuestCommand -Name $vm.Name -ExecutablePath $guestPwsh -ArgumentList $psArgs -WorkingDirectory $WorkingDirectory -Environment $Environment -TimeoutSeconds $TimeoutSeconds -OperationId $OperationId -StageId $StageId -Credential $cred -Apply -AuthorizeGuestExec -ManifestRoot $ManifestRoot
    if ($Reboot3010AsRebootRequired -and $execRes.exit_code -eq 3010) {
        $execRes.status = 'REBOOT_REQUIRED'
        $execRes.reason_code = 'installer_reboot_required_3010'
    }
    $execRes | Add-Member -NotePropertyName 'script_sha256' -NotePropertyValue $actualSha -Force
    return $execRes
}
