# Plan Handoff: Host Adoption and Runtime Handoff

Updated: 2026-10-17 (America/Los_Angeles).

## For Argon Taking Over:

### Context
`local_agent_bridge` has reached release 2.0.0. The independent installer and CLI hierarchy are committed at `a617d29e`. All unit tests (`.venv/Scripts/python.exe -m pytest modules/local_agent_bridge/tests`) pass.

### Objectives & Progress
1. **Expand & Reconcile Host Profiles (Stage 1 — COMPLETED)**:
   - Audited `~/.codex/` and `~/.gemini/`. Verified active user instructions in `~/.gemini/GEMINI.md` (104 lines) and `~/.codex/AGENTS.md` (24 lines) are preserved as `adopted` baselines rather than overwritten by older templates.
   - Generated and inspected `modules/local_agent_bridge/.pytest_tmp_root/migration-plan.json`.
   - Applied the plan via `.venv/Scripts/python.exe -m local_agent_bridge.commands setup apply -i modules/local_agent_bridge/.pytest_tmp_root/migration-plan.json -j`.
   - Verified post-install state with `local_agent setup status -j` (0 drift, 0 conflicts, 15 managed resources) and rollback readiness with `local_agent setup remove -j` (0 conflicts, backups recorded under `~/.local/share/local-agent/backups/478a76f14cec4be983c64d33f2780175/`).
2. **Expand & Wire Dotfiles Hooks (Stage 2 — COMPLETED)**:
   - Audited `dotfiles/setup/symlinks.ps1`, `dotfiles/symlinked/llms/symlinks.sh`, and `dotfiles/symlinked/llms/custom_agents/symlinks.sh`.
   - Wired `integrations/setup-agents.ps1` and `setup-agents.sh` into dotfiles while preserving Claude/Cursor symlinks and active `local` receipt mode.
   - Verified dry-runs on both PowerShell (`-WhatIf`) and POSIX shell (`--dry-run` / `DOTFILES_DRY_RUN=1`).
3. **Runtime Evaluation Harness & Symlink Decommissioning Audit (Stages 3 & 5 — COMPLETED BY ARGON)**:
   - Initialized disposable git test repo at `modules/local_agent_bridge/.pytest_tmp_root/eval_workspace` (commit `b53168d`, tag `baseline`).
   - Authored complete step-by-step execution runbook in [03_flash-execution-runbook.md](03_flash-execution-runbook.md) with exact MCP tool call JSON arguments for Scenarios A, B, C, and D, plus the Stage 5 symlink audit.
4. **Execute Live Delegation Benchmark (Stage 4 — READY FOR GEMINI 3.8 FLASH)**:
   - Open [03_flash-execution-runbook.md](03_flash-execution-runbook.md) and execute Steps 4.0 through 4.5 sequentially.
   - Author `modules/local_agent_bridge/docs/BENCHMARK.md` and remove the temporary `eval_workspace` directory when finished.

Refer to [03_flash-execution-runbook.md](03_flash-execution-runbook.md), [plan.md](plan.md), [design.md](design.md), [STATUS.md](STATUS.md), and [checklist.md](checklist.md) for full task breakdowns.
