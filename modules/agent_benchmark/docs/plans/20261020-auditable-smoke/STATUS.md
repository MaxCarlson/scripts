# Auditable smoke execution (1.12.0)

## Goal

Resolve the shared task/tool/scoring contract mismatch exposed by five-model experiment
`EXP_20261020_042422`. Preserve historical evidence, strict scoring, time limits, and memory safety.
No new benchmark tasks, model inference, shared configuration edits, or model load/unload.

## Investigation and root cause

Read all five S0/S1 trees, scope audits, submitted prompts, session histories and tool outputs.
Traced `prepare_workspace -> run_attempt -> bridge.preflight/dispatch -> audit_scope -> trial_from_attempt`.
The task invites optional worker tests and exposes a generic shell-capable worker, but the strict
scorer requires proved scope compliance. `audit_transcript` records every shell invocation as
unverifiable, including commands categorized as read-only. Snapshots cannot establish all external
or transient mutations by arbitrary Python/shell code. This is an incompatible default execution
contract for a tiny externally verified implementation task, not evidence all models cannot code.

| Model | Frozen verifier replay | Actual issue |
| --- | --- | --- |
| GPT-OSS | failed | edit replacement contains literal leading `+` diff markers; syntax error at line 16. Its `pytest` command ran no tests. |
| Qwen Q6 | passed | 3 shell operations; only allowed deliverable and scratch changes; no detected scope violation. |
| Muse Glimmer | passed | 10 uncertain operations, including Git inspection and todo bookkeeping. Initial scratch test import failed because its script directory replaced the workspace on Python's import path. |
| Ornith | passed | 1 shell Python check; only grep.py changed; no detected scope violation. |
| Devstral | passed | completed correct first edit at 12.68 seconds after user-message creation, then spent the remaining budget on tests. Python cp1252 output failed on check marks; model repeatedly edited test print statements, wrote invalid extra assertions, and eventually timed out. First non-`-B` Python import generated the recorded pycache violation. |

Reconstructed Devstral's first edit from S0 plus the exact first edit tool input; it independently
passes the same hidden verifier. Replayed the verifier against disposable copies of all five frozen
implementations: four pass, GPT-OSS fails. Original grep.py hashes remained unchanged. Replay
artifacts: `.pytest_tmp_root/forensic-f5ccaf` (local diagnostic scratch, not canonical results).
No inference was involved; the verifier runs on disposable local copies as in offline regressions.

## Architectural decision

For this small task, use an explicit `file-tools-v1` profile and harness-owned verification. Stop
relying on another warning asking unrestricted agents to avoid shell tests. Do not declare shell
commands safe based on names or suppress pycache/scope evidence to increase scores. Do not extend
the budget or give successful late code a grace-period pass. GPT-OSS's malformed code remains a
real failure; passing the model is not the goal.

The design and functional-scoring alternative were presented to the user during investigation.
With no contrary preference received, proceeded with the recommended task-local file-tool profile
under the user's implementation authority. Generic/custom tasks default to retained `shell-v1`.

## Implementation and boundaries

- Existing smoke manifest declares `file-tools-v1`; task suite 0.1.1 -> 0.2.0 and package -> 1.12.0.
- Generate a reserved `benchmark-files` primary role only in each fresh owned LM Studio trial's
  opencode.json, preserving exact provider registration. Shared config/agents are untouched.
- Default-deny permissions allow read/edit/write via edit, glob/grep/list and completion output;
  shell, task delegation, skills, web and unknown tools remain denied. Deterministic role prompt
  explicitly assigns verification to the harness and explains literal edits (no diff prefixes).
- Check effective `/agent` permissions before session creation; missing or broadened tool policy
  fails preflight. Persist role, permissions and profile in runtime/lifecycle and run metadata.
- OpenCode automatically appends access to its own tool-output directory, even after explicit
  external-directory denial. Preserve that observed rule; validate tool permissions separately.
  File writes still undergo exact path/snapshot/transcript auditing. This is not an OS sandbox.
- CLI-based Codex/agy retain their existing shell-capable prompt/behavior and record a distinct
  effective profile; this OpenCode role does not claim to constrain those processes.
- No historical result is relabeled. Score interpretation and shell uncertainty stay unchanged.

## Boundary verification

- Inspected cached pinned opencode-mcp@3.0.0: job-contract.js accepts agent as an optional string;
  jobs.js forwards it to session prompt requests. Custom role dispatch does not require a bridge
  package change.
- Read-only GET /agent on the installed OpenCode server using an owned temporary project config:
  benchmark-files exists and effective permissions pass the same preflight validator. No session,
  prompt, inference, model load/unload, or shared setting change.
- Official agent configuration reference: https://opencode.ai/docs/agents/ . Effective local
  permissions, rather than documentation alone, were checked. Provider-bound schemas and actual
  model use of the new profile remain live acceptance, not claimed by this read-only probe.

## Validation / status

Initial red: new regression failed because tool_profile module did not exist. Profile/attempt checks
then passed (22). Integration exposed six legacy fixture/mock assumptions; updated those mocks
for the explicit role and retained a separate shell-profile scratch regression. Focused integration:
107 passed, 1 skipped. Full suite: `python -m pytest modules/agent_benchmark/tests -q
--basetemp=modules/agent_benchmark/.pytest_tmp_root/r20`: 327 passed, 3 skipped in 53.61s.
Final bridge diagnostic change had a separate red test (2 cases failed before the correction), then
`bridge_test.py tool_profile_test.py bridge_isolation_test.py`: 55 passed using basetemp r22.
`python -m ruff check modules/agent_benchmark` and `git diff --check`: passed.

Implementation and offline validation complete. Commit/push feature and merge local main under
standing user authorization. A new real model run remains live acceptance; do not claim that
any particular model is guaranteed to pass. The same five-model CLI command selects the new
profile automatically after version 1.12.0 is integrated. No inference was submitted here.
