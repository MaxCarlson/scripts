# Hybrid Remote/Local Development Workflow

## Purpose

Use the browser/app agent for as much planning, implementation, review, documentation, and test authoring as possible. Reserve local agents and the local machine for work that genuinely requires the checked-out repository, operating system, installed tools, credentials, hardware, services, or live integration environment.

This reduces local-agent token and compute usage while keeping implementation quality high and preserving a tight validation loop.

## Default Responsibility Split

### Browser/App Agent

The browser/app agent should normally:

1. Inspect connected repository contents and existing documentation.
2. Create or update the project-local plan, status, checklist, and handoff files.
3. Create a dedicated feature branch.
4. Implement one coherent stage of the plan.
5. Add or update unit, integration, regression, and failure-mode tests.
6. Add platform-specific validation scripts when ordinary tests cannot cover the behavior.
7. Add one project-local test orchestrator that runs the complete validation set.
8. Perform a static review for obvious defects, interface regressions, unsafe behavior, and documentation drift.
9. Commit and push the completed stage to the feature branch.
10. Tell the user exactly how to pull and run the validation entry point.
11. Read the committed validation output and use it to implement the next pass.

The browser/app agent should not hand broad implementation work to a local agent merely because the repository is local. It should offload only the smallest environment-dependent remainder.

### Local Machine or Local Agent

The local side should normally:

1. Pull the remote feature branch.
2. Run one project-local validation command.
3. Allow that command to run the complete automated test suite and any platform-specific test scripts.
4. Avoid redesigning or independently reimplementing the stage unless explicitly assigned.
5. Commit and push the generated validation-result file or other requested evidence.
6. Report only environment-specific failures or observations that cannot be captured automatically.

Local agents are especially useful for:

- operating-system integration,
- installed CLI and dependency behavior,
- hardware-dependent behavior,
- credentials and private services,
- schedulers and services,
- GUI/TUI behavior,
- network and remote storage integration,
- real backup/restore validation,
- performance and long-running tests.

## Stage Loop

For each stage:

1. **Plan** — define scope, invariants, risks, acceptance criteria, and tests.
2. **Implement remotely** — modify source, tests, scripts, and documentation on the feature branch.
3. **Review remotely** — inspect the complete diff and correct obvious defects.
4. **Publish stage** — commit and push the coherent stage.
5. **Pull locally** — update the local checkout from the feature branch.
6. **Run one command** — execute the project-local test orchestrator.
7. **Publish evidence** — commit and push the tracked test-result file.
8. **Diagnose remotely** — read the result file and implement the next patch or stage.
9. **Repeat** until automated, environment-specific, and acceptance validation pass.

## Test-Orchestrator Requirements

Each substantial project should provide one test entry point at the project or module root. It should:

- run the normal language-native test suite,
- run all project-defined test scripts,
- include stdout and stderr from every command,
- preserve nonzero exit codes,
- continue far enough to report all independent test sections when practical,
- print branch, commit, platform, runtime, and relevant configuration context,
- write a deterministic, tracked result file that can be committed and pushed,
- overwrite the previous result file rather than creating unbounded timestamped artifacts,
- keep temporary files and coverage databases in ignored project-local directories,
- avoid production mutation by default,
- require explicit switches for production read-only or destructive acceptance checks.

Use the platform-native orchestration language when practical:

- PowerShell 7+ on Windows,
- Bash or Zsh on Unix-like systems,
- Python when cross-platform orchestration is more maintainable.

Python remains the preferred implementation language for portable helper utilities, but the workflow must not assume Python, pytest, PowerShell, or Windows unless the project requires them.

## Branch and Documentation Rules

- Use a dedicated feature branch for substantial work.
- Keep the active plan under the repository's canonical planning system.
- Update status, checklist, and handoff documents before and after each stage.
- Preserve public interfaces unless a breaking change is explicitly approved.
- Keep implementation and test changes in the same stage.
- Do not have remote and local agents independently edit the same branch concurrently.
- Use separate patch branches when a local agent must author code.
- Do not merge until the required local validation and user acceptance are complete.

## Safety Rules

- Default tests must use temporary repositories, fixtures, mocks, or isolated resources.
- Production read-only checks must be explicit and narrowly scoped.
- Destructive tests require explicit approval and a clearly isolated target.
- Never infer success from a scheduler launch, dry run, skipped operation, or wrapper exit alone.
- Preserve full command output and exact exit codes in the result file.
- Never require the user to manually reconstruct failures that the orchestrator can capture.

## Optimization Principle

Minimize local-agent work, not local validation. The browser/app agent should carry the reasoning-heavy and implementation-heavy workload; the local environment should provide authoritative execution evidence where remote access is insufficient.
