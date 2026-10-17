# Coordinator and local worker integration

Date: 2026-10-17 (America/Los_Angeles).

## Goal and accepted design

Help Codex and Antigravity proactively hand worthwhile bounded repository tasks
to the existing LM Studio worker, then monitor and verify the result with less
coordinator context. The user authorized starting implementation after the web
research. The module is `modules/local_agent_bridge`; the package/CLI is already
ported and is an input to this work.

The existing skill/resource workflow is the implementation boundary. One shared
coordinator skill, a short policy snippet and a canonical worker prompt stay in
this module. OpenCode examples select worker/reviewer capabilities; MCP operations
remain the existing opencode-mcp@3.0.0 tools. See [RESEARCH.md](../../RESEARCH.md)
for the sourced decisions and [INTEGRATION.md](../../INTEGRATION.md) for deployment.

Execution: inline. No model delegation or live configuration changes during local
resource authoring. No loader redesign, new CLI command hierarchy or new server.
The current work does not install user profiles, edit dotfiles or publish changes.

## Stage 1: Implement the coordinator/worker contract

Paths are relative to the module root.

- [x] Update `skills/local-agent-handoff/SKILL.md`: precise automatic discovery,
  worthwhile-task selection, first-use readiness, explicit directory/model/agent,
  shared-checkout ownership, dispatch and bounded observation by job ID.
- [x] Add `skills/local-agent-handoff/agents/openai.yaml`: implicit discovery,
  a usable default prompt and the existing opencode_worker MCP dependency.
- [x] Update `instructions/coordinator.snippet.md`: shared coordinator routing,
  explicit no-delegation override and delegated-worker role guard.
- [x] Update `resources/local-worker.md` inside the skill: scope, role, honest
  evidence, compact result and clear treatment of missing authority/context.
- [x] Update `integrations/opencode-agent.example.json`: local-worker and
  local-reviewer share that prompt, both deny task/handoff recursion, and the
  reviewer denies built-in edits and shell execution. Other runtime rules inherit.
- [x] Add `resources/result.schema.json` inside the skill: outcome, summary,
  changed_paths, evidence, checks and blockers. This is optional; plain text stays
  supported when StructuredOutput/runtime support is unavailable.
- [x] Update task/recovery references: concrete fire/wait examples, exact job
  correlation, required input, follow-up IDs, timeout versus cancellation and
  handle expiry. Do not resubmit ambiguous jobs or choose a cloud fallback.
- [x] Update README, integration/settings/validation docs and the source map.
- [x] Bump module/package version to 1.1.0 and synchronize its existing help entry.
- [x] Run the skill validator, parse JSON/YAML and check local links/prompt paths.
- [x] Exercise result-contract examples with assertions for all used keywords,
  check role constraints and unchanged CLI hash. Full schema engine unavailable.
- [x] Inspect only the intended changes, update handoff and record exact results.

Review conditions: metadata alone does not activate resources, tool profiles are
not permission boundaries, reviewer permissions are not an OS sandbox, returned
completion is not proof of task correctness, and arbitrary timeout/unknown state
must not create duplicate work. Offline checks cannot prove model behavior.

## Stage 2: Activate and evaluate the existing workflow

This stage changes live profiles and invokes models; perform it when those
actions are authorized. Prepare concrete targets before requesting approval.

- [ ] Inspect effective user skill/rule/MCP locations for both installed clients.
  Inventory existing same-name resources and settings before linking anything.
- [ ] Link the module's skill into exactly one discovery location per client;
  add the short routing policy to one effective instructions source per client.
  Preserve existing instructions and other skill/MCP entries.
- [ ] Merge the named-agent fragment into OpenCode and resolve its prompt path
  for the destination config. Confirm selected directory/provider/API alias/agent
  and the effective inherited tool permissions. Reload the relevant connection.
- [ ] Confirm fresh Codex and agy sessions expose the skill and the required MCP
  tools. This is a runtime check, not a filesystem-presence claim.
- [ ] In a disposable project, compare an inspection task and an authorized edit
  with and without the skill. Confirm the reviewer's restrictions, honest evidence
  and no recursive dispatch. Inspect actual requests to confirm local-model use.
- [ ] Exercise delayed completion, required input and a related follow-up. Keep
  job/session/message IDs and confirm no duplicate submission after timeout.
- [ ] If supported, check a schema-formatted result; otherwise record the exact
  incompatibility and continue with text. Review the diff and permitted checks.
- [ ] Record quality, retries, elapsed time, coordinator token usage if available
  and rework. Keep model/sampling/context settings fixed for the comparison.

Stage 2 succeeds when both clients discover and use the same resource workflow,
the intended local model/role executes the tasks, and results/recovery are verified.
It does not require proving token savings from an unmeasured assumption.

## Stage 3: Package only the integration that proves useful

Optional follow-up after Stage 2. No new plugin/installer commands are part of
Stage 1. Detailed implementation choices remain for this stage's design review.

- [ ] Build separate Codex and Antigravity plugin adapters from the same source
  skill/references/prompt. Test the assembled relative paths and client schemas.
- [ ] Choose whether each client keeps its existing MCP registration or uses a
  bundled connection; never register both for the same bridge.
- [ ] Package resources explicitly and test the build artifact, since installing
  the current Python package exposes the CLI but not the root resource directory.
- [ ] Validate installation/update/removal against temporary profiles before
  changing real profiles. Preserve unrelated config and pre-existing resources.
- [ ] Add a readiness or job-bookkeeping hook only for an observed gap. Keep
  inference out of session-start hooks and adapt formats/events per client.
- [ ] Consider a thin MCP wrapper only if tool ergonomics or enforced argument
  validation remain inadequate. Retain the existing service topology otherwise.

## Progress ownership

[STATUS.md](STATUS.md) and [checklist.md](checklist.md) record this plan's state.
[Module HANDOFF](../../HANDOFF.md) is the resume entry point. The older repository
plan records the initial module port and is historical for this integration work.
