# agent_benchmark

Thin evaluator for local coding workers. Initial development slice: termination confirmation and owned-workspace cleanup safeguards only. No CLI or runnable benchmark yet. No benchmark_core substitutes.

[Implementation plan](docs/plans/20261019-implementation/plan.md) contains the staged architecture, model allocation, acceptance gates and current repository findings.

Tests (from module directory):

```powershell
python -m pytest tests -q --basetemp=.pytest_tmp_root/lifecycle
python -m ruff check agent_benchmark tests
```

A cached job status or abort acknowledgement cannot prove termination. Fresh correlated idle/finished/tool state is required; unresolved work preserves workspace and stops dispatch. Shared services and processes are never terminated by this module. This is trusted-fixture isolation, not a security sandbox.
