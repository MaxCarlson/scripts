# LLM Monitor Phase 3B Plan

## Goal

Make persisted telemetry useful for offline session comparison, historical diagnostics, privacy-safe evidence export, and static visualization without changing the live collector architecture or Phase 3A database schema.

## Baseline and constraints

- Base commit: published Phase 3A `6701f3a698680d07b3d1ef3ee37e85aed32d94f3`.
- Python 3.11+, SQLite schema v1, no mandatory runtime dependency additions.
- Preserve existing CLI flags and JSON fields. Keep `report --history` offline.
- Do not alter provider databases, run inference, edit `local_agent_bridge`, or touch unrelated worktrees/root-checkout changes.
- Export and visualization are preview-only unless `--write` is present.
- Never export prompts, responses, source content, tool output, raw arguments, or endpoint credentials.

## Approaches considered

1. **Analyze the existing 10,000-event report page.** Lowest implementation cost, but historical statistics would silently omit earlier events. Rejected for comparison/export.
2. **Load every event into memory for each command.** Straightforward and compatible with current list-based rules, but scales poorly and complicates large exports. Rejected as the primary data path.
3. **Add a read-only streaming store API and a shared history analyzer, then make compare/export/SVG consumers of its structured result.** This preserves current storage and collectors, provides complete offline history, and keeps formatting out of SQL. Selected.

## Design decisions

- Add `TelemetryStore.session_context()` and `iter_session_records()` so analyses/export can stream all events in deterministic order while loading only bounded pages. Keep `history_bundle()` and its current semantics for compatibility.
- Record one sanitized `lifecycle/state_observation` event per persisted poll (state, blocker counts, coverage state, error source names). Use the existing events table and provider/session identity, so schema v1 databases need no migration. Older records without these samples retain unknown idle/waiting duration.
- Implement reusable `history_analysis.py` APIs for aggregation, interval union, sampled-state accounting, timeline projection, comparison, and historical findings. Existing diagnostics remain in use by the current report; new findings are aggregated by rule and identify their evidence references.
- Represent duration metrics with value, method, sample count, time range, and coverage. Compute per-category interval unions and combined activity union separately; never sum overlapping categories as wall time. Unclassified time remains unknown, not idle.
- Use exact descriptive percentiles over observed metric values. Mark small samples and incomplete histories; do not make statistical significance claims.
- Compare two or more sessions against the first selected run, with absolute and percentage deltas only for known nonzero denominators. Include fairness warnings for unknown task equivalence, model/config changes, and coverage differences. Do not add persisted user annotations or migrate the schema in this phase.
- Export a ZIP package built only from sanitized database records. Include JSON summary/diagnostics, JSONL timeline/events, and CSV analytical tables; record member hashes/counts/redaction policy in `manifest.json`. Verify member paths and SHA-256 values. Dry-run reports contents and counts without creating files; `--write` writes via a sibling temporary archive then atomically replaces the target.
- Generate a self-contained static SVG from the same structured analysis. Escape all text, downsample only visual marks with an explicit aggregation note, and require `--write` for output. No external resources or network dependencies.
- Keep output schema version 1 for established report fields; add new `historical_analytics` and `comparison` sections without changing prior field meanings.

## Planned files

- `llm_monitor/storage.py`: bounded streaming/context query APIs and safe state-observation persistence.
- `llm_monitor/history_analysis.py`: streaming aggregates, timeline records, interval accounting, comparisons, and advanced findings.
- `llm_monitor/evidence_export.py`: preview/write ZIP package, manifest, CSV escaping, and verification.
- `llm_monitor/visualization.py`: static SVG rendering from structured analysis only.
- `llm_monitor/cli.py`: `compare`, `export`, and `visualize`; historical report integration.
- `tests/history_analysis_test.py`, `tests/evidence_export_test.py`, `tests/visualization_test.py`, and focused storage/CLI regression tests.
- `README.md`, module version, Scripts Help registry, and this plan's status/checklist.

## Stages

1. **A — Baseline:** verify branch, Phase 3A tests/package/interfaces/fixtures, and document unsupported metrics.
2. **B — Analytics:** stream persisted records; aggregate metrics, confidence/coverage, timeline, state intervals, and diagnostics; test long histories.
3. **C — Compare:** multi-session API and CLI, differences/normalization/fairness warnings, ambiguity handling.
4. **D — Export:** privacy-safe package, manifests/checksums, dry-run/write, verification, JSONL/CSV safety.
5. **E — Visualization/report:** static SVG timelines/trends/comparisons and shared analytics in historical reports.
6. **F — Delivery:** full regressions, packaging, help, performance measurements, docs, review, commit and push; no merge.

## Acceptance checks

- Phase 3A database opens without schema migration; fresh and existing v1 DBs both work.
- Phase 2A/2B fixtures validate only fields represented in fixture data; exploratory reference runs are not treated as statistically significant or causal.
- Long histories are streamed; repeated polling of equivalent persisted observations is deduplicated.
- Inference token totals remain per-request vs session-summed; context utilization requires matching capacity evidence.
- Incomplete histories, absent durations, and task acceptance remain partial/unknown/unverified.
- Exports are preview-only without `--write`, checksums verify, and tampering/missing members are detected.
- SVG/CSV/HTML-facing strings are escaped and CSV formula injection is neutralized.
- Existing tests and command contracts remain green; no provider or original forensic evidence is modified.
