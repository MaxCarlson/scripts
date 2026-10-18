# Local agent setup handoff

Updated: 2026-10-17 (America/Los_Angeles).

Branch: `compression-inventory-estimation-20261017`. Module/package stays
`modules/local_agent_bridge`; version 2.0.0 exposes the new `local_agent` CLI.
Legacy `local-agent-bridge` and `python -m local_agent_bridge` remain compatible.

## Completed stage: independent installer and CLI

The user approved implementation, copying the dotfiles LLM folder, and keeping
local capabilities separate from generic profiles. No dependency on the unreviewed
agent_abilities or agent_skills modules was introduced.

Implemented `setup plan/apply/status/remove/recover`, `model list/rename/remove`
and `run`. Setup accepts `-m generic|local`, client selection, link/copy/auto,
isolated home/state roots, saved fingerprint plans and exact adoption IDs.
Generic sources have named insertion anchors; local delegation text is authored
separately. Mode changes remove owned local contributions while preserving generic
rules/settings/custom skills. Recognizable pre-existing bridge entries are disabled
in generic mode and restored to their original state on uninstall.

The installer includes per-field config ownership, preserving TOML edits with
tomlkit, receipts, backups, locking, a recovery journal, drift/stale-plan checks,
rollback and exact-contribution removal. Windows replacement retries are bounded
and recheck target contents. Runtime bridge writers share the preserving helpers
and update the default-state receipt for intentional model switches.

Assets are now packaged under `local_agent_bridge/resources/`; old root skill,
instruction and agent-example files were relocated. All 26 dotfiles LLM files were
copied into `resources/dotfiles_llms`. One credential-shaped value in Claude settings
was redacted; source/copied hashes and the exception are in `resources/migration.json`.
Original dotfiles files were not edited or deleted. Module-owned replacement
bootstrap hooks are prepared in `integrations/setup-agents.ps1` and `.sh`; they
have not been wired into dotfiles. Claude/Cursor/non-skill resource migration is
still deferred; do not retire their existing wiring prematurely.

## Verification

- `.venv/Scripts/python.exe -m pytest modules/local_agent_bridge/tests -q --basetemp modules/local_agent_bridge/.pytest_tmp_root/setup --tb=short`
  passed 26 checks with one file-symlink test skipped because host privilege is
  unavailable. Checks cover mode switching, insertion/adoption, update/removal,
  unrelated settings, permissions, stale/tampered plans, source changes, locking,
  rollback failures/recovery, Windows replacement and runtime alias synchronization.
- The file-symlink test was also attempted outside the sandbox; still skipped.
  Automatic link fallback/copy is exercised. No claim of host file-symlink coverage.
- `.venv/Scripts/python.exe -m build --no-isolation --wheel --outdir modules/local_agent_bridge/.pytest_tmp_root/dist modules/local_agent_bridge`
  built `local_agent_bridge-2.0.0-py3-none-any.whl`. Sandbox temporary-directory
  permissions prevented the first build; the host build succeeded.
- Wheel entries/CLI metadata/resources were inspected; caches are excluded. An
  isolated `python -I` import from the extracted wheel passed generic apply/status,
  local enable, generic disable and removal against a temporary home.
- Both CLI help paths work. The repository virtualenv has tomlkit and an editable
  2.0.0 install. Its generated `bin/local_agent.cmd` wrapper is available on PATH.
- Real-home planning was read-only. The default plan flags a legacy Codex
  test-verify skill collision. An explicit adoption plan for codex.instructions,
  agy.instructions and codex.custom-skill.test-verify has no conflicts.
- Git inspection ignores inaccessible pscripts submodule metadata. Concurrent
  compression changes belong to another task and must remain unstaged.

## Completed stage: Stage 1 Live Host Profile Adoption (Argon)

- Audited live `~/.codex/AGENTS.md`, `~/.codex/config.toml`, `~/.gemini/GEMINI.md`, `~/.gemini/settings.json`, and MCP configs (`~/.gemini/antigravity-cli/mcp_config.json`, `~/.gemini/config/mcp_config.json`).
- Executed read-only plan and live adoption:
  - `.venv/Scripts/python.exe -m local_agent_bridge.commands setup plan -c codex agy -s auto -m local -A codex.instructions agy.instructions codex.custom-skill.test-verify -o modules/local_agent_bridge/.pytest_tmp_root/migration-plan.json -j`
  - `.venv/Scripts/python.exe -m local_agent_bridge.commands setup apply -i modules/local_agent_bridge/.pytest_tmp_root/migration-plan.json -j`
- Confirmed `baseline_origin: "adopted"` in `~/.local/share/local-agent/receipt.json` for both `codex.instructions` and `agy.instructions`, preserving the 104-line user instructions in `~/.gemini/GEMINI.md` and 24-line instructions in `~/.codex/AGENTS.md` while appending the `<!-- local_agent:insert capabilities -->` slot and `coordinator.snippet.md` block.
- Confirmed `local_agent setup status -j` reports `code: 0`, `conflicts: []`, and `unchanged` across all 15 managed resources.
- Confirmed `local_agent setup remove -j` preview reports `code: 0` with complete rollback fidelity from `~/.local/share/local-agent/backups/478a76f14cec4be983c64d33f2780175/`.
- Note: `dotfiles/symlinked/llms` remains untouched so rollback links and unmigrated clients (Claude/Cursor) remain valid.

## Completed stage: Stage 2 Dotfiles Integration & Transition Safety (Argon)

- Audited `dotfiles/setup/symlinks.ps1`, `dotfiles/symlinked/llms/symlinks.sh`, and `dotfiles/symlinked/llms/custom_agents/symlinks.sh`.
- Enhanced `integrations/setup-agents.ps1` and `integrations/setup-agents.sh` so they preserve active `local` mode from `~/.local/share/local-agent/receipt.json` when no `-Mode`/`-m` is passed, support dry-run preview (`-WhatIf`, `--dry-run`, `DOTFILES_DRY_RUN=1`), and resolve `local_agent` via PATH, repo `bin/`, or `.venv`.
- Wired `setup-agents.ps1` into `dotfiles/setup/symlinks.ps1` and `setup-agents.sh` into `dotfiles/symlinked/llms/symlinks.sh`, removing duplicate Codex/Gemini config/skill writers while preserving Claude (`~/.claude/*`), Cursor (`~/.cursor/*`), `~/.local/share/agent-abilities/*`, and Codex non-skill resources (`agents`, `prompts`, `instructions`).
- Verified `pwsh -NoProfile -File C:\Users\mcarls\src\dotfiles\setup\symlinks.ps1 -WhatIf` and Git `sh` dry-runs (`sh setup-agents.sh --dry-run` and `DOTFILES_DRY_RUN=1 . symlinked/llms/symlinks.sh`) exit `0` with all 15 managed resources reporting `unchanged`.

## Completed stage: Stage 3 Evaluation Harness & Stage 5 Symlink Audit (Argon)

- Created disposable evaluation git repository at `modules/local_agent_bridge/.pytest_tmp_root/eval_workspace` (commit `b53168d`, tagged `baseline`) with `AGENTS.md`, `src/retry_policy.py` (2 intentional bugs), `src/forbidden_guard.py` (scope sentinel), and `tests/retry_policy_test.py`.
- Authored [03_flash-execution-runbook.md](plans/20261017-1650_host-adoption-and-runtime-handoff/03_flash-execution-runbook.md) containing exact copy-pasteable `opencode_worker` MCP JSON payloads, shell verification commands, pass/fail criteria for Scenarios A–D, and the complete Stage 5 symlink retirement audit.

## Next stage: Stage 4 Live Delegation Benchmark Execution (Gemini 3.8 Flash)

Follow [03_flash-execution-runbook.md](plans/20261017-1650_host-adoption-and-runtime-handoff/03_flash-execution-runbook.md) Steps 4.0–4.5 to run the live LM Studio / OpenCode trials and generate `modules/local_agent_bridge/docs/BENCHMARK.md`.

Active plan:
[Flash Runbook](plans/20261017-1650_host-adoption-and-runtime-handoff/03_flash-execution-runbook.md),
[Plan](plans/20261017-1650_host-adoption-and-runtime-handoff/plan.md),
[design](plans/20261017-1650_host-adoption-and-runtime-handoff/design.md),
[STATUS](plans/20261017-1650_host-adoption-and-runtime-handoff/STATUS.md),
[checklist](plans/20261017-1650_host-adoption-and-runtime-handoff/checklist.md), and
[plan handoff](plans/20261017-1650_host-adoption-and-runtime-handoff/HANDOFF.md).
Prior installer stage: [20261017-1602_local-agent-setup](plans/20261017-1602_local-agent-setup/plan.md).
