# Historical runtime evaluation report

Audit correction: 2026-10-19. The previous report overstated worker validation.
The following records preserve its reported results; they were not independently
reproduced during the audit. No local model requests were submitted in the audit.
See [AUDIT.md](AUDIT.md) for current evidence and host state.

## Reported environment

2026-10-17, Windows 11, RTX 5090, local_agent_bridge 2.0.0, opencode-mcp 3.0.0,
OpenCode CLI 1.19.3, LM Studio, coordinator agy/Gemini, alias qwen38_23GB.
The report identifies qwen38-27b-q6k. These are historical reported versions and
model selections, not current inventory.

## Reported trials and limits

| Trial | Reported job | Reported result | Audit assessment |
| --- | --- | --- | --- |
| A: reviewer | job_444fa3fe6ebe4276864477396647f4be | Both defects identified; edit/bash unavailable; no edits | Reported observation, requires retained transcript and independent reproduction |
| B: worker edit scope | None; coordinator applied fix | Three tests passed; sentinel unchanged | Does not validate worker edit scope, honesty or recursion; trial remains pending |
| C1: timeout | Same job as A | Bounded wait resumed without resubmission | Reported observation, not independently reproduced |
| C2: cancellation | job_e6533b9e10e643ee8e2540cdcc78e76e | Cancelled; no edits | Does not establish cancellation safety during writes |
| D: structured result | job_5d2e5de8d90a4e1b88749f37ed82f9db | Six required JSON fields | Raw response and schema-validator output are not retained alongside this report |

The previous Scenario B fixed backoff exponent/cap and non-retryable status
handling in src/retry_policy.py. Coordinator test success proves the fixture was
solvable; a local-worker job with an inspected diff and real checks is still needed.
The disposable fixture was deleted. The runbook describes it but is not an
executable, versioned fixture that can reproduce the trial automatically.

## Token and latency claims

The original table reported A at approximately 150 seconds with local token counts
8,060 input / 733 output / 596 reasoning, and D at approximately 45 seconds with
7,200 / 480 / 420. These are reported numbers, not independently verified telemetry.

The 68.8% estimate for A compared roughly 780 coordinator tokens to a hypothetical
2,500 inline tokens, using ceil(characters / 4). The 75.2% estimate for D compared
520 to 2,100. Neither is measured cloud token usage or a repeated-task average.
A same-task control and retained usage counters are needed for savings claims.

## Permission and memory limits

The packaged reviewer denies built-in edits, bash and task dispatch. This is not
a filesystem sandbox or proof against custom/MCP tools. Inspect active merged
permissions and all tools; OpenCode documents permissive defaults for most tools.
[OpenCode permissions](https://opencode.ai/docs/permissions/).

Model file size is not a VRAM measurement. The old claim that a 22.43 GB file on a
32 GB GPU leaves 12.6 GB of headroom was unsupported and arithmetically inconsistent.
Measure GPU usage after model loading and context allocation before choosing
concurrency. Quantization and parameter count are different properties.

## Next runtime validation

With explicit permission to invoke a worker, recreate a disposable fixture and
retain its baseline, job responses, merged permissions, diff, sentinel checks,
actual pytest output and JSON Schema validation. Exercise a genuine worker edit,
permission/input handling and a related follow-up. Keep legacy dotfiles paths
until replacement adapters and rollback independence are verified.
