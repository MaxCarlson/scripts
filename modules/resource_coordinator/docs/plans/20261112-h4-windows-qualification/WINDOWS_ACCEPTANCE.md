# H4 Windows Acceptance Harness and Procedure

## Harness

`modules/resource_coordinator/tools/h4_qualification/windows_acceptance.py` is a fail-closed runner. It uses an explicitly created, absolute `h4-rc-*` artifact directory. Default execution performs only preflight and writes bounded JSON artifacts. It never falls back to the source host when guest verification fails.

The `offline` profile runs mock-backed installation regressions and the protected-file helper transport test. The `task` profile creates one random `RC-Disposable-*` Scheduled Task, exports a transient in-memory snapshot, changes/restores its harmless `cmd.exe /d /c exit 0` action, disables it, and verifies exact deletion. Both the runner and the task test independently inspect WMI guest identity plus task, service, and process inventories. Unknown inventory, a detected RC task/service/miner/coordinator process, a non-guest host, a symlinked test path, or an unrecognized artifact blocks the task profile. The task profile also requires the exact explicit authorization phrase documented by the runner. A post-creation inventory failure is a failed test, not a permission skip. It does not invoke RC setup/upgrade or use production config/credentials.

Artifacts include `environment.json`, `preflight.json`, `test-results.json`, timestamped `junit-*.xml`, `pytest-output.log`, `upgrade-receipts/`, `task-snapshots/`, `cleanup-manifest.json`, `process-identity.json`, `rollback-result.json`, and `cleanup-result.json`. Task snapshots are reduced summaries; task XML and credentials are not retained. A failed task cleanup fails the test and remains recorded for operator review.

Example PowerShell 7 usage (run only in a separately authorized guest):

```powershell
$module = 'C:\path\to\scripts\modules\resource_coordinator'
$run = Join-Path $env:TEMP ('h4-rc-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run | Out-Null
Set-Location $module
python tools\h4_qualification\windows_acceptance.py --test-root $run

# Offline/mock-backed profile; this does not mutate tasks or processes.
python tools\h4_qualification\windows_acceptance.py --test-root $run --apply --profile offline `
  --json

# Task Scheduler mutation: only after independently verifying this is the
# approved disposable guest and authorizing this specific operation.
python tools\h4_qualification\windows_acceptance.py --test-root $run --apply --profile task `
  --authorization 'I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION'
```

The current host preflight is not eligible for the `task` profile. The explicit phrase is not guest proof; WMI and inventory checks remain mandatory.

## Full installation, upgrade, fault, and rollback matrix

The source currently has safe mock-backed setup/upgrade/rollback tests and an opt-in real task/helper test. The task runner intentionally does not synthesize a production installation through `ManagedInstallation`: that class owns fixed RC task names, global credential lookup, service status, and runtime activation paths, so a caller-selected temporary config alone is not sufficient isolation. The actual fresh-install/upgrade/rollback sequence therefore remains pending a dedicated guest test account and a scoped launcher/config seam. Do not run `rc system setup --apply` or `rc system upgrade --apply` against the primary host.

In the authorized VM, take a clean checkpoint, use a dedicated guest account and test-only package copies, set an isolated config/state/credential root, and use no miner executable or upstream model service. Capture the installed distribution and source revision before and after. Exercise setup, v1.0.0 upgrade, receipt/task snapshot, task replacement, process identity/readiness, every interruption boundary, legacy journal export/parser load, old launcher/task restoration, and blocked rollback. At each failure, retain the receipt and prove the old and new launchers cannot both own the journal. Cleanup only task/process/path identities recorded by the run manifest; restore the VM checkpoint if scoped cleanup cannot be proven.

## H4.5 guest-only installation lifecycle profiles

The 2026-11-12 H4 implementation did not call the real mutating `ManagedInstallation` lifecycle because production task names, global credentials, fixed listener identity, and host process/task discovery were not isolated. H4.5 adds a guarded `InstallationRuntime`, isolated installation paths, and test-scoped task/helper/credential dependencies. That source-level seam does not establish Windows operational acceptance. Do not run `rc system setup --apply` or `rc system upgrade --apply` against the primary host.

The runner now recognizes `install`, `upgrade`, `rollback`, `full`, and `cleanup`. All are read-only preflight unless `--apply` is supplied. A mutating run additionally requires `--authorize-guest-mutation`, the exact phrase below, `RC_H4_DISPOSABLE_GUEST_AUTHORIZED` set to that phrase, WMI-confirmed virtual hardware, readable task/service/process inventories, no unrelated RC installation, and a fresh exact-resource guard before each installer mutation. The phrase authorizes one scoped guest run; it does not prove the environment is disposable or owned.

The runner expects two separately staged source trees: current RC `1.0.0` and legacy RC `0.14.0`. The tree hashes are recorded before execution; the old and new roots must differ, package versions must match, and reparse points under module source are rejected. `upgrade` and `rollback` require `--old-source-root`. `rollback` injects a test failure at a selected supported checkpoint and requires the installer to report a verified rollback. `full` runs fresh setup, upgrade, and the rollback exercise in separate phase roots and verifies exact task, listener, and process cleanup after each phase. Before installer mutations, the guard also checks that the phase's non-production loopback port is unbound or owned by the exact recorded test process (PID, creation time, and executable path). Failure retains the run manifest and requires inspection before the separate `cleanup` profile is used.

PowerShell 7 command shape (run only inside a separately authorized disposable guest; the variables must point to staged source copies and a new guest-local root):

```powershell
$module = 'C:\h4-source\current\modules\resource_coordinator'
$source = 'C:\h4-source\current'
$oldSource = 'C:\h4-source\rc-0.14.0'
$run = Join-Path $env:TEMP ('h4-rc-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run | Out-Null
Set-Location $module
python tools\h4_qualification\windows_acceptance.py --test-root $run --json

# Only after the guest owner separately authorizes these guest mutations:
$env:RC_H4_DISPOSABLE_GUEST_AUTHORIZED = 'I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION'
python tools\h4_qualification\windows_acceptance.py --test-root $run --apply --profile full `
  --authorization 'I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION' --authorize-guest-mutation `
  --source-root $source --old-source-root $oldSource --timeout-seconds 900 --json

# After interruption, re-run preflight and inspect the manifest before scoped cleanup:
python tools\h4_qualification\windows_acceptance.py --test-root $run --apply --profile cleanup `
  --authorization 'I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION' --authorize-guest-mutation `
  --source-root $source --json
```

The `--fault-stage` option can target `after_prepared_receipt`, `after_old_service_stopped`, `before_task_replacement`, `after_task_replacement`, or `after_new_service_ready`. The `rollback` and `full` profiles exercise the selected point in an isolated source-backed lifecycle and require a verified rollback result. These fault points are implemented but have not been exercised against actual Task Scheduler/service state. No H4.5 guest lifecycle profile has been executed; Task Scheduler/UAC/service/upgrade/rollback remains `NOT_TESTED` until the named guest and mutation permission are recorded.

The latest H4.5 focused combined regression passed 134 tests with 3 opt-in Windows task tests skipped. Ruff, compilation, and `git diff --check` passed on the changed Python paths. An earlier environment attempt failed to load `_ssl`/`_ctypes`; that result is historical and superseded for the focused installer/runner suites by the later successful run. WDDM tests were not repeated. Refer to `STATUS.md` for exact commands and outcomes.

## WinError 206 status

Prior harmless native Windows probes reproduced error 206 with oversized command arguments and an overlong executable path. This demonstrates that both boundaries can produce the code; it does not identify the historical failing upgrade operation. The existing file-backed helper transport has offline tests proving large task XML stays out of the process command line. The actual RC upgrade orchestration has not been executed in an isolated Windows guest, so the historical issue is not declared fixed.

## Reproducible guest bundle and staging (H4.6 / H4.7)

Source integrity uses `tools/h4_qualification/source_integrity.py` (`rc-h4-tree-sha256-v2`): canonical sorted POSIX relative paths, explicit exclusion of `.git`/`__pycache__`/`.pytest_cache`/`.pytest_tmp_*`/`*.pyc`/`*.pyo`, explicit empty-directory entries, reparse-point/symlink rejection, and Unicode/case collision checks.

Build and verify a portable guest bundle (`h4-windows-acceptance.zip`) from immutable Git commits into an ignored destination:

```powershell
$module = 'C:\path\to\scripts\modules\resource_coordinator'
$env:PYTHONPATH = $module
$out = Join-Path $module '.pytest_tmp_root\h4-release-bundle'
python tools\h4_qualification\bundle_builder.py -o $out -a -j
```

Inside the authorized disposable guest (after taking a standard Hyper-V checkpoint), extract `h4-windows-acceptance.zip` and run the read-only preflight entry point:

```powershell
pwsh -File .\scripts\Verify-H4GuestBundle.ps1 -BundleRoot .
```

The bundle `manifest.json` sits outside `sources/rc-1.0.0/` and `sources/rc-0.14.0/` (non-self-referential) and is enforced via `--source-manifest` before any test or guest mutation. `resource-metrics==0.2.0` is staged in-bundle under `sources/rc-1.0.0/modules/resource_metrics`.
