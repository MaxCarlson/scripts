# vm_lab Python Migration & CLI Completion — Status

**Integrated Branch:** `main` (from `feature/vm-lab-cli-launchers-20261115`, feature worktree `C:\Users\mcarls\src\scripts\.worktrees\vm-lab-cli-launchers-20261115`)  
**Prior `main` Baseline SHA:** `8326eea05464541ec994503bc6212a21b48c68fe`  
**Integrated Feature Tip SHA:** `fec4ed8e59f4d2626a3547854a47ea3ed4a04dfa`  
**Authoritative Plan:** [pwshToModuleMasterPlan.md](pwshToModuleMasterPlan.md)  

## Baseline Validation (Phase 0)

- **Pester suite** (`Invoke-Pester -Script "...\modules\vm_lab\tests" -PassThru`): **60 Passed, 0 Failed, 0 Skipped** (exit `0`, mocked Hyper-V/PS-Direct boundaries).
- **Live Hyper-V**: `NOT_TESTED` (protected H4 VM `RC-H4-Windows-Acceptance` / `d8483f98-8884-4758-abd1-cd6107c83c03` untouched).

## Package Layout Decision

- Map Python package `vm_lab` to `modules/vm_lab` via setuptools `package-dir = { vm_lab = "." }` (matching `modules/system_manager`), preserving all PowerShell files (`Invoke-VmLab.ps1`, `Invoke-VmLabApprovedPlan.ps1`, `vm_lab.psd1`, `vm_lab.psm1`, `src/`, `templates/`, `examples/`) as package data without moving them.
- Console scripts in `pyproject.toml`:
  - `vm = "vm_lab.cli:main"`
  - `vm-lab = "vm_lab.cli:main"`

## Phase Progress

| Phase | State | Validated Commit | Summary |
|---|---|---|---|
| 0 — Baseline & Design | COMPLETED | `3a231cb6` | Baseline 60 Pester passed; package layout & compatibility inventory recorded |
| 1 — Real Python Package | COMPLETED | `749cc258` | `pyproject.toml`, `__init__.py`, `__main__.py`, `backend.py`, `results.py`, `exceptions.py`, `cli.py`; 11 pytest passed (including wheel build & isolated venv install) |
| 2 — Bootstrap & CLI Migration | COMPLETED | `07f1a9fa` | Full subcommands (`commands.py`), legacy `-o` compat, removed `launcher_generator.py` special case (`vm` & `vm-lab` discovered via `pyproject.toml`); 44 pytest passed |
| 3 — Host, Identity, Media & Boot | COMPLETED | `efe86c54` | `src/HostBoot.ps1` (`Resolve-VmLabTargetVm`, `Test-VmLabIsoMedia`, `Set-VmLabBootMedia`, `Set-VmLabFirmwareBootOrder`, `Get-VmLabBootRecovery`) + `vm media iso`, `vm boot`, `vm host` |
| 4 — Guest Execution & Lifecycle | COMPLETED | `efe86c54` | `Get-VmLabGuestInventory`, `Invoke-VmLabGuestScript` (`3010` -> `REBOOT_REQUIRED`), `Restart-VmLabGuest`, `Get-VmLabCheckpointDetail` + `vm guest`, `vm restart`, `vm checkpoint inspect` |
| 5 — Workflow & Acceptance Semantics | COMPLETED | `efe86c54` | Honored `on_failure`, `timeout_seconds`, `idempotency_class`, `guest_identity`, `vm.connect` in `Contracts.ps1` & `WorkflowEngine.ps1` + `vm approval`, `vm workflow validate/results`, `vm evidence inspect` |
| 6 — Windows Setup & OOBE | COMPLETED | `efe86c54` | `vm setup plan/status/guide/answer-media` wired to `Get-VmLabSetupProgressReport` & `New-VmLabAnswerMediaStaging` (live OOBE `NOT_TESTED`) |
| 7 — Final Validation & Docs | COMPLETED | `fec4ed8e` | Artifact CLI `--source` + `--manifest`/`--destination` contract, internal `-Json` exit classification + human output without `-j`, `bootstrap_latest.run()` migration test (following `efe86c54`, `3ff58e18`); live Hyper-V `NOT_TESTED` |

## Integration & Activation (2026-11-15)

- **Source integration:** Fast-forward merged `feature/vm-lab-cli-launchers-20261115` (`fec4ed8e59f4d2626a3547854a47ea3ed4a04dfa`) into `main` (`8326eea0..fec4ed8e`) and pushed to `origin/main`.
- **Environment installation:** Installed editable `vm_lab` (`0.2.0`) into `C:\Users\mcarls\src\scripts\.venv` pointing to `C:\Users\mcarls\src\scripts\modules\vm_lab`.
- **Launcher bootstrap:** `bootstrap_latest.ps1` created `C:\Users\mcarls\src\scripts\bin\vm.cmd` and `C:\Users\mcarls\src\scripts\bin\vm-lab.cmd` (`0` failures; repeat run confirmed `0 missing launcher(s)`). `scripts_manifest.json` registers both `vm` and `vm-lab` (`console_script`, `module:vm_lab`).
- **Non-mutating CLI smoke verification:** `vm -h`, `vm-lab -h`, `vm version --json`, `vm-lab version --json`, `vm templates -j`, `vm doctor -j` (`attention_required` in non-elevated session), and `vm workflow validate modules/vm_lab/examples/h4-like-acceptance.workflow.json -j` (`PLANNED`) all exited `0`. `vm list -j` exited `1` with Hyper-V permission denied in the non-elevated agent shell.
- **Focused regression suite on `main`:** `pytest modules/vm_lab/tests/test_cli.py modules/script_logging/tests/test_launcher.py` passed (`95 passed`).
- **Real Hyper-V qualification:** `NOT_TESTED` (no VMs created, modified, started, stopped, or checkpointed; protected H4 VM untouched).

## Post-Integration Maintenance & Wizard Fix (2026-11-15)

- **Maintenance branch:** `fix/vm-lab-post-integration-20261115` (worktree `C:\Users\mcarls\src\scripts\.worktrees\vm-lab-post-integration-20261115`), fast-forward merged into `main` (`2e471cd2..18d4036d`) and pushed to `origin/main`.
- **Host resources & JSON contract fixes (`67329083`):** Implemented and exported `Get-VmLabHostResources`; fixed duplicate stderr JSON emission in `backend.py`/`cli.py`/`results.py` and added post-parse JSON redaction; added deterministic PowerShell AST + `Import-Module` CLI/backend registration audit.
- **Wizard fix (`18d4036d`):** Removed undefined `json_mode` fallback in `cli.py`'s interactive `wizard` branch so inherited console I/O exits cleanly without `UnboundLocalError`; added 5 wizard/CLI regression tests.
- **Validation:** `vm_lab` + `script_logging` + `scripts_help` pytest (`264 passed`, 0 failed); full `vm_lab` Pester (`68 passed`, 0 failed); PowerShell AST parse (`23` files, `0` errors) and export parity (`68` functions, `0` diff).
- **Installed CLI activation:** Verified `.venv` editable install points to `C:\Users\mcarls\src\scripts\modules\vm_lab`; `vm -h`, `vm-lab -h`, `vm version -j`, `vm host resources -j` (`status: "OK"`), `vm doctor -j` (`status: "attention_required"` in non-elevated shell) exited `0`, and `vm list -j` exited `1` with a single valid JSON error in the non-elevated agent shell.
- **Real Hyper-V / Windows OOBE qualification:** `NOT_TESTED` (disposable-VM provisioning and Windows OOBE remain to be qualified in an elevated session; protected H4 VM `RC-H4-Windows-Acceptance` / `d8483f98-8884-4758-abd1-cd6107c83c03` untouched).

## Compatibility Inventory (`Invoke-VmLab.ps1` Operations)

| Operation | Authority / Class | Notes |
|---|---|---|
| `list`, `status`, `plan`, `templates`, `template-info`, `checkpoints`, `boot-diagnostics`, `recovery-plan`, `doctor`, `guest-command-plan`, `artifact-plan`, `evidence-plan`, `workflow-plan`, `workflow-status`, `workflow-doctor` | Read-only | Safe without `-Apply` |
| `create`, `quickstart`, `unattend-xml`, `evidence-collect` | Host-mutating | Requires `-Apply` (and `host_mutation` in workflows) |
| `start`, `stop`, `connect`, `start-connect`, `checkpoint`, `baseline`, `lifecycle-transaction` | VM-lifecycle | Requires `-Apply` (and `vm_lifecycle` in workflows) |
| `guest-copy`, `guest-bootstrap`, `artifact-deploy` | Guest-mutating | Requires `-Apply` (+ `-AuthorizeGuestMutation` where applicable) + credential |
| `guest-exec` | Guest-exec | Requires `-Apply` + `-AuthorizeGuestExec` + credential |
| `guest-status`, `guest-verify` | Guest read-only | Requires credential |
| `workflow-apply`, `workflow-resume` | Orchestration | Requires `-Apply` + per-stage capability flags |
| `wizard` | Interactive | Non-JSON interactive assistant |
