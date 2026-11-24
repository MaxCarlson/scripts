# Coordinator and Docker qualification diagnosis

- Incident interval: 2026-11-24T01:17:59Z through 2026-11-24T01:30:10Z (2026-11-23 17:17:59–17:30:10 local).
- Evidence collected read-only from existing Windows, Coordinator, Docker, WSL, mining, benchmark, and local-agent-bridge records.
- Repository evidence baseline: branch agent/harbor-route-preflight-20261123, prior HEAD ec534a84e18a4b7a239b388f75de8d6a6da5a98b.
- No service was restarted, no container was created, no inference was sent, and no safety/mining/configuration state was changed.

## Finding

The reason Coordinator PID 53788 disappeared cannot be determined from the retained evidence. There is no Coordinator shutdown, crash, or process-exit record for the incident interval. The Docker and WSL resource spike overlaps the qualification window, but the Coordinator is launched by a native Windows Python process; the available records do not prove that Docker/WSL caused its exit.

The most specific pre-incident Coordinator error is a client connection reset at 2026-11-24T01:12:27.366Z (local 17:12:27), 5 minutes 32 seconds before the interval. It is an asyncio Proactor transport ConnectionResetError / WinError 10054 and does not identify the process exit. The next Coordinator log lines are at 17:36:39 local, after the interval; they include a lifecycle restart-gate warning and a service startup banner, but do not explain when or why PID 53788 ended.

## Evidence and limits

| Source | Observed evidence | Interpretation limit |
| --- | --- | --- |
| Coordinator log | No lines in the stated interval. Last pre-window exception was the 17:12:27 client connection reset. | No exit cause, exit code, or termination actor is logged. Absence of log entries does not show the process was healthy or stopped. |
| Managed runtime | The installed managed launcher invokes native Windows Python, writes coordinator.log/state, and points PYTHONPATH at external worktree C:\Users\mcarls\src\llm-agent-toolkit\.worktrees\delegation-teardown-20261123 (branch feat/delegation-teardown-20261123, HEAD 6283f20f42db6e7ee125bb07752891d0899643). It is managed by the ResourceCoordinator-KRig-UserLogon scheduled task. | This is an active ownership boundary. Do not edit or restart it from this assignment. The deployed launcher/code identity is not the scripts repository's read-only module checkout. |
| Task Scheduler | UserLogon task was enabled, Status Ready; last run 2026-11-23 15:24:22 local, last result -1. The named Boot task was not found. Task Scheduler Operational channel is disabled. | Last run predates the incident. No task history establishes a launch, stop, or failure during the window. |
| Windows event logs | System log had three informational Hyper-V WSL switch create/connect/delete events at 01:23:28Z and 01:28:38Z. Security query for process create/exit IDs 4688/4689 returned no events in the interval. | The Hyper-V events align with Docker/WSL startup and cleanup. Security results do not establish that process auditing was disabled; they provide no PID exit evidence. |
| Coordinator state snapshot | coordinator_state.json was last written 2026-11-24T01:42:17.853Z, after the window. No persisted request record showed an update timestamp inside the interval. | It is a later snapshot, not a process lifecycle journal, and cannot identify why PID 53788 disappeared. |
| Docker Desktop | At 01:24:35Z the API proxy's /_ping failed to dial 192.168.65.7:2376; at 01:24:42Z the Docker events request timed out and event streamer returned HTTP 500. At 01:25:35Z logs still said it was waiting for the Docker daemon. Desktop was explicitly stopped later; no diagnostic container was created. | Docker engine was not qualified and image inventory was not read. This failure explains why container-route checks could not proceed, not the Coordinator exit. |
| Docker VM log | Structured incident-window scan found the OOM tracer startup at 01:25:35Z and no matching OOM, killed-process, panic, or fatal message fields. | This is not proof that Windows or WSL had no resource failure; no complete kernel/ETW process history was collected. |
| WSL/resource observations | .wslconfig specifies memory=8GB, swap=0, autoMemoryReclaim=dropcache. During the prior authorized Docker startup, vmmemWSL reached about 6.48 GiB, host free RAM fell to about 19.86 GiB, disk reads reached about 72.4 MiB/s with queue 11, and GPU utilization/power fell to about 7%/65.81W. After cleanup, memory/disk/GPU returned near baseline. | These are temporal resource observations, not a causal link to the Coordinator exit. |
| KRig output log | Retrospective timestamped output includes accepted shares during the interval. It contains repeated/appended streams whose counters diverge at matching times (for example, totals around 14 and 3141 near 17:25 local). | The file does not provide a trustworthy PID-bound single trajectory for the interval. Mining activity is evidenced, but rate/share impact attributable to Docker or Coordinator is unknown. The qualification-time monitor had not captured mining output telemetry. |

## Recovery boundary and safest next steps

1. Keep Docker, WSL, and Coordinator in their last recorded post-qualification state until an operator explicitly authorizes a new window. Do not try to reproduce the disappearance.
2. Coordinator recovery requires separate explicit authorization to start the managed Coordinator launcher because that runtime owns miner lifecycle controls. Before the authorized start, the service owner should confirm the intended external worktree/runtime identity and expected miner state. Capture the launcher's exit code, process identity/creation time, parent process, stdout/stderr, and Coordinator status/runtime identity. Do not edit the external worktree or scheduled task as part of recovery.
3. A future Docker route qualification requires explicit authorization to start Docker Desktop and its WSL2 backend and create one disposable diagnostic container. Before startup, establish a resource/mining baseline and operator-defined abort thresholds. If readings cross those thresholds, stop the qualification safely and report measurements.
4. First run bounded read-only Docker daemon and local image inventory checks. Continue only if Docker reports a healthy engine and the exact approved Harbor worker image is already present. Image pull/download, WSL limit changes, or network-policy changes each require separate authorization and are outside this assignment.
5. Using that present approved image and an already-approved network, issue GET-only probes to the Coordinator status and authenticated Monitor status/model inventory. Confirm endpoint identity, protected upstream, runtime continuity, and Monitor readiness. Do not send chat/completion, response, generation, load/unload, or other inference-triggering requests. A status GET establishes readiness only; it does not prove future per-request admission.
6. Record direct protected-route readiness, monitored-route readiness, and isolated-study network receipt status as separate results. A generic host connectivity probe is not a run-bound isolated-study receipt. Clean up the one disposable container and return Docker/WSL to their original state if the operator requests that cleanup and no unrelated workload is affected.

For root-cause certainty, the missing evidence is an event/process lifecycle record for PID 53788 in the interval. A later read-only snapshot cannot recreate that history. Enabling new process/Task Scheduler audit channels or installing tracing is a separate host-configuration change and needs explicit authorization.

## Docker-independent delegation readiness

The shortest existing native path is a one-task disposable fixture through the connected OpenCode worker MCP, with the exact job/session/message IDs, baseline, resulting diff hash, and independent verifier output retained. The existing local_agent_bridge validation record documents a real connected-MCP worker edit and focused test, but its 2026-10-24 Codex CLI acceptance also records that enabled ephemeral Codex sessions returned NO_TOOL for opencode_worker. Current AGY tool exposure has not been verified. Treat that historical blocker as requiring a fresh read-only capability check in the actual AGY process before dispatch.

No agent_benchmark backend currently measures actual Codex/AGY-to-MCP-to-OpenCode delegation:
- harbor uses Docker and is an official Harbor execution path.
- direct_chat sends a real model chat-completion request and is not a delegation path.
- mock is offline and deterministic; it can verify suite plumbing but cannot establish actual worker delegation.
Do not label a native delegation fixture as an official Harbor score.

Actual worker delegation would send a model request and allow fixture edits, so it requires separate explicit authorization for local inference and scoped worker execution. Before that authorization, the only non-inference step is a capability-only check that the actual AGY process exposes the intended MCP tool; no task dispatch should occur. Independent verification should run outside the worker after inspecting the fixture diff and sentinel hash.

## Separately authorized benchmark execution path

The existing one-task monitored Harbor smoke recorded in monitor-coordinator-live-noninference-20261124.json was not executed. Its exact command from modules/agent_benchmark is:

    python -m agent_benchmark.cli suite run -M .\docs\qualification\aider-revision-smoke.json -a opencode -m openai/qwen38_23GB -L -R content -A openai_chat_completions -j 1 -F -U http://host.docker.internal:8789/v1 -H http://127.0.0.1:8789 -x

This command sends real benchmark inference and must not be run without separate explicit authorization. The report lists the required prerequisites: healthy Docker engine and already-present approved Harbor image; separately authorized isolated Monitor on port 8789 routed to Coordinator :1235; fresh matching authenticated runtime/readiness identities and no active safety restrictions; a model present in fresh LM Studio inventory; a valid frozen Harbor dataset/toolchain; stable resource/mining readings; and a valid run-bound network receipt if the selected study requires one. The prior qualification observed zero LM Studio models, so model readiness remains unqualified.

## Evidence provenance

- Coordinator: %USERPROFILE%\.resource_coordinator\coordinator.log, coordinator_state.json, config.yaml, start-coordinator-managed.ps1, scheduled task query.
- Windows: System and Security event queries for the exact interval; Task Scheduler Operational was disabled.
- Docker: %LOCALAPPDATA%\Docker\log\host\monitor.log, com.docker.backend.exe.log and rotated log, Docker Desktop stdout/stderr, vm\init.log.
- Host limits: %USERPROFILE%\.wslconfig.
- Mining: %USERPROFILE%\.resource_coordinator\krig-output.log (summary fields only; no pool/job identifiers persisted).
- Repo evidence: modules/agent_benchmark/docs/qualification/monitor-coordinator-live-noninference-20261124.json; modules/local_agent_bridge/docs/VALIDATION.md, BENCHMARK.md, and agent_benchmark execution backend source.
