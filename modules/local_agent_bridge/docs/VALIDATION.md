# Current installer validation

The 2.0.0 independent installer passed 26 focused checks with one host file-symlink
privilege skip. Wheel build/assets/entry points and an isolated wheel lifecycle
also passed. See [HANDOFF.md](HANDOFF.md) for exact commands and limits. Real
profile activation and model handoffs remain pending. Historical worker scenarios
below remain acceptance criteria for that next stage.

# Resource validation

## Offline checks

Invoke the module with `python -m local_agent_bridge --help` from its installed
environment. Confirm it exposes the existing loader options. The installed
`local-agent-bridge` console script uses the same CLI entry point.

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
