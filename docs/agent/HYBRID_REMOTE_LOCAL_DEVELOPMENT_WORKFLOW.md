# Hybrid Remote/Local Development Workflow

## Purpose

Use the browser or app-based agent for as much planning, implementation, test creation, documentation, review, commit, push, and diagnosis work as connected repository tools permit. Reserve local agents and the local machine for authoritative execution that genuinely requires the checked-out repository, operating system, installed tools, credentials, hardware, services, or live environment.

The goal is to minimize local-agent work without minimizing local validation.

## Default Responsibility Split

### Browser/App Agent

The browser/app agent should normally:

1. Inspect the connected repository and repository-specific instructions.
2. Create or update the active plan, status, checklist, and handoff files.
3. Create a dedicated feature branch for substantial work.
4. Implement one coherent stage of the plan.
5. Add unit, integration, regression, edge-case, and failure-mode tests.
6. Add platform-specific validation scripts when ordinary tests cannot cover the behavior.
7. Configure the repository-root validation dispatcher for the modules affected by the stage.
8. Review the complete diff for defects, unsafe behavior, interface regressions, and documentation drift.
9. Commit and push the completed stage.
10. Tell the user to pull and run the same repository-root validation command.
11. Read each target's authoritative `LATEST.txt` report and use it to implement the next pass.

Do not delegate broad implementation work to a local agent merely because the repository is local. Offload only the smallest environment-dependent remainder.

### Local Machine or Local Agent

The local side should normally:

1. Pull the remote feature branch.
2. Run one repository-root validation command.
3. Allow that command to bootstrap declared dependencies, run all selected test suites, and execute platform-specific validation scripts.
4. Avoid redesigning or independently reimplementing the stage unless explicitly assigned.
5. Commit and push the generated tracked validation reports.
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

## Stage Loop

For each stage:

1. **Plan** — define scope, invariants, risks, acceptance criteria, and tests.
2. **Implement remotely** — modify source, tests, scripts, and documentation on the feature branch.
3. **Review remotely** — inspect the full diff and correct obvious defects.
4. **Publish** — commit and push the coherent stage.
5. **Pull locally** — update the local checkout.
6. **Run one command** — execute the repository-root validation dispatcher.
7. **Publish evidence** — commit and push the generated validation reports.
8. **Diagnose remotely** — read `docs/test-results/<target>/LATEST.txt` and implement the next patch or stage.
9. **Repeat** until automated, environment-specific, and acceptance validation pass.

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
- platform-specific validation-script globs and arguments.

The active remote agent updates the manifest when the current stage needs different modules, commands, scripts, setup operations, or read-only checks. The user continues to run the same root command.

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
- one obvious current report per target,
- bounded prior-report history.

Reports should use this shape:

```text
docs/test-results/<target>/
├── LATEST.txt
└── history/
    └── YYYYMMDD-HHMMSS_<target>.txt
```

`LATEST.txt` is authoritative. History exists only for regression comparison. A reasonable default is three prior reports and a 14-day maximum age, with repository-specific overrides when needed.

This structure keeps the current evidence immediately identifiable, allows multiple modules in one stage, and prevents result directories from accumulating indefinitely.

## Portability

Use the platform-native orchestration language when practical:

- PowerShell 7+ on Windows,
- Bash or Zsh on Unix-like systems,
- Python when cross-platform orchestration is more maintainable.

The pattern is independent of language and test framework. A different repository may use pytest, unittest, cargo test, go test, Pester, CTest, npm test, shell scripts, or any combination.

## Branch and Documentation Rules

- Use a dedicated feature branch for substantial work.
- Follow the repository's canonical planning and handoff structure.
- Update status, checklist, and handoff files before and after every stage.
- Preserve public interfaces unless a breaking change is explicitly approved.
- Implement source changes and their tests in the same stage.
- Do not let remote and local agents independently edit the same branch concurrently.
- Use a separate patch branch when a local agent must author code.
- Do not merge until required local validation and user acceptance are complete.

## Safety Rules

- Default tests use temporary repositories, fixtures, mocks, or isolated resources.
- Production read-only checks are explicit and narrowly scoped.
- Destructive tests require explicit approval and an isolated target.
- Never infer success solely from a scheduler launch, dry run, skipped operation, wrapper exit code, or local status file.
- Preserve full command output and exact exit codes in validation reports.
- Never require the user to manually reconstruct information the dispatcher can capture.

## Guiding Principle

**Minimize local-agent work, not local validation.**

The browser/app agent carries the reasoning-heavy and implementation-heavy workload. The local environment supplies authoritative execution evidence where remote access is insufficient.
