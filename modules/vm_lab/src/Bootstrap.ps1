#Requires -Version 7.0

function ConvertTo-VmLabNormalizedPackageName {
    param([Parameter(Mandatory)][string]$Name)
    return ([regex]::Replace($Name.Trim().ToLowerInvariant(), '[-_.]+', '-'))
}

function Get-VmLabRequirementsPackageNames {
    param([Parameter(Mandatory)][string]$RequirementsPath)
    if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
        throw "Requirements file not found: '$RequirementsPath'."
    }
    $names = [System.Collections.Generic.List[string]]::new()
    foreach ($rawLine in (Get-Content -LiteralPath $RequirementsPath -Encoding utf8)) {
        $line = ($rawLine -replace '\s+#.*$', '').Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#') -or $line.StartsWith('-')) {
            continue
        }
        $pkgToken = ($line -split '[\s;\[=<>!~]', 2)[0].Trim()
        if (-not [string]::IsNullOrWhiteSpace($pkgToken)) {
            $names.Add((ConvertTo-VmLabNormalizedPackageName -Name $pkgToken))
        }
    }
    return @($names | Select-Object -Unique)
}

function Test-VmLabIsWindowsAppsAlias {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    return ($Path -match '(?i)[\\/]WindowsApps[\\/]python(\d+(\.\d+)?)?\.exe$')
}

function ConvertFrom-VmLabPythonVersionText {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    if ($Text -match '(\d+)\.(\d+)(?:\.(\d+))?') {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        $patch = if ($Matches[3]) { [int]$Matches[3] } else { 0 }
        return [version]::new($major, $minor, $patch)
    }
    return $null
}

function Read-VmLabGuestBootstrapStore {
    param([string]$StateRoot = 'C:\ProgramData\vm_lab')
    $statePath = Join-Path $StateRoot 'bootstrap-state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return [pscustomobject]@{
            exists         = $false
            valid          = $true
            path           = $statePath
            schema_version = 2
            profiles       = @{}
            error          = $null
        }
    }

    try {
        $raw = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 -ErrorAction Stop
        if ([string]::IsNullOrWhiteSpace($raw)) {
            throw 'Bootstrap state file is empty.'
        }
        $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return [pscustomobject]@{
            exists         = $true
            valid          = $false
            path           = $statePath
            schema_version = 0
            profiles       = @{}
            error          = $_.Exception.Message
        }
    }

    $profiles = @{}
    $schemaVersion = if ($parsed.PSObject.Properties['schema_version']) { [int]$parsed.schema_version } else { 1 }
    if ($schemaVersion -ge 2 -and $parsed.PSObject.Properties['profiles'] -and $null -ne $parsed.profiles) {
        foreach ($prop in $parsed.profiles.PSObject.Properties) {
            $profiles[$prop.Name] = $prop.Value
        }
    } elseif ($parsed.PSObject.Properties['profile'] -and -not [string]::IsNullOrWhiteSpace([string]$parsed.profile)) {
        $profiles[[string]$parsed.profile] = [pscustomobject]@{
            profile         = [string]$parsed.profile
            completed       = [bool]$parsed.completed
            status          = if ($parsed.completed) { 'completed' } else { 'incomplete' }
            completed_at    = $parsed.completed_at
            reboot_required = $false
            details         = $parsed.details
            legacy_v1       = $true
        }
    }

    return [pscustomobject]@{
        exists         = $true
        valid          = $true
        path           = $statePath
        schema_version = $schemaVersion
        profiles       = $profiles
        error          = $null
    }
}

function Write-VmLabGuestBootstrapStoreAtomic {
    param(
        [Parameter(Mandatory)][string]$StateRoot,
        [Parameter(Mandatory)][hashtable]$Profiles
    )
    if (-not (Test-Path -LiteralPath $StateRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
    }
    $statePath = Join-Path $StateRoot 'bootstrap-state.json'
    $tmpPath = Join-Path $StateRoot ("bootstrap-state.json.tmp.{0}.{1}" -f $PID, [guid]::NewGuid().ToString('N'))

    $payload = [ordered]@{
        schema_version = 2
        updated_at     = [DateTimeOffset]::UtcNow.ToString('o')
        profiles       = $Profiles
    }
    try {
        $json = $payload | ConvertTo-Json -Depth 10
        [System.IO.File]::WriteAllText($tmpPath, $json, [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::Move($tmpPath, $statePath, $true)
    } catch {
        if (Test-Path -LiteralPath $tmpPath -PathType Leaf) {
            Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue
        }
        throw
    }
    return $statePath
}

function Update-VmLabGuestProcessPath {
    $parts = [System.Collections.Generic.List[string]]::new()
    foreach ($scope in @('Machine', 'User')) {
        $val = [Environment]::GetEnvironmentVariable('Path', $scope)
        if (-not [string]::IsNullOrWhiteSpace($val)) {
            foreach ($p in ($val -split ';')) {
                if (-not [string]::IsNullOrWhiteSpace($p) -and ($parts -notcontains $p)) {
                    $parts.Add($p)
                }
            }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($env:Path)) {
        foreach ($p in ($env:Path -split ';')) {
            if (-not [string]::IsNullOrWhiteSpace($p) -and ($parts -notcontains $p)) {
                $parts.Add($p)
            }
        }
    }
    if ($parts.Count -gt 0) {
        $env:Path = ($parts -join ';')
    }
}

function Resolve-VmLabGuestPythonInterpreter {
    param(
        [string]$PythonPath,
        [string[]]$SearchRoots,
        [switch]$SkipPathSearch,
        [scriptblock]$CommandRunner
    )
    if (-not $CommandRunner) {
        $CommandRunner = {
            param([string]$Exe, [string[]]$ExeArgs)
            $out = & $Exe @ExeArgs 2>&1
            return [pscustomobject]@{
                exit_code = $LASTEXITCODE
                output    = (($out | ForEach-Object { [string]$_ }) -join "`n").Trim()
            }
        }
    }

    $candidates = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "Specified -PythonPath does not exist: '$PythonPath'."
        }
        if (Test-VmLabIsWindowsAppsAlias -Path $PythonPath) {
            throw "Specified -PythonPath points to a WindowsApps execution alias stub: '$PythonPath'."
        }
        $candidates.Add($PythonPath)
    } else {
        if (-not $SkipPathSearch) {
            foreach ($cmd in (Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
                if ($cmd.Source -and ($candidates -notcontains $cmd.Source)) {
                    $candidates.Add($cmd.Source)
                }
            }
        }
        $roots = if ($SearchRoots -and $SearchRoots.Count -gt 0) {
            $SearchRoots
        } else {
            @(
                (Join-Path $env:ProgramFiles 'Python3*'),
                (Join-Path $env:LocalAppData 'Programs\Python\Python3*')
            )
        }
        foreach ($pattern in $roots) {
            foreach ($dir in (Get-Item -Path $pattern -ErrorAction SilentlyContinue)) {
                $exe = Join-Path $dir.FullName 'python.exe'
                if ((Test-Path -LiteralPath $exe -PathType Leaf) -and ($candidates -notcontains $exe)) {
                    $candidates.Add($exe)
                }
            }
        }
    }

    $rejected = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in $candidates) {
        if (Test-VmLabIsWindowsAppsAlias -Path $candidate) {
            $rejected.Add("$candidate (WindowsApps alias)")
            continue
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $probe = & $CommandRunner $candidate @('-c', 'import sys, struct; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{struct.calcsize(''P'')*8}")')
        $ver = $null
        $bits = 64
        if ($probe.exit_code -eq 0 -and $probe.output -match '^(\d+\.\d+\.\d+)\|(\d+)$') {
            $ver = [version]$Matches[1]
            $bits = [int]$Matches[2]
        } else {
            $verProbe = & $CommandRunner $candidate @('--version')
            if ($verProbe.exit_code -eq 0) {
                $ver = ConvertFrom-VmLabPythonVersionText -Text $verProbe.output
            }
        }
        if ($null -eq $ver) {
            $rejected.Add("$candidate (unparseable version)")
            continue
        }
        if ($ver.Major -lt 3 -or ($ver.Major -eq 3 -and $ver.Minor -lt 12)) {
            $rejected.Add("$candidate (version $ver < 3.12)")
            continue
        }
        if ($bits -lt 64) {
            $rejected.Add("$candidate (${bits}-bit < 64-bit)")
            continue
        }
        return [pscustomobject]@{
            path    = $candidate
            version = $ver.ToString()
            bitness = $bits
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
        throw "Python interpreter at '$PythonPath' did not satisfy Python 3.12+ (64-bit) requirement: $($rejected -join '; ')."
    }
    return $null
}

function Resolve-VmLabGuestPwshExecutable {
    param(
        [string]$PwshPath,
        [string[]]$StandardPaths,
        [switch]$SkipPathSearch,
        [scriptblock]$CommandRunner
    )
    if (-not $CommandRunner) {
        $CommandRunner = {
            param([string]$Exe, [string[]]$ExeArgs)
            $out = & $Exe @ExeArgs 2>&1
            return [pscustomobject]@{
                exit_code = $LASTEXITCODE
                output    = (($out | ForEach-Object { [string]$_ }) -join "`n").Trim()
            }
        }
    }

    $candidates = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($PwshPath)) {
        $candidates.Add($PwshPath)
    } else {
        if (-not $SkipPathSearch) {
            $cmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($cmd -and $cmd.Source) { $candidates.Add($cmd.Source) }
        }
        $std = if ($StandardPaths -and $StandardPaths.Count -gt 0) {
            $StandardPaths
        } else {
            @((Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'))
        }
        foreach ($p in $std) {
            if ($p -and ($candidates -notcontains $p)) { $candidates.Add($p) }
        }
    }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $probe = & $CommandRunner $candidate @('-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()')
        if ($probe.exit_code -eq 0 -and $probe.output -match '(\d+)\.(\d+)') {
            $major = [int]$Matches[1]
            if ($major -ge 7) {
                return [pscustomobject]@{
                    path    = $candidate
                    version = $probe.output.Trim()
                }
            }
        }
    }
    return $null
}

function Invoke-VmLabGuestBootstrapLocal {
    param(
        [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$Profile = 'windows-minimal',
        [string]$InstallerPath,
        [string]$ExpectedInstallerSha256,
        [string]$PythonPath,
        [string]$WheelhousePath,
        [string]$RequirementsPath,
        [string[]]$Packages,
        [string]$VenvPath = 'C:\venvs\dev',
        [switch]$Offline,
        [switch]$AllowOnlineInstall,
        [string]$StateRoot = 'C:\ProgramData\vm_lab',
        [string[]]$PythonSearchRoots,
        [string[]]$PwshStandardPaths,
        [scriptblock]$CommandRunner,
        [scriptblock]$ProcessRunner
    )

    if (-not $CommandRunner) {
        $CommandRunner = {
            param([string]$Exe, [string[]]$ExeArgs)
            $out = & $Exe @ExeArgs 2>&1
            return [pscustomobject]@{
                exit_code = $LASTEXITCODE
                output    = (($out | ForEach-Object { [string]$_ }) -join "`n").Trim()
            }
        }
    }
    if (-not $ProcessRunner) {
        $ProcessRunner = {
            param([string]$FilePath, [string[]]$ArgumentList)
            $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -Wait -PassThru -ErrorAction Stop
            return [int]$proc.ExitCode
        }
    }

    if (-not (Test-Path -LiteralPath $StateRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
    }

    $store = Read-VmLabGuestBootstrapStore -StateRoot $StateRoot
    $profilesMap = if ($store.valid -and $store.profiles) { @{} + $store.profiles } else { @{} }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    $details = [ordered]@{
        profile      = $Profile
        ps_version   = $PSVersionTable.PSVersion.ToString()
        is_admin     = $isAdmin
    }

    $saveProfileState = {
        param([bool]$Completed, [string]$Status, [bool]$RebootRequired, [string]$ErrorMessage)
        $profilesMap[$Profile] = [pscustomobject]@{
            profile         = $Profile
            completed       = $Completed
            status          = $Status
            reboot_required = $RebootRequired
            completed_at    = if ($Completed) { [DateTimeOffset]::UtcNow.ToString('o') } else { $null }
            updated_at      = [DateTimeOffset]::UtcNow.ToString('o')
            error           = $ErrorMessage
            details         = $details
        }
        $null = Write-VmLabGuestBootstrapStoreAtomic -StateRoot $StateRoot -Profiles $profilesMap
        return $profilesMap[$Profile]
    }

    $verifyInstallerHash = {
        param([string]$Path, [string]$ExpectedSha)
        if (-not [string]::IsNullOrWhiteSpace($ExpectedSha)) {
            $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $ExpectedSha.Trim().ToLowerInvariant()) {
                throw "Installer SHA-256 mismatch for '$Path': expected '$ExpectedSha', got '$actual'."
            }
            $details.installer_sha256 = $actual
        }
    }

    try {
        if ($Profile -eq 'python-dev') {
            $skipPath = $PSBoundParameters.ContainsKey('PythonSearchRoots')
            $pyInfo = Resolve-VmLabGuestPythonInterpreter -PythonPath $PythonPath -SearchRoots $PythonSearchRoots -SkipPathSearch:$skipPath -CommandRunner $CommandRunner
            if (-not $pyInfo -and -not [string]::IsNullOrWhiteSpace($InstallerPath)) {
                if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
                    throw "Python installer not found on guest: '$InstallerPath'."
                }
                & $verifyInstallerHash $InstallerPath $ExpectedInstallerSha256
                $instExit = & $ProcessRunner $InstallerPath @('/quiet', 'InstallAllUsers=1', 'PrependPath=1')
                if ($instExit -eq 3010) {
                    $details.installer_exit_code = 3010
                    return (& $saveProfileState $false 'reboot_required' $true 'Python installer requires a guest reboot (exit code 3010).')
                }
                if ($instExit -ne 0) {
                    throw "Python installer exited with code $instExit."
                }
                Update-VmLabGuestProcessPath
                $pyInfo = Resolve-VmLabGuestPythonInterpreter -PythonPath $PythonPath -SearchRoots $PythonSearchRoots -SkipPathSearch:$skipPath -CommandRunner $CommandRunner
            }
            if (-not $pyInfo) {
                throw 'Python 3.12+ (64-bit, non-WindowsApps) is not installed on guest and no valid -InstallerPath was provided.'
            }
            $details.python_path = $pyInfo.path
            $details.python_version = $pyInfo.version
            $details.python_bitness = $pyInfo.bitness

            $venvPy = Join-Path $VenvPath 'Scripts\python.exe'
            if (-not (Test-Path -LiteralPath $venvPy -PathType Leaf)) {
                $venvRes = & $CommandRunner $pyInfo.path @('-m', 'venv', $VenvPath)
                if ($venvRes.exit_code -ne 0) {
                    throw "Failed to create virtual environment at '$VenvPath': $($venvRes.output)"
                }
            }
            if (-not (Test-Path -LiteralPath $venvPy -PathType Leaf)) {
                throw "Virtual environment Python not found at '$venvPy' after creation."
            }
            $venvPyInfo = Resolve-VmLabGuestPythonInterpreter -PythonPath $venvPy -CommandRunner $CommandRunner
            $details.venv_path = $VenvPath
            $details.venv_python_version = $venvPyInfo.version

            $requestedPackages = [System.Collections.Generic.List[string]]::new()
            if ($Packages) {
                foreach ($pkg in $Packages) {
                    if (-not [string]::IsNullOrWhiteSpace($pkg)) {
                        $pkgToken = ($pkg.Trim() -split '[\s;\[=<>!~]', 2)[0].Trim()
                        if ($pkgToken) { $requestedPackages.Add((ConvertTo-VmLabNormalizedPackageName -Name $pkgToken)) }
                    }
                }
            }
            if (-not [string]::IsNullOrWhiteSpace($RequirementsPath)) {
                foreach ($rPkg in (Get-VmLabRequirementsPackageNames -RequirementsPath $RequirementsPath)) {
                    $requestedPackages.Add($rPkg)
                }
            }
            $expectedPkgs = @($requestedPackages | Select-Object -Unique)
            $details.expected_packages = $expectedPkgs

            $hasWheelhouse = -not [string]::IsNullOrWhiteSpace($WheelhousePath)
            $hasPackageRequest = ($expectedPkgs.Count -gt 0) -or (-not [string]::IsNullOrWhiteSpace($RequirementsPath))

            if ($hasWheelhouse -and -not $hasPackageRequest) {
                throw '-WheelhousePath requires -RequirementsPath or -Packages; refusing to upgrade only pip without explicit package inputs.'
            }
            if ($hasWheelhouse) {
                if (-not (Test-Path -LiteralPath $WheelhousePath -PathType Container)) {
                    throw "Wheelhouse directory not found on guest: '$WheelhousePath'."
                }
            }

            if ($hasPackageRequest) {
                $pipArgs = [System.Collections.Generic.List[string]]::new()
                $pipArgs.AddRange([string[]]@('-m', 'pip', 'install'))
                if ($hasWheelhouse) {
                    $pipArgs.Add('--no-index')
                    $pipArgs.Add('--find-links')
                    $pipArgs.Add($WheelhousePath)
                    $details.install_mode = 'offline-wheelhouse'
                } elseif ($Offline) {
                    throw 'Offline package installation requested (-Offline) without -WheelhousePath.'
                } elseif ($AllowOnlineInstall) {
                    $details.install_mode = 'online'
                } else {
                    throw 'Refusing implicit online pip install: provide -WheelhousePath for offline install or -AllowOnlineInstall for online install.'
                }

                if (-not [string]::IsNullOrWhiteSpace($RequirementsPath)) {
                    $pipArgs.Add('-r')
                    $pipArgs.Add($RequirementsPath)
                }
                if ($Packages) {
                    foreach ($pkg in $Packages) {
                        if (-not [string]::IsNullOrWhiteSpace($pkg)) { $pipArgs.Add($pkg.Trim()) }
                    }
                }

                $pipRes = & $CommandRunner $venvPy $pipArgs.ToArray()
                if ($pipRes.exit_code -ne 0) {
                    throw "pip install failed with exit code $($pipRes.exit_code): $($pipRes.output)"
                }

                $listRes = & $CommandRunner $venvPy @('-m', 'pip', 'list', '--format=json')
                if ($listRes.exit_code -ne 0) {
                    throw "Failed to verify installed packages via pip list: $($listRes.output)"
                }
                $installedList = @($listRes.output | ConvertFrom-Json -ErrorAction Stop)
                $installedNames = @($installedList | ForEach-Object { ConvertTo-VmLabNormalizedPackageName -Name ([string]$_.name) })
                $missing = @($expectedPkgs | Where-Object { $installedNames -notcontains $_ })
                if ($missing.Count -gt 0) {
                    throw "Package verification failed; missing expected packages: $($missing -join ', ')."
                }
                $details.installed_packages = $installedNames
            }
        } elseif ($Profile -eq 'powershell-dev') {
            $skipPwshPath = $PSBoundParameters.ContainsKey('PwshStandardPaths')
            $pwshInfo = Resolve-VmLabGuestPwshExecutable -StandardPaths $PwshStandardPaths -SkipPathSearch:$skipPwshPath -CommandRunner $CommandRunner
            if (-not $pwshInfo -and -not [string]::IsNullOrWhiteSpace($InstallerPath)) {
                if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
                    throw "PowerShell 7 installer not found on guest: '$InstallerPath'."
                }
                if ([System.IO.Path]::GetExtension($InstallerPath).ToLowerInvariant() -ne '.msi') {
                    throw "PowerShell 7 installer must be an .msi package: '$InstallerPath'."
                }
                & $verifyInstallerHash $InstallerPath $ExpectedInstallerSha256
                $msiExit = & $ProcessRunner 'msiexec.exe' @('/i', $InstallerPath, '/quiet', '/norestart')
                $details.installer_exit_code = $msiExit
                if ($msiExit -eq 3010) {
                    return (& $saveProfileState $false 'reboot_required' $true 'PowerShell 7 MSI installer requires a guest reboot (exit code 3010).')
                }
                if ($msiExit -ne 0) {
                    throw "PowerShell 7 MSI installer exited with code $msiExit."
                }
                Update-VmLabGuestProcessPath
                $pwshInfo = Resolve-VmLabGuestPwshExecutable -StandardPaths $PwshStandardPaths -SkipPathSearch:$skipPwshPath -CommandRunner $CommandRunner
            }
            if (-not $pwshInfo) {
                throw 'PowerShell 7 (pwsh.exe >= 7.0) is not installed on guest and no valid -InstallerPath was provided.'
            }
            $details.pwsh_path = $pwshInfo.path
            $details.pwsh_version = $pwshInfo.version
        }

        return (& $saveProfileState $true 'completed' $false $null)
    } catch {
        $null = & $saveProfileState $false 'failed' $false $_.Exception.Message
        throw
    }
}

function Test-VmLabGuestVerifyLocal {
    param(
        [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$Profile = 'windows-minimal',
        [string]$VenvPath = 'C:\venvs\dev',
        [string[]]$Packages,
        [string]$RequirementsPath,
        [string]$StateRoot = 'C:\ProgramData\vm_lab',
        [string[]]$PwshStandardPaths,
        [scriptblock]$CommandRunner
    )
    if (-not $CommandRunner) {
        $CommandRunner = {
            param([string]$Exe, [string[]]$ExeArgs)
            $out = & $Exe @ExeArgs 2>&1
            return [pscustomobject]@{
                exit_code = $LASTEXITCODE
                output    = (($out | ForEach-Object { [string]$_ }) -join "`n").Trim()
            }
        }
    }

    $failures = [System.Collections.Generic.List[string]]::new()
    $stateDirPresent = Test-Path -LiteralPath $StateRoot -PathType Container
    $store = Read-VmLabGuestBootstrapStore -StateRoot $StateRoot

    $checks = [ordered]@{
        state_dir_present = $stateDirPresent
        bootstrap_marker  = $store.exists
        marker_valid_json = $store.valid
        profile_recorded  = $false
        profile_completed = $false
        reboot_required   = $false
    }

    $status = 'verified'
    if (-not $stateDirPresent) {
        $failures.Add("State directory missing: '$StateRoot'.")
        $status = 'incomplete'
    }
    if (-not $store.exists) {
        $failures.Add("Bootstrap state file missing: '$($store.path)'.")
        $status = 'incomplete'
    } elseif (-not $store.valid) {
        $failures.Add("Bootstrap state JSON is invalid: $($store.error)")
        $status = 'failed'
    } else {
        $profEntry = $store.profiles[$Profile]
        if ($null -eq $profEntry) {
            $failures.Add("Profile '$Profile' has not been recorded in bootstrap state.")
            $status = 'incomplete'
        } else {
            $checks.profile_recorded = $true
            $checks.profile_completed = [bool]$profEntry.completed
            $checks.reboot_required = [bool]$profEntry.reboot_required
            if ($profEntry.reboot_required) {
                $failures.Add("Profile '$Profile' requires a guest reboot before verification can pass.")
                $status = 'incomplete'
            } elseif (-not [bool]$profEntry.completed) {
                $errText = if ($profEntry.error) { ": $($profEntry.error)" } else { '' }
                $failures.Add("Profile '$Profile' is incomplete (status=$($profEntry.status))$errText")
                $status = if ($profEntry.status -eq 'failed') { 'failed' } else { 'incomplete' }
            }
        }
    }

    if ($Profile -eq 'python-dev') {
        $venvPy = Join-Path $VenvPath 'Scripts\python.exe'
        $checks.venv_python_present = Test-Path -LiteralPath $venvPy -PathType Leaf
        if (-not $checks.venv_python_present) {
            $failures.Add("Virtual environment Python not found: '$venvPy'.")
            if ($status -eq 'verified') { $status = 'failed' }
        } else {
            try {
                $pyInfo = Resolve-VmLabGuestPythonInterpreter -PythonPath $venvPy -CommandRunner $CommandRunner
                $checks.python_version = $pyInfo.version
                $checks.python_bitness = $pyInfo.bitness
            } catch {
                $failures.Add($_.Exception.Message)
                $status = 'failed'
            }

            $expectedPkgs = [System.Collections.Generic.List[string]]::new()
            if ($store.valid -and $store.profiles[$Profile] -and $store.profiles[$Profile].details -and $store.profiles[$Profile].details.expected_packages) {
                foreach ($ep in $store.profiles[$Profile].details.expected_packages) {
                    $expectedPkgs.Add((ConvertTo-VmLabNormalizedPackageName -Name ([string]$ep)))
                }
            }
            if ($Packages) {
                foreach ($p in $Packages) {
                    $tok = ($p.Trim() -split '[\s;\[=<>!~]', 2)[0].Trim()
                    if ($tok) { $expectedPkgs.Add((ConvertTo-VmLabNormalizedPackageName -Name $tok)) }
                }
            }
            if (-not [string]::IsNullOrWhiteSpace($RequirementsPath)) {
                foreach ($rp in (Get-VmLabRequirementsPackageNames -RequirementsPath $RequirementsPath)) {
                    $expectedPkgs.Add($rp)
                }
            }
            $uniqueExpected = @($expectedPkgs | Select-Object -Unique)
            if ($uniqueExpected.Count -gt 0) {
                $listRes = & $CommandRunner $venvPy @('-m', 'pip', 'list', '--format=json')
                if ($listRes.exit_code -ne 0) {
                    $failures.Add("pip list failed with exit code $($listRes.exit_code).")
                    $status = 'failed'
                } else {
                    try {
                        $installedNames = @(($listRes.output | ConvertFrom-Json -ErrorAction Stop) | ForEach-Object { ConvertTo-VmLabNormalizedPackageName -Name ([string]$_.name) })
                        $missing = @($uniqueExpected | Where-Object { $installedNames -notcontains $_ })
                        $checks.missing_packages = $missing
                        if ($missing.Count -gt 0) {
                            $failures.Add("Missing expected Python packages: $($missing -join ', ').")
                            $status = 'failed'
                        }
                    } catch {
                        $failures.Add("Failed to parse pip list JSON output: $($_.Exception.Message)")
                        $status = 'failed'
                    }
                }
            }
        }
    } elseif ($Profile -eq 'powershell-dev') {
        $skipPwshPath = $PSBoundParameters.ContainsKey('PwshStandardPaths')
        $pwshInfo = Resolve-VmLabGuestPwshExecutable -StandardPaths $PwshStandardPaths -SkipPathSearch:$skipPwshPath -CommandRunner $CommandRunner
        $checks.pwsh_present = ($null -ne $pwshInfo)
        if (-not $pwshInfo) {
            $failures.Add('PowerShell 7 (pwsh.exe >= 7.0) is not available on guest.')
            if ($status -eq 'verified') { $status = 'failed' }
        } else {
            $checks.pwsh_path = $pwshInfo.path
            $checks.pwsh_version = $pwshInfo.version
        }
    }

    return [pscustomobject]@{
        status   = $status
        checks   = [pscustomobject]$checks
        failures = @($failures)
    }
}

function Get-VmLabRemoteBootstrapPrelude {
    $fnNames = @(
        'ConvertTo-VmLabNormalizedPackageName',
        'Get-VmLabRequirementsPackageNames',
        'Test-VmLabIsWindowsAppsAlias',
        'ConvertFrom-VmLabPythonVersionText',
        'Read-VmLabGuestBootstrapStore',
        'Write-VmLabGuestBootstrapStoreAtomic',
        'Update-VmLabGuestProcessPath',
        'Resolve-VmLabGuestPythonInterpreter',
        'Resolve-VmLabGuestPwshExecutable',
        'Invoke-VmLabGuestBootstrapLocal',
        'Test-VmLabGuestVerifyLocal'
    )
    return (($fnNames | ForEach-Object {
        $def = (Get-Item "Function:\$_").Definition
        "function $_ {`n$def`n}"
    }) -join "`n")
}

function Invoke-VmLabGuestBootstrap {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$Profile = 'windows-minimal',
        [string]$InstallerPath,
        [string]$ExpectedInstallerSha256,
        [string]$PythonPath,
        [string]$WheelhousePath,
        [string]$RequirementsPath,
        [string[]]$Packages,
        [string]$VenvPath = 'C:\venvs\dev',
        [switch]$Offline,
        [switch]$AllowOnlineInstall,
        [int]$MaxConnectAttempts = 1,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    if ([string]$vm.State -ne 'Running') {
        throw "Refusing guest-bootstrap on VM '$Name': VM must be Running (current state: '$($vm.State)')."
    }

    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($Name, "Run guest bootstrap profile '$Profile'")
        }
        return [pscustomobject]@{
            status            = 'planned'
            operation         = 'guest-bootstrap'
            vm_name           = $Name
            vm_id             = [string]$vm.Id
            profile           = $Profile
            installer_path    = $InstallerPath
            python_path       = $PythonPath
            wheelhouse_path   = $WheelhousePath
            requirements_path = $RequirementsPath
            packages          = $Packages
            venv_path         = $VenvPath
            offline           = [bool]$Offline
            allow_online      = [bool]$AllowOnlineInstall
        }
    }

    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        throw 'Guest credentials are required for guest-bootstrap (-Credential or -PromptCredential).'
    }
    if (-not $PSCmdlet.ShouldProcess($Name, "Run guest bootstrap profile '$Profile'")) {
        return [pscustomobject]@{ status = 'declined'; operation = 'guest-bootstrap'; vm_name = $Name; profile = $Profile }
    }

    $prelude = Get-VmLabRemoteBootstrapPrelude
    return (Invoke-VmLabGuestSession -VmId ([guid]$vm.Id) -VmName $vm.Name -Credential $cred -MaxConnectAttempts $MaxConnectAttempts -ScriptBlock {
        param($sess)
        $res = Invoke-VmLabPSSessionCommand -Session $sess -ArgumentList @(
            $prelude, $Profile, $InstallerPath, $ExpectedInstallerSha256, $PythonPath,
            $WheelhousePath, $RequirementsPath, $Packages, $VenvPath, [bool]$Offline, [bool]$AllowOnlineInstall
        ) -ScriptBlock {
            param($pre, $prof, $instPath, $expSha, $pyPath, $wheelPath, $reqPath, $pkgs, $vPath, $isOff, $allowOnline)
            . ([scriptblock]::Create($pre))
            Invoke-VmLabGuestBootstrapLocal `
                -Profile $prof `
                -InstallerPath $instPath `
                -ExpectedInstallerSha256 $expSha `
                -PythonPath $pyPath `
                -WheelhousePath $wheelPath `
                -RequirementsPath $reqPath `
                -Packages $pkgs `
                -VenvPath $vPath `
                -Offline:$isOff `
                -AllowOnlineInstall:$allowOnline
        }

        if ($null -eq $res) {
            throw "Guest bootstrap returned no result for profile '$Profile'."
        }

        $outerStatus = if ($res.PSObject.Properties['reboot_required'] -and $res.reboot_required) {
            'reboot_required'
        } elseif ($res.PSObject.Properties['completed'] -and -not $res.completed) {
            'failed'
        } else {
            'bootstrapped'
        }

        return [pscustomobject]@{
            status    = $outerStatus
            operation = 'guest-bootstrap'
            vm_name   = $Name
            vm_id     = [string]$vm.Id
            profile   = $Profile
            result    = $res
        }
    })
}

function Test-VmLabGuestVerify {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$Profile = 'windows-minimal',
        [string]$VenvPath = 'C:\venvs\dev',
        [string[]]$Packages,
        [string]$RequirementsPath,
        [int]$MaxConnectAttempts = 1,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    if ([string]$vm.State -ne 'Running') {
        throw "Cannot verify guest '$Name': VM is not Running (current state: '$($vm.State)')."
    }
    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        throw 'Guest credentials are required for guest-verify (-Credential or -PromptCredential).'
    }

    $prelude = Get-VmLabRemoteBootstrapPrelude
    return (Invoke-VmLabGuestSession -VmId ([guid]$vm.Id) -VmName $vm.Name -Credential $cred -MaxConnectAttempts $MaxConnectAttempts -ScriptBlock {
        param($sess)
        $v = Invoke-VmLabPSSessionCommand -Session $sess -ArgumentList @($prelude, $Profile, $VenvPath, $Packages, $RequirementsPath) -ScriptBlock {
            param($pre, $prof, $vPath, $pkgs, $reqPath)
            . ([scriptblock]::Create($pre))
            Test-VmLabGuestVerifyLocal -Profile $prof -VenvPath $vPath -Packages $pkgs -RequirementsPath $reqPath
        }

        return [pscustomobject]@{
            status    = $v.status
            operation = 'guest-verify'
            vm_name   = $Name
            vm_id     = [string]$vm.Id
            profile   = $Profile
            checks    = $v.checks
            failures  = $v.failures
        }
    })
}
