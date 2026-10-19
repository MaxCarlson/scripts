# Phase 1d — OpenCode project isolation

Status: implemented and tested offline; separately authorized non-inference API acceptance now completed. Exact project/empty-session bindings passed; generated-prompt inheritance and actual inference remain unverified. See the current HANDOFF.md and reports/20261019T141839Z-phase1d-api-af4085b5/ACCEPTANCE.md. Stop for review.

## Authorized design and boundaries

The user's corrected Phase 1d handoff takes precedence over Gemini's supporting investigation (C:/Users/mcarls/Downloads/Technical Investigation Report.txt). Establish independent trial Git identity, validate exact OpenCode project/session bindings before inference, use common header routing, preserve scope/scoring/evidence. No scratch-policy changes, scoring redesign, benchmark_core edits, live workers, shared-service changes, or historical-artifact changes.

Implementation/model allocation: Sol Medium owns Git/bridge/lifecycle integration. Gemini Flash can handle routine fixtures later only after another user instruction; return to Sol for API/provenance/attribution issues. No development-agent delegation or model router.

## Stages and commits

1. `8a94f580`: git_workspace.initialize_git creates a bounded, trial-local SHA-1 repository and unique UUID-bearing root commit. prepare_workspace returns GitIdentity before S0 capture. Git-specific inherited environment and system/global configuration, templates and hooks cannot redirect initialization; no remote is added. Identical public task bytes produce equal S0 hashes but distinct Git roots, including equal workspace basenames.
2. `15efb1dc72eca0a7ef2f28e261b85cb49ab6bb61`: bridge project/session gate, header routing, project-bound handles/reconciliation/cleanup, provenance and integration regressions. Windows read-only Git objects are handled only during confirmed, owned cleanup. No process termination introduced.
3. Documentation checkpoint: this plan, HANDOFF.md, README, status and checklist. Module version 1.1.0; task/verifier suite remains 0.1.1. Environment isolation policy is `isolated-git-project-v1`.

## Interfaces and execution order

- `prepare_workspace(task, workspace) -> GitIdentity(trial_id, root_commit, worktree, policy_version)`: copies public bytes; rejects seed-owned root .git; creates one independent root commit with no remote. Git commands have 10-second bounds and run without a shell. Initialization writes only within the fresh owned trial repository.
- S0/S1 capture prunes only the workspace-root .git directory. Ordinary nested .git-named paths are retained; archive integrity checking does not hide newly inserted .git paths. Links/junctions are still rejected. This filtering is not mutation permission: transcript writes to .git are violations even if a task mistakenly lists them as allowed. Opaque shell operations remain uncertain.
- `OpenCodeBridge.preflight(..., project_id=local_root_commit)`: read-only configuration checks plus GET /path and GET /project/current. Require exact resolved directory/worktree, Git vcs, and project ID equal to this trial's unique root commit (not merely any non-global value).
- `prepare_session(directory, project_id=...)`: revalidates project, POSTs one empty session, GETs its persisted record, requires matching ID/directory/projectID, empty history and idle state. A failed/uncertain session creation cannot be retried on the same bridge. This step is not inference.
- `dispatch`: requires that validated session and submits opencode_fire with its sessionId exactly once. A mismatched receipt preserves original ownership and the returned diagnostic receipt; it cannot redirect cancellation. Unknown submission still latches persistent dispatch blocking.
- HTTP directory routing uses only x-opencode-directory, without a redundant query parameter. Existing MCP 3.0.0 forwarding uses that header too.
- WorkerHandle adds optional project_id. New journals retain it; new cleanup validates it against the owned Git identity. Retained older journals without Git provenance keep the legacy path/session safeguards.
- Provenance: RunInfo metadata benchmark_version/isolation_policy; runtime.json and canonical runtime metadata git/project/session; lifecycle.json Git and handle identity; session-preflight.json creation/persisted binding evidence, including failed validation when available; TrialResult.details.project_id. Core contracts are unchanged.

The task budget still begins with first-attempt dispatch observation after preparation; no budgets were increased. A created empty session without inference does not count as an unresolved worker. Failed project/session preflight produces infrastructure_error and releases the no-inference reservation. Failures after possible prompt submission retain blocking unless termination is confirmed.

## Source verification and corrections to the supplied snippets

Pinned sources independently inspected:

- [OpenCode 1.19.3 Git discovery and root history](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/core/src/git.ts): discovery searches ancestors; unborn HEAD has no root commit.
- [Project resolver](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/core/src/project.ts): ID preference is remote, repository cache, root commit, then global. Fresh benchmark repositories have no remote or previous cache; compare the actual root commit ID.
- [Instance /path handler](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/server/routes/instance/httpapi/handlers/instance.ts), [project handler](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/server/routes/instance/httpapi/handlers/project.ts), [session creation/lookup](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/session/session.ts): persisted session directory and projectID are available for validation. Do not require a nonexistent session worktree field.
- [Instance routing](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/server/routes/instance/httpapi/middleware/workspace-routing.ts) and [location routing](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/server/src/location.ts): x-opencode-directory is common to both; no conflicting query is needed.
- Installed opencode-mcp 3.0.0 source at C:/Users/mcarls/AppData/Local/npm-cache/_npx/283414c155cc5b4e/node_modules/opencode-mcp/dist/{client,jobs,job-contract}.js confirms header forwarding and an existing-session branch that submits to prompt_async without creating another session. The benchmark uses that supported sessionId interface.

The investigation's broad .git exemption and redundant header/query proposal were not adopted. Global OpenCode instructions/configuration and tool permissions remain in effect. Logical project isolation and post-execution scope auditing do not enforce OS filesystem isolation. The benchmark command lock serializes its own state users; it cannot guarantee exclusive use of shared inference services by other clients. No instance disposal or service control was added.

## Validation

Interpreter: C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe.

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/phase1d-full
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/benchmark_core/tests -q -rs --basetemp=modules/benchmark_core/.pytest_tmp_root/phase1d-full
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests modules/agent_benchmark/__init__.py modules/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy --cache-dir modules/benchmark_core/.pytest_tmp_root/mypy-phase1d modules/benchmark_core/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy --cache-dir modules/agent_benchmark/.pytest_tmp_root/mypy-git-final modules/agent_benchmark/agent_benchmark/git_workspace.py
```

Results: 175 agent tests passed, 2 skips (Windows symlink privilege); 83 core tests passed; Ruff clean; configured core Mypy clean (9 files); new Git helper Mypy clean. Offline full-adapter mocks test successful canonical provenance and project/session failures with no inference. Existing unknown-submission/restart blocking, timeouts, scope uncertainty and frozen failed-S1/passed-S3 regressions remain green.

Optional broad `mypy ... modules/agent_benchmark/agent_benchmark` is not clean: 22 legacy diagnostics in Windows fcntl stubs, dynamic outer benchmark_core exports, parse_observation narrowing and CLI annotations. Shadow-file comparison against 4b445d44 found 27 diagnostics in those existing areas; the five eliminated errors are preflight/history narrowing. No unrelated package/state/CLI typing refactor was undertaken. This is not a claim of agent-wide Mypy cleanliness.

Historical reports: 59 files; unchanged path/content digest 4560c4d9b3b0c3a8d0865f57d3e0d6e9a043e46054ce10507e8645d179baa3fb. No live API request, worker execution, service reconfiguration or artifact regeneration occurred in Phase 1d.

## Original non-inference verification checklist (superseded by acceptance evidence)

The following was the planned probe matrix. The authorized acceptance exercised two committed repositories, exact header/project/session validation and negative binding checks; it did not create additional uninitialized/unborn controls, which remain covered offline. No inference was performed:

1. Use owned fresh control directories (uninitialized and unborn Git) plus two distinct benchmark-prepared committed repositories. Never initialize or change a historical workspace or the home repository.
2. Call GET /path and GET /project/current with the common directory header. Confirm ancestor/global control behavior and exact trial directory/worktree/Git/root-commit project IDs for both prepared repositories. Assert distinct prepared project IDs.
3. If authorized as part of the probe, POST one empty session per prepared repository, then GET its persisted record, history and status. Confirm directory/projectID and empty/idle state. This creates session records but must not submit prompt_async, opencode_fire, or any model request. Retain evidence.
4. Record actual server/schema results before claiming live project isolation. Separately authorized future live-worker acceptance is required to prove the whole prepared-session MCP path in operation.

Stop here. No scratch policy, scoring changes, suite expansion, model run, instance disposal or shared-service change is authorized by this checkpoint.
