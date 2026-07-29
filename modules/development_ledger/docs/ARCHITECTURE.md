# Development Ledger Architecture

## Purpose

The development ledger is a narrow event-sourced subsystem for software-development progress. It is designed for repositories where a remote/browser LLM performs most planning and implementation while a local machine or local LLM supplies authoritative environment-dependent validation.

The primary consumer is a fresh LLM entering the project. Human-readable output is retained, but the generated files prioritize deterministic structure, explicit evidence, low duplication, and fast handoff.

## Design principles

1. **Intent and evidence are separate.** The LLM declares what it attempted; scripts record what actually happened.
2. **One small structured plan block is edited manually.** Test summaries, progress history, traceability views, and handoffs are generated.
3. **Validation runs are immutable events.** Current views are projections from the event ledger.
4. **Raw output is supporting evidence.** Permanent history uses normalized facts rather than unlimited console transcripts.
5. **Automated and manual verification are distinct.** Passing tests do not imply complete acceptance.
6. **Feature/test links are bidirectional.** Plan items declare expected tests, and tests may declare item IDs.
7. **Routing is evidence-gated.** The system recommends remote continuation, replanning, manual checks, or local debugging from longitudinal evidence.
8. **The repository remains authoritative.** No hosted service or database is required.

## Layers

```text
1. INTENT
   Markdown plan + structured JSON state block

2. EXECUTION
   Invoke-Tests.ps1 or another repository validation dispatcher

3. NORMALIZATION
   JUnit XML, generic script-result JSON, and legacy transcript adapters

4. HISTORY
   RUNS.jsonl immutable validation and manual-check events

5. PROJECTIONS
   LATEST.json, PROGRESS.md, TRACEABILITY.md,
   MANUAL_CHECKS.md, and LOCAL_HANDOFF.md
```

## Event types

### `validation_run`

A validation event binds:

- plan and stage identity,
- the LLM-declared objective, hypothesis, and target items,
- actor and execution mode,
- tested branch and commit,
- baseline commit and changed-file metadata,
- normalized automated tests,
- failure fingerprints,
- plan-item verification states,
- manual-check states,
- semantic deltas from the prior run,
- progress classification,
- remote/local routing recommendation,
- paths to supporting artifacts.

### `manual_check`

A manual event records:

- stable manual-check ID,
- pass/fail/blocked/waived state,
- actor,
- tested commit,
- platform,
- evidence note.

Manual events update generated projections without rewriting prior validation events.

## Generated projections

### `PROGRESS.md`

The first project-specific file a fresh LLM should read. It summarizes:

- current stage and tested commit,
- latest intent and result,
- each item’s implementation, automated, manual, and verification state,
- persistent failures,
- complete compact run history,
- routing decision,
- relevant evidence paths.

### `TRACEABILITY.md`

Shows:

- plan item → expected test patterns,
- plan item → tests actually matched,
- plan item → manual checks,
- test → plan items,
- unmapped regression-only tests.

### `MANUAL_CHECKS.md`

Contains exact user-executable validation steps that cannot be automated. It does not claim completion until a manual event is recorded.

### `LOCAL_HANDOFF.md`

When local escalation is recommended, this becomes a self-contained prompt for local Codex. It includes the blocker, model/reasoning recommendation, repository state, recent attempts, failures, evidence paths, narrow scope, and required final report.

When no escalation is active, the file explicitly says so to prevent stale handoff use.

## Progress classification

The first run establishes a baseline. Later runs are classified as:

- `progressing`: meaningful verification or failure-resolution progress,
- `partial_progress`: progress occurred but failures remain,
- `stalled`: no semantic progress,
- `looping`: the same failure set persists without a successful new hypothesis,
- `regressing`: new failures or lost verification,
- `ready`: all non-deferred plan items are verified.

Progress is based on plan-item transitions and normalized failures, not source-line count or document churn.

## Routing decisions

The generated recommendation is one of:

- `continue_remote`
- `one_targeted_remote_pass`
- `replan_remote`
- `handoff_local`
- `ready_for_acceptance`

The LLM remains responsible for the final judgment, but it must explain any departure from the generated evidence.

## Scope boundary

This module does not:

- execute arbitrary validation suites itself,
- replace the repository dispatcher,
- infer product requirements from source code,
- claim manual verification automatically,
- merge branches,
- mutate production systems,
- replace raw logs needed for diagnosis.

It normalizes evidence and generates the control-plane artifacts used by agents.
