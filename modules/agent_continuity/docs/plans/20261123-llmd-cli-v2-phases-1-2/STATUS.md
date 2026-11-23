# LLMD CLI v2 phases 1-4

Status: Phase 4 implemented; validated; local commit pending on feature/llmd-cli-v2-20261123.

Positional start is preview-only by default and requires --new plus --apply before provider initialization. Legacy named start and direct continue preserve their existing authorization defaults. Historical continuation resolves only IDs present in activation history; provider matching refuses ambiguity, exact IDs disambiguate. Switch reuse uses the same resolver and preserves latest-provider behavior.

Validation: python -m pytest -q --basetemp=.pytest_tmp_root/phase4-final-full; python -m ruff check agent_continuity/dispatcher.py agent_continuity/dispatcher_cli.py tests/dispatcher_v2_test.py; git diff --check.

Next: review and commit locally. No push or merge.
