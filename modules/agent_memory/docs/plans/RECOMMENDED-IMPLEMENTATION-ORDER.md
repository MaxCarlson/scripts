# Recommended Implementation Order for Revised Plans

The plan filenames remain PLAN-5 through PLAN-12 for continuity, but the dependency-safe implementation order is:

```text
PLAN-5  Schema V2
PLAN-6  Frontmatter hardening
PLAN-7  Structured classification
PLAN-8  Search/ranking and benchmark baseline
PLAN-11 Handoff schema
PLAN-9  Context retrieval
PLAN-10 Compaction
PLAN-12 Performance and ergonomics
```

## Rationale

- `PLAN-5` must define metadata and SQLite/index implications before any later phase depends on those fields.
- `PLAN-6` must harden parsing/validation before writing more complex frontmatter.
- `PLAN-7` depends on V2 classification metadata and validation behavior.
- `PLAN-8` should capture a benchmark baseline before changing FTS tokenization/ranking.
- `PLAN-11` should precede `PLAN-9` because context retrieval should understand structured handoff payloads.
- `PLAN-10` depends on schema, validation, search, relationship metadata, and safe status transitions.
- `PLAN-12` documents final performance guidance and only implements sharding if benchmarks justify it.
