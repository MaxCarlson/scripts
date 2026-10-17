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

No real profile apply, model/inference request, service restart, original dotfiles
change or hook activation was performed. Full legacy model loading and live
Codex/agy discovery/delegation remain unverified.

## Next stage

See [MIGRATION.md](MIGRATION.md) for the exact adoption command and rollback caveats.
Review a fresh actual-home plan, reconcile the active instruction baselines and
legacy skill, then apply the intended real migration and verify both clients.
Original Codex instructions still link into dotfiles until that adoption occurs.
The old folder must remain available while live links or rollback targets use it.

[Design](plans/20261017-1602_local-agent-setup/design.md),
[implementation plan](plans/20261017-1602_local-agent-setup/plan.md), and
[status](plans/20261017-1602_local-agent-setup/STATUS.md).
