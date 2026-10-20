# First supervised acceptance test — review gates

**Review outcome: CONDITIONAL GO. Operational state: NO-GO until all gates below have evidence and the user separately authorizes execution.** Codex's recommendation is not execution authorization. No live work was done during this review.

Scope: one normal, sequential non-streaming `/v1/chat/completions` request, preloaded idle Qwen, no tools, one GPU/client and one coordinator-owned miner. Interruptions, native APIs, streams, recovery, crash continuation and model operations are outside this first test.

## Required independently verifiable evidence

1. Pin the reviewed branch/commit and private config. Retain `new_console=false`, external stop/restart/adoption=false, force=false. Exact executable, working directory, arguments, device and policy mapping must be reviewed; placeholders are not usable configuration. Use the real CLI/factory/lifespan and default managed gateway, never standalone mode. Config preflight passing proves configuration checks, not upstream idle or watchdog absence.
2. Record installed LM Studio/Krig versions and exact launch context. Establish dedicated coordinator-owned group in the same console, expected CTRL_BREAK behavior and no unrelated group members. The stop path must positively verify exact original identity and known descendants absent before forwarding; failure vetoes the request and aborts the experiment. No force fallback or external adoption. Initial `--start-miner` is explicit authority only after this test itself is authorized.
3. Exclude all competing clients, services, scheduled tasks, wrappers, watchdogs, miners and independent coordinators/launchers. Absence of a Windows service alone is insufficient. **Traffic sent directly to LM Studio port 1234 bypasses protection.** Isolate both ports and ensure only the designated client uses the coordinator. No model-loading hooks or independent process actions.
4. Independently verify the designated Qwen is preloaded and execution idle, with no queued/unknown requests. Measure actual VRAM and compute headroom for resident Qwen plus mining on this GPU; no assumed model-size estimate is acceptance evidence. Loading/unloading is separate operator work, outside review authority.
5. Configure the private operator token in service and operator terminal; review authenticated abort and out-of-band exact-identity intervention. Maintain a present operator and independent observations. Abort endpoint existence is not upstream cancellation or physical shutdown proof.
6. Review the strict crash-abort protocol: any crash, stall, timeout, uncertain result or unexpected restart ends the experiment. No automatic relaunch, inhibition clearing, process restart or recovery to continue. Keep launchers disabled until all possibly active execution is independently reconciled. Agree how the operator will achieve that if the gateway is unresponsive.
7. Review offline evidence and obtain **separate explicit user authorization** specifying this one experiment, launch flags, endpoint/model, stop conditions and operator intervention authority. No gate has been certified from live host inspection in this review.

## Sequence to include in a separately authorized runbook

- Start the single managed service with explicit initial miner launch and shutdown-stop flags; record READY only after positive coordinator-owned RUNNING verification.
- Submit exactly one small non-streaming chat request through port 1235. Observe pending claim and verified miner absence before upstream forwarding. Require HTTP 200 and normal completion; errors/uncertainty abort.
- Observe the configured full cooldown with no early restart. Verify the subsequent miner identity is coordinator-owned and no inference remains active.
- Gracefully shut down after the request. Verify miner absence, gateway termination and no delayed relaunch. A stopped service alone is insufficient evidence.
- Review logs/observations; any discrepancy fails acceptance and returns NO-GO. No second request or interruption experiment is implied.

Read [abort/crash procedure](EMERGENCY_ABORT_PROCEDURE.md) before authorization. Shutdown drain has a deadline, but synchronous Windows calls can delay total shutdown; never treat elapsed timeout as proof of termination.

Unattended operation remains NO-GO pending write-ahead safety persistence/startup reconciliation, cross-resource transactions, single-instance authority/containment and reviewed real Windows/TCP/crash evidence. See [the full review](PHASE_D_SAFETY_REVIEW.md).
