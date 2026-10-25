# llm_monitor

Read-only diagnostics for locally hosted LLM coding sessions. Python 3.11+; install with `python -m pip install -e .` and run `llm-monitor --help`.

## Commands

```text
llm-monitor status [-u URL] [-d DIRECTORY] [-f text|json]
llm-monitor sessions [-u URL] [-d DIRECTORY] [-f text|json]
llm-monitor watch -s SESSION_ID [-i SECONDS] [-v] [-f text|json]
llm-monitor watch --all [-i SECONDS] [-v] [-f text|json]
llm-monitor diagnose -s SESSION_ID [-u URL] [-l LM_STUDIO_URL] [--mcp-jobs JSON] [-f text|json]
llm-monitor report -s SESSION_ID [-u URL] [-l LM_STUDIO_URL] [--mcp-jobs JSON] [-f text|json]
llm-monitor gpu [-f text|json]
```

OpenCode defaults to `http://127.0.0.1:4096`; LM Studio defaults to `http://127.0.0.1:1234`. The optional `--mcp-jobs` input is an explicit JSON snapshot; the monitor does not connect to MCP or invoke job operations. Its records are field-whitelisted, and directory-only matches are labeled hypotheses.

## Evidence and limits

The collector probes the documented cursor message endpoint once and uses it when the server returns its cursor envelope. Otherwise it polls the legacy bounded message endpoint with overlap and provider-ID deduplication. Polling retains a bounded metadata-only event cache. Full-history analysis labels a full legacy window partial; a short legacy response only describes the records returned and cannot prove older database history was never pruned.

Events retain IDs, timestamps, token categories, tool names and safe target metadata. Prompt text, source contents, tool output, and arbitrary MCP error text are not retained. Counts are `null` when a source is unavailable and scoped to observed history when coverage is partial.

Context utilization is only computed when the OpenCode model ID exactly matches a loaded LM Studio model and both configured and loaded context values are available. The estimate uses the smaller capacity minus the OpenCode output reservation. Cache read/write counts remain separate from input counts. Cumulative session token totals never stand in for a single request's context use.

Compaction counts are unique normalized operations; raw compaction parts are reported separately. Duration is shown only when both boundaries exist. Repeated-read findings are hypotheses based on recognizable tool metadata and exact normalized paths. Tool-reported edit success is not independent proof of file contents, tests, ownership, or task acceptance. `finish=stop` only describes one inference.

GPU output is a point-in-time device sample. Process memory is shown only where `resource_metrics` supports it. Device utilization and power are not attributed to a monitored session; the command does not create an inference peak sample.

`report` summarizes the history currently retrievable from OpenCode. It is not a persistent post-run forensic report. Phase 3 history storage and raw evidence export are out of scope.

## Development checks

Run `python -m pytest tests -q --basetemp=.pytest_tmp_root`. Tests use synthetic data and do not require a live model, server, MCP connection, or GPU.
