#Requires -Version 7.0

function Invoke-VmLabGuestBootstrap {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$Profile = 'windows-minimal',
        [string]$InstallerPath,
        [string]$WheelhousePath,
        [string]$VenvPath = 'C:\venvs\dev',
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
            status          = 'planned'
            operation       = 'guest-bootstrap'
            vm_name         = $Name
            vm_id           = [string]$vm.Id
            profile         = $Profile
            installer_path  = $InstallerPath
            wheelhouse_path = $WheelhousePath
            venv_path       = $VenvPath
        }
    }

    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        throw 'Guest credentials are required for guest-bootstrap (-Credential or -PromptCredential).'
    }
    if (-not $PSCmdlet.ShouldProcess($Name, "Run guest bootstrap profile '$Profile'")) {
        return [pscustomobject]@{ status = 'declined'; operation = 'guest-bootstrap'; vm_name = $Name; profile = $Profile }
    }

    return (Invoke-VmLabGuestSession -VmId ([guid]$vm.Id) -VmName $vm.Name -Credential $cred -ScriptBlock {
        param($sess)
        $res = Invoke-VmLabPSSessionCommand -Session $sess -ArgumentList @($Profile, $InstallerPath, $WheelhousePath, $VenvPath) -ScriptBlock {
            param($prof, $instPath, $wheelPath, $vPath)
            $stateDir = 'C:\ProgramData\vm_lab'
            if (-not (Test-Path -LiteralPath $stateDir)) {
                New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
            }

            $os = Get-CimInstance Win32_OperatingSystem
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
            $principal = [Security.Principal.WindowsPrincipal]::new($identity)
            $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            $drive = [System.IO.DriveInfo]::new('C')

            $details = [ordered]@{
                profile         = $prof
                os_caption      = $os.Caption
                os_version      = $os.Version
                os_architecture = $os.OSArchitecture
                ps_version      = $PSVersionTable.PSVersion.ToString()
                is_admin        = $isAdmin
                c_free_bytes    = [int64]$drive.AvailableFreeSpace
            }

            if ($prof -eq 'python-dev') {
                $pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
                if (-not $pyCmd -and -not [string]::IsNullOrWhiteSpace($instPath)) {
                    if (-not (Test-Path -LiteralPath $instPath -PathType Leaf)) {
                        throw "Python installer not found on guest: '$instPath'."
                    }
                    $proc = Start-Process -FilePath $instPath -ArgumentList @('/quiet', 'InstallAllUsers=1', 'PrependPath=1') -Wait -PassThru -ErrorAction Stop
                    if ($proc.ExitCode -ne 0) {
                        throw "Python installer exited with code $($proc.ExitCode)."
                    }
                    $pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
                }
                if (-not $pyCmd) {
                    throw 'Python 3.12+ is not installed on guest and no valid -InstallerPath was provided.'
                }
                $pyVer = (& $pyCmd.Source --version) 2>&1
                $details.python_version = [string]$pyVer
                if (-not (Test-Path -LiteralPath (Join-Path $vPath 'Scripts\python.exe'))) {
                    & $pyCmd.Source -m venv $vPath
                    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment at '$vPath'." }
                }
                $venvPy = Join-Path $vPath 'Scripts\python.exe'
                if (-not [string]::IsNullOrWhiteSpace($wheelPath)) {
                    if (-not (Test-Path -LiteralPath $wheelPath -PathType Container)) {
                        throw "Wheelhouse directory not found on guest: '$wheelPath'."
                    }
                    & $venvPy -m pip install --no-index --find-links $wheelPath --upgrade pip
                    if ($LASTEXITCODE -ne 0) { throw "Offline wheelhouse install failed from '$wheelPath'." }
                }
                $details.venv_path = $vPath
            } elseif ($prof -eq 'powershell-dev') {
                $pwshCmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -First 1
                if (-not $pwshCmd -and -not [string]::IsNullOrWhiteSpace($instPath)) {
                    if (-not (Test-Path -LiteralPath $instPath -PathType Leaf)) {
                        throw "PowerShell 7 installer not found on guest: '$instPath'."
                    }
                    $proc = Start-Process -FilePath 'msiexec.exe' -ArgumentList @('/i', $instPath, '/quiet', '/norestart') -Wait -PassThru -ErrorAction Stop
                    if ($proc.ExitCode -ne 0) {
                        throw "PowerShell 7 MSI installer exited with code $($proc.ExitCode)."
                    }
                    $pwshCmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -First 1
                }
                if (-not $pwshCmd) {
                    throw 'PowerShell 7 (pwsh.exe) is not installed on guest and no valid -InstallerPath was provided.'
                }
                $details.pwsh_path = $pwshCmd.Source
                $details.pwsh_version = [string](& $pwshCmd.Source -NoProfile -Command '$PSVersionTable.PSVersion.ToString()')
            }

            $marker = [pscustomobject]@{
                schema_version = 1
                completed      = $true
                profile        = $prof
                completed_at   = [DateTimeOffset]::UtcNow.ToString('o')
                details        = $details
            }
            $marker | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stateDir 'bootstrap-state.json') -Encoding utf8
            return $marker
        }

        return [pscustomobject]@{
            status    = 'bootstrapped'
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

    return (Invoke-VmLabGuestSession -VmId ([guid]$vm.Id) -VmName $vm.Name -Credential $cred -ScriptBlock {
        param($sess)
        $v = Invoke-VmLabPSSessionCommand -Session $sess -ArgumentList @($Profile, $VenvPath) -ScriptBlock {
            param($prof, $vPath)
            $markerPath = 'C:\ProgramData\vm_lab\bootstrap-state.json'
            $hasMarker = Test-Path -LiteralPath $markerPath -PathType Leaf
            $checks = [ordered]@{
                state_dir_present = (Test-Path -LiteralPath 'C:\ProgramData\vm_lab' -PathType Container)
                bootstrap_marker  = $hasMarker
            }
            if ($prof -eq 'python-dev') {
                $venvPy = Join-Path $vPath 'Scripts\python.exe'
                $checks.venv_python_present = (Test-Path -LiteralPath $venvPy -PathType Leaf)
                if ($checks.venv_python_present) {
                    $checks.python_version = [string](& $venvPy --version)
                }
            } elseif ($prof -eq 'powershell-dev') {
                $pwshCmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -First 1
                $checks.pwsh_present = ($null -ne $pwshCmd)
                if ($pwshCmd) {
                    $checks.pwsh_version = [string](& $pwshCmd.Source -NoProfile -Command '$PSVersionTable.PSVersion.ToString()')
                }
            }
            return $checks
        }

        return [pscustomobject]@{
            status    = 'verified'
            operation = 'guest-verify'
            vm_name   = $Name
            vm_id     = [string]$vm.Id
            profile   = $Profile
            checks    = $v
        }
    })
}
