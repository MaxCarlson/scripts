# Shared helpers for locating the repos that power the customization stack.
# Every setup entry point (admin, non-admin, env bootstrap) uses these
# functions so the environment variables are consistent across machines.

function Get-NormalizedPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    try {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        return $item.FullName.TrimEnd('\', '/')
    } catch {
        return $null
    }
}

function Get-RepoCandidates {
    param(
        [Parameter(Mandatory = $true)][string]$RepoName,
        [string]$AnchorPath,
        [string[]]$EnvValues
    )

    $candidates = [System.Collections.Generic.List[string]]::new()

    foreach ($value in $EnvValues) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            [void]$candidates.Add($value)
        }
    }

    $anchorNormalized = Get-NormalizedPath -Path $AnchorPath
    if ($anchorNormalized) {
        $anchorParent = Split-Path -Path $anchorNormalized -Parent
        if ($anchorParent) {
            [void]$candidates.Add((Join-Path $anchorParent $RepoName))
            $anchorGrandParent = Split-Path -Path $anchorParent -Parent
            if ($anchorGrandParent) {
                [void]$candidates.Add((Join-Path $anchorGrandParent $RepoName))
            }
        }
    }

    $homeDir = [Environment]::GetFolderPath('UserProfile')
    if ($homeDir) {
        [void]$candidates.Add((Join-Path $homeDir $RepoName))
        foreach ($sub in 'Repos', 'src', 'projects') {
            [void]$candidates.Add((Join-Path (Join-Path $homeDir $sub) $RepoName))
        }
    }

    return $candidates
}

function Resolve-RepoPath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoName,
        [string]$AnchorPath,
        [string[]]$EnvValues = @()
    )

    $candidates = Get-RepoCandidates -RepoName $RepoName -AnchorPath $AnchorPath -EnvValues $EnvValues
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($candidate in $candidates) {
        $normalized = Get-NormalizedPath -Path $candidate
        if ($normalized -and $seen.Add($normalized)) {
            return $normalized
        }
    }

    $anchorNormalized = Get-NormalizedPath -Path $AnchorPath
    if (-not $anchorNormalized) {
        return $null
    }

    $driveRoot = [System.IO.Path]::GetPathRoot($anchorNormalized)
    if (-not $driveRoot) {
        return $null
    }

    try {
        $match = Get-ChildItem -LiteralPath $driveRoot -Directory -Filter $RepoName -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ieq $RepoName } |
            Select-Object -First 1
        return $match.FullName
    } catch {
        Write-Verbose ("Failed repo search for {0}: {1}" -f $RepoName, $_)
        return $null
    }
}

function Resolve-RepoEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$AnchorPath,
        [ValidateSet('W11-powershell', 'scripts', 'dotfiles')]
        [string]$AnchorRepoName = 'W11-powershell'
    )

    $anchorNormalized = Get-NormalizedPath -Path $AnchorPath
    if (-not $anchorNormalized) {
        throw "Anchor path '$AnchorPath' could not be resolved."
    }

    $thisRepo = $AnchorRepoName

    $w11Repo = if ($thisRepo -eq 'W11-powershell') {
        $anchorNormalized
    } else {
        Resolve-RepoPath -RepoName 'W11-powershell' -AnchorPath $anchorNormalized -EnvValues @($env:PWSH_REPO, $env:W11_ROOT)
    }

    $scriptsRepo = if ($thisRepo -eq 'scripts') {
        $anchorNormalized
    } else {
        Resolve-RepoPath -RepoName 'scripts' -AnchorPath $anchorNormalized -EnvValues @($env:SCRIPTS_REPO, $env:SCRIPTS)
    }

    $dotfilesRepo = if ($thisRepo -eq 'dotfiles') {
        $anchorNormalized
    } else {
        Resolve-RepoPath -RepoName 'dotfiles' -AnchorPath $anchorNormalized -EnvValues @($env:DOTFILES_REPO, $env:DOTFILES, $env:DOTFILES_PATH)
    }

    $pscripts = $null
    if ($scriptsRepo) {
        $candidate = Join-Path $scriptsRepo 'pscripts'
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            $pscripts = $candidate
        }
    }

    $ytdlp = $null
    if ($pscripts) {
        $ytdlpCandidate = Join-Path $pscripts 'video\yt_dlp\ytdlp.ps1'
        if (Test-Path -LiteralPath $ytdlpCandidate -PathType Leaf) {
            $ytdlp = $ytdlpCandidate
        }
    }

    $projects = $null
    foreach ($base in @($w11Repo, $scriptsRepo, $dotfilesRepo)) {
        if ($base) {
            $parent = Split-Path -Path $base -Parent
            if ($parent -and (Test-Path -LiteralPath $parent -PathType Container)) {
                $projects = $parent
                break
            }
        }
    }

    return [ordered]@{
        PWSH_REPO     = $w11Repo
        W11_ROOT      = $w11Repo
        SCRIPTS_REPO  = $scriptsRepo
        SCRIPTS       = $scriptsRepo
        PSCRIPTS      = $pscripts
        DOTFILES_REPO = $dotfilesRepo
        DOTFILES      = $dotfilesRepo
        DOTFILES_PATH = $dotfilesRepo
        PROJECTS      = $projects
        YTDLP_PATH    = $ytdlp
    }
}

function Set-RepoEnvironmentVariables {
    param(
        [Parameter(Mandatory = $true)][hashtable]$PathMap,
        [ValidateSet('User', 'Machine')][string[]]$PersistScopes = @('User')
    )

    foreach ($entry in $PathMap.GetEnumerator()) {
        $name  = $entry.Key
        $value = $entry.Value
        if ([string]::IsNullOrWhiteSpace($value)) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
            foreach ($scope in $PersistScopes) {
                [Environment]::SetEnvironmentVariable($name, $null, $scope)
            }
            Write-Host "[env:clear] $name (path not found)" -ForegroundColor DarkGray
        } else {
            Set-Item -Path "Env:$name" -Value $value
            foreach ($scope in $PersistScopes) {
                [Environment]::SetEnvironmentVariable($name, $value, $scope)
            }
            Write-Host "[env] $name => $value" -ForegroundColor Green
        }
    }
}

function Initialize-RepoEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$AnchorPath,
        [ValidateSet('W11-powershell', 'scripts', 'dotfiles')]
        [string]$AnchorRepoName = 'W11-powershell',
        [ValidateSet('User', 'Machine')][string[]]$PersistScopes = @('User')
    )

    $map = Resolve-RepoEnvironment -AnchorPath $AnchorPath -AnchorRepoName $AnchorRepoName
    Set-RepoEnvironmentVariables -PathMap $map -PersistScopes $PersistScopes
    return $map
}

