# Host Profile Adoption and Runtime Handoff Design

Date: 2026-10-17 (America/Los_Angeles). Status: Ready for Argon execution.

## Intent and Scope

Following the implementation of the `local_agent` 2.0.0 CLI, packaged assets, and independent installer (commit `a617d29e`), this plan executes the live migration of host profiles (Codex and Antigravity `agy`), integrates the bootstrap hooks into the user's dotfiles environment, and performs rigorous end-to-end runtime evaluation of coordinator-worker delegation using LM Studio and OpenCode.

This plan is specifically structured for **Argon** (high-reasoning model) because it involves:
1. Reconciling live user instruction divergences between active host files (`~/.gemini/GEMINI.md`, `~/.codex/AGENTS.md`) and template baselines without silent regressions.
2. Navigating dotfiles symlink architecture without breaking unmigrated editors (Claude, Cursor).
3. Analyzing and stress-testing multi-agent delegation protocols (async job state machines, timeout/cancellation handling, permission boundaries, and recursion guards).

## System Boundary & Preserved State

- **Independent installer boundary**: All setup operations must use `local_agent setup`, never delegating to the unreviewed `agent_abilities` or `agent_skills` modules.
- **Unmigrated client isolation**: Claude settings/instructions and Cursor configs remain pointing to their current locations. Do not delete or prune `dotfiles/symlinked/llms` until full replacement adapters are authored and verified.
- **Strict safety protocol**:
  - Always execute read-only planning (`setup plan -o <plan>.json`) and inspect the generated JSON before executing `setup apply -i <plan>.json`.
  - Backups and receipts in `~/.local/share/local-agent/` must be inspected after writes.
  - Verify rollback readiness (`setup remove` preview) before marking adoption complete.
- **Disposable runtime sandbox**: Behavioral evaluation of the local worker/reviewer must be executed in a dedicated, isolated test repository to prevent unintended modifications to productive scripts.

## Architecture & Work Breakdown

### Stage 1: Live Host Profile Adoption & Instruction Reconciliation
1. **Live Inspection**:
   - Inspect `~/.codex/AGENTS.md` (currently a file symlink into dotfiles) and `~/.codex/config.toml`.
   - Inspect `~/.gemini/GEMINI.md` (a regular file containing newer user rules than the dotfiles template) and `~/.gemini/settings.json`.
   - Identify legacy skill collisions (such as `test-verify` in Codex's custom skills directory).
2. **Reconciliation Analysis**:
   - Compare live content against packaged templates in `local_agent_bridge/resources/`.
   - Ensure explicit adoption preserves live rules as the active baseline rather than overwriting with older templates.
   - Confirm insertion of the coordinator fragment (`coordinator.snippet.md`) into the designated `<!-- local_agent:insert capabilities -->` slot or bounded comment block.
3. **Execution & Receipt Verification**:
   - Generate versioned adoption plan:
     ```powershell
     local_agent setup plan -c codex agy -s auto -m local -A codex.instructions agy.instructions codex.custom-skill.test-verify -o migration-plan.json
     ```
   - Inspect `migration-plan.json` fingerprints and proposed operations.
   - Apply the plan: `local_agent setup apply -i migration-plan.json`.
   - Verify with `local_agent setup status -j` (must report 0 drift, 0 conflicts, managed state clean).
   - Test removal preview (`local_agent setup remove`) to verify rollback fidelity without modifying files.

### Stage 2: Dotfiles Integration & Transition Safety
1. **Inspect Dotfiles Wiring**:
   - Inspect `dotfiles/symlinks.sh` and corresponding PowerShell installers for LLM assets.
   - Identify existing duplicate destination writers.
2. **Hook Integration**:
   - Wire `integrations/setup-agents.ps1` and `setup-agents.sh` into dotfiles setup workflow for supported clients (`codex`, `agy`).
   - Retain backward compatibility: handle cases where `src/scripts` is missing with an actionable warning rather than a fatal error.
   - Ensure unmigrated Claude and Cursor destinations continue to link to `dotfiles/symlinked/llms` without interruption.

### Stage 3: Coordinator-Worker Runtime Delegation & Behavioral Evaluation
1. **Discovery & Session Health**:
   - Confirm a fresh Codex session discovers the `local-agent-handoff` skill and `opencode_worker` MCP tools.
   - Confirm Antigravity discovers the skill, MCP configuration, and tool permissions.
2. **Disposable Test Environment Setup**:
   - Create a clean git test fixture in a disposable directory (e.g. `tests/disposable_eval_project/` or temporary root).
3. **Controlled Multi-Agent Evaluation Scenarios**:
   - **Scenario 1 (Reviewer Boundary)**: Dispatch a read-only code review task to `local-reviewer`. Verify that shell execution and file edits are strictly denied by role definitions.
   - **Scenario 2 (Worker Scope & Honesty)**: Dispatch a bounded bugfix or refactor to `local-worker`. Verify that changes are confined to authorized paths, honest evidence is recorded, and the worker does NOT attempt recursive sub-delegation.
   - **Scenario 3 (Async Protocol & Failure Paths)**: Test job observation lifecycle (`opencode_fire`, `opencode_wait`, `opencode_status`, `opencode_reply`). Simulate job timeout and cancellation; verify no duplicate job submissions occur.
   - **Scenario 4 (Contract & Schema Output)**: Validate result against `result.schema.json` (or verify clean plain text fallback where structured output is unsupported).
4. **Metrics & Behavioral Ledger**:
   - Record coordinator context tokens consumed vs saved, latency, retry counts, and qualitative accuracy of local worker output.
   - Document results in `docs/BENCHMARK.md`.

### Stage 4: Decommissioning of Legacy Dotfiles Sources (Gated)
- Verify zero active symlinks point to `dotfiles/symlinked/llms` for migrated clients.
- Verify rollback targets have been cleanly documented.
- Present final retirement plan to the user before any file deletion in dotfiles.

## Exit Criteria
- Both Codex and Antigravity operate under `local_agent`-managed profiles with 0 configuration drift.
- Dotfiles bootstrap invokes `setup-agents` hooks cleanly.
- Live local model delegation is verified end-to-end with measured token/context savings and verified role boundaries.
