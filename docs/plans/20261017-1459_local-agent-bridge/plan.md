# Local Agent Bridge Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans when implementation is
> authorized. Work inline; the user has prohibited delegation for now.

**Goal:** Package the existing Python bridge without changing its behavior, then
provide effective Codex/Antigravity interaction resources.

**Architecture:** Existing Python implementation and parser become one module CLI.
Existing MCP/OpenCode/LM Studio topology stays the same. One shared skill,
short coordinator rules and one worker prompt live in dotfiles.

**Spec:** [design.md](design.md). Interaction details:
[interaction-guide.md](interaction-guide.md).

**Status:** Corrected after user scope clarification. Interaction resources are
inside `modules/local_agent_bridge/`; dotfiles paths below are future destinations
only. The Python implementation has been moved into the module and package/CLI
wiring is in progress. See the module README and HANDOFF for current state.

## Part 1: Small module/CLI port

Files:
- Create `modules/local_agent_bridge/pyproject.toml`, README.md and AGENTS.md.
- Create `modules/local_agent_bridge/local_agent_bridge/{__init__,__main__,cli}.py`.
- Create `modules/local_agent_bridge/tests/cli_compatibility_test.py`.
- The old `pyscripts/loadlmscodexbridge.py` path is removed after the move.
- Add help registry entry in `modules/scripts_help/scripts_help/registry/registry.py`.

Interfaces:
- Keep the existing `build_parser()` and `main() -> int`.
- Entry point: `local-agent-bridge = local_agent_bridge.cli:main`.
- Module invocation: `python -m local_agent_bridge`.
- Initial package and exposed version: 1.0.0; Python >=3.11; stdlib runtime only.

- [ ] When code changes are authorized, inspect current status and use an isolated
  implementation branch/worktree. Original source and plan documents are untracked:
  carry only those explicit inputs to the worktree, verifying source hashes.
- [ ] Before moving code, add focused characterization checks for existing help,
  parser defaults/aliases and representative mocked execution branches.
  Cover ls, model/variant/nickname, rename/delete, context/GPU/TTL, reload,
  keep-other-models, no-servers, client selection, ports and model directory.
- [ ] Run characterization against the existing script with subprocess/network/
  filesystem writes mocked. These baseline tests should pass; no contrived failing
  test is needed to prove the existing implementation works.
- [ ] Add a failing installed-entry-point/module-invocation check. Move the Python
  implementation into cli.py with only packaging changes; keep the existing parser
  and behavior. Add __main__ and matching version metadata.
- [ ] Verify identical parser values and mocked operation calls for old/new entry
  points. Install only the new package into an isolated test environment for the
  entry-point check. No global setup, live config edits or model loads.
- [ ] Make the original Python path a thin launcher to the installed package.
  Document the targeted installation command if missing; do not add a second loader.
- [ ] Add help registry entry and its required version update. Leave the defunct
  PowerShell file alone unless cleanup is separately requested.
- [ ] Run focused bridge tests and help-registry checks, Ruff and Black120 where
  applicable. Inspect the port diff: unexpected behavior changes fail this task.

Future focused command:
`python -m pytest modules/local_agent_bridge/tests --basetemp=modules/local_agent_bridge/.pytest_tmp_root/run`.

This task is complete when existing invocations and the new CLI execute the same
implementation. New commands and behavior changes are outside its acceptance criteria.

## Part 2: Shared interaction resources — primary work

Files in dotfiles:
- `symlinked/llms/custom_agents/skills/local-agent-handoff/SKILL.md`.
- Its `references/task-envelope.md` and `references/results-and-recovery.md`.
- Its `resources/local-worker.md`: one canonical worker prompt.
- `symlinked/llms/codex/AGENTS.md`, `symlinked/llms/gemini/GEMINI.md`.
- Existing installer files only where needed to expose the new skill/prompt.

- [ ] Use the interaction guide as the concrete starting point. Check applicable
  dotfiles instructions and skill-authoring guidance before creating actual skills.
- [ ] Write the single shared skill: suitable tasks, bounded handoff, explicit
  workspace/model, tool discovery, continuation, blocked/input-required handling,
  result verification and fallback. No new orchestration service or task framework.
- [ ] Add the short routing paragraph to the effective Codex and agy global sources.
  Keep detailed workflows out of always-loaded instructions.
- [ ] Maintain one worker prompt with concise task/evidence/validation rules.
  Document how an OpenCode agent selects it; do not assume the LM Studio GUI prompt
  is used by API requests. Worker edits are governed by the task's authority;
  do not impose an analysis-only redesign.
- [ ] Document current model/settings as the baseline and upstream-supported options.
  Separate load-time settings, inference settings and handoff/context limits.
  Flag unsupported parameter forwarding as unknown rather than adding bridge features.
- [ ] Add narrow links for Codex's shared skill location and agy's skill location;
  preserve existing directories and use temporary-home installation checks.
  No standalone Gemini CLI MCP/skill work.
- [ ] Document normal use and failure recovery in the module README by linking these
  resources. No script behavior change is required to document the workflow.

## Part 3: Validate actual interaction when enabled

These are future checks, not permission to call a local model now.

- [ ] Confirm each client discovers the same shared skill and the expected
  opencode_worker MCP tools; confirm model/provider and explicit workspace.
- [ ] Once local-worker use is enabled, try one small read/review task and one
  authorized disposable coding task. Check useful output, valid tool use, precise
  evidence, honest test reporting and continuation after a delayed response.
- [ ] Verify the selected OpenCode agent actually uses the worker prompt.
- [ ] Record time, retries, token/context use and memory. Start with existing settings;
  change one setting only if a concrete problem justifies it.
- [ ] Report client differences and any unsupported settings. Make a separate small
  proposal only for a demonstrated integration gap.

## Review focus and completion

- Packaging must not change arguments, defaults or existing operations.
- Skill discovery and the worker prompt must be confirmed, not inferred from files.
- Observation timeout must not cause duplicate task submission.
- Tests must not touch the real home directory or load/unload real models.
- “agy/gemini” means agy only; the existing dotfiles gemini directory is an ownership path.

No automatic commits or publication. Current no-script-change/no-delegation
instructions remain active. Native/inline execution is the intended recommendation.
