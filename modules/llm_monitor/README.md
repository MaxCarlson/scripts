# llm_monitor

Read-only diagnostics and optional local telemetry recording for locally hosted LLM coding sessions. Python 3.11+; install with `python -m pip install -e .` and run `llm-monitor --help`.

## Commands

```text
llm-monitor status [-u URL] [-d DIRECTORY] [-f text|json]
llm-monitor sessions [-u URL] [-d DIRECTORY] [-f text|json]
llm-monitor watch -s SESSION_ID [-i SECONDS] [-v] [-f text|json]
llm-monitor watch --all [-i SECONDS] [-v] [-f text|json]
llm-monitor live -p PROJECT_DIRECTORY -s SESSION_ID [-u URL] [-t SECONDS] [-f text|json]
llm-monitor diagnose -s SESSION_ID [-u URL] [-l LM_STUDIO_URL] [--mcp-jobs JSON] [-f text|json]
llm-monitor report -s SESSION_ID [-u URL] [-l LM_STUDIO_URL] [--mcp-jobs JSON] [-f text|json]
llm-monitor record -s SESSION_ID [-i SECONDS] [-d DATABASE] [-f text|json]
llm-monitor record --all [-i SECONDS] [-d DATABASE] [-g] [-f text|json]
llm-monitor history [-s SESSION_ID] [-d DATABASE] [-f text|json]
llm-monitor report -s SESSION_ID --history [-D DATABASE] [-f text|json]
llm-monitor db info [-d DATABASE] [-f text|json]
llm-monitor db check [-d DATABASE] [-f text|json]
llm-monitor db prune -r DAYS [-d DATABASE] [-w] [-f text|json]
llm-monitor gpu [-f text|json]
llm-monitor tui [-s SESSION_ID | -a] [-d DATABASE] [-i SECONDS]
llm-monitor alerts list|rules|test|acknowledge [options]
```

OpenCode defaults to `http://127.0.0.1:4096`; LM Studio defaults to `http://127.0.0.1:1234`. `-d/--directory` remains the OpenCode project-directory option on existing live commands; database commands use `-d/--database`. The historical `report` uses `-D/--database` to preserve that existing directory flag. Optional `--mcp-jobs` input is an explicit JSON snapshot; the monitor does not connect to MCP or invoke job operations.

## Live reasoning diagnostics

`live` is an opt-in, read-only OpenCode SSE observer for one exact project and session. It reconciles the session summary and bounded tool history before and after the event window. Text output runs until interrupted unless `--observe-seconds` is supplied. JSON always requires a bounded window:

```powershell
llm-monitor live --url http://127.0.0.1:4096 `
  --project-directory 'C:\path\to\pilot' --session ses_example `
  --observe-seconds 5 --format json

# Continuous compact terminal display
llm-monitor live -p 'C:\path\to\pilot' -s ses_example

# Reasoning text is sensitive and hidden unless explicitly requested
llm-monitor live -p 'C:\path\to\pilot' -s ses_example --show-reasoning
```

The stream capability is one of `streaming`, `completion_only`, `activity_only`, or `unavailable`. A healthy event connection with no incremental content is not called a stall. Reconnection gaps and malformed/oversized frames mark coverage incomplete. Reasoning and ordinary output character counts are separate from exact token usage; `current_reasoning_tokens` stays `null`. The observer never persists reasoning and does not cancel or restart workers.

The JSON `reasoning_configuration` object keeps reported settings separate from independently captured outbound parameters. `--requested-variant` is an operator-reported expectation. OpenCode's `session_recorded_variant`, model alias options, limits, completed-message token statistics, and optional LM Studio loaded-model capabilities each identify their source and verification status. A variant recorded by OpenCode does not prove the same parameter reached LM Studio. `--lmstudio-url` opts into a read-only model inventory lookup; it does not issue an inference request.

An external experimental harness may supply sanitized outbound request evidence with `--request-evidence evidence.json`. Evidence uses schema version 1 and records `session_id`, `message_id`, exact `message_created_at`, `request_observed_at`, `provider`, `model`, and an allowlisted `parameters` object. LLM Monitor accepts only an exact session/message/creation-time match and only `reasoning`, `reasoning_effort`, `max_tokens`, `max_output_tokens`, `temperature`, `top_p`, and `top_k`. Prompts, credentials, and full request bodies are not accepted or persisted. This is a correlation interface; the passive monitor does not intercept provider traffic.

Advisory diagnostics include `length_finish`, reasoning allowance exhaustion, no successful file edits when stored history coverage is complete, long read-only discovery sequences, repeated tool calls, quiet periods during extended inference, and differences from reported limits. These observations do not establish a model defect. See the [OpenCode 1.19.3 compatibility report](docs/validation/live-reasoning-opencode-1.19.3-20261029.md).

For a future Codex coordinator, `opencode_worker` can expose the bounded `live --observe-seconds N --format json` result for the already selected project/session. Keep that bridge read-only, omit reasoning text by default, preserve the snapshot's source/status fields, and do not treat missing events as a reason to intervene. No MCP contract changes are part of this release.

## Persistent collection

Recording is opt-in. `watch` remains an in-memory live view and does not write the telemetry database.

```powershell
llm-monitor record --all --project-directory "C:\\path\\to\\project" --interval 2 --hardware
llm-monitor history
llm-monitor report --session SESSION_ID --history --format json
llm-monitor db info
llm-monitor db check
llm-monitor db prune --older-than-days 90   # preview only
llm-monitor db prune --older-than-days 90 --write
```

```sh
llm-monitor record --session SESSION_ID --interval 2 --database ./telemetry.sqlite3
llm-monitor history --session SESSION_ID --database ./telemetry.sqlite3 --format json
llm-monitor report --session SESSION_ID --history --database ./telemetry.sqlite3
```

By default, the database is outside the current directory: `%LOCALAPPDATA%\\llm-monitor\\telemetry.sqlite3` on Windows, `~/Library/Application Support/llm-monitor/telemetry.sqlite3` on macOS, and `$XDG_DATA_HOME/llm-monitor/telemetry.sqlite3` on Linux, WSL2, and Termux (falling back to `~/.local/share`). Set `-d/--database` to choose a different file. The current schema is version 2; opening a writable v1 database performs a transactional forward migration that adds local alert state. Read-only history access remains compatible with v1. New databases use SQLite WAL; event batches and their checkpoints commit in one transaction. SQLite serializes writers and unique event keys make repeated polling idempotent. Multiple sessions can be recorded by one `record --all` process; independent processes can share the database through SQLite locking.

`record --all` discovers every session visible to the selected OpenCode project. Pass `-p/--project-directory` for the worker's project context; OpenCode may group sibling worktrees under one project, so discovered sessions can show other worktree paths. Use `--session` to pin recording to one worker session. The recorder prints the sanitized server origin and selected scope each cycle so a project mismatch is visible. Verify discovery before recording with `llm-monitor sessions --url URL --directory PATH`.

New sessions receive one initial history collection. Later cycles use the existing bounded/cursor-aware OpenCode poller. A restart replays the available overlap and records an offline gap; older events outside a provider's bounded window cannot be reconstructed. Partial and unavailable intervals remain represented as gaps. A historical report reads only stored telemetry, so it works without OpenCode but can only cover monitoring observations.

## Privacy, retention, and integrity

The store keeps normalized metadata, timestamps, identifiers, token/timing data, tool names/outcomes, model configuration, safe coverage metadata, and optional hardware samples. It excludes prompt/response text, source contents, tool outputs, raw provider responses, MCP error bodies, working directories, session titles, and tool arguments. Recognized file targets are stored as SHA-256 identifiers. Process names in hardware attribution are hashed; device metrics remain device-level and are not assigned to a session. On POSIX, the database and newly created parent directory are restricted to the current user.

Automatic retention is disabled. `db prune` previews event and hardware rows older than the requested age; only `--write` deletes them. A coverage gap is retained for sessions whose events were pruned. Back up the database with SQLite's backup API or while the monitor is stopped; WAL databases may have uncheckpointed data in sidecar files. Do not copy or point the tool at OpenCode's own database. `db check` runs SQLite integrity and foreign-key checks. Unsupported future schema versions and incomplete databases are rejected without replacement.

## Evidence and metric limits

The collector probes a cursor message endpoint when supported, otherwise uses bounded recent-message polling with overlap and provider-ID deduplication. A monitor starting late reports its observable window; it does not claim complete earlier history. Session cumulative token totals remain distinct from per-inference counts. Context utilization is computed only when stored OpenCode limits and a matching loaded LM Studio context are available. Compactions are unique normalized operations; raw parts remain separate and durations require both boundaries.

`finish=stop` ends one inference only. Provider/session completion, work-product completion, and task acceptance remain distinct. Edit-tool success is not independent proof of file contents, tests, ownership, or acceptance. Optional MCP correlation uses an explicit supplied JSON snapshot and is not a live MCP transport. GPU readings are timestamped device or process measurements; point-in-time utilization/power are not attributable to a session and do not establish inference peaks. Missing observations are not treated as zero activity.

## Historical comparison, export, and visualization

`compare` analyzes two or more stored sessions offline. It presents deltas against the first session and reports coverage, model, context, hardware-sampling, and task-equivalence caveats. Percentage differences are omitted when the baseline is unknown or zero. These are descriptive comparisons, not statistical significance or causal claims; absent task/acceptance metadata means outcomes cannot be assumed equivalent.

```powershell
llm-monitor compare -s SESSION_A -s SESSION_B -d "$env:LOCALAPPDATA\llm-monitor\telemetry.sqlite3" -f json
llm-monitor export -s SESSION_A -s SESSION_B -o .\runs.zip                 # preview; no file written
llm-monitor export -s SESSION_A -s SESSION_B -o .\runs.zip --write -F csv
llm-monitor export --action verify -o .\runs.zip
llm-monitor visualize -s SESSION_A -o .\timeline.svg --write
llm-monitor tui --all --interval 2
llm-monitor tui --session SESSION_ID --database .\telemetry.sqlite3
llm-monitor tui --all --persist-alerts --database .\telemetry.sqlite3
llm-monitor alerts rules --format json
llm-monitor alerts test --session SESSION_ID --database .\telemetry.sqlite3 --format json
llm-monitor alerts list --database .\telemetry.sqlite3
llm-monitor alerts acknowledge --id ALERT_ID --database .\telemetry.sqlite3
```

```sh
llm-monitor compare -s SESSION_A -s SESSION_B --database ./telemetry.sqlite3
llm-monitor export -s SESSION_A -o ./evidence.zip --write
llm-monitor visualize -s SESSION_A -o ./timeline.html --format html --write
llm-monitor tui --all --interval 2
llm-monitor alerts test --session SESSION_ID --database ./telemetry.sqlite3 --format json
```

Export creation previews unless `--write` is supplied. The ZIP contains session metadata, normalized event rows, analysis, coverage gaps, configuration, optional sampled hardware observations, and a manifest with per-file SHA-256 checksums. It serializes only the privacy-safe telemetry already stored: prompts, responses, source content, tool output, and raw arguments are not reconstructed. CSV cells are guarded against spreadsheet formula interpretation. Verification checks package structure and checksums; a valid checksum proves package integrity, not provider authenticity. Export schema is version 1; the manifest reports the actual source telemetry schema version.

`visualize` produces a static SVG timeline or self-contained HTML wrapper. It previews metadata by default and writes only with `--write`. The current view marks known inference, tool, compaction, lifecycle, and hardware events; it does not interpolate missing intervals or fabricate continuous hardware samples. Comparison visualization shows observed wall-duration bars. Large event histories use the analyzer's bounded marker sampling. Percentiles require at least five samples. Message-boundary throughput is approximate and is not decode throughput. Time categories are interval unions; unclassified wall time is not called idle. Sampled state durations are limited to their observed coverage and may be unavailable for older transition-only histories.

## Interactive dashboard and alerts

`tui` is a live-only consumer of the shared `ObservabilityService`; it does not start persistent recording. Historical sessions are included when a database is available. Use arrows or `j/k` to select, Enter to inspect, Tab to change sections, `/` to filter, `s` to cycle session/state/context/activity sorting, `r` to refresh, `p` to pause display refreshes, `[`/`]` to scroll, `?` for help, and `q` to exit. Pause affects the dashboard's own refresh loop only. A TTY is required; use `watch`, `status`, or `report` for non-interactive output. Hardware readings remain device-level unless source data explicitly provides process attribution.

Alerts are local diagnostic state, not external notifications. `alerts test` evaluates stored session evidence without writing; `alerts list` reads existing alert state; `alerts acknowledge` explicitly changes local telemetry state. `tui --persist-alerts` opts into persisting alert state and migrates a v1 database to schema v2 if needed. Rules distinguish observation from confidence; missing metrics do not trigger numerical alerts. Sustained hardware-pressure and recorder/database-error alerts are not emitted because this release has no shared sampled hardware alert stream or recorder error feed. No external notification destinations are configured by this module.

The reusable snapshot/detail envelope and authenticated-host mapping are documented in [docs/API.md](docs/API.md). `llm_monitor.runmux_adapter.RunmuxMonitoringAdapter` provides framework-neutral snapshot, detail, persisted timeline, and stored-alert reads over the existing service and store. It does not implement HTTP routes or authentication. The host must preserve provider-instance/session identity and enforce its existing authentication, origin, and no-store protections. See [the original Runmux integration contract](docs/RUNMUX_INTEGRATION_HANDOFF.md) and the [verified Runmux host implementation handoff](docs/RUNMUX_HOST_IMPLEMENTATION_HANDOFF.md). This module does not modify Runmux or expose an HTTP server.

## Development checks

Run `python -m pytest tests -q --basetemp=.pytest_tmp_root`. Tests use synthetic data and do not require a live model, server, MCP connection, or GPU.
