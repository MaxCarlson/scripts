# Pending live acceptance: separate authorization required

Do not execute as part of this offline delivery. Proposed acceptance uses one model, one task,
one submission, no automatic retry. Capture plan/configuration and inspect the actual verdict/evidence;
a particular model is not required to pass. Read-only installed OpenCode 1.19.3 profile inspection
passed, but that does not prove live editing. File permissions are an audited contract, not an OS sandbox.

```powershell
agent_benchmark experiment plan -m lms/ornith-1.5-35b-a3b -t py-grep-smoke -r 1 -c 16384 -b canonical-120s
# Execute only after explicit live-run authorization:
agent_benchmark experiment run -x -m lms/ornith-1.5-35b-a3b -t py-grep-smoke -r 1 -c 16384 -b canonical-120s -o (Join-Path $env:USERPROFILE 'tmp/reports/experiments')
```

Retain runtime.json effective role/prompt/permissions/output provenance; S0/S1; complete lifecycle,
worker history, scope audit, verifier receipt/output; benchmark.log and generated reports. Confirm
functional/artifact/execution/budget/termination judgments agree with raw evidence and comparison
conditions are established. If they are missing, the result cannot establish strict success or equivalence.

Stop on RAM >=85% or available RAM <4 GiB (existing sampled guard), failed memory estimates,
insufficient reserves, uncertain transition/worker termination, configuration mismatch or dispatch hold.
Do not clean/retry/reuse an unresolved workspace. Retain partial reports. No four-model expansion
until this outcome is inspected. No unrelated service shutdown or global model eviction authorized here.
