# Phase 3D Live Read-only Smoke Validation

**Date:** 2026-10-29  
**Environment:** Windows 11 host, Python 3.12, local loopback providers, NVIDIA telemetry available  
**Method:** Bounded GET-only requests and existing read-only telemetry commands. No inference, session edits, model loads, process control, or database changes were performed. Output was restricted to counts, field availability, statuses, and version metadata; identifiers, paths, prompts, arguments, and process names were not retained.

## Results

| Provider/capability | Result | Observed evidence | Limits |
|---|---|---|---|
| OpenCode health/version | Pass | `/global/health` returned HTTP 200, fields `healthy` and `version`, version `1.19.3`. | One configured local instance. |
| Session discovery | Pass | `/session` returned HTTP 200 and 5 sessions. | Snapshot only. |
| Message retrieval | Pass, legacy path | Bounded polling selected the legacy message endpoint; one session exposed 9 messages and complete bounded-window coverage. | Cursor endpoint was not negotiated; this is not proof of full session history. |
| Event normalization | Pass for sampled records | 22 normalized records: 9 message, 7 inference, 6 tool. All 7 inferences had token, finish, and duration fields; all 6 tool outcomes were `succeeded`; all 22 had timestamps. | Sampled session had no compaction parts, blockers, or failures to exercise those live cases. |
| LM Studio model inventory | Pass | `/api/v1/models` returned 11 records. | 0 loaded instances and 0 loaded context values; effective active context and model matching were unavailable. No fallback to theoretical maximum was used. |
| NVIDIA device telemetry | Pass | One GPU discovered; utilization, used/total VRAM, and temperature were available. | Power was unavailable in the regular device query; this was one point-in-time sample, not a peak or session attribution. |
| NVIDIA process memory | Pass | 32 compute-process records returned. | The validation counted records only and did not retain PIDs/names or attribute them to an OpenCode session. Memory attribution does not provide per-process utilization. |
| MCP job metadata | Partial | Read-only host job-list tool returned successfully with an empty retained-job array. | This host tool is not a stable Python adapter used by the module. Portable MCP integration remains explicit JSON snapshot correlation. |

## Interpretation

OpenCode 1.19.3's legacy message response matched the adapter's current list shape for this sample. Token and duration parsing worked on the observed records. The available evidence does not validate cursor pagination, in-progress message mutation, compaction lifecycle timing, permissions/questions, model identity changes, or reconnect sequences against live data.

LM Studio inventory was reachable but no model was loaded, so configured effective context was not testable. Hardware measurements were device-level point observations and are not correlated with the sampled session. The empty retained MCP list does not imply any worker failed or that no historical job existed.

The first unsandboxed loopback attempt was denied by Windows socket policy; the same bounded GET checks succeeded after the execution was approved for local read-only access. No live workloads were initiated.

## Validation levels

| Level | Status |
|---|---|
| Unit | `python -m pytest tests -v --basetemp=.pytest_tmp_phase3d_final --tb=short`: 88 passed, 1 skipped (POSIX-only permission test on Windows). |
| Contract | Seven synthetic adapter tests passed, including concurrent database readers, privacy projection, keyset paging, and offline handling; live OpenCode response was also parsed through the existing adapter. |
| Integration | LLM Monitor adapter + ObservabilityService + temporary SQLite tests; no Runmux route integration in scope. |
| Live read-only | OpenCode 1.19.3, LM Studio v1 inventory, and NVIDIA telemetry as above. |
| Controlled workload | Not performed; no inference authorization was given. |
| Unverified | Runmux browser/API end-to-end, loaded LM Studio context, MCP portable transport, OpenCode cursor/compaction/reconnect edge cases. |

## Synthetic adapter workload

One synthetic run on Windows 11 / Python 3.12.10 used temporary SQLite databases with 100 normalized inference events per session. Each page query returned 100 events. One `snapshot()` exercised the fake client and one 100-row timeline page was measured; the repeated-query figure is the median of five additional identical page reads. Values are wall seconds from one run and are not production guarantees.

| Sessions | Stored rows (including session/checkpoint records) | Snapshot seconds | First page seconds | Repeated page median seconds |
|---:|---:|---:|---:|---:|
| 1 | 102 | 0.0030 | 0.0061 | 0.0060 |
| 10 | 1,020 | 0.0037 | 0.0063 | 0.0065 |
| 50 | 5,100 | 0.0069 | 0.0072 | 0.0068 |

`ruff check llm_monitor/runmux_adapter.py llm_monitor/storage.py tests/runmux_adapter_test.py`, `python -m compileall -q llm_monitor`, and `git diff --check` passed. A whole-module Ruff scan reported seven existing findings in untouched files (`alerts.py`, `cli.py`, `diagnostics.py`, `history_analysis.py`, and `tests/alerts_test.py`); no unrelated cleanup was included. CLI help succeeded. Wheel build succeeded with `python -m pip wheel . --no-deps --no-build-isolation`; the isolated build attempt could not reach PyPI to provision build dependencies, and the default pip temp directory had an ACL error before retrying within the worktree.
