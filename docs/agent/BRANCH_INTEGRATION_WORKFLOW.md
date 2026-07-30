# Branch and Integration Workflow

## Purpose

Use a predictable branch topology so browser/app agents, local agents, and the user can work in parallel without editing the same branch or repeatedly merging unrelated feature branches into each other.

## Canonical Branch Roles

### `main`

`main` is the stable, accepted baseline.

- Merge into `main` only after combined validation and required manual acceptance pass.
- Do not use `main` for ordinary implementation work.
- A change present only on a feature or integration branch is not considered accepted repository behavior.

### `agent/unified`

`agent/unified` is the shared integration branch.

- Create it from the current accepted `main` baseline.
- Merge completed agent/feature branches into it before merging to `main`.
- Resolve cross-feature conflicts and integration-only defects here.
- Run combined validation here after integrating multiple branches.
- Do not use it as a long-lived personal feature branch.

### `agent/<work>`

Use a dedicated branch for each coherent implementation stream.

- Create it from the current `agent/unified` unless the user explicitly chooses another base.
- Keep the branch limited to one plan, feature, correction stream, or agent assignment.
- Name it descriptively, for example `agent/unified-workflow-ledger` or `agent/rrbackup-pause-control`.
- Merge it into `agent/unified` after its own automated and manual acceptance requirements pass.
- Retire it after integration unless a narrowly scoped correction branch is required.

## Multi-Agent Rules

- Two agents must not independently edit the same branch at the same time.
- A local agent that must author source changes uses a separate patch branch.
- A browser/app agent should not continue publishing to a feature branch after the user has merged or retired it.
- Before starting a substantial pass, compare the intended base and target branches and confirm the feature branch is not behind the integration baseline in a way that changes the task.
- Preserve unrelated user commits and generated validation evidence during integration.

## Standard Lifecycle

```text
main
  ↓ create or refresh integration baseline
agent/unified
  ↓ create coherent work branch
agent/<work>
  ↓ remote implementation and static review
local validation and manual checks
  ↓ evidence commit
agent/<work>
  ↓ merge completed work
agent/unified
  ↓ combined validation and conflict resolution
main
```

## Feature-Branch Loop

1. Create `agent/<work>` from current `agent/unified`.
2. Update the active plan's development-ledger state block.
3. Implement one bounded stage with source, tests, documentation, and validation configuration.
4. Review the complete branch diff.
5. Commit and push the coherent stage.
6. Have the local side pull and run the repository-root validation command.
7. Commit and push generated evidence.
8. Review `ledger/PROGRESS.md`, routing output, manual checks, and the current raw transcript.
9. Continue, replan, or complete the feature branch.
10. Merge the accepted branch into `agent/unified`.

## Integration-Branch Loop

After one or more feature branches are merged into `agent/unified`:

1. Check for overlapping public interfaces, shared configuration, documentation, and validation-target changes.
2. Resolve integration conflicts without silently dropping either feature's behavior.
3. Run all affected validation targets together.
4. Perform cross-feature manual checks where isolated feature validation is insufficient.
5. Record integration evidence in the active repository-wide ledger.
6. Merge into `main` only after the integrated state is accepted.

## Evidence and Merge Gates

A feature is ready for `agent/unified` when:

- intended implementation is present;
- targeted automated validation passes, or remaining failures are explicitly understood and accepted for integration diagnosis;
- required manual checks pass or are explicitly deferred;
- generated ledger state is current;
- public-interface and cross-module impacts are documented;
- the branch contains no unrelated edits.

`agent/unified` is ready for `main` when:

- combined affected-target validation passes;
- integration-specific defects are resolved;
- required user-visible/manual acceptance passes;
- the integration ledger shows no unresolved blocker or unexplained regression;
- the user approves the merge.

## Recovery and Stale Branches

- If a feature branch diverges substantially from `agent/unified`, prefer rebasing or merging the integration baseline once at a deliberate checkpoint rather than repeatedly cross-merging every active feature branch.
- If a merged branch receives new work accidentally, create a new correction branch from current `agent/unified` and cherry-pick only the intended commits.
- Delete or archive obsolete remote branches after their commits are safely integrated and traceable.
