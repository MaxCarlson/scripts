# Kavita Module and MangaDL Collection Assignment

## Intended result

Add a reusable `kavita` Python module that uses Kavita's supported authenticated HTTP API for collections and reading lists. Integrate MangaDL so a run can associate every successful URL-file/direct-URL download with one or more requested collections. Keep existing URL files unchanged, use exact path matching only, and retain unresolved associations durably until Kavita indexes the series.

Mutations must be previewable and require an explicit apply/write option. Preserve existing MangaDL CLI behavior, including the current `-c/--config` option; the new collection flag will therefore be `--collections` without a `-c` short alias.

## Invariants and risks

- No live Kavita API calls in automated tests; use mocked HTTP responses.
- Credentials come from an explicitly named environment variable and never enter logs or persistent plans.
- Collection and reading-list adds are additive/idempotent; no delete or replace behavior is added.
- Match URL associations to Kavita series only by unique exact normalized folder path after explicit path mapping. Missing or duplicate matches stay pending.
- Keep each URL association tied to its exact canonical source URL and expected local series path. Do not fall back to title/name similarity.
- URL file syntax and parsing remain unchanged. Per-URL collection annotations are deferred unless a compatible existing format is discovered.
- Existing `mangadl -c/--config` behavior remains supported; collection assignment uses `--collections`.
- Kavita API drift is a risk; cite and test against official controller DTOs/endpoints current at implementation time.

## Stage 1 — reusable API, durable assignment, and MangaDL integration

Implement the package, tests, docs, and validation target together. The reusable module will expose configuration, authenticated API access, exact series path lookup, collection/reading-list create/list/add operations, and a durable pending-assignment store. MangaDL will add `--collections`, explicit `--apply-kavita` semantics and an explicit reconciliation command for assignments left pending after a server scan.

### Acceptance checks

- Collection and reading-list endpoint payloads follow current official Kavita source.
- Dry-run is the default for all API mutations; applying changes is explicit.
- Unique exact path matches assign; missing and duplicate matches remain pending and are reported.
- Successful downloads persist source URL, expected path, and requested collection names; the explicit reconcile command can apply them after scanning.
- Existing URL-file syntax, legacy `-c/--config`, and unrelated download behavior remain intact.
- Focused package and MangaDL suites, CLI help checks, compile, and Ruff pass; root dispatcher targets capture authoritative reports.
- Complete diff is reviewed, committed, and pushed to the feature branch. Do not merge without user approval.

## Approval and branch

- User explicitly authorized implementation, tests, docs, feature branch, commit, push, and review.
- User did not authorize merge.
- Branch: `codex/kavita-module-mangadl-collections-20261009-0349`.
