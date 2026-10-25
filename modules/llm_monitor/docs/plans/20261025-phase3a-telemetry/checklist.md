# Phase 3A Checklist

## Stage A — Baseline verification

- [x] Verify Phase 2 branch and remote SHA.
- [x] Run existing tests and compile checks.
- [x] Verify isolated installation and installed CLI entry point.
- [x] Probe available read-only provider endpoints.
- [x] Inspect privacy-safe events, identity, polling, packaging, and CLI contracts.

## Stage B — Storage foundation

- [x] Default database paths and SQLite schema/migration handling
- [x] Provider/session/event identities and idempotent transactional ingestion
- [x] Privacy-safe payload projection
- [x] Query APIs, indexes, WAL and multi-writer behavior
- [x] Database info, integrity check, and dry-run pruning

## Stage C — Recording and recovery

- [x] `record --session` and `record --all`
- [x] Initial and incremental collection with checkpoints/gaps
- [x] Restart overlap deduplication and transactional rollback tests
- [x] Multiple sessions/writers and clean interruption

## Stage D — Historical analysis

- [x] Offline history queries and paginated event retrieval
- [x] `report --history` reusing existing analyses
- [x] Restart/interruption fixture and 10,000-event synthetic ingestion/query workload

## Stage E — Operations and release

- [x] CLI compatibility and database commands
- [x] README, schema, privacy, retention, and recovery documentation
- [x] Full tests, isolated packaging, help, compile, and diff verification
- [x] Commit and push Phase 3A branch; do not merge
