# AEBN Downloader Module Instructions

These instructions apply to modules/aebndl_module/. Follow the scripts/ root AGENTS.md and REPO_LLM_INSTRUCTIONS.md too. This is a vendored module; consult SUBTREE_SYNC.md before changes that may overlap upstream.

## Project facts

- The package is aebndl; pyproject.toml is authoritative for Python version, dependencies, version, and entry points.
- The CLI entry point is aebndl. Preserve its existing arguments and both short and long forms.
- FFmpeg must be available on PATH for download workflows.
- Treat downloads and proxy-backed tests as external side effects. Do not run live download tests unless the task explicitly requires them.

## Validation

- Run tests in an isolated environment with dependencies from `pyproject.toml` installed; do not install into system Python.
- For isolated CLI/parser tests, use python -m pytest tests/test_urls.py tests/test_utils.py -q from this directory.
- Before choosing broader tests, inspect their markers and behavior; some tests require a proxy or perform real downloads.
- Follow the repository's versioning and testing standards when changing Python behavior.

## Git and safety

- Preserve unrelated changes and use the current repository branch.
- Do not fetch, rebase, push, force-push, or commit unless the user explicitly authorizes that action.
- Do not assume the old machine-specific checkout path in historical notes is valid.
