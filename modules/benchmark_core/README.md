# benchmark_core

`benchmark_core` is a lightweight, reusable benchmarking results normalization, aggregation, and reporting utility in the `scripts` repository.

## Capabilities

- **Shared Contracts:** Defines standard data models (`RunInfo`, `TrialResult`, `MetricValue`) for benchmark batches and trial outcomes.
- **Persistence:** Clean file layout (`run.json`, `trials.jsonl`, `summary.json`, `summary.csv`, `report.md`) with offline regenerability.
- **Descriptive Statistics:** Computes observations, available/missing counts, mean, median, min, max, and sample standard deviation using Python's standard library.
- **Capability Success Rates:** Distinguishes between all-scored duration and successful-only duration; handles micro and macro success rates with strict denominator filtering.
- **Wide-Form Tabular Summaries:** Deterministic CSV schema with one row per variant and uniform metric columns.
- **Run Comparisons:** Basic variant and run comparison reports with absolute and percentage deltas.
- **External Tool Importers:** Ingestion of Hyperfine benchmark outputs.

## Usage

```python
from benchmark_core import RunInfo, TrialResult, MetricValue
```

## Comparison conditions (0.1.3)

`comparison-conditions-v1` metadata explicitly establishes task/verifier identity, execution profiles,
scope/isolation policy, context, budget and environment/runtime identity. Missing or malformed conditions
suppress numerical run deltas and canonical experiment rankings. Known incompatible conditions form
separate comparison groups; raw observations remain available. Eligible variants with zero scored
trials stay unranked diagnostics, preserving denominators and functional metrics. JSON, CSV, Markdown,
terminal and optional HTML outputs retain these distinctions. Historical records remain readable and
are never rewritten to invent missing comparison metadata.

Condition-group CSV rendering deserializes nested groups at runtime; report regeneration is covered
for nonempty groups across CSV, Markdown and optional interactive HTML.
