# Krig lifecycle control — reviewed preparation

Status: **NO-GO for the supplied live procedure.** This document records code/API constraints, not a successful Krig acceptance test. See [Phase C review](PHASE_C_SAFETY_REVIEW.md).

Gemini reported a Krig 1.5.6 installation under the local Mining checkout and no active Kryptex/watchdog supervisor. These are historical observations, not independently verified current facts. This review performed no host topology or GPU probes and no live miner operations. Recheck actual executable, parent/child tree, scheduled tasks/services/launchers and exact identities before any separately authorized test. File presence, version help or a point-in-time process listing cannot certify future lifecycle behavior.

## Actual Windows control contract

| Launch/ownership | What the backend can establish | Conditions/limits |
| --- | --- | --- |
| Coordinator-owned, `new_console: false` | Starts a dedicated process group, retaining the inherited console; remembers the group PID | Caller and target must actually share a console. Sending break successfully does not establish exit. |
| Coordinator-owned, `new_console: true` | Starts a new console; no known signalable shared-console group is recorded | Graceful break is not assumed. With force disabled, stop refuses. |
| External process, any parent | Discovery by configured executable can provide PID/create-time snapshot | No console-group identity is established. Stop/restart require independent permissions; forceful stop also requires explicit force permission. Current template denies all three. |
| Watchdog/relaunch supervisor | A short absence scan may detect an immediate relaunch | A later relaunch remains possible; no continuous containment or supervisor handoff is implemented. |

Microsoft documents that [process-group control events](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent) reach group members sharing the caller's console. [Creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags) specify that NEW_PROCESS_GROUP is ignored with NEW_CONSOLE. Ownership alone does not prove a usable console exists. Do not attach to or signal a foreign console as an unreviewed workaround.

The backend verifies exact known PID/create-time identity, signals only its remembered group, scans for absence for 0.3 seconds, and checks captured descendants. Ambiguity/access denial is not success. The quiet interval and child snapshot do not cover delayed relaunch, detached descendants, or identity changes after a check. Forceful Windows termination is not graceful; no CUDA synchronization, share-flush duration, memory-release timing or full-VRAM availability has been established here. No implicit terminate/kill fallback is authorized by the revised template.

## Adoption and restart permissions

The template now sets `allow_external_stop`, `allow_external_restart`, `adopt_external`, and `allow_force_termination` to false, selects inherited-console group mode, and uses an explicit placeholder executable directory. It cannot intentionally adopt a matching external instance through those permissions. Turning both external permissions on can authorize external control even with `adopt_external: false`; that flag does not negate explicit permissions. Path matching alone cannot select one intended instance when multiple matching executables exist. No exact externally pinned-identity adoption workflow is supplied.

Literal argument placeholders must be replaced in a private, reviewed local test config; shell-style environment substitution is not supported. Do not commit credentials or assume configuration validation verifies binary ownership or safe arguments.

A coordinator-owned startup harness/control path is still missing from the CLI. `serve` does not launch mining, and standalone `miner pause/resume` remain disabled. Do not substitute an external manual launch and claim coordinator ownership. A separately reviewed startup/shutdown path and a separately authorized Windows acceptance test are required before any GO recommendation.
