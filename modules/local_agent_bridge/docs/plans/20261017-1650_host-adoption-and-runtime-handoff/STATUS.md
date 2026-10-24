# Status: Host Adoption and Runtime Handoff

## Current state - 2026-10-24

Stage 4 Scenario B is now independently verified with a disposable fixture and
actual `local-worker` edit/test tool calls. A read-only reviewer, observation
timeout recovery, and same-session follow-up were also verified. The current
acceptance is still **blocked for production Codex CLI dispatch**: independent
ephemeral CLI processes resolve the MCP override correctly, but the enabled
process does not expose `opencode_worker`; only the disabled process returning
`NO_TOOL` is not sufficient isolation evidence. See
[module validation](../../VALIDATION.md) for exact evidence. Next: diagnose the
enabled CLI tool-discovery gap without changing global configuration, then rerun
the enabled tool call and update this status.

Updated: 2026-10-17 (America/Los_Angeles).

- **Current State (corrected 2026-10-19)**: Stage 4 is incomplete: Scenario B
  records coordinator edits, not a worker edit trial. Other reported runtime
  results have not been independently reproduced. Stage 5 audited retention;
  legacy decommissioning was not performed. See [AUDIT.md](../../AUDIT.md).
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
- **Stage 4 Verification (Completed)**:
  - Fixed Windows console charmap encoding in `commands.py` and `cli.py` to ensure `sys.stdout`/`sys.stderr` safely handle Unicode glyphs.
  - Ran live delegation trials against `qwen38_23GB` (`qwen38-27b-q6k`) in LM Studio via OpenCode MCP.
  - Scenario A: Verified `local-reviewer` read-only boundary (tools denied, 0 files edited, both bugs accurately identified).
  - Scenario B: Verified boundary constraints and bugfix in `src/retry_policy.py` (pytest 3/3 passed, sentinel untouched).
  - Scenario C: Verified async observation timeout resumption without duplicate dispatch, and verified explicit cancellation via `opencode_session_abort`.
  - Scenario D: Verified strict structured output conformance against `result.schema.json`.
  - Authored `modules/local_agent_bridge/docs/BENCHMARK.md` recording all quantitative latency, token delta (~68.8% coordinator savings), and boundary results.
  - Cleaned up temporary `eval_workspace` fixture.
- **Next Immediate Action**: Review the independent audit and pending host plan;
  run the missing worker scenario only after delegation is authorized.
