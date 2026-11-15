[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$MiningRoot,
    [Parameter(Mandatory)][string]$RcRepo,
    [Parameter(Mandatory)][string]$ExpectedRcCommit,
    [Parameter(Mandatory)][string]$PythonExe,
    [Parameter(Mandatory)][string]$RcPythonSitePackages
)

# Review-only adapter for Mining's unchanged H3 tests. It points those tests at
# the selected RC review commit and overrides only h3_support.RC_COMMIT in memory.
# The original Mining harness and its pinned H3 evidence remain untouched.
$ErrorActionPreference = 'Stop'
$MiningRoot = (Resolve-Path -LiteralPath $MiningRoot).Path
$RcRepo = (Resolve-Path -LiteralPath $RcRepo).Path
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
$RcPythonSitePackages = (Resolve-Path -LiteralPath $RcPythonSitePackages).Path

$MiningPinned = 'deea3e019b35615f4d95e6f510450f7f392fb82a'
$MiningHead = (& git -C $MiningRoot rev-parse HEAD).Trim()
$RcHead = (& git -C $RcRepo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $MiningHead -ne $MiningPinned) {
    throw "Combined H3 review requires Mining $MiningPinned, found $MiningHead"
}
if ($RcHead -ne $ExpectedRcCommit) {
    throw "Expected RC review commit $ExpectedRcCommit, found $RcHead"
}
foreach ($repo in @($MiningRoot, $RcRepo)) {
    $dirty = @(& git -C $repo -c submodule.recurse=false status --porcelain --untracked-files=all --ignore-submodules=all)
    if ($dirty.Count -gt 0) { throw "Selected source tree is dirty: $repo" }
}

$MiningH2d = '4787f9bac06d811ca82a8a3752a61c69f181aafb'
& git -C $MiningRoot merge-base --is-ancestor $MiningH2d HEAD
if ($LASTEXITCODE -ne 0) { throw "Mining HEAD is not based on H2D $MiningH2d" }

$RcSource = Join-Path $RcRepo 'modules\resource_coordinator'
$MiningTests = Join-Path $MiningRoot 'tests\h3'
$Artifacts = Join-Path (Join-Path $env:LOCALAPPDATA 'Temp') ('rc-part23-h3-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $Artifacts)
$env:H3_RC_REPO = $RcRepo
$env:H3_RC_SOURCE = $RcSource
$env:H3_RC_EXPECTED_COMMIT = $ExpectedRcCommit
$env:H3_RC_SITE_PACKAGES = $RcPythonSitePackages
$env:H3_MINING_ROOT = $MiningRoot
$env:H3_TESTS = $MiningTests
$env:H3_BASETEMP = Join-Path $Artifacts 'pytest-temp'
$env:H3_JUNIT = Join-Path $Artifacts 'junit.xml'
$env:PYTHONPATH = "$RcSource;$MiningRoot;$(Join-Path $MiningRoot 'modules\program_optimizer');$MiningTests"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'

$PythonCode = @'
import importlib, importlib.util, os, pathlib, site, sys, pytest
site.addsitedir(os.environ['H3_RC_SITE_PACKAGES'])
root = pathlib.Path(os.environ['H3_MINING_ROOT']).resolve()
rc_repo = pathlib.Path(os.environ['H3_RC_REPO']).resolve()
rc_source = pathlib.Path(os.environ['H3_RC_SOURCE']).resolve()
tests = pathlib.Path(os.environ['H3_TESTS']).resolve()
sys.path[:0] = [str(rc_source), str(root), str(root / 'modules' / 'program_optimizer'), str(tests)]
spec = importlib.util.spec_from_file_location('h3_support', tests / 'h3_support.py')
if spec is None or spec.loader is None:
    raise RuntimeError('Could not load read-only Mining H3 support module')
h3_support = importlib.util.module_from_spec(spec)
sys.modules['h3_support'] = h3_support
spec.loader.exec_module(h3_support)
h3_support.RC_COMMIT = os.environ['H3_RC_EXPECTED_COMMIT']
rc = importlib.import_module('resource_coordinator')
mining = importlib.import_module('mining_optimizer')
assert rc_source in pathlib.Path(rc.__file__).resolve().parents, rc.__file__
assert root in pathlib.Path(mining.__file__).resolve().parents, mining.__file__
assert rc_source == (rc_repo / 'modules' / 'resource_coordinator').resolve()
raise SystemExit(pytest.main([
    '-c', str(tests / 'pytest.ini'), '--rootdir', str(root),
    '--basetemp', os.environ['H3_BASETEMP'], '--junitxml', os.environ['H3_JUNIT'],
    '-W', 'ignore::pytest.PytestUnknownMarkWarning', '-q', str(tests),
]))
'@

Push-Location $MiningRoot
try { & $PythonExe -c $PythonCode; $PytestExit = $LASTEXITCODE } finally { Pop-Location }
if (-not (Test-Path -LiteralPath $env:H3_JUNIT)) { throw "No JUnit report; pytest exit $PytestExit" }
[xml]$Report = [IO.File]::ReadAllText($env:H3_JUNIT)
$Cases = @($Report.SelectNodes('//testcase'))
$Counts = [ordered]@{
    total = $Cases.Count
    passed = @($Cases | Where-Object { -not $_.SelectSingleNode('failure') -and -not $_.SelectSingleNode('error') -and -not $_.SelectSingleNode('skipped') }).Count
    failed = @($Cases | Where-Object { $_.SelectSingleNode('failure') }).Count
    errors = @($Cases | Where-Object { $_.SelectSingleNode('error') }).Count
    skipped = @($Cases | Where-Object { $_.SelectSingleNode('skipped') }).Count
}
$Summary = [ordered]@{
    schema_version = 1
    mining_commit = $MiningHead
    rc_commit = $RcHead
    exit_code = $PytestExit
    counts = $Counts
    junit_path = $env:H3_JUNIT
}
$Summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Artifacts 'summary.json') -Encoding utf8
Write-Output "H3_REVIEW_ARTIFACTS=$Artifacts"
Write-Output "H3_REVIEW_SUMMARY=$(Join-Path $Artifacts 'summary.json')"
exit $PytestExit
