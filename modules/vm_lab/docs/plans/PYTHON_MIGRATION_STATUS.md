# vm_lab Python Migration & CLI Completion — Status

**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\vm-lab-cli-launchers-20261115`  
**Branch:** `feature/vm-lab-cli-launchers-20261115`  
**Baseline SHA (`main` / `origin/main`):** `8326eea05464541ec994503bc6212a21b48c68fe`  
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
| 1 — Real Python Package | COMPLETED | pending commit | `pyproject.toml`, `__init__.py`, `__main__.py`, `backend.py`, `results.py`, `exceptions.py`, `cli.py`; 11 pytest passed (including wheel build & isolated venv install) |
| 2 — Bootstrap & CLI Migration | IN_PROGRESS | — | Full subcommands, legacy `-o` compat, `bootstrap_latest` / `launcher_generator.py` migration |
| 3 — Host, Identity, Media & Boot | NOT_STARTED | — | H01–H03 (VM ID lookup, ISO SHA-256, media attach/detach, boot diagnostics/recovery) |
| 4 — Guest Execution & Lifecycle | NOT_STARTED | — | H05–H10 (guest inventory, trusted script exec, 3010 reboot, graceful reboot, checkpoint inspect) |
| 5 — Workflow & Acceptance Semantics | NOT_STARTED | — | H11–H14 (`on_failure`, `timeout_seconds`, `idempotency_class`, `guest_identity`, `vm.connect`, approval CLI) |
| 6 — Windows Setup & OOBE | NOT_STARTED | — | H04 (answer-media workflow, attachment, readiness) |
| 7 — Final Validation & Docs | NOT_STARTED | — | Full Python + Pester + wheel/editable + bootstrap + security tests |

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
