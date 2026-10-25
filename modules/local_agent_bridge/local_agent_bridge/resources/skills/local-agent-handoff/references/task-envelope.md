# Task envelope

Use these fields for the task, adapting detail to its size:

```text
Objective:
Workspace: absolute project path
Context: relevant paths, established facts and applicable project instructions
Dispatch record: jobId, sessionId, initiating messageId, absolute directory,
provider ID, model ID, and explicit agent (record returned IDs immediately)
Allowed work: inspect, propose a patch, or edit the named paths
Constraints: exclusions and authority limits
Checks: acceptance criteria and permitted validation commands
Return: deliverable, changed paths, evidence, checks/results and unresolved issues
```

Example review task:

```text
Objective: Review retry behavior in the HTTP client's request method.
Workspace: C:\work\example-client
Context: Inspect src/client.py and tests/client_test.py. Read applicable project
instructions. Focus on how timeouts and HTTP 429 responses are retried.
Allowed work: Inspect those files and return findings; no edits or shell commands.
Constraints: Do not access live endpoints or change dependencies/settings.
Checks: Identify whether attempts are bounded and whether non-retryable errors
are surfaced. Give file/line evidence and explain any unverified assumption.
Return: Findings ordered by impact, or no findings. State that tests were not run.
```

For an authorized coding task, replace the allowed-work line with exact writable
paths and specify the permitted focused test command. Supplying a test name does
not authorize unrelated installation, publication or configuration changes.

Pass workspace and model selection as tool parameters as well as task context.
Use the runtime's discovered schema. For example, submit this review through
`opencode_fire` after replacing `prompt` with the full envelope:

```json
{
  "prompt": "Review retry behavior using the complete task envelope above.",
  "directory": "C:\\work\\example-client",
  "providerID": "lmstudio",
  "modelID": "qwen-local",
  "agent": "local-reviewer"
}
```

Here `qwen-local` is an example loaded API identifier, not the GGUF download key.
Use the actual configured alias. Select the named agent only after verifying it
is configured; otherwise resolve the missing prompt setup before dispatch.
An authorized coding task uses `local-worker` with exact writable paths and checks.
Copy the returned `jobId`, `sessionId`, initiating `messageId`, directory,
provider/model IDs, and agent into the dispatch record. These values are
task-specific; paths and symbols supplied in `Context` are optional starting
points and must be verified in the current workspace.

Observe the returned job with the same directory. A bounded wait example is:

```json
{
  "jobId": "<returned-job-id>",
  "directory": "C:\\work\\example-client",
  "timeoutSeconds": 30
}
```

This is an `opencode_wait` input, not a second task submission. The example wait
fits beneath Codex's documented 60-second default tool timeout; allow headroom
for transport and server processing and check the actual client's configuration.

For automated consumption, the optional [result schema](../resources/result.schema.json)
can be supplied in the prompt tool's `format` parameter as
`{"type": "json_schema", "schema": <schema object>, "retryCount": 0}`.
Pass the parsed schema object, not its local filename. OpenCode must permit its
StructuredOutput tool, and the serving model must support the required tool use.
Keep ordinary text results when structured output is unavailable. Schema validation
checks the result's shape; the coordinator still checks the source and diff.
