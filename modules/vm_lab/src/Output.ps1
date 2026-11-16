#Requires -Version 7.0

function Invoke-VmLab {
    <#
    .SYNOPSIS
        Unified CLI and PowerShell entry point for vm_lab Hyper-V lab operations.
    .DESCRIPTION
        Supports read-only inspection (list, status, plan, templates, template-info, checkpoints, boot-diagnostics),
        interactive setup (wizard), VMConnect (connect, start-connect), and dry-run-by-default
        mutating operations (quickstart, create, start, stop, checkpoint) requiring -Apply.
    .EXAMPLE
        Invoke-VmLab -Operation templates -Json
    .EXAMPLE
        Invoke-VmLab -o quickstart -t windows11-dev -n Dev-Win11-01 -r C:\VMs\Dev-Win11-01 -j
    .EXAMPLE
        Invoke-VmLab -o quickstart -t windows11-dev -n Dev-Win11-01 -r C:\VMs\Dev-Win11-01 -Apply -Start
    #>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory, Position = 0)]
        [Alias('o')]
        [ValidateSet('list', 'status', 'plan', 'quickstart', 'wizard', 'templates', 'template-info', 'create', 'start', 'stop', 'connect', 'start-connect', 'boot-diagnostics', 'guest-status', 'guest-copy', 'guest-bootstrap', 'guest-verify', 'guest-command-plan', 'guest-exec', 'artifact-plan', 'artifact-deploy', 'evidence-plan', 'evidence-collect', 'lifecycle-transaction', 'checkpoint', 'baseline', 'checkpoints', 'recovery-plan', 'doctor', 'unattend-xml')]
        [string]$Operation,

        [Alias('n')][string]$Name,
        [Alias('c')][string]$ConfigPath,
        [Alias('t')][string]$TemplateName = 'windows11-h4',
        [Alias('i')][string]$IsoPath,
        [Alias('r')][string]$VmRoot,
        [Alias('s')][string]$SwitchName,
        [Alias('m')][string]$CheckpointName,
        [Alias('a')][switch]$Apply,
        [Alias('j')][switch]$Json,
        [Alias('oo')][switch]$OwnedOnly,
        [Alias('rb')][int64]$MinReserveBytes = 4GB,
        [Alias('st')][int]$ShutdownTimeoutSeconds = 30,
        [Alias('mr')][string]$ManifestRoot = (Get-VmLabDefaultManifestRoot),
        [switch]$Start,
        [switch]$Connect,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [string]$SourcePath,
        [string]$DestinationPath,
        [ValidateSet('ToGuest', 'FromGuest')][string]$Direction = 'ToGuest',
        [switch]$Overwrite,
        [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$GuestProfile = 'windows-minimal',
        [string]$InstallerPath,
        [string]$ExpectedInstallerSha256,
        [string]$PythonPath,
        [string]$WheelhousePath,
        [string]$RequirementsPath,
        [string[]]$Packages,
        [string]$VenvPath = 'C:\venvs\dev',
        [switch]$Offline,
        [switch]$AllowOnlineInstall,
        [switch]$RequireGuestVerified,
        [int]$MaxConnectAttempts = 1,
        [string]$OutputPath,
        [string]$Locale = 'en-US',
        [string]$KeyboardLayout = 'en-US',
        [string]$ImageEdition,
        [string]$ExecutablePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = 'C:\Windows\Temp',
        [string]$ExpectedSha256,
        [Alias('am')][string]$ArtifactManifestPath,
        [string[]]$GuestRoots,
        [Alias('er')][string]$EvidenceRoot,
        [Alias('op')][string]$OperationId,
        [switch]$AuthorizeHostMutation,
        [switch]$AuthorizeVmLifecycle,
        [switch]$AuthorizeGuestMutation,
        [switch]$AuthorizeGuestExec,
        [switch]$RestartAfter
    )

    $result = switch ($Operation) {
        'list' {
            @(Get-VmLabList -OwnedOnly:$OwnedOnly -ManifestRoot $ManifestRoot)
        }
        'status' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for status.' }
            Get-VmLabStatus -Name $Name -ManifestRoot $ManifestRoot
        }
        'templates' {
            @(Get-VmLabTemplates)
        }
        'template-info' {
            Get-VmLabTemplateInfo -TemplateName $TemplateName
        }
        'plan' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if ($PSBoundParameters.ContainsKey('Name')) { $cfg.vm_name = $Name }
            if ($PSBoundParameters.ContainsKey('IsoPath')) { $cfg.iso_path = $IsoPath }
            if ($PSBoundParameters.ContainsKey('VmRoot')) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            Test-VmLabPlan -Config $cfg -ManifestRoot $ManifestRoot
        }
        'quickstart' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if ($PSBoundParameters.ContainsKey('Name')) { $cfg.vm_name = $Name }
            if ($PSBoundParameters.ContainsKey('IsoPath')) { $cfg.iso_path = $IsoPath }
            if ($PSBoundParameters.ContainsKey('VmRoot')) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            Invoke-VmLabQuickstart -Config $cfg -Apply:$Apply -Start:$Start -Connect:$Connect -MinHostReserveBytes $MinReserveBytes -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'wizard' {
            if ($Json) {
                throw 'Interactive wizard cannot prompt in -Json mode. Use -o plan or -o quickstart with explicit parameters.'
            }
            Invoke-VmLabWizard -DefaultTemplate $TemplateName -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'create' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if ($PSBoundParameters.ContainsKey('Name')) { $cfg.vm_name = $Name }
            if ($PSBoundParameters.ContainsKey('IsoPath')) { $cfg.iso_path = $IsoPath }
            if ($PSBoundParameters.ContainsKey('VmRoot')) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            New-VmLabMachine -Config $cfg -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'start' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for start.' }
            Start-VmLabMachine -Name $Name -MinHostReserveBytes $MinReserveBytes -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'stop' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for stop.' }
            Stop-VmLabMachine -Name $Name -ShutdownTimeoutSeconds $ShutdownTimeoutSeconds -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'connect' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for connect.' }
            Connect-VmLabMachine -Name $Name -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'start-connect' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for start-connect.' }
            Start-AndConnectVmLabMachine -Name $Name -MinHostReserveBytes $MinReserveBytes -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'boot-diagnostics' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for boot-diagnostics.' }
            Get-VmLabBootDiagnostics -Name $Name -ManifestRoot $ManifestRoot
        }
        'guest-status' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for guest-status.' }
            Get-VmLabGuestStatus -Name $Name -Credential $Credential -PromptCredential:$PromptCredential -ManifestRoot $ManifestRoot
        }
        'guest-copy' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for guest-copy.' }
            if ([string]::IsNullOrWhiteSpace($SourcePath)) { throw '-SourcePath is required for guest-copy.' }
            if ([string]::IsNullOrWhiteSpace($DestinationPath)) { throw '-DestinationPath is required for guest-copy.' }
            Copy-VmLabGuestItem -Name $Name -SourcePath $SourcePath -DestinationPath $DestinationPath -Direction $Direction -Credential $Credential -PromptCredential:$PromptCredential -Overwrite:$Overwrite -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'guest-bootstrap' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for guest-bootstrap.' }
            Invoke-VmLabGuestBootstrap -Name $Name -Profile $GuestProfile -InstallerPath $InstallerPath -ExpectedInstallerSha256 $ExpectedInstallerSha256 -PythonPath $PythonPath -WheelhousePath $WheelhousePath -RequirementsPath $RequirementsPath -Packages $Packages -VenvPath $VenvPath -Offline:$Offline -AllowOnlineInstall:$AllowOnlineInstall -MaxConnectAttempts $MaxConnectAttempts -Credential $Credential -PromptCredential:$PromptCredential -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'guest-verify' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for guest-verify.' }
            Test-VmLabGuestVerify -Name $Name -Profile $GuestProfile -VenvPath $VenvPath -Packages $Packages -RequirementsPath $RequirementsPath -MaxConnectAttempts $MaxConnectAttempts -Credential $Credential -PromptCredential:$PromptCredential -ManifestRoot $ManifestRoot
        }
        { $_ -in @('guest-command-plan', 'guest-exec') } {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw "-Name (-n) is required for $Operation." }
            if ([string]::IsNullOrWhiteSpace($ExecutablePath)) { throw "-ExecutablePath is required for $Operation." }
            $applyExec = ($Operation -eq 'guest-exec') -and $Apply
            Invoke-VmLabGuestCommand -Name $Name -ExecutablePath $ExecutablePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -ExpectedSha256 $ExpectedSha256 -OperationId $OperationId -Credential $Credential -PromptCredential:$PromptCredential -Apply:$applyExec -AuthorizeGuestExec:$AuthorizeGuestExec -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        { $_ -in @('artifact-plan', 'artifact-deploy') } {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw "-Name (-n) is required for $Operation." }
            if ([string]::IsNullOrWhiteSpace($SourcePath)) { throw "-SourcePath is required for $Operation." }
            if (-not [string]::IsNullOrWhiteSpace($ArtifactManifestPath)) {
                $manifestObj = Get-Content -LiteralPath $ArtifactManifestPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
            } else {
                if ([string]::IsNullOrWhiteSpace($DestinationPath)) { throw "-DestinationPath or -ArtifactManifestPath is required for $Operation." }
                $manifestObj = New-VmLabArtifactManifest -SourceRoot $SourcePath -DestinationRoot $DestinationPath
            }
            $applyDeploy = ($Operation -eq 'artifact-deploy') -and $Apply
            Publish-VmLabArtifactBundle -Name $Name -SourceRoot $SourcePath -Manifest $manifestObj -Credential $Credential -PromptCredential:$PromptCredential -Apply:$applyDeploy -AuthorizeGuestMutation:$AuthorizeGuestMutation -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        { $_ -in @('evidence-plan', 'evidence-collect') } {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw "-Name (-n) is required for $Operation." }
            $roots = if ($GuestRoots -and $GuestRoots.Count -gt 0) { $GuestRoots } elseif (-not [string]::IsNullOrWhiteSpace($SourcePath)) { @($SourcePath) } else { throw "-GuestRoots or -SourcePath is required for $Operation." }
            $destEv = if (-not [string]::IsNullOrWhiteSpace($EvidenceRoot)) { $EvidenceRoot } elseif (-not [string]::IsNullOrWhiteSpace($DestinationPath)) { $DestinationPath } else { throw "-EvidenceRoot or -DestinationPath is required for $Operation." }
            if ($Operation -eq 'evidence-plan') {
                Get-VmLabEvidencePlan -Name $Name -GuestRoots $roots -HostDestination $destEv -ManifestRoot $ManifestRoot
            } else {
                Receive-VmLabGuestEvidence -Name $Name -GuestRoots $roots -HostDestination $destEv -Credential $Credential -PromptCredential:$PromptCredential -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
            }
        }
        'lifecycle-transaction' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for lifecycle-transaction.' }
            $cpName = if ([string]::IsNullOrWhiteSpace($CheckpointName)) { 'tx-checkpoint' } else { $CheckpointName }
            Invoke-VmLabCheckpointTransaction -Name $Name -CheckpointName $cpName -RestartAfter:$RestartAfter -ShutdownTimeoutSeconds $ShutdownTimeoutSeconds -MinHostReserveBytes $MinReserveBytes -Credential $Credential -PromptCredential:$PromptCredential -Apply:$Apply -AuthorizeVmLifecycle:$AuthorizeVmLifecycle -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'checkpoint' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for checkpoint.' }
            if ([string]::IsNullOrWhiteSpace($CheckpointName)) { throw '-CheckpointName (-m) is required for checkpoint.' }
            New-VmLabCheckpoint -Name $Name -CheckpointName $CheckpointName -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'baseline' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for baseline.' }
            $cpName = if ([string]::IsNullOrWhiteSpace($CheckpointName)) { 'clean-baseline' } else { $CheckpointName }
            New-VmLabBaselineCheckpoint -Name $Name -CheckpointName $cpName -RequireGuestVerified:$RequireGuestVerified -GuestProfile $GuestProfile -VenvPath $VenvPath -Credential $Credential -PromptCredential:$PromptCredential -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'checkpoints' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for checkpoints.' }
            @(Get-VmLabCheckpoint -Name $Name -ManifestRoot $ManifestRoot)
        }
        { $_ -in @('recovery-plan', 'doctor') } {
            Get-VmLabRecoveryPlan -Name $Name -VmRoot $VmRoot -Credential $Credential -ManifestRoot $ManifestRoot
        }
        'unattend-xml' {
            New-VmLabUnattendXml -OutputPath $OutputPath -Locale $Locale -KeyboardLayout $KeyboardLayout -ImageEdition $ImageEdition -Overwrite:$Overwrite -Apply:$Apply -WhatIf:$WhatIfPreference
        }
    }

    if ($Json) {
        if ($Operation -in @('list', 'checkpoints', 'templates')) {
            return (ConvertTo-Json -InputObject @($result) -Depth 8)
        }
        return (ConvertTo-Json -InputObject $result -Depth 8)
    }
    return $result
}
