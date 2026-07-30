# Hybrid Remote/Local Development Workflow

## Purpose

Use the browser or app-based agent for as much planning, implementation, test creation, documentation, review, commit, push, and diagnosis work as connected repository tools permit. Reserve local agents and the local machine for authoritative execution that genuinely requires the checked-out repository, operating system, installed tools, credentials, hardware, services, or live environment.

The goal is to minimize local-agent work without minimizing local validation.

## Default Responsibility Split

### Browser/App Agent

The browser/app agent should normally:

1. Inspect the connected repository and repository-specific instructions.
2. Identify the active plan and read its handoff plus generated `ledger/PROGRESS.md` when present.
3. Create a dedicated `agent/<work>` branch from current `agent/unified` for substantial work.
4. Update the active plan's structured development-ledger state block.
5. Implement one coherent stage of the plan.
6. Add unit, integration, regression, edge-case, and failure-mode tests.
7. Add platform-specific validation scripts when ordinary tests cannot cover the behavior.
8. Configure the repository-root validation dispatcher for the modules and evidence affected by the stage.
9. Review the complete diff for defects, unsafe behavior, interface regressions, and documentation drift.
10. Commit and push the completed stage.
11. Tell the user to pull and run the same repository-root validation command.
12. Read the pushed ledger projections and raw validation transcript before the next modification pass.

Do not delegate broad implementation work to a local agent merely because the repository is local. Offload only the smallest environment-dependent remainder.

### Local Machine or Local Agent

The local side should normally:

1. Pull the remote feature branch.
2. Run one repository-root validation command.
3. Allow that command to bootstrap declared dependencies, run all selected test suites, execute platform-specific validation scripts, normalize evidence, and record the ledger event.
4. Avoid redesigning or independently reimplementing the stage unless explicitly assigned.
5. Commit and push generated validation and ledger evidence.
6. Report only environment-specific observations that cannot be captured automatically.

Local execution is especially useful for:

- operating-system integration,
- installed CLI and dependency behavior,
- credentials and private services,
- schedulers and background services,
- hardware,
- GUI/TUI behavior,
- networking and remote storage,
- real backup/restore or deployment validation,
- performance and long-running tests.

## Local-Agent Hybrid Reminder

For a substantial task that could be implemented primarily through browser/app repository tools, a local agent should give one brief advisory reminder near the start of the conversation before beginning a long local implementation.

The reminder should be given at most once per conversation, should not block progress, and should not be used for small fixes or genuinely local work. Continue locally unless the user redirects the task.

## Branch Topology

Use:

```text
main
  ↑ accepted integration
agent/unified
  ↑ completed feature branches
agent/<work>
```

- `main` is the stable accepted baseline.
- `agent/unified` is the shared integration branch.
- Substantial feature branches start from current `agent/unified`.
- Remote and local agents must not independently edit the same branch.
- Local source changes require a separate patch branch.
- Follow `BRANCH_INTEGRATION_WORKFLOW.md` for merge gates and recovery rules.

## Stage Loop

For each stage:

```text
Update plan state
→ implement remotely
→ review and publish implementation commit
→ validate locally
→ normalize results
→ append immutable plan event
→ regenerate LLM projections
→ publish evidence commit
→ remote stage review
→ continue, replan, manual-check, local handoff, or integrate
```

Detailed steps:

1. **Orient** — read instructions, handoff documents, active plan, and generated progress.
2. **Plan** — define scope, invariants, risks, acceptance criteria, tests, manual checks, and environment dependencies.
3. **Update structured state** — record the bounded objective, hypothesis, target IDs, implementation states, mappings, and relevant files.
4. **Implement remotely** — modify source, tests, scripts, documentation, and validation configuration on the feature branch.
5. **Review remotely** — inspect the full diff and correct obvious defects.
6. **Publish implementation** — commit and push the coherent stage.
7. **Pull locally** — update the local checkout.
8. **Run one command** — execute the repository-root validation dispatcher.
9. **Record evidence** — preserve raw output, normalize test/script results, append the immutable event, and regenerate projections.
10. **Publish evidence** — commit and push generated validation and ledger artifacts.
11. **Diagnose remotely** — read `PROGRESS.md`, `TRACEABILITY.md`, `MANUAL_CHECKS.md`, routing output, and the current raw transcript.
12. **Route** — continue remotely, replan, request manual validation, create a narrow local handoff, or integrate the accepted branch.

## Progress Classifications

Use these terms consistently when reviewing a validation event or stage:

### Material progress

The pass completed or verified one or more plan items, removed a blocker, reduced failure scope, or added diagnostic evidence that materially changes the next action.

### Partial progress

The pass improved implementation or evidence but left the targeted item incomplete. The next action is narrower and supported by new information.

### Stalled

The pass produced no meaningful implementation, verification, or diagnostic narrowing. Repeating the same action is unlikely to help without a new hypothesis or environment evidence.

### Looping

Two or more consecutive passes repeat substantially the same edits, tests, or failure pattern without narrowing the problem or changing the hypothesis.

### Regressing

Previously passing behavior, accepted interfaces, or validated plan items now fail or become uncertain because of the current pass.

### Ready

All targeted implementation is present, required automated evidence passes, required manual checks pass or are explicitly accepted as deferred, and no unresolved blocker or unexplained regression remains.

## Immediate Local-Escalation Triggers

Generate or request a narrow local handoff immediately when progress depends on:

- reproducible behavior available only on the user's operating system or hardware;
- installed-package, PATH, shell, scheduler, service, GUI, or TUI state;
- credentials, private endpoints, production-like storage, or network topology;
- performance, resource pressure, or long-running behavior;
- a failure that remote static inspection cannot distinguish between code and environment;
- two materially different remote hypotheses that require authoritative execution evidence.

Do not escalate broad implementation merely because local execution is eventually required.

## Model and Reasoning Recommendation

Use the least expensive capable model/reasoning level for mechanical edits and straightforward fixes. Recommend deeper local reasoning only when the task has high diagnostic ambiguity, cross-system behavior, complex concurrency/state, or repeated evidence-supported failure. A routing recommendation must identify the narrow question the stronger model or local environment should answer.

## Repository-Root Validation Dispatcher Pattern

Each substantial repository should provide one stable validation entry point at the repository root. In this repository it is:

```powershell
./Invoke-Tests.ps1
```

The dispatcher reads a small target manifest:

```text
validation-targets.json
```

The manifest defines:

- default targets,
- each target's working directory,
- environment variables,
- bootstrap/install commands,
- language-native test commands,
- declarative file-target rules,
- platform-specific validation-script globs and arguments,
- active plan and ledger output paths,
- JUnit and generic script-result outputs,
- raw transcript and manual-check metadata.

The active remote agent updates the manifest when the current stage needs different modules, commands, scripts, setup operations, evidence paths, or read-only checks. The user continues to run the same root command.

The dispatcher should support:

- one target,
- several named targets,
- all configured targets,
- target listing,
- dependency bootstrap by default,
- explicit bootstrap skipping,
- explicit production read-only checks,
- complete stdout and stderr capture,
- exact command and exit-code reporting,
- continued execution of independent sections when practical,
- one obvious current raw report per target,
- bounded prior-report history,
- ledger recording as the final evidence phase.

During migration, reports retain this shape:

```text
docs/test-results/<target>/
├── LATEST.txt
└── history/
    └── YYYYMMDD-HHMMSS_<target>.txt
```

`LATEST.txt` remains the authoritative raw transcript. A ledger-enabled plan additionally provides permanent normalized history and generated current-state views under its `ledger/` directory.

## Evidence Precedence

For a ledger-enabled plan, read in this order:

1. normal repository/project handoff documents;
2. active `00_implementation-plan.md`;
3. generated `ledger/PROGRESS.md`;
4. `ledger/TRACEABILITY.md` and `ledger/MANUAL_CHECKS.md`;
5. current raw `docs/test-results/<target>/LATEST.txt` when detailed diagnosis is needed;
6. `ledger/LOCAL_HANDOFF.md` only when generated.

Never manually edit `RUNS.jsonl` or generated ledger projections.

## Portability

Use the platform-native orchestration language when practical:

- PowerShell 7+ on Windows,
- Bash or Zsh on Unix-like systems,
- Python when cross-platform orchestration is more maintainable.

The pattern is independent of language and test framework. A different repository may use pytest, unittest, cargo test, go test, Pester, CTest, npm test, shell scripts, or any combination.

## Safety Rules

- Default tests use temporary repositories, fixtures, mocks, or isolated resources.
- Production read-only checks are explicit and narrowly scoped.
- Destructive tests require explicit approval and an isolated target.
- Never infer success solely from a scheduler launch, dry run, skipped operation, wrapper exit code, or local status file.
- Preserve full command output and exact exit codes in validation reports.
- Never require the user to manually reconstruct information the dispatcher can capture.
- Ledger generation must not hide or replace the original validation failure status.

## Guiding Principle

**Minimize local-agent work, not local validation.**

The browser/app agent carries the reasoning-heavy and implementation-heavy workload. The local environment supplies authoritative execution evidence where remote access is insufficient.
