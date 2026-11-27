# Active reasoning validation evidence matrix

**Branch:** `codex/llm-monitor-live-validation-20261029`
**Base:** `88a50d9b81fbb210ffb5192d6f0c373da39509d5`
**Scope:** Standalone LLM Monitor validation. No inference, model/runtime change, Runmux/local-agent worktree access, or telemetry database access was performed.

## Evidence classes and findings

| Evidence class | Result | Status and boundary |
|---|---|---|
| Installed OpenCode version and health | CLI and `/global/health` report 1.19.3 and healthy; `/doc` returned HTTP 200 | Verified read-only in this validation |
| OpenCode event contract | `/event` supports project `directory` scoping; delta and part-update identity fields and global envelope are described in `/doc` | Verified against installed schema; see [compatibility report](live-reasoning-opencode-1.19.3-20261029.md) |
| Active inference session | No trial/session handoff was provided; no active session was inspected | **Unverified pending a future controlled trial** |
| Earlier completed pilot session | Existing compatibility report records `completion_only`, zero matching SSE events, one reconnection gap, `finish=length`, 16,384 reasoning tokens, zero output tokens, four tool calls, and zero successful file edits | Historical completed-session evidence only; not re-queried in this follow-up, and not proof about active streaming |
| Synthetic SSE behavior | Fixtures cover event framing, identities, reasoning/text, out-of-order updates, duplicates, reconnect state, malformed/oversized events, and history reconciliation | Verified by deterministic tests only; does not prove server streaming support |
| OpenCode configuration and session variant | Prior report records alias `qwen38_23GB`, context 98,304, output 8,192, empty effective variants map, and session-recorded `medium` | Reported OpenCode evidence from the earlier completed session; variant does not prove provider forwarding |
| Actual provider request | No sanitized request-capture record was supplied | **Unavailable**; `reasoning_effort` and forwarded output limit remain unverified |
| LM Studio inventory | The earlier addendum reports `off`/`on`; no live model-inventory query was made in this validation | User-supplied prior evidence; current loaded capability not independently verified |
| Provider completion usage | Earlier OpenCode completion reports `finish=length`, 16,384 reasoning tokens, output 0; configured output limit was reported as 8,192 | Observed completion metadata with an inferred configured/observed difference; accounting and outbound limit semantics remain unresolved |
| Tools and file changes | Earlier complete bounded history reports `bash`, `read`, `read`, `read`, with no successful file edit | OpenCode history evidence; not independent file-content verification |
| MCP job and independent verifier | No MCP job state or verifier artifact was supplied | **Unavailable**; worker/task acceptance is unknown |

## Configuration provenance for the available completed observation

| Fact | Value | Source | Verification |
|---|---|---|---|
| Model family and alias | Qwen3.8-27B Q4_K_M / `qwen38_23GB` | User-provided investigation context and prior OpenCode report | Reported; loaded runtime inventory not queried here |
| Session-recorded variant | `medium` | OpenCode assistant/session metadata in prior report | Reported |
| Effective model variant map | Empty | OpenCode provider configuration in prior report | Reported |
| Context/output limits | 98,304 / 8,192 | OpenCode provider configuration in prior report | Reported configuration; forwarded request unverified |
| LM Studio reasoning choices | `off`, `on` | User-provided addendum | Reported by user; not re-queried here |
| Provider request parameters | Unknown | No sanitized request evidence available | Unavailable |
| Completion usage/finish | 16,384 reasoning / 0 output; `length` | Completed OpenCode assistant message in prior report | Reported completion metadata |
| Successful edits | 0 observed | Complete bounded OpenCode history in prior report | OpenCode history only; no independent file verifier |

The 16,384 reported reasoning tokens versus the 8,192 configured output limit is retained as an unresolved difference. It does not establish what LM Studio received, how either component accounts for reasoning tokens, or a model/provider defect.

## Monitor correction

Static review found that the monitor deduplicated SSE event IDs internally but did not report duplicate deliveries or expose a timestamped reasoning/tool event sequence in its bounded JSON snapshot. The follow-up adds a capped metadata-only timeline, duplicate counters, connection attempt/gap times, first/last matching-event times, reasoning/text delta counts and times, and optional operator-supplied `--trial-id`. Timeline entries omit delta text, prompts, and tool arguments; `event_timeline_truncated` marks rollover. Deterministic regressions verify duplicate suppression and counting, bounded timeline rollover, privacy, and preservation of partial reasoning across a reconnect.

## Conservative classification

- **Generation-length exhaustion:** the earlier completed message reports `finish=length` and no ordinary output; this is termination evidence, not proof of the cause.
- **Completed generation without accepted work:** no successful edit is present in the bounded history, but no independent verifier result was supplied, so acceptance remains unverified.
- **Incomplete streaming evidence:** the prior short observation had no matching event and a reconnect gap. It cannot establish whether active deltas are emitted.
- **Request forwarding/accounting:** unresolved without the runtime investigator's sanitized request capture and provider-side semantics.
- **Potential inference stall:** not diagnosed. The completed observation and absent event delivery do not establish an active no-progress interval.

## Recommendations for the future controlled trial

1. Provide the exact trial ID, OpenCode project directory, session ID, endpoint, requested condition, and expected maximum output allowance before inference starts when possible.
2. Start `llm-monitor live -p PROJECT -s SESSION -T TRIAL_ID -t 60 -f json` after the session exists and before the worker begins inference. Preserve the observer start time and any reconnect gaps.
3. Supply only the sanitized exact-match provider request evidence owned by the runtime harness; retain session, message, creation timestamp, request timestamp, provider/model, and allowlisted parameters.
4. Supply separate MCP job state and independent verifier output. A completed generation, worker/session state, edit-tool outcome, changed file, and accepted task must remain separate facts.
5. Do not include raw prompts, reasoning, source, credentials, or full provider request bodies in monitor evidence.
