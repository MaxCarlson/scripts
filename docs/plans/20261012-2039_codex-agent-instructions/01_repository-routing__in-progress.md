# Stage 1: Repository routing

## Scope

- Keep `AGENTS.md` concise and directly useful at startup.
- Route Python, validation, hybrid workflow, and planning reads to the tasks that need them.
- Remove the remote commit instruction that conflicts with the approval rule.
- Make the new handoff pointer identify this branch and stage without rewriting unrelated plan histories.

## Verification

- Check all referenced paths and inspect the changed instruction diff.
- Run `git diff --check` and check Git status with submodule recursion disabled because `pscripts` metadata is inaccessible in this sandbox.
- Use a fresh Codex session from repo root to check supplied instructions versus files merely named for later reading. Check nested module loading in stage 3, when nested files are changed.

## Boundary

The user reviewed the work and explicitly authorized staging, committing, pushing, and merging it into `main`.
