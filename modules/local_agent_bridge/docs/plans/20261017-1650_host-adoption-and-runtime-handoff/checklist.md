# Checklist: Host Adoption & Runtime Handoff

## Stage 1: Live Profile Adoption & Instruction Reconciliation
- [x] **[Argon Expand]** Inspect active host files: `~/.codex/AGENTS.md`, `~/.codex/config.toml`, `~/.gemini/GEMINI.md`, and `~/.gemini/settings.json`.
- [x] **[Argon Expand]** Perform semantic audit between active host rules and packaged template baselines; ensure active user edits in `GEMINI.md` are preserved.
- [x] **[Argon Expand]** Generate read-only migration plan (`local_agent setup plan -c codex agy -s auto -m local -A codex.instructions agy.instructions codex.custom-skill.test-verify -o migration-plan.json`).
- [x] **[Argon Implement]** Review and verify the generated JSON plan fingerprints, operations, and backups.
- [x] **[Argon Implement]** Execute adoption (`local_agent setup apply -i migration-plan.json`).
- [x] **[Argon / Flash]** Verify post-apply status (`local_agent setup status -j`) confirms 0 drift and 0 conflicts.
- [x] **[Argon Implement]** Validate rollback readiness with preview removal (`local_agent setup remove`).

## Stage 2: Dotfiles Integration & Transition Safety
- [x] **[Argon Expand]** Audit dotfiles repository symlinks (`dotfiles/symlinks.sh` and PowerShell scripts) originating from `dotfiles/symlinked/llms`.
- [x] **[Argon Expand]** Design non-disruptive retention strategy for unmigrated clients (Claude, Cursor).
- [x] **[Argon Expand]** Design hook wiring for `setup-agents.ps1` and `setup-agents.sh` handling missing repository fallbacks.
- [x] **[Argon Implement]** Wire replacement hooks into dotfiles setup scripts.
- [x] **[Argon / Flash]** Test dotfiles bootstrap dry-runs on PowerShell (`-WhatIf`) and Bash.

## Stage 3: Runtime Evaluation Harness (Completed by Argon)
- [x] **[Argon Expand]** Design isolated disposable evaluation test repository structure (`modules/local_agent_bridge/.pytest_tmp_root/eval_workspace`, git tag `baseline`).
- [x] **[Argon Expand]** Author test prompts for Scenario A (`local-reviewer` read-only enforcement) in [03_flash-execution-runbook.md](03_flash-execution-runbook.md).
- [x] **[Argon Expand]** Author test prompts for Scenario B (`local-worker` bounded edits, honesty, recursion guards) in [03_flash-execution-runbook.md](03_flash-execution-runbook.md).
- [x] **[Argon Expand]** Author test scenarios for Scenario C (OpenCode async job timeout, cancellation, duplicate submission prevention) in [03_flash-execution-runbook.md](03_flash-execution-runbook.md).
- [x] **[Argon Expand]** Define schema verification rules for Scenario D (`result.schema.json` vs text fallback) in [03_flash-execution-runbook.md](03_flash-execution-runbook.md).
- [x] **[Argon Implement]** Initialize the disposable test project environment (`eval_workspace` committed at `b53168d`, tagged `baseline`).

## Stage 4: Live Delegation Benchmark Execution (Ready for Flash — follow `03_flash-execution-runbook.md`)
- [ ] **[Flash Execute]** Start local model bridge via LM Studio and OpenCode MCP (Step 4.0 in `03_flash-execution-runbook.md`).
- [ ] **[Flash Execute]** Execute Scenario A and verify reviewer tool denials (no shell/edit) (Step 4.1 in `03_flash-execution-runbook.md`).
- [ ] **[Flash Execute]** Execute Scenario B and verify worker diff boundaries and evidence (Step 4.2 in `03_flash-execution-runbook.md`).
- [ ] **[Flash Execute]** Execute Scenario C and verify async state handling and cancellation recovery (Step 4.3 in `03_flash-execution-runbook.md`).
- [ ] **[Flash Execute]** Execute Scenario D (`result.schema.json` structured output check) (Step 4.4 in `03_flash-execution-runbook.md`).
- [ ] **[Flash Execute]** Analyze coordinator token savings, latency, and model output quality, and author `modules/local_agent_bridge/docs/BENCHMARK.md` (Step 4.5 in `03_flash-execution-runbook.md`).

## Stage 5: Legacy Decommissioning Review (Pre-Audited by Argon)
- [x] **[Argon Expand]** Audit remaining live symlinks depending on `dotfiles/symlinked/llms` (documented in Section 3 of [03_flash-execution-runbook.md](03_flash-execution-runbook.md): `~/.claude/CLAUDE.md`, `~/.local/share/agent-abilities/*`, and rollback targets in `receipt.json`).
- [x] **[Argon Expand]** Document final retirement plan and retention conditions in [03_flash-execution-runbook.md](03_flash-execution-runbook.md) (`dotfiles/symlinked/llms` must be retained until Claude/Cursor/custom-agent adapters are implemented).
