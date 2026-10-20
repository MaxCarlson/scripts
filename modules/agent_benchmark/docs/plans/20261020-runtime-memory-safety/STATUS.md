# Runtime memory safety (1.11.0)

## Goal and scope

Protect the host during local inference and retain an attributable partial result when memory
pressure halts a batch. No inference, shared configuration edits, historical result edits, benchmark
suite expansion, scope relaxation, or shared process termination.

## Confirmed incident evidence

`EXP_20261020_031934`: RAM rose during GPT-OSS, not during a Qwen load. Resource samples show
57% near 20:20:25, 87.5% at 20:20:42, and 99.5% at 20:20:53. GPT-OSS finished at 20:20:55.
Only then did transition unload GPT-OSS (20:20:56-58); no Qwen estimate/load was issued.
The first empty-inventory snapshot still had about 21.2 GiB GPU memory resident and insufficient
RAM headroom. The between-model guard correctly refused the next load but arrived too late to
protect the host during GPT-OSS.

LM Studio `server-logs/2026-10/2026-10-19.2.log` records four GPT-OSS peg-native output-format
HTTP 500 errors at 20:19:47, :50, :56, and 20:20:06. OpenCode stream records select GPT-OSS;
no second model load is recorded in that interval. The errors do not establish the owner/cause
of the later allocation. Existing telemetry has no process attribution; historical ownership remains
unconfirmed. Do not label this a proven model leak, second model load, or Qwen allocation.

## Implementation

- Half-second checks while dispatch/observation calls are pending, using inexpensive RAM sampling.
- Stop at >=85% host RAM or <4 GiB available; request cancellation and use existing strict
  termination reconciliation. No forced shared-process kill or automatic unsafe unload.
- Preserve `ResourceLimitExceeded` diagnostics, current trial, run reference and partial reports;
  abort before subsequent trials/models. Do not turn infrastructure aborts into quality failures.
- Log top process names/PIDs/RSS every five seconds and at the limit; no command lines.
- After unload, wait within the existing deadline for empty inventory AND measured headroom;
  retain estimate and explicit context checks before actual loading.
- Public API addition is optional `run_attempt(resource_check=...)`; standalone legacy callers
  remain compatible. Scheduler local experiments enable the guard automatically.

## Verification / next action

Offline validation complete:

- `python -m pytest modules/agent_benchmark/tests -q --basetemp=modules/agent_benchmark/.pytest_tmp_root/r14`: 321 passed, 3 skipped (51.78s).
- Initial focused attempt/telemetry/lifecycle/scheduler checks: 54 passed; additional cancellation ownership and process attribution checks: 28 passed.
- `python -m ruff check modules/agent_benchmark` and `git diff --check`: passed.
- One initial full run exposed a test-only caplog propagation dependency after CLI logging tests; corrected isolation and reran the complete suite successfully.

No inference, load/unload, shared configuration changes, or rescoring. Ready for feature commit/push
and merge into local main under existing user authorization. This reduces host risk but cannot
establish the historical allocation owner or guarantee protection from sudden native allocations.
