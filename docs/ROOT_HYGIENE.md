# Repository Root Hygiene (`scripts`)

This document defines what belongs in the `scripts/` repository root, where temporary test artifacts should be placed, and how root cleanup is managed safely.

## What belongs in the root

- **Tracked source, setup & documentation**: `modules/`, `pyscripts/`, `pwsh/`, `shell-scripts/`, `scripts_setup/`, `tests/`, `docs/`, `agents/`, `experiments/`, `knowledge_manager/`, `plans/`, `pyprjs/`, `python/`, `todo/`, `validation/`, `bootstrap*.ps1|sh|py`, `setup.py`, `Invoke-Tests.ps1`, `validation-targets.json`, `pytest.ini`, `conftest.py`.
- **Git submodules**: `pscripts/` and module `refs/` submodules. Preserve their `.git` metadata.
- **Persistent local environment & state (ignored)**: `.venv/`, `bin/`, `scripts_manifest.json`, `.claude/`, `.codex`, `.superpowers/`.
- **Evidence & operational logs (retained unless explicitly retired)**: `diagnostics/`, `reports/`, `.harbor-jobs/`, `logs/`, `setup_logs/`, `setup_errors.log`, `setup_log.log`.
- **Agent worktrees (ignored)**: `.worktrees/` (managed via `git worktree`).

## Preventing root clutter

- Per `docs/agent/SCRIPTS_REPO_STANDARDS.md`, module tests must keep generated temp directories inside the owning module (`modules/<module>/.pytest_tmp_root/<module>-temp-<pid>/`) rather than creating root-level `.pytest_tmp*` or `.tmp-*` folders.
- `pytest.ini` excludes `.worktrees`, `.pytest_tmp*`, `.mypy_cache`, `.ruff_cache`, `htmlcov`, `reports`, and `.harbor-jobs` via `norecursedirs` so root `pytest` invocations do not recurse into worktrees or artifact directories.
- `.gitignore` explicitly ignores `.ruff_cache/` and `setup_logs/` alongside `.mypy_cache/`, `.pytest_cache/`, `.pytest_tmp*`, `htmlcov/`, `.coverage`, and `coverage.xml`.

## Reversible cleanup & worktree lifecycle

- Regenerable caches (`__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `htmlcov/`, `.coverage`, `coverage.xml`) and empty `.pytest_tmp*` folders should be moved to an external quarantine directory with a `MANIFEST.json` rather than deleted in place.
- Worktree retirement (`git worktree remove` / `git worktree prune`) requires verifying branch merge status and working-tree cleanliness first, and requires explicit approval before removal.
