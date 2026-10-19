# Benchmark Core Agent Instructions

This file applies to work in `modules/benchmark_core/`. Codex and Gemini agents load it when operating in this module.

## Core Rules

- Prefer correctness, testability, and lightweight standard library code over external frameworks.
- Do not implement task scheduling, subprocess management, or LLM-specific operations here.
- Shared models (`RunInfo`, `TrialResult`, `MetricValue`) must maintain backward compatibility with `agent_benchmark`.
- Run tests via `pytest` and ensure tests pass cleanly on Windows.
- Keep module test temp roots inside `modules/benchmark_core/.pytest_tmp_root/` or use `tmp_path`.
