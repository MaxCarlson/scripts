#Requires -Version 7.0

function Get-VmLabProtectedVmRegistry {
    [CmdletBinding()]
    param()
    return [pscustomobject]@{
        names = @('RC-H4-Windows-Acceptance')
        ids   = @('d8483f98-8884-4758-abd1-cd6107c83c03')
    }
}

function Assert-VmLabTargetNotProtected {
    [CmdletBinding()]
    param(
        [string]$VmName,
        [string]$VmId
    )
    $reg = Get-VmLabProtectedVmRegistry
    if (-not [string]::IsNullOrWhiteSpace($VmName) -and ($reg.names -contains $VmName)) {
        throw "Refusing operation against protected VM name '$VmName'."
    }
    if (-not [string]::IsNullOrWhiteSpace($VmId)) {
        $normId = $VmId.Trim().ToLowerInvariant()
        if ($reg.ids -contains $normId) {
            throw "Refusing operation against protected VM ID '$VmId'."
        }
    }
}

function Test-VmLabSafePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label,
        [string]$WithinRoot,
        [switch]$AllowRelative,
        [switch]$CheckReparsePoints
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Label path cannot be empty."
    }
    if ($Path.StartsWith('\\')) {
        throw "$Label path must not be a UNC path: '$Path'."
    }
    if ($Path -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "$Label path must not contain '..' traversal: '$Path'."
    }
    if (-not $AllowRelative -and $Path -notmatch '^[A-Za-z]:[\\/]') {
        throw "$Label path must be fully qualified with a drive letter: '$Path'."
    }

    $normalized = if ($AllowRelative -and $Path -notmatch '^[A-Za-z]:[\\/]') {
        $Path.Replace('/', '\').TrimStart('\')
    } else {
        [System.IO.Path]::GetFullPath($Path)
    }

    if (-not [string]::IsNullOrWhiteSpace($WithinRoot)) {
        $rootFull = [System.IO.Path]::GetFullPath($WithinRoot).TrimEnd('\', '/')
        $targetFull = [System.IO.Path]::GetFullPath($normalized)
        $prefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
        if (-not $targetFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -and
            -not $targetFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "$Label path '$targetFull' must reside within '$rootFull'."
        }
    }

    if ($CheckReparsePoints -and $normalized -match '^[A-Za-z]:[\\/]') {
        $cur = $normalized
        while (-not [string]::IsNullOrWhiteSpace($cur)) {
            if (Test-Path -LiteralPath $cur) {
                $item = Get-Item -LiteralPath $cur -Force -ErrorAction Stop
                if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                    throw "$Label path refuses reparse point: '$cur'."
                }
            }
            $parent = Split-Path -Parent $cur
            if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $cur) { break }
            $cur = $parent
        }
    }

    return $normalized
}

function ConvertTo-VmLabCanonicalObject {
    param([object]$Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [string] -or $Value -is [bool] -or $Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) {
        return $Value
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $ordered = [ordered]@{}
        foreach ($k in ($Value.Keys | Sort-Object)) {
            $ordered[[string]$k] = ConvertTo-VmLabCanonicalObject -Value $Value[$k]
        }
        return $ordered
    }
    if ($Value -is [pscustomobject]) {
        $ordered = [ordered]@{}
        foreach ($p in ($Value.PSObject.Properties | Sort-Object Name)) {
            $ordered[$p.Name] = ConvertTo-VmLabCanonicalObject -Value $p.Value
        }
        return $ordered
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $arr = @()
        foreach ($item in $Value) {
            $arr += ,(ConvertTo-VmLabCanonicalObject -Value $item)
        }
        return $arr
    }
    return [string]$Value
}

function ConvertTo-VmLabCanonicalJson {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$InputObject)
    $canon = ConvertTo-VmLabCanonicalObject -Value $InputObject
    return ($canon | ConvertTo-Json -Depth 20 -Compress)
}

function Get-VmLabCanonicalSha256 {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$InputObject)
    $json = ConvertTo-VmLabCanonicalJson -InputObject $InputObject
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-VmLabWorkflowAllowedOperations {
    return @(
        'host.preflight',
        'vm.create',
        'vm.connect',
        'windows.install_handoff',
        'guest.wait',
        'artifact.deploy',
        'guest.bootstrap',
        'guest.exec',
        'vm.shutdown',
        'vm.checkpoint_transaction',
        'vm.start',
        'evidence.collect',
        'workflow.assert'
    )
}

function Get-VmLabWorkflowCapabilities {
    return @('none', 'host_mutation', 'vm_lifecycle', 'guest_mutation', 'guest_exec', 'elevation')
}

function Get-VmLabOperationCapabilityPolicy {
    [CmdletBinding()]
    param()
    return @{
        'host.preflight'            = 'none'
        'vm.create'                 = 'host_mutation'
        'vm.connect'                = 'vm_lifecycle'
        'windows.install_handoff'   = 'none'
        'guest.wait'                = 'none'
        'artifact.deploy'           = 'guest_mutation'
        'guest.bootstrap'           = 'guest_mutation'
        'guest.exec'                = 'guest_exec'
        'vm.shutdown'               = 'vm_lifecycle'
        'vm.checkpoint_transaction' = 'vm_lifecycle'
        'vm.start'                  = 'vm_lifecycle'
        'evidence.collect'          = 'host_mutation'
        'workflow.assert'           = 'none'
    }
}

function Get-VmLabOperationStates {
    return @('PLANNED', 'AWAITING_AUTHORIZATION', 'RUNNING', 'AWAITING_INTERACTION', 'BLOCKED', 'PARTIAL', 'FAILED', 'SUCCEEDED', 'INVALIDATED')
}

function Get-VmLabTopologicalStageOrder {
    param([Parameter(Mandatory)][object[]]$Stages)
    $byId = @{}
    $inDegree = @{}
    $adj = @{}
    foreach ($s in $Stages) {
        $id = [string]$s.id
        $byId[$id] = $s
        $inDegree[$id] = 0
        $adj[$id] = @()
    }
    foreach ($s in $Stages) {
        $id = [string]$s.id
        $deps = @($s.depends_on)
        foreach ($d in $deps) {
            $depId = [string]$d
            if (-not $byId.ContainsKey($depId)) {
                throw "Stage '$id' depends on unknown stage '$depId'."
            }
            if ($depId -eq $id) {
                throw "Stage '$id' cannot depend on itself."
            }
            $adj[$depId] += $id
            $inDegree[$id]++
        }
    }
    $queue = [System.Collections.Generic.Queue[string]]::new()
    foreach ($s in $Stages) {
        $id = [string]$s.id
        if ($inDegree[$id] -eq 0) {
            $queue.Enqueue($id)
        }
    }
    $order = @()
    while ($queue.Count -gt 0) {
        $cur = $queue.Dequeue()
        $order += $cur
        foreach ($nxt in $adj[$cur]) {
            $inDegree[$nxt]--
            if ($inDegree[$nxt] -eq 0) {
                $queue.Enqueue($nxt)
            }
        }
    }
    if ($order.Count -ne $Stages.Count) {
        throw 'Workflow stages contain a dependency cycle.'
    }
    return $order
}

function Test-VmLabWorkflowSchema {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Definition)

    $allowedTopKeys = @('schema_version', 'workflow_id', 'description', 'vm', 'operation_root', 'commands', 'stages')
    $props = @($Definition.PSObject.Properties.Name)
    foreach ($k in $props) {
        if ($allowedTopKeys -notcontains $k) {
            throw "Unknown workflow definition key '$k'."
        }
    }
    if ($Definition.schema_version -ne 1) {
        throw "Unsupported workflow schema_version '$($Definition.schema_version)'. Expected 1."
    }
    if ([string]::IsNullOrWhiteSpace([string]$Definition.workflow_id) -or $Definition.workflow_id -notmatch '^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$') {
        throw "Invalid workflow_id '$($Definition.workflow_id)'."
    }
    if ($null -eq $Definition.vm) {
        throw 'Workflow definition requires a vm object.'
    }

    $allowedVmKeys = @('template', 'name', 'root', 'iso', 'network_policy', 'guest_identity')
    foreach ($k in @($Definition.vm.PSObject.Properties.Name)) {
        if ($allowedVmKeys -notcontains $k) {
            throw "Unknown workflow.vm key '$k'."
        }
    }
    if ([string]::IsNullOrWhiteSpace([string]$Definition.vm.name)) {
        throw 'Workflow vm.name is required.'
    }
    Assert-VmLabTargetNotProtected -VmName ([string]$Definition.vm.name)
    $null = Test-VmLabSafePath -Path ([string]$Definition.vm.root) -Label 'workflow.vm.root'
    $null = Test-VmLabSafePath -Path ([string]$Definition.operation_root) -Label 'workflow.operation_root'
    if (-not [string]::IsNullOrWhiteSpace([string]$Definition.vm.iso)) {
        $null = Test-VmLabSafePath -Path ([string]$Definition.vm.iso) -Label 'workflow.vm.iso'
    }

    $stages = @($Definition.stages)
    if ($stages.Count -eq 0) {
        throw 'Workflow definition must include at least one stage.'
    }

    $allowedOps = Get-VmLabWorkflowAllowedOperations
    $allowedCaps = Get-VmLabWorkflowCapabilities
    $allowedStageKeys = @(
        'id', 'type', 'depends_on', 'capability', 'idempotency_class',
        'manifest', 'command_ref', 'args', 'working_directory', 'environment',
        'timeout_seconds', 'checkpoint_name', 'checkpoint_type', 'require_off',
        'restart_after', 'profile', 'destination', 'sources', 'expected_status',
        'assertions', 'on_failure', 'policy'
    )

    $seenIds = @{}
    foreach ($s in $stages) {
        foreach ($k in @($s.PSObject.Properties.Name)) {
            if ($allowedStageKeys -notcontains $k) {
                throw "Unknown key '$k' in stage '$($s.id)'."
            }
        }
        $sid = [string]$s.id
        if ([string]::IsNullOrWhiteSpace($sid) -or $sid -notmatch '^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$') {
            throw "Invalid stage id '$sid'."
        }
        if ($seenIds.ContainsKey($sid)) {
            throw "Duplicate stage id '$sid'."
        }
        $seenIds[$sid] = $true

        $stype = [string]$s.type
        if ($allowedOps -notcontains $stype) {
            throw "Unknown workflow stage type '$stype' in stage '$sid'."
        }
        $capPolicy = Get-VmLabOperationCapabilityPolicy
        $requiredCap = [string]$capPolicy[$stype]
        $hasDeclaredCap = ($null -ne $s.capability -and -not [string]::IsNullOrWhiteSpace([string]$s.capability))
        if ($hasDeclaredCap -and ($allowedCaps -notcontains [string]$s.capability)) {
            throw "Unknown capability '$($s.capability)' in stage '$sid'."
        }
        if ($requiredCap -ne 'none' -and -not $hasDeclaredCap) {
            throw "Stage '$sid' of type '$stype' requires explicit capability '$requiredCap'."
        }
        if ($hasDeclaredCap -and [string]$s.capability -ne $requiredCap) {
            throw "Stage '$sid' of type '$stype' declares capability '$($s.capability)', which does not match required capability '$requiredCap'."
        }
        if ($stype -eq 'artifact.deploy' -and [string]::IsNullOrWhiteSpace([string]$s.manifest)) {
            throw "Stage '$sid' of type 'artifact.deploy' requires 'manifest'."
        }
        if ($stype -eq 'guest.exec') {
            if ([string]::IsNullOrWhiteSpace([string]$s.command_ref)) {
                throw "Stage '$sid' of type 'guest.exec' requires 'command_ref'."
            }
            if ($null -eq $Definition.commands -or -not ($Definition.commands.PSObject.Properties.Name -contains [string]$s.command_ref)) {
                throw "Stage '$sid' references undefined command_ref '$($s.command_ref)'."
            }
        }
    }

    $order = Get-VmLabTopologicalStageOrder -Stages $stages

    # Validate VM power-state edges in topological order
    $stageMap = @{}
    foreach ($s in $stages) { $stageMap[[string]$s.id] = $s }
    $powerState = 'unknown'
    $guestReady = $false
    foreach ($sid in $order) {
        $s = $stageMap[$sid]
        switch ([string]$s.type) {
            'vm.create' {
                $powerState = 'off'
                $guestReady = $false
            }
            'vm.start' {
                $powerState = 'running'
                $guestReady = $false
            }
            'vm.shutdown' {
                $powerState = 'off'
                $guestReady = $false
            }
            'vm.checkpoint_transaction' {
                $reqOff = if ($null -ne $s.require_off) { [bool]$s.require_off } else { $true }
                if ($reqOff) {
                    $powerState = if ($s.restart_after -eq $true) { 'running' } else { 'off' }
                    $guestReady = $false
                }
            }
            'guest.wait' {
                if ($powerState -eq 'off') {
                    throw "Invalid power-state edge at stage '$sid' (guest.wait): VM is powered off; add vm.start before guest.wait."
                }
                $powerState = 'running'
                $guestReady = $true
            }
            { $_ -in @('artifact.deploy', 'guest.bootstrap', 'guest.exec', 'evidence.collect') } {
                if ($powerState -eq 'off' -or -not $guestReady) {
                    throw "Invalid power-state edge at stage '$sid' ($($s.type)): requires an active guest.wait readiness stage before guest operations."
                }
            }
        }
    }

    return [pscustomobject]@{
        valid           = $true
        schema_version  = 1
        workflow_id     = [string]$Definition.workflow_id
        workflow_digest = (Get-VmLabCanonicalSha256 -InputObject $Definition)
        stage_order     = $order
    }
}

function Test-VmLabArtifactManifestSchema {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Manifest)

    $allowedTop = @('schema_version', 'manifest_id', 'trusted_root_digest', 'destination_root', 'artifacts')
    foreach ($k in @($Manifest.PSObject.Properties.Name)) {
        if ($allowedTop -notcontains $k) {
            throw "Unknown artifact manifest key '$k'."
        }
    }
    if ($Manifest.schema_version -ne 1) {
        throw "Unsupported artifact manifest schema_version '$($Manifest.schema_version)'. Expected 1."
    }
    $items = @($Manifest.artifacts)
    if ($items.Count -eq 0) {
        throw 'Artifact manifest must include at least one artifact entry.'
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Manifest.destination_root)) {
        $null = Test-VmLabSafePath -Path ([string]$Manifest.destination_root) -Label 'manifest.destination_root'
    }

    $allowedItemKeys = @('relative_path', 'source_path', 'destination_relative', 'sha256', 'length', 'publisher', 'kind')
    foreach ($item in $items) {
        foreach ($k in @($item.PSObject.Properties.Name)) {
            if ($allowedItemKeys -notcontains $k) {
                throw "Unknown artifact item key '$k'."
            }
        }
        $rel = [string]$item.relative_path
        if ([string]::IsNullOrWhiteSpace($rel) -or $rel -match '^[A-Za-z]:' -or $rel.StartsWith('\\') -or $rel.StartsWith('/') -or $rel -match '(^|[\\/])\.\.([\\/]|$)') {
            throw "Invalid artifact relative_path '$rel'."
        }
        if ([string]$item.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
            throw "Invalid artifact sha256 for '$rel'."
        }
        if ($null -eq $item.length -or [int64]$item.length -lt 0) {
            throw "Invalid artifact length for '$rel'."
        }
    }

    return [pscustomobject]@{
        valid           = $true
        schema_version  = 1
        artifact_count  = $items.Count
        manifest_digest = (Get-VmLabCanonicalSha256 -InputObject $Manifest)
    }
}

function Test-VmLabOperationJournalSchema {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Journal,
        [string]$ExpectedOperationId,
        [string]$ExpectedVmId,
        [string]$ExpectedWorkflowDigest
    )
    $required = @('schema_version', 'operation_id', 'workflow_id', 'workflow_digest', 'vm_id', 'vm_name', 'vm_config_path', 'overall_state', 'stage_states')
    $props = @($Journal.PSObject.Properties.Name)
    foreach ($r in $required) {
        if ($props -notcontains $r) {
            throw "Operation journal missing required field '$r'."
        }
    }
    if ($Journal.schema_version -ne 1) {
        throw "Unsupported operation journal schema_version '$($Journal.schema_version)'."
    }
    $validStates = Get-VmLabOperationStates
    if ($validStates -notcontains [string]$Journal.overall_state) {
        throw "Invalid journal overall_state '$($Journal.overall_state)'."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedOperationId) -and [string]$Journal.operation_id -ne $ExpectedOperationId) {
        throw "Journal operation_id '$($Journal.operation_id)' does not match expected '$ExpectedOperationId'."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedVmId) -and ([string]$Journal.vm_id).ToLowerInvariant() -ne $ExpectedVmId.ToLowerInvariant()) {
        throw "Journal vm_id '$($Journal.vm_id)' does not match expected '$ExpectedVmId'."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedWorkflowDigest) -and [string]$Journal.workflow_digest -ne $ExpectedWorkflowDigest) {
        throw "Journal workflow_digest '$($Journal.workflow_digest)' does not match expected '$ExpectedWorkflowDigest'."
    }
    return $true
}

function Test-VmLabStageReceiptSchema {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Receipt,
        [string]$ExpectedOperationId,
        [string]$ExpectedStageId,
        [string]$ExpectedVmId
    )
    $required = @('schema_version', 'operation_id', 'stage_id', 'stage_type', 'attempt', 'vm_id', 'result_status', 'reason_code')
    $props = @($Receipt.PSObject.Properties.Name)
    foreach ($r in $required) {
        if ($props -notcontains $r) {
            throw "Stage receipt missing required field '$r'."
        }
    }
    if ($Receipt.schema_version -ne 1) {
        throw "Unsupported stage receipt schema_version '$($Receipt.schema_version)'."
    }
    $validStates = Get-VmLabOperationStates
    if ($validStates -notcontains [string]$Receipt.result_status) {
        throw "Invalid receipt result_status '$($Receipt.result_status)'."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedOperationId) -and [string]$Receipt.operation_id -ne $ExpectedOperationId) {
        throw "Receipt operation_id '$($Receipt.operation_id)' does not match '$ExpectedOperationId'."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedStageId) -and [string]$Receipt.stage_id -ne $ExpectedStageId) {
        throw "Receipt stage_id '$($Receipt.stage_id)' does not match '$ExpectedStageId'."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedVmId) -and ([string]$Receipt.vm_id).ToLowerInvariant() -ne $ExpectedVmId.ToLowerInvariant()) {
        throw "Receipt vm_id '$($Receipt.vm_id)' does not match '$ExpectedVmId'."
    }
    return $true
}

function Test-VmLabCapabilityAuthorized {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Capability,
        [switch]$Apply,
        [switch]$AuthorizeHostMutation,
        [switch]$AuthorizeVmLifecycle,
        [switch]$AuthorizeGuestMutation,
        [switch]$AuthorizeGuestExec,
        [switch]$AuthorizeElevation
    )
    if ($Capability -eq 'none') {
        return $true
    }
    if (-not $Apply) {
        return $false
    }
    switch ($Capability) {
        'host_mutation'  { return [bool]$AuthorizeHostMutation }
        'vm_lifecycle'   { return [bool]$AuthorizeVmLifecycle }
        'guest_mutation' { return [bool]$AuthorizeGuestMutation }
        'guest_exec'     { return [bool]$AuthorizeGuestExec }
        'elevation'      { return [bool]$AuthorizeElevation }
        default          { return $false }
    }
}
