# Benchmark Core Documentation

`benchmark_core` is a lightweight benchmarking data, normalization, aggregation, and reporting package.

## Architecture

```mermaid
flowchart TD
    Consumer["Benchmark Consumers (e.g. agent_benchmark, CLI, Hyperfine)"] -->|TrialResult / RunInfo| Models["benchmark_core.models"]
    Models --> Storage["benchmark_core.storage\n(run.json, trials.jsonl)"]
    Storage --> Stats["benchmark_core.stats\n(aggregations, micro/macro rates)"]
    Stats --> Reporting["benchmark_core.reporting\n(summary.json, summary.csv, report.md)"]
    Stats --> Compare["benchmark_core.compare\n(variant and run diffs)"]
```

## Public Contracts

- `RunInfo`: Represents a benchmark batch and configuration (with variant matrix, reproducibility metadata, scoring basis).
- `TrialResult`: Represents a single execution attempt of a task/variant repetition.
- `MetricValue`: Represents a numerical measurement with source, unit, and provenance quality.

## Documentation Index

- [HANDOFF.md](HANDOFF.md): Current operational status, branch, and immediate next steps.
- [plans/HANDOFF.md](plans/HANDOFF.md): Index of active and completed implementation plans.
