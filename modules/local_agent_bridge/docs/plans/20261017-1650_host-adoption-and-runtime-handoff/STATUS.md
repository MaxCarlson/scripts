# Status: Host Adoption and Runtime Handoff

Updated: 2026-10-17 (America/Los_Angeles).

- **Current State**: Stages 1, 2, 3, and 5 (audit) complete. Ready for **Gemini 3.8 Flash** to execute Stage 4 using [03_flash-execution-runbook.md](03_flash-execution-runbook.md).
- **Prerequisite Complete**: Commit `a617d29e` implemented `local_agent` 2.0.0 CLI, independent installer, and packaged assets. 26 unit tests passing.
- **Stage 1 Verification**:
  - Audited `~/.codex/AGENTS.md`, `~/.codex/config.toml`, `~/.gemini/GEMINI.md`, `~/.gemini/settings.json`, and MCP configs.
  - Verified `~/.gemini/GEMINI.md` user rules (104 lines) and `~/.codex/AGENTS.md` rules (24 lines) were preserved as `adopted` baselines (`baseline_origin: "adopted"` in `~/.local/share/local-agent/receipt.json`), appending only `<!-- local_agent:insert capabilities -->` + `coordinator.snippet.md`.
  - Applied migration plan (`code: 0`, 12 resources changed, 3 existing MCP/permission configs unchanged).
  - Verified `local_agent setup status -j` (`code: 0`, 0 conflicts, all 15 resources `unchanged`) and `local_agent setup remove -j` preview (`code: 0`, 0 conflicts, all backups intact under `~/.local/share/local-agent/backups/478a76f14cec4be983c64d33f2780175/`).
- **Stage 2 Verification**:
  - Audited all dotfiles LLM writers (`dotfiles/setup/symlinks.ps1`, `dotfiles/symlinked/llms/symlinks.sh`, `dotfiles/symlinked/llms/custom_agents/symlinks.sh`).
  - Enhanced `integrations/setup-agents.ps1` and `integrations/setup-agents.sh` to auto-detect previously applied `local` mode from `~/.local/share/local-agent/receipt.json`, support `-WhatIf`/`--dry-run`/`DOTFILES_DRY_RUN=1`, and fall back to repository `bin/local_agent*` or `.venv` Python.
  - Wired `setup-agents.ps1` and `setup-agents.sh` into dotfiles while preserving Claude (`~/.claude/*`), Cursor (`~/.cursor/*`), central `agent-abilities` links, and non-skill Codex resources (`agents`, `prompts`, `instructions`).
  - Verified PowerShell dry-run (`pwsh -NoProfile -File C:\Users\mcarls\src\dotfiles\setup\symlinks.ps1 -WhatIf`) and Git Bash dry-run (`DOTFILES_DRY_RUN=1 . C:/Users/mcarls/src/dotfiles/symlinked/llms/symlinks.sh`) exit `0` with all 15 `local_agent` resources `unchanged`.
- **Stage 3 & 5 Verification**:
  - Initialized disposable evaluation repository at `modules/local_agent_bridge/.pytest_tmp_root/eval_workspace` (tagged `baseline`, commit `b53168d`) with `AGENTS.md`, `src/retry_policy.py` (2 intentional bugs), `src/forbidden_guard.py`, and `tests/retry_policy_test.py`.
  - Authored [03_flash-execution-runbook.md](03_flash-execution-runbook.md) with copy-pasteable JSON MCP payloads, pass/fail assertions, and Stage 5 symlink retirement audit.
- **Next Immediate Action**: Switch to **Gemini 3.8 Flash** and execute Stage 4 by following [03_flash-execution-runbook.md](03_flash-execution-runbook.md) step-by-step.
