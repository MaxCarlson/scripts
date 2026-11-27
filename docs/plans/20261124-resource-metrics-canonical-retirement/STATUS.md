# Resource Metrics Canonical Source Retirement

## Scope

Remove the obsolete tracked `modules/resource_metrics` implementation, migrate
all direct Scripts package dependencies to `mxc-resource-metrics>=0.3.0,<0.4`,
and qualify consumer imports against the canonical wheel. Preserve the
`resource_metrics` import namespace and all existing monitor/telemetry behavior.

## Current state

- Branch: `retire/resource-metrics-incremental-20261126` (incremental branch
  from `scripts/main`, reconciled through PR #41 and PR #38 without importing
  unrelated H4 history).
- Deleted the 9 tracked files under `modules/resource_metrics/`.
- Migrated remaining active consumers (`modules/llm_monitor/pyproject.toml` at
  `0.9.0` with `llm_monitor/__init__.py` synced, and
  `modules/resource_coordinator/pyproject.toml` at `1.0.0`) to
  `mxc-resource-metrics>=0.3.0,<0.4`.
- Reconciled `scripts_setup/tests/transferred_modules_test.py` and
  `.github/source-ownership-exceptions.json`.

## H4 integration gate

`mxc-resource-metrics==0.3.0` is published on PyPI, but `scripts/main` still
contains `modules/resource_coordinator/tools/h4_qualification/bundle_builder.py`
lines 446–447 exporting `modules/resource_metrics` directly from git commits.
Therefore, H4 owner integration of `feat/resource-metrics-canonical-bundle-20261125`
(`8d98af2f`) into `scripts/main` is required before merging this physical
retirement PR.
