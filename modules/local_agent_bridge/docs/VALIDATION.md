# Current installer validation

## Live Codex dispatch acceptance - 2026-10-24

**Status: blocked for production Codex CLI dispatch.** OpenCode and LM Studio
worker behavior are verified through the connected MCP runtime, but an enabled
ephemeral `codex exec` process did not expose the configured `opencode_worker`
tool. Do not enable production dispatch on the strength of this run alone.

### Preflight

- Installed package and CLI are `local-agent-bridge` 3.1.0; Codex CLI is
  0.164.0. `local-agent setup status -j` returned code 0, all managed resources
  unchanged, no conflicts or warnings.
- The installed skill exists at `~/.agents/skills/local-agent-handoff` and the
  runtime skill catalog exposes `local-agent-handoff`. Fresh CLI auto-discovery
  was not independently established.
- OpenCode 1.19.3 reported healthy. Project context was
  `C:\Users\mcarls\src\scripts`, branch `main`; nine agents were listed,
  including `local-worker` and `local-reviewer`.
- Active model: LM Studio ID `qwen38_23GB`, quantization `Q4_K_M`, loaded
  context 32768 (maximum 262144), `tool_use` capability, state `loaded`. OpenCode
  selected `lmstudio/qwen38_23GB`, configured label `qwen38-27b-q4km`.

### MCP process isolation

Separate `codex mcp get --json opencode_worker` invocations resolved
`enabled=false` with `-c mcp_servers.opencode_worker.enabled=false` and
`enabled=true` from the default config. In ephemeral read-only CLI sessions:

- Disabled session `01a1702b-9353-71c3-8787-8b7b5359703a` returned `NO_TOOL`.
- Enabled sessions `01a1702b-cd95-7282-ad76-217c2dada0ac` and
  `01a1702c-a224-7a00-a92e-9e859221955e` also returned `NO_TOOL`, including
  when asked for the exact identifier `mcp__opencode_worker__opencode_setup`.

Thus the disable override prevented tool access, but the enabled CLI process
did not expose the tool either. Config resolution passed; the required enabled
call did not. A separate `--oss --local-provider lmstudio` probe failed before
tool use with the Qwen chat-template error `System message must be at the
beginning`. No CLI configuration was changed.

### Reviewer and worker behavior

- Read-only reviewer session `ses_e8fd7e2efffefuL6XSjmFxj4dX` used
  `lmstudio/qwen38_23GB` and completed in 23.2 seconds. Conversation evidence
  shows one `read` of `commands.py`, no writes or shell calls, and no file diff.
  It correctly reported that this file delegates model-list handling to
  `cli.handle_ls_command()` (lines 112–114); model inventory behavior is outside
  the requested review scope.
- Worker job `job_87d5e1aec6394aa6bae6fe78a97fa751`, session
  `ses_e8fd6b4a1ffe1IoELdLovqSEGt`, used `local-worker` and
  `lmstudio/qwen38_23GB`. It completed in 20.3 seconds. The actual tool trace
  shows reads of fixture `AGENTS.md`, source, and tests; one `edit` to
  `src/retry_policy.py`; and `bash` running the focused pytest command (exit 0,
  `3 passed in 0.05s`). No coordinator source rework was needed.
- Exact worker diff:

  ```diff
  - return min(base * (2 ** (attempt + 1)), cap)  # BUG: attempt zero should return base
  + return min(base * (2 ** attempt), cap)
  ```

- The staged fixture baseline included `AGENTS.md`, `tests/test_retry_policy.py`,
  and `PROTECTED.txt`. The test and sentinel had no working-tree diff; sentinel
  SHA-256 before/after was
  `E0E84D647A9C159FA01CBE2B809F98F721CD0E74DDBFDE5CCF8188A57E1B7D1A`.
  Coordinator rerun from the fixture root passed `3 passed in 0.07s`. The initial
  coordinator test invocation from the parent directory failed import collection;
  rerunning from the fixture root reproduced the intentional baseline failure
  (`2 failed, 1 passed`) before dispatch. Worker was not asked to repair tests.

### Job lifecycle and permission handling

- Async dispatch returned job `job_87d5e1aec6394aa6bae6fe78a97fa751`, session
  `ses_e8fd6b4a1ffe1IoELdLovqSEGt`, and message
  `msg_170294a66001b3fcde64d02bf6`.
- A one-second wait returned `running` with `timedOut=true`. Observation resumed
  on the same job ID; no resubmission occurred. The job then completed.
- Related follow-up job `job_d6ddc2553016481e93e2a4d8d6d2df8b` reused the same
  session and completed in 3.5 seconds without tools or edits.
- Permission list returned `No pending permission requests`; question lists for
  both reviewer and worker sessions were empty.

The earlier historical Scenario B used coordinator edits and remains unverified
as reported in [AUDIT.md](AUDIT.md). This run independently verifies actual
worker editing and job lifecycle through the connected MCP runtime, but the
production Codex CLI enabled-session tool call remains the release blocker.

The independent 2026-10-19 audit supersedes the historical status below:
[AUDIT.md](AUDIT.md). Release 3.0.0 has 47 passing focused tests and one
Windows file-symlink privilege skip. No inference was requested during the audit.
Historical benchmark reports are qualified in [BENCHMARK.md](BENCHMARK.md).

The 2.0.0 independent installer passed 26 focused checks with one host file-symlink
privilege skip. Wheel build/assets/entry points and an isolated wheel lifecycle
also passed. See [HANDOFF.md](HANDOFF.md) for exact commands and limits. Real
profile activation and model handoffs remain pending. Historical worker scenarios
below remain acceptance criteria for that next stage.

# Resource validation

## Offline checks

Invoke the module with `python -m local_agent_bridge --help` from its installed
environment. Confirm it exposes the existing loader options. The installed
`local-agent` console script exposes setup/model/run; `python -m local_agent_bridge`
retains the original loader interface.

Validate SKILL.md metadata with the skill-creator validator, resolve local Markdown
links, parse example JSON, and confirm the prompt reference resolves relative to
that example. Check for unfinished scaffold text and accidental live configuration
changes. These checks do not invoke the model or prove behavioral quality. Also verify:

- Codex metadata names `opencode_worker` and permits implicit skill discovery.
- Both OpenCode example agents resolve to the same canonical prompt file.
- Both deny recursive delegation; the reviewer denies edits and shell execution.
- The result JSON Schema accepts completed, partial and blocked result examples,
  and rejects missing fields or invented check statuses.
- Task-envelope JSON and wait examples match the pinned bridge's inputs.

## Behavioral scenarios â€” pending

Run only when delegation/model use is enabled, in a disposable workspace. For an
independent evaluation, compare the same task without and with the skill; retain
actual results rather than inferring improvement from this checklist.

| Scenario | Observable acceptance |
| --- | --- |
| Focused review | Worker inspects named source, cites real evidence and leaves files unchanged |
| Small authorized edit | Only allowed paths change; checks/results are inspectable |
| Missing context | Worker names the missing file/fact instead of inventing behavior |
| Delayed response | Coordinator observes the same job; no duplicate submission |
| Required permission/decision | Coordinator handles it within current authority or surfaces the specific gap |
| Related follow-up | Same session is used and previous evidence remains available |
| Unavailable bridge | Coordinator reports the gap or works locally, without installing or retuning tools |
| Explicit no-delegation instruction | No worker request is dispatched |
| Tiny task | Coordinator completes it directly when handoff/review would cost more |
| Worker sees coordinator rules/skills | Worker completes its task without recursively dispatching another worker |
| Reviewer profile | Built-in edits and shell requests are denied; inspect other configured tools separately |
| Follow-up correlation | New work in the same session is observed using its new job ID |
| Structured output | If enabled, final shape validates and its claims match source/diff evidence |
| Model selection | Explicit lmstudio provider and the configured API alias are used; no cloud fallback |

Verify skill discovery for both Codex and agy and selection of the intended
OpenCode agent/prompt/model. A selected agent name or a prompt file on disk alone
does not prove the actual model request used it.

For each comparison record the task and resource version, coordinator/client,
provider/model alias, tool/job IDs, elapsed time, coordinator token usage if
available, retries, edits outside scope, and whether the coordinator had to redo
the work. Report missing measurements as unavailable. Change one setting at a time.

Current status: resources are not installed and behavioral scenarios and
baseline/control comparisons have **not been run**. Static checks establish
resource consistency, not runtime discovery or better delegation. No subagents
or inference calls were used to author these resources. See the
[handoff](HANDOFF.md) for the exact current offline verification results.
