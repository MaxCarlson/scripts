# Runmux Module Instructions

These instructions apply to modules/runmux/. Follow the repository root AGENTS.md and REPO_LLM_INSTRUCTIONS.md as well. When a task starts from scripts/, explicitly read this file and any more-specific instructions covering the target paths.

## Project guidance

- Treat modules/runmux/ as the project root for runmux-owned plans and handoffs.
- For substantial or resumed work, read relevant files under docs/ that exist, including the current handoff and active plan.
- Use README.md for current commands and behavior; verify claims against source and tests.
- Preserve existing runmux CLI argument forms.

## Validation

- Run focused tests from this directory with python -m pytest tests/<relevant-file> -q.
- Run python -m pytest when shared behavior changes; pyproject.toml configures module-local temporary roots.
- Run ruff check . when Python code changes.
- Do not run tests that contact live services or mutate user state unless the task explicitly requires them.