<#
.SYNOPSIS
Safely fast-forward local Git repositories against their configured remote main branch.

.DESCRIPTION
Inspects each target Git repository, verifies branch, upstream, working-tree state
(distinguishing staged changes, tracked modifications, untracked files, and submodule
dirtiness), and divergence. Defaults to dry-run preview without mutating Git refs or
working trees. In -Apply mode, fetches current remote refs and runs `git merge --ff-only`
when on main and not ahead/diverged, letting Git preserve compatible local/untracked
changes and stopping safely if Git reports an overwrite conflict.
#>
[CmdletBinding()]
param(
    [Parameter()]
    [Alias('r')]
    [string]$Root = (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'src'),

    [Parameter()]
    [Alias('p')]
    [string[]]$Repos,

    [Parameter()]
    [Alias('c')]
    [string]$ConfigPath,

    [Parameter()]
    [Alias('n')]
    [switch]$DryRun,

    [Parameter()]
    [Alias('a')]
    [switch]$Apply,

    [Parameter()]
    [Alias('j')]
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$DefaultRepos = @('scripts', 'llm-agent-toolkit', 'shared-python-modules')

function Invoke-Git {
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string[]]$Args
    )

    $output = & git -C $RepoPath @Args 2>&1
    $exitCode = $LASTEXITCODE
    $lines = @()
    if ($null -ne $output) {
        $lines = @($output | ForEach-Object { $_.ToString() })
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = ($lines -join "`n").Trim()
        Lines    = $lines
    }
}

function Get-SubmodulePaths {
    param([Parameter(Mandatory)][string]$RepoPath)

    $paths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $gitmodules = Join-Path $RepoPath '.gitmodules'
    if (-not (Test-Path -LiteralPath $gitmodules -PathType Leaf)) {
        return ,$paths
    }
    $res = Invoke-Git -RepoPath $RepoPath -Args @('config', '--file', '.gitmodules', '--get-regexp', '^submodule\..*\.path$')
    if ($res.ExitCode -eq 0) {
        foreach ($line in $res.Lines) {
            $parts = $line -split '\s+', 2
            if ($parts.Count -eq 2 -and -not [string]::IsNullOrWhiteSpace($parts[1])) {
                [void]$paths.Add($parts[1].Trim().TrimEnd('/'))
            }
        }
    }
    return ,$paths
}

function Get-WorkingTreeClassification {
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$StatusLines
    )

    $subPaths = Get-SubmodulePaths -RepoPath $RepoPath
    $staged = [System.Collections.Generic.List[string]]::new()
    $trackedMod = [System.Collections.Generic.List[string]]::new()
    $untracked = [System.Collections.Generic.List[string]]::new()
    $subDirty = [System.Collections.Generic.List[string]]::new()

    foreach ($line in $StatusLines) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.Length -lt 4) {
            continue
        }
        $xy = $line.Substring(0, 2)
        $pathPart = $line.Substring(3).Trim().TrimEnd('/')
        if ($pathPart -match ' -> (.+)$') {
            $pathPart = $Matches[1].Trim().TrimEnd('/')
        }

        if ($xy -eq '??') {
            [void]$untracked.Add($pathPart)
            continue
        }
        if ($subPaths.Contains($pathPart)) {
            [void]$subDirty.Add($pathPart)
            continue
        }
        $x = $xy[0]
        $y = $xy[1]
        if ($x -ne ' ' -and $x -ne '?') {
            [void]$staged.Add($pathPart)
        }
        if ($y -ne ' ' -and $y -ne '?') {
            [void]$trackedMod.Add($pathPart)
        }
    }

    return [pscustomobject]@{
        Staged           = @($staged)
        TrackedModified  = @($trackedMod)
        Untracked        = @($untracked)
        SubmoduleDirty   = @($subDirty)
        IsClean          = ($StatusLines.Count -eq 0)
    }
}

function Resolve-TargetRepos {
    param(
        [string]$BaseRoot,
        [string[]]$ExplicitRepos,
        [string]$ConfigFile
    )

    $specs = [System.Collections.Generic.List[string]]::new()
    if ($ExplicitRepos -and $ExplicitRepos.Count -gt 0) {
        foreach ($item in $ExplicitRepos) {
            foreach ($part in ($item -split ',')) {
                if (-not [string]::IsNullOrWhiteSpace($part)) {
                    [void]$specs.Add($part.Trim())
                }
            }
        }
    } elseif (-not [string]::IsNullOrWhiteSpace($ConfigFile)) {
        if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) {
            throw "Configuration file not found: $ConfigFile"
        }
        $raw = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $configured = if ($raw -is [System.Array]) { $raw } elseif ($null -ne $raw.repos) { $raw.repos } else { @() }
        foreach ($item in $configured) {
            if (-not [string]::IsNullOrWhiteSpace([string]$item)) {
                [void]$specs.Add(([string]$item).Trim())
            }
        }
    } else {
        foreach ($item in $DefaultRepos) {
            [void]$specs.Add($item)
        }
    }

    $resolved = [System.Collections.Generic.List[object]]::new()
    foreach ($spec in $specs) {
        $candidatePath = if ([System.IO.Path]::IsPathRooted($spec)) {
            $spec
        } else {
            Join-Path $BaseRoot $spec
        }
        $name = Split-Path -Path $candidatePath -Leaf
        [void]$resolved.Add([pscustomobject]@{
            Name = $name
            Path = $candidatePath
        })
    }
    return $resolved
}

function Sync-SingleRepo {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][bool]$IsApply
    )

    $modeLabel = if ($IsApply) { 'apply' } else { 'dry-run' }
    $baseResult = [ordered]@{
        name                  = $Name
        path                  = $RepoPath
        mode                  = $modeLabel
        status                = 'failed'
        reason                = ''
        branch                = $null
        upstream              = $null
        is_clean              = $false
        is_worktree           = $false
        ahead                 = $null
        behind                = $null
        head_before           = $null
        head_after            = $null
        staged_changes        = @()
        tracked_modifications = @()
        untracked_files       = @()
        submodule_changes     = @()
        dirty_entries         = @()
        remaining_changes     = @()
    }

    if (-not (Test-Path -LiteralPath $RepoPath -PathType Container)) {
        $baseResult.reason = 'missing_directory'
        return [pscustomobject]$baseResult
    }

    $normalizedInput = ([System.IO.Path]::GetFullPath($RepoPath)).TrimEnd('\', '/')
    if ($normalizedInput -match '(?i)[\\/]scripts[\\/]pscripts$') {
        $baseResult.status = 'skipped'
        $baseResult.reason = 'submodule_controlled_by_parent'
        return [pscustomobject]$baseResult
    }

    $inside = Invoke-Git -RepoPath $RepoPath -Args @('rev-parse', '--is-inside-work-tree')
    if ($inside.ExitCode -ne 0 -or $inside.Output -ne 'true') {
        $baseResult.reason = 'invalid_git_repository'
        return [pscustomobject]$baseResult
    }

    $top = Invoke-Git -RepoPath $RepoPath -Args @('rev-parse', '--show-toplevel')
    if ($top.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($top.Output)) {
        $baseResult.reason = 'git_toplevel_error'
        return [pscustomobject]$baseResult
    }
    $normalizedTop = ([System.IO.Path]::GetFullPath($top.Output)).TrimEnd('\', '/')
    if (-not [string]::Equals($normalizedInput, $normalizedTop, [System.StringComparison]::OrdinalIgnoreCase)) {
        $baseResult.reason = 'not_repository_root'
        return [pscustomobject]$baseResult
    }

    $gitDir = Invoke-Git -RepoPath $RepoPath -Args @('rev-parse', '--git-dir')
    $commonDir = Invoke-Git -RepoPath $RepoPath -Args @('rev-parse', '--git-common-dir')
    if ($gitDir.ExitCode -eq 0 -and $commonDir.ExitCode -eq 0) {
        $gdFull = [System.IO.Path]::GetFullPath((Join-Path $RepoPath $gitDir.Output))
        $cdFull = [System.IO.Path]::GetFullPath((Join-Path $RepoPath $commonDir.Output))
        $baseResult.is_worktree = -not [string]::Equals($gdFull, $cdFull, [System.StringComparison]::OrdinalIgnoreCase)
    }

    $headBefore = Invoke-Git -RepoPath $RepoPath -Args @('rev-parse', 'HEAD')
    if ($headBefore.ExitCode -ne 0) {
        $baseResult.reason = 'unborn_or_invalid_head'
        return [pscustomobject]$baseResult
    }
    $baseResult.head_before = $headBefore.Output
    $baseResult.head_after = $headBefore.Output

    $branchRes = Invoke-Git -RepoPath $RepoPath -Args @('symbolic-ref', '--quiet', '--short', 'HEAD')
    if ($branchRes.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($branchRes.Output)) {
        $baseResult.branch = 'DETACHED'
    } else {
        $baseResult.branch = $branchRes.Output
    }

    $statusRes = Invoke-Git -RepoPath $RepoPath -Args @('status', '--porcelain=v1')
    if ($statusRes.ExitCode -ne 0) {
        $baseResult.reason = 'git_status_error'
        return [pscustomobject]$baseResult
    }
    $dirtyLines = @($statusRes.Lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $wtClass = Get-WorkingTreeClassification -RepoPath $RepoPath -StatusLines $dirtyLines
    $baseResult.dirty_entries = $dirtyLines
    $baseResult.remaining_changes = $dirtyLines
    $baseResult.staged_changes = $wtClass.Staged
    $baseResult.tracked_modifications = $wtClass.TrackedModified
    $baseResult.untracked_files = $wtClass.Untracked
    $baseResult.submodule_changes = $wtClass.SubmoduleDirty
    $baseResult.is_clean = $wtClass.IsClean

    if ($baseResult.branch -eq 'DETACHED') {
        $baseResult.status = 'skipped'
        $baseResult.reason = 'detached_head'
        return [pscustomobject]$baseResult
    }

    if ($baseResult.branch -ne 'main') {
        $baseResult.status = 'skipped'
        $baseResult.reason = "not_on_main ($($baseResult.branch))"
        return [pscustomobject]$baseResult
    }

    $upstreamRes = Invoke-Git -RepoPath $RepoPath -Args @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
    if ($upstreamRes.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($upstreamRes.Output)) {
        $originUrl = Invoke-Git -RepoPath $RepoPath -Args @('remote', 'get-url', 'origin')
        if ($originUrl.ExitCode -ne 0) {
            $baseResult.status = 'failed'
            $baseResult.reason = 'missing_remote'
        } else {
            $baseResult.status = 'skipped'
            $baseResult.reason = 'missing_upstream'
        }
        return [pscustomobject]$baseResult
    }

    $upstream = $upstreamRes.Output
    $baseResult.upstream = $upstream
    $remoteName = ($upstream -split '/', 2)[0]
    $remoteBranch = ($upstream -split '/', 2)[1]
    if ($remoteBranch -ne 'main') {
        $baseResult.status = 'skipped'
        $baseResult.reason = "upstream_not_main ($upstream)"
        return [pscustomobject]$baseResult
    }

    $remoteCheck = Invoke-Git -RepoPath $RepoPath -Args @('remote', 'get-url', $remoteName)
    if ($remoteCheck.ExitCode -ne 0) {
        $baseResult.status = 'failed'
        $baseResult.reason = "missing_remote ($remoteName)"
        return [pscustomobject]$baseResult
    }

    if ($IsApply) {
        $fetchRes = Invoke-Git -RepoPath $RepoPath -Args @('fetch', '--no-tags', $remoteName)
        if ($fetchRes.ExitCode -ne 0) {
            $baseResult.status = 'failed'
            $baseResult.reason = "fetch_failed: $($fetchRes.Output)"
            return [pscustomobject]$baseResult
        }
    }

    $countsRes = Invoke-Git -RepoPath $RepoPath -Args @('rev-list', '--left-right', '--count', "HEAD...$upstream")
    if ($countsRes.ExitCode -ne 0) {
        $baseResult.status = 'failed'
        $baseResult.reason = "rev_list_failed: $($countsRes.Output)"
        return [pscustomobject]$baseResult
    }
    $parts = $countsRes.Output -split '\s+'
    if ($parts.Count -lt 2) {
        $baseResult.status = 'failed'
        $baseResult.reason = "unexpected_rev_list_output: $($countsRes.Output)"
        return [pscustomobject]$baseResult
    }
    $ahead = [int]$parts[0]
    $behind = [int]$parts[1]
    $baseResult.ahead = $ahead
    $baseResult.behind = $behind

    if ($ahead -eq 0 -and $behind -eq 0) {
        $baseResult.status = 'already_current'
        $baseResult.reason = if ($baseResult.is_clean) { 'up_to_date' } else { 'up_to_date_with_local_changes' }
        return [pscustomobject]$baseResult
    }

    if ($ahead -gt 0 -and $behind -eq 0) {
        $baseResult.status = 'skipped'
        $baseResult.reason = 'local_commits_ahead'
        return [pscustomobject]$baseResult
    }

    if ($ahead -gt 0 -and $behind -gt 0) {
        $baseResult.status = 'skipped'
        $baseResult.reason = 'diverged_histories'
        return [pscustomobject]$baseResult
    }

    # ahead == 0 and behind > 0
    if (-not $IsApply) {
        if ($baseResult.is_clean) {
            $baseResult.status = 'would_fast_forward'
            $baseResult.reason = "behind_by_${behind}_confirmed_clean"
        } else {
            $baseResult.status = 'would_fast_forward_with_local_changes'
            $baseResult.reason = "behind_by_${behind}_requires_git_ff_safety_check"
        }
        return [pscustomobject]$baseResult
    }

    $mergeRes = Invoke-Git -RepoPath $RepoPath -Args @('merge', '--ff-only', $upstream)
    if ($mergeRes.ExitCode -ne 0) {
        $msg = $mergeRes.Output
        if ($msg -match 'would be overwritten by merge|Not possible to fast-forward') {
            $baseResult.status = 'skipped'
            $baseResult.reason = 'ff_blocked_by_local_changes'
        } else {
            $baseResult.status = 'failed'
            $baseResult.reason = "ff_merge_failed: $msg"
        }
        return [pscustomobject]$baseResult
    }

    $headAfter = Invoke-Git -RepoPath $RepoPath -Args @('rev-parse', 'HEAD')
    $branchAfter = Invoke-Git -RepoPath $RepoPath -Args @('symbolic-ref', '--quiet', '--short', 'HEAD')
    $statusAfter = Invoke-Git -RepoPath $RepoPath -Args @('status', '--porcelain=v1')
    $remaining = @($statusAfter.Lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $baseResult.head_after = $headAfter.Output
    $baseResult.remaining_changes = $remaining
    if ($headAfter.ExitCode -ne 0 -or $branchAfter.Output -ne 'main') {
        $baseResult.status = 'failed'
        $baseResult.reason = 'post_merge_verification_failed'
        return [pscustomobject]$baseResult
    }

    $baseResult.status = 'updated'
    $baseResult.reason = if ($remaining.Count -eq 0) {
        "fast_forwarded_$behind"
    } else {
        "fast_forwarded_${behind}_preserved_local_changes"
    }
    return [pscustomobject]$baseResult
}

$isApply = [bool]($Apply.IsPresent -and -not $DryRun.IsPresent)
$targets = Resolve-TargetRepos -BaseRoot $Root -ExplicitRepos $Repos -ConfigFile $ConfigPath
$results = [System.Collections.Generic.List[object]]::new()

foreach ($target in $targets) {
    $res = Sync-SingleRepo -Name $target.Name -RepoPath $target.Path -IsApply $isApply
    [void]$results.Add($res)
}

$failedCount = @($results | Where-Object { $_.status -eq 'failed' }).Count
$summary = [ordered]@{
    mode            = if ($isApply) { 'apply' } else { 'dry-run' }
    root            = $Root
    total           = $results.Count
    updated         = @($results | Where-Object { $_.status -eq 'updated' }).Count
    already_current = @($results | Where-Object { $_.status -eq 'already_current' }).Count
    would_update    = @($results | Where-Object { $_.status -in @('would_fast_forward', 'would_fast_forward_with_local_changes') }).Count
    skipped         = @($results | Where-Object { $_.status -eq 'skipped' }).Count
    failed          = $failedCount
    repositories    = $results
}

if ($Json.IsPresent) {
    $summary | ConvertTo-Json -Depth 6
} else {
    Write-Output ("[{0}] root={1} total={2} updated={3} current={4} would_ff={5} skipped={6} failed={7}" -f `
        $summary.mode.ToUpperInvariant(), $summary.root, $summary.total, $summary.updated, `
        $summary.already_current, $summary.would_update, $summary.skipped, $summary.failed)
    foreach ($r in $results) {
        $branchText = if ($r.branch) { $r.branch } else { '-' }
        Write-Output ("  - {0,-24} status={1,-36} branch={2,-10} reason={3}" -f $r.name, $r.status, $branchText, $r.reason)
    }
}

if ($failedCount -gt 0) {
    exit 1
}
exit 0
