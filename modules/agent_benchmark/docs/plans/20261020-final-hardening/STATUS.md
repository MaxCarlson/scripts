# Final benchmark hardening

## Baseline and ownership

Worktree `.worktrees/benchmark-live-stats`, branch `agent/benchmark-live-stats`, baseline
52d4a0f9cae0c66ec48d0f190b8e17319ef9f678. Clean before work. Preserve 1.12.0 file-tools smoke
contract and historical artifacts. Current user plan is the scope authority.

## Stages

1. Profile hardening: ordered effective permission semantics, narrowly trusted output-directory
   exception, role/prompt identity, actionable rejection before session creation.
2. Additive judgments, timings, zero-denominator diagnostics, explicit comparison contract and
   consistent terminal/JSON/CSV/Markdown/HTML rendering. Preserve strict precedence and CLI unknowns.
3. Document and assess a real shell boundary. Never enable sandboxed-shell-v1 or downgrade it to
   host execution without demonstrated containment of worker AND verifier. No live inference authorized.
4. Retain existing memory admission. No unvalidated formula replacement or blind batch continuation.

## Validation and delivery

Add focused red/green regressions, run offline agent/core/report suites and lint. Independent verifier
reviews the resulting diff and representative raw evidence. Commit/push reviewed stages and merge
local main before user trials. Prepare one-model/one-submission live acceptance, do not execute it.

## Status

Stage 1 committed as 21061733. Stage 2 implemented and independently reviewed. Package versions:
agent 1.13.0, core 0.1.2, reports 0.1.1. The earlier 1.12.0/task 0.2.0 smoke contract is preserved.

Profile trust is correlated to the local listener PID/executable/startup XDG_DATA_HOME; unsupported
layouts fail closed. Installed OpenCode 1.19.3 read-only inspection accepted the exact exception;
no session was created. Effective permissions and prompt identity are checked before session creation.

Current judgments distinguish functional/artifact/execution/budget/termination. Missing evidence stays
unknown, malformed audit components prevent strict success, CLI correct artifacts without execution
history stay UNSCORED. Correlated timing is observational, never retrospective correctness scoring.

Explicit conditions separate incompatible settings/runtime identities and suppress unknown equivalence.
Zero scored trials retain observations without ranks. Terminal/JSON/CSV/Markdown/HTML preserve those
results. Duplicate run-local trial IDs cannot overwrite inspector records; ambiguous legacy evidence
lookups are skipped rather than attributing another run's output.

Stage 3 is deliberately NOT implemented as containment. Docker engine probe failed because the
Linux-engine named pipe was absent. See shell-boundary.md: real worker AND verifier containment,
network/mount/resource controls and real prohibited-write tests remain required. Requests for
sandboxed-shell-v1 fail before workspace allocation/model transitions, without host fallback.

Stage 4: conservative estimate/headroom admission and lifecycle safeguards remain unchanged.
No model load/unload, inference, shared configuration mutation or historical artifact migration occurred.

## Final offline validation

Run from `.worktrees/benchmark-live-stats` using the main virtualenv interpreter:

```powershell
$python = 'C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe'
& $python -m pytest -c modules/agent_benchmark/pyproject.toml modules/agent_benchmark/tests -q --basetemp=modules/agent_benchmark/.pytest_tmp_root/r35
# 354 passed, 3 skipped in 52.89s (Windows symlink privilege cases)
& $python -m pytest -c modules/agent_benchmark/pyproject.toml modules/benchmark_core/tests modules/interactive_reports/tests -q --basetemp=modules/benchmark_core/.pytest_tmp_root/r10
# 131 passed, 1 skipped in 0.40s (unavailable historical report directory)
C:/Users/mcarls/src/scripts/.venv/Scripts/ruff.exe check modules/agent_benchmark modules/benchmark_core modules/interactive_reports
# All checks passed
 git diff --check
# No whitespace errors
```

Use separate pytest processes to avoid duplicate test basenames, and explicit -c for worktree imports.
Windows sandbox temp ACL failures were rerun via the authorized elevated offline route. Regressions
reproduced duplicate inspector overwrite and missing permissions hashed as null before correction.

Isolated headless Edge file:// inspection confirmed no zero-denominator winner, visible unranked
functional/duration diagnostics, five scope judgments and unknown timings; no JavaScript errors.
Screenshots were inspected at owned ignored `.pytest_tmp_root/ui-final/final*.png`. The first browser
assertion inspected an inactive tab; switching to Scope & Safety passed. One diagnostic print hit the
shell's cp1252 encoding; ASCII-safe output resolved that inspection issue without changing report data.

Independent read-only review recomputed all five EXP_20261020_042422 verdicts using current
trial_from_attempt and saved raw lifecycle/checkpoint/audit/verifier evidence: GPT FAILED,
Qwen/Muse/Ornith UNSCORED, Devstral TIMEOUT. All 34 read inputs rehashed unchanged. Correct,
audited file-only mocked execution can earn strict PASSED; opaque/CLI execution cannot. No real
sandbox or live worker acceptance is claimed.

## Delivery

Feature commits 21061733 and bb3d68df were pushed to origin/agent/benchmark-live-stats. Initial local
main integration is 5b17f0a8. Post-merge imports and installed agent_benchmark --version resolve to
main's agent 1.13.0 and core 0.1.2; interactive_reports also resolves to main. The only main checkout
change is the preserved unrelated untracked docs/plans/common_feature_refactoring.md. Main was not
pushed because it contains unrelated local commits. This final delivery ledger follows as a small
documentation commit on the same feature branch and is merged into main as well.

Next: separate authorization for live-acceptance.md; no multi-model inference yet. Stage 3 remains
unavailable pending actual worker/verifier containment, with no strict sandbox claim.
