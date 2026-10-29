# T1 OpenCode session telemetry

Date: 2026-10-29 (UTC)

The merged `llm-monitor live` CLI in `main` reports module version 0.6.0 and exposes the documented project/session/trial/window options. The venv executable is `C:\Users\mcarls\src\scripts\.venv\Scripts\llm-monitor.exe`; it imports the same main-tree source at `modules/llm_monitor/llm_monitor`. Installed distribution metadata still reports 0.1.0. A prior 40-second live observation connected but did not return; this is consistent with the source path that blocks inside the SSE iterator without checking the deadline. The coordination agent found no direct LLM Monitor developer channel and reports the defect remains in its clean/pushed source. Port 4196 is currently running again, but the completed T1 sessions cannot be observed retroactively. No additional inference was dispatched for the Monitor version/deadline check.

This report summarizes persisted LLM Monitor observations for two fresh, independently verified `qwen-file-creation` trials. It is separate from the direct LM Studio reasoning probes. Both sessions used isolated OpenCode 1.19.3 on `http://127.0.0.1:4196`, model `qwen38-27b-q4km` Q4_K_M, context 98,304, and configured output limit 8,192. Exact session histories and normalized comparison evidence are in `telemetry.sqlite3` and `t1-monitor-comparison.json`.

| Trial | Requested profile | Outcome | Inferences | Input tokens per inference | Reasoning tokens per inference | Output tokens per inference | Time to first write | Tool outcomes |
|---|---|---|---:|---|---|---|---:|---|
| `EXP_20261029_152214` | No explicit reasoning field | Independent verifier passed | 3 | 2,917; 3,132; 3,335 | 15, 45, 95 | 80, 135, 151 | 4.73 s | read, write; both succeeded |
| `EXP_20261029_152614` | `reasoning_effort=none` | Independent verifier passed | 4 | 2,884; 3,119; 3,320; 3,619 | 0, 0, 0, 0 | 107, 179, 84, 77 | 4.65 s | glob, read, write, read; all succeeded |

All inferences completed. The first two baseline inferences and first three `none` inferences ended with `finish_reason=tool-calls`; the last inference in each session ended with `finish_reason=stop`. Monitor coverage is complete for both sessions. The session histories also report one successful write per session. The baseline reached its first write after its second inference; the `none` run wrote after its third inference. These token counts are per inference; they should not be added and interpreted as a single generation allowance.

The two results are one-off completions and do not establish reliability or a causal quality difference. The task is deliberately small. Agent Benchmark did not mark these runs leaderboard-eligible because effective settings were not independently observed at the runtime boundary, despite the requested profiles and model/context/output configuration being recorded.

The database contains device-level GPU samples without process attribution. No prompt or completion text was retained. Monitor history does not establish outbound request parameters; the sanitized mock-provider capture remains the evidence for OpenCode serialization.

`llm-monitor report --history` requires the endpoint when resolving these sessions, for example `--url http://127.0.0.1:4196`; initial lookups without that disambiguator produced `history_available=false`, despite the complete history being present. Inspection of `OpenCodeSSEClient.events()` shows it delegates to a blocking SSE iterator without checking the deadline until the iterator ends. Thus live OpenCode incremental event delivery remains unverified; persisted polling/history worked.
