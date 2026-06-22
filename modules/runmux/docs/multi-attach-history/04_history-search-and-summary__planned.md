# Cycle 04: History Search and Summary

Status: planned

## Implementation

- Add locked `history.jsonl`, `saved_commands.json`, and configuration storage.
- Migrate `commands.json` idempotently with a preserved backup.
- Enforce configurable retention.
- Record exit codes and attachment statistics.
- Add prefix/contains filtering and recent/frequency ordering.
- Add incremental interactive search and aggregate summaries.
- Update README, CLI help, and scripts-help registry.

## Tests

- Migration, backup, retention, and corrupt-data errors.
- Concurrent writers.
- Prefix and contains matching.
- Recent and frequency ordering.
- Runtime, exit-code, success-rate, and attachment summaries.
