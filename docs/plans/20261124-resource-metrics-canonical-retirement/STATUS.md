# Resource Metrics Canonical Source Retirement

## Scope

Remove the obsolete tracked `modules/resource_metrics` implementation and
install-list entry, migrate all direct Scripts package dependencies to the
canonical `mxc-resource-metrics` distribution, and qualify consumer imports
against the qualified canonical wheel. Preserve the `resource_metrics` import
namespace and all existing monitor/telemetry behavior.

## Current state

- Branch: `retire/resource-metrics-physical-20261124` (merged `origin/main` at `d76b7a9e`).
- Deleted the 9 tracked files under `modules/resource_metrics/`.
- Migrated remaining active consumers (`modules/llm_monitor/pyproject.toml` at `0.9.0` with `llm_monitor/__init__.py` synced, and `modules/resource_coordinator/pyproject.toml`) to `mxc-resource-metrics>=0.3.0,<0.4`.
- Reconciled `scripts_setup/tests/transferred_modules_test.py` (`RETIRED_TOOLKIT_SOURCE_DIRS`) and `.github/source-ownership-exceptions.json`.
- Qualified against `tests/test_resource_metrics_retirement.py`, `scripts_setup/tests/`, and `modules/resource_coordinator/tests/`.
