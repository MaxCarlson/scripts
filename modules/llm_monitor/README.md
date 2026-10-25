# llm_monitor

Read-only diagnostics and optional local telemetry recording for locally hosted LLM coding sessions. Python 3.11+; install with `python -m pip install -e .` and run `llm-monitor --help`.

## Commands

```text
llm-monitor status [-u URL] [-d DIRECTORY] [-f text|json]
llm-monitor sessions [-u URL] [-d DIRECTORY] [-f text|json]
llm-monitor watch -s SESSION_ID [-i SECONDS] [-v] [-f text|json]
llm-monitor watch --all [-i SECONDS] [-v] [-f text|json]
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
```

OpenCode defaults to `http://127.0.0.1:4096`; LM Studio defaults to `http://127.0.0.1:1234`. `-d/--directory` remains the OpenCode project-directory option on existing live commands; database commands use `-d/--database`. The historical `report` uses `-D/--database` to preserve that existing directory flag. Optional `--mcp-jobs` input is an explicit JSON snapshot; the monitor does not connect to MCP or invoke job operations.

## Persistent collection

Recording is opt-in. `watch` remains an in-memory live view and does not write the telemetry database.

```powershell
llm-monitor record --all --interval 2 --hardware
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

By default, the database is outside the current directory: `%LOCALAPPDATA%\\llm-monitor\\telemetry.sqlite3` on Windows, `~/Library/Application Support/llm-monitor/telemetry.sqlite3` on macOS, and `$XDG_DATA_HOME/llm-monitor/telemetry.sqlite3` on Linux, WSL2, and Termux (falling back to `~/.local/share`). Set `-d/--database` to choose a different file. The current schema is version 1. New databases use SQLite WAL; event batches and their checkpoints commit in one transaction. SQLite serializes writers and unique event keys make repeated polling idempotent. Multiple sessions can be recorded by one `record --all` process; independent processes can share the database through SQLite locking.

New sessions receive one initial history collection. Later cycles use the existing bounded/cursor-aware OpenCode poller. A restart replays the available overlap and records an offline gap; older events outside a provider's bounded window cannot be reconstructed. Partial and unavailable intervals remain represented as gaps. A historical report reads only stored telemetry, so it works without OpenCode but can only cover monitoring observations.

## Privacy, retention, and integrity

The store keeps normalized metadata, timestamps, identifiers, token/timing data, tool names/outcomes, model configuration, safe coverage metadata, and optional hardware samples. It excludes prompt/response text, source contents, tool outputs, raw provider responses, MCP error bodies, working directories, session titles, and tool arguments. Recognized file targets are stored as SHA-256 identifiers. Process names in hardware attribution are hashed; device metrics remain device-level and are not assigned to a session. On POSIX, the database and newly created parent directory are restricted to the current user.

Automatic retention is disabled. `db prune` previews event and hardware rows older than the requested age; only `--write` deletes them. A coverage gap is retained for sessions whose events were pruned. Back up the database with SQLite's backup API or while the monitor is stopped; WAL databases may have uncheckpointed data in sidecar files. Do not copy or point the tool at OpenCode's own database. `db check` runs SQLite integrity and foreign-key checks. Unsupported future schema versions and incomplete databases are rejected without replacement.

## Evidence and metric limits

The collector probes a cursor message endpoint when supported, otherwise uses bounded recent-message polling with overlap and provider-ID deduplication. A monitor starting late reports its observable window; it does not claim complete earlier history. Session cumulative token totals remain distinct from per-inference counts. Context utilization is computed only when stored OpenCode limits and a matching loaded LM Studio context are available. Compactions are unique normalized operations; raw parts remain separate and durations require both boundaries.

`finish=stop` ends one inference only. Provider/session completion, work-product completion, and task acceptance remain distinct. Edit-tool success is not independent proof of file contents, tests, ownership, or acceptance. Optional MCP correlation uses an explicit supplied JSON snapshot and is not a live MCP transport. GPU readings are timestamped device or process measurements; point-in-time utilization/power are not attributable to a session and do not establish inference peaks. Missing observations are not treated as zero activity.

## Development checks

Run `python -m pytest tests -q --basetemp=.pytest_tmp_root`. Tests use synthetic data and do not require a live model, server, MCP connection, or GPU.
