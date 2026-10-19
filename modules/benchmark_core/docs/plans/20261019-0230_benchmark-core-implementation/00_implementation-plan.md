# Implementation Plan: `benchmark_core`

## Purpose
Lightweight, reusable benchmarking results and reporting utility for CLI utilities, algorithms, compression experiments, and local LLM coding agents.

## Scope & Stages
- **Stage 1 (Gate 1):** Shared contracts (`RunInfo`, `TrialResult`, `MetricValue`), serialization, validation, canonical fixtures, contract tests.
- **Stage 2:** Persistence (`storage.py`) and descriptive statistics / macro-micro rates (`stats.py`).
- **Stage 3:** Output generators (`summary.json`, wide-form deterministic `summary.csv`, `report.md`), comparison logic (`compare.py`), and CLI (`cli.py`).
- **Stage 4:** Hyperfine JSON importer and end-to-end integration verification.
