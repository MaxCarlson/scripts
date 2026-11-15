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

## WinError 206 status

Prior harmless native Windows probes reproduced error 206 with oversized command arguments and an overlong executable path. This demonstrates that both boundaries can produce the code; it does not identify the historical failing upgrade operation. The existing file-backed helper transport has offline tests proving large task XML stays out of the process command line. The actual RC upgrade orchestration has not been executed in an isolated Windows guest, so the historical issue is not declared fixed.
