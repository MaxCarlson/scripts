# B1 lifecycle implementation root-cause analysis

Date: 2026-10-29. This is the disposable Agent Benchmark analogue of the historical
Runmux B1 failure, not an exact reproduction: the original Runmux prompt and permission
snapshot are unavailable. All worker sessions used OpenCode 1.19.3, LM Studio 0.4.26.0,
Qwen3.8-27B Q4_K_M (`qwen38_23GB`), 98,304 context, `reasoning_effort=none`, and the
`file-tools-v1` role. The relevant coding attempts used a 16,384 output ceiling.

## Findings

### Visibility resume: intent was not retained

The first B1 implementation (`EXP_20261029_174653`) correctly refused to start another
request while `pendingController` was set. In `setVisible(true)`, it returned immediately
when a request was active. When that request settled, the `finally` block cleared the
controller and the normal completion path scheduled the regular interval. It did not
remember that visibility had returned, so it missed the required immediate follow-up.
The acceptance verifier observed one sample where it required two.

The task prompt required both “Never overlap requests” and “resume with one immediate
request when visible again.” It did not spell out their interaction when visibility returns
before the active request settles. This is a composition edge that a worker could infer,
but the task should state it directly. The verifier's sequence is valid: start one unresolved
request, hide, show, assert no overlap, settle the request, then require exactly one immediate
follow-up.

The one bounded repair (`EXP_20261029_181249`) added `resumeAfterInflight`. Visibility return
sets this intent while the controller remains active; after the response settles, the worker
clears the flag and calls `requestImmediate()` once. Terminal results clear the flag. The
repaired artifact passed the independent acceptance verifier (27 checks). This is a real
state-machine correction, not a coordinator patch or score rewrite.

### Single-flight: abort was mistaken for settlement

A separate fresh implementation (`EXP_20261029_181006`) failed the explicit single-flight
assertion: two fetches had started while the verifier expected one. Its `abortInFlight()`
called `controller.abort()` and immediately set `controller = null`. The visibility-hide path
then allowed visibility restore to call `request()` because the marker looked idle, although
the original fetch promise had not settled. Abort is a request to cancel; it is not proof that
the asynchronous operation has completed. The implementation therefore violated the explicit
“Never overlap requests” requirement.

This defect is distinct from the visibility-resume omission. The later bounded repair was
performed on the original visibility-resume artifact; it does not establish that the fresh
single-flight-failing artifact was repaired.

## Worker inspection and checks

The failed and repaired workers inspected the relevant source before editing (roughly seven to
nine read calls in the captured sessions). They used read, grep, write, and edit tools. The
effective `file-tools-v1` profile has no shell, despite version 1.0.0's instruction telling the
worker to run `node tests/polling_public_test.js`; the worker could not run that command. The
Agent Benchmark harness ran the public and independent acceptance verifiers after the worker
completed. Do not interpret the absence of worker-run tests as evidence that the implementation
was checked locally.

## Smallest changes likely to prevent recurrence

1. State the two coupled invariants: an aborted fetch remains in flight until its promise
   settles; visibility restored during a fetch queues exactly one immediate follow-up after
   settlement if the poller remains eligible.
2. Keep the active request/promise sentinel separate from whether its `AbortController` has
   been signaled. Only clear the sentinel in the promise's settlement path.
3. Make the harness, rather than a shell-less worker, run the public and hidden tests. Keep
   the worker prompt aligned with the effective tool profile.
4. During review, trace the state changes `visible -> hidden -> visible` while a request is
   unresolved and confirm the sequence is `one active request -> one settlement -> one
   immediate follow-up`, with no second request before settlement.

## Preserved evidence and provenance

Original visibility-resume first attempt:
`runs/EXP_20261029_174653/.../trial-001/S1/src/telemetry_polling.js`
(session `ses_e773a55caffeHj15DIE5tQPZrS`). Repair:
`runs/EXP_20261029_181249/.../trial-001/S1/src/telemetry_polling.js`
(session `ses_e77229381ffeCr10vlMTXdWKRW`). Separate single-flight failure:
`runs/EXP_20261029_181006/.../trial-001/S1/src/telemetry_polling.js`
(session `ses_e77251202ffejX5jWasdTRD7S2`). Raw session records and source snapshots remain
in the evidence tree and are not copied into this report.

Historical fixture revision 1.0.0 used instruction SHA-256
`9013c5b3c6c00d0bae24b6a65eecb12072c7e7789bb2388703d5b01d7064443f`; task manifest SHA-256
`95b54c6e145d62ba415faf61351651689d7334852ce28ce24ff86fcec722c111`; acceptance verifier
SHA-256 `7f2ddb176f6958796027450c9bc54ca6d7f1ece837b3a3f51f2a93efb71953dc`. The task is now
revision 1.0.1: its worker instruction clarifies the in-flight visibility edge and says the
harness runs tests, matching the shell-less tool profile. Historical first-attempt verdicts
and recorded fixture hashes remain unchanged.
