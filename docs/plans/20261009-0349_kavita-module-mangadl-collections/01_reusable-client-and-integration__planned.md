# Stage 1 — Reusable client and MangaDL integration

## Scope

Build a reusable Kavita package for collection and reading-list APIs, exact path matching, and durable pending assignments. Wire MangaDL's URL-file run to requested collections and expose dry-run-first reconciliation. Update package and project docs, tests, CLI registry/validation targets as required.

## Sequence

1. Implement the independent Kavita package and mocked endpoint/storage tests.
2. Add MangaDL collection flags, post-download association persistence, and an explicit reconciliation command; retain existing short flags and URL file syntax.
3. Add cross-module tests and usage documentation; update handoffs and validation dispatcher.
4. Run focused suites, CLI checks, compile and lint; review full diff and git status.
5. Commit and push the feature branch; inspect the pushed commit and report the branch without merging.

## Boundaries

- Never perform live Kavita writes in tests or validation.
- Exact unique path matching only. Any missing/ambiguous match is pending.
- Mutation endpoints run only under explicit `--apply`.
- No migration of existing URL files or downloaded folders.
