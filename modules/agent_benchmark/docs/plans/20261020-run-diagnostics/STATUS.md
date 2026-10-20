# Run diagnostics and model identifier cleanup

## Goal

Use concise `lms/` or bare LM Studio model identifiers, preserve existing `lmstudio/` inputs, and make multi-model run failures and resource pressure diagnosable from saved artifacts.

## Findings

- The latest saved four-model experiment contains three completed run references. GPT-OSS failed hidden verification because generated `grep.py` had invalid syntax; Muse passed verification but was unscored because its scope audit was uncertain; Ornith timed out at the 60-second budget. No fourth model run was persisted.
- `transition_model` already calls `lms unload -a` and waits for `lms ps` to become empty. It previously accepted the target when it was one of multiple loaded models, did not inspect busy/unknown statuses, and had no host-memory headroom check.
- The attempt subprocess uses byte pipes and UTF-8 replacement decoding. LM Studio CLI and `nvidia-smi` text-mode subprocess calls used locale-default decoding. Explicit UTF-8 replacement decoding addresses a plausible Windows failure mode; the stored artifacts do not prove that decoding caused any recorded trial status.
- The scheduler performed model transitions outside the OS-backed command lock. This allowed another benchmark invocation to unload/switch a model while a different run was active.
- Agent benchmark has module loggers but no run-scoped logging configuration. TermDash has an optional component log; benchmark_core does not own runtime orchestration.
- There is no persisted trace of the missing fourth model's transition or native-process exit. The saved run therefore does not establish whether Devstral failed to load, the host/process stopped, or another cause occurred.

## Implementation

- Accept `lms/<key>`, legacy `lmstudio/<key>`, and bare local runtime keys; report LM Studio inventory as `lms/<key>`. Keep internal/OpenCode provider ID `lmstudio` and canonicalize Codex only through `codex/`.
- Add UTF-8 replacement decoding to text-mode subprocess calls.
- Configure an experiment-scoped UTF-8 log using the shared `script_logging` handler; record model transitions, bounded LM Studio stdout/stderr tails, resource samples, trial outcomes and exceptions, and partial-report persistence. Do not log prompts or process arguments.
- Keep partial reports usable when a later model transition fails.
- Hold the cross-process command lock across the complete multi-model run, including transitions and trials. Refuse transitions when LM Studio reports a busy or unknown model status.
- Before loading a local model, require measured available RAM to cover the discovered model file size plus 25% headroom, and refuse at 90% total RAM use. This is a conservative pre-load estimate; it does not prove driver or process memory reclamation and does not interrupt an active trial.
- Mark models with any failed, timed-out, infrastructure-error, or unscored trial as unsuccessful in the live summary; retain functional, scope, and budget outcomes as separate trial metrics.

## Verification

- Add offline tests for identifier parsing, UTF-8 subprocess options, run-log lifecycle, resource samples, high-RAM load guard, and partial report persistence.
- Run focused agent_benchmark tests, Ruff, and `git diff --check`. Do not run inference or change shared LM Studio/OpenCode state.

## Status

Implementation complete on `agent/benchmark-live-stats`; offline verification passed. `agent_benchmark` tests: 295 passed, 3 skipped. `benchmark_core` tests: passed (one skip). Ruff and `git diff --check` passed. No live inference, OpenCode configuration change, or LM Studio load/unload was performed. Remaining uncertainty: exact cause of the historical Devstral process disappearance and whether any `_readerthread` exception caused trial outcomes. Host-wide model ownership beyond benchmark processes cannot be inferred from `lms ps`; the new status guard catches active/unknown states but idle models may still be used by external clients.

Integration: implementation commit `b384b057` was pushed to `agent/benchmark-live-stats` and merged into local `main`. The merged main checkout passed the same agent test suite. Main retains unrelated uncommitted `resource_coordinator` edits and was not pushed.
