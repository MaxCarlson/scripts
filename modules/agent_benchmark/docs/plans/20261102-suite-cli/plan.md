# Agent Benchmark Suite CLI Implementation Plan

> **For agentic workers:** Execute this plan task by task and keep the checklist current.

**Goal:** Add a persistent cohort CLI that runs authorized Harbor trials sequentially with compact output, safe background operation, validated monitor routing, and recoverable reports.

**Architecture:** Keep existing `external` commands stable and add `suite` CLI wiring over the Harbor planner/runner/importer. Store immutable run manifests and atomically updated checkpoints under a per-run directory; dispatch one task per Harbor job for accepted-trial checkpoints. Background execution reuses a detached Python worker with a per-run exclusive lock. Monitor checks use LLM Monitor's versioned local inference status and recording endpoints.

**Tech Stack:** Python 3.12, argparse, pathlib, JSON, subprocess, httpx, pytest, Harbor 0.25.0.

**Spec:** User-provided Handoff B and integration baseline update in this conversation.

## Global Constraints

- Base exactly `d13372389ef6b5f344e26ee150e67722a50a92ac`; isolated feature branch and worktree.
- No full ten-task inference run during implementation.
- All inference execution requires explicit `-x/--execute`; no direct fallback when monitor is required.
- Frozen `aider-python-10` order comes from the preserved baseline manifest and source revision `f30b14415dd733c83627204bad0af69a89ceb46f`.
- `--llm-friendly` changes only output and subprocess capture, never Harbor plan settings.
- Preserve existing CLI interfaces and native Harbor evidence.
- No push, merge, or external publication.

## Review Focus

1. Duplicate/background worker races: atomic exclusive ownership and stable run IDs.
2. Interrupted Harbor jobs: reconcile artifacts; never mark incomplete work scored.
3. Monitor mismatch or recording drift: fail closed before scored dispatch.
4. Existing OpenCode API format conflict: inspect effective config and refuse unsupported/conflicting endpoint or protocol.
5. Large Harbor logs: redirect to run artifacts and cap immediate output.

## Files

- `agent_benchmark/suite.py`: cohorts, immutable manifests, run/checkpoint lifecycle, resume, aggregation.
- `agent_benchmark/suite_monitor.py`: monitor health, route and recording preflight.
- `agent_benchmark/suite_output.py`: JSONL/human output and file-backed subprocess behavior.
- `agent_benchmark/suite_worker.py`: detached worker entry point.
- `agent_benchmark/cli.py`: parser integration and external-run compact flag.
- `tests/suite_test.py`, `tests/suite_monitor_test.py`, `tests/suite_cli_test.py`: synthetic lifecycle and contracts.
- `README.md`, `docs/suite-cli.md`: command and recovery guide.

## Tasks

### Task 1: Frozen cohorts and manifest

- [x] Write tests for exact ordered `aider-python-10`, revision pin, deterministic manifest digest, and custom manifest validation.
- [x] Implement cohort resolution and immutable plan serialization.
- [x] Run focused cohort tests.

### Task 2: Checkpoints, sequential execution, status, resume, report

- [x] Write tests for explicit authorization, sequential one-task Harbor calls, atomic checkpoints, completed-trial deduplication, coding/infrastructure classification, and recovery.
- [x] Implement persistent run state and task-at-a-time Harbor execution.
- [x] Run focused lifecycle tests.

### Task 3: LLM Monitor preflight and provenance

- [x] Write tests for URL, API format, effective OpenCode provider configuration, unsupported Responses endpoint, recording mode, monitor outage, and health/coverage failures.
- [x] Implement fail-closed monitor validation and provenance.
- [x] Run focused monitor tests with mocked HTTP.

### Task 4: Compact output and background lifecycle

- [x] Write tests for JSONL schema, output bounding, workload equivalence, external run `-F`, detached worker metadata, lock ownership, and recoverable process state.
- [x] Implement shared output/capture and detached worker/status lifecycle.
- [x] Run focused output/background tests on Windows fixtures.

### Task 5: CLI integration and documentation

- [x] Add all requested suite subcommands/flags and preserve old CLI parsing.
- [x] Add command reference and agent examples; document platform limits and fidelity boundary.
- [x] Run focused Agent Benchmark, Benchmark Core, relevant LLM Monitor tests, Ruff, help, and package checks; never run the full cohort.
- [x] Review the final diff and record exact validation and limitations.
- [x] Preflight the frozen Aider revision through Harbor 0.25.0's registry resolver and persist the exact dispatched registry snapshot.
- [x] Add revision-match, mismatch, unavailable-resolution, snapshot-forwarding, and pre-dispatch fail-closed tests.
- [x] Document the bounded one-task live monitor/revision smoke without running the full cohort.
