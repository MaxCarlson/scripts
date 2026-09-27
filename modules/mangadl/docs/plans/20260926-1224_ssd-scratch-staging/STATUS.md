# Scratch staging status

Stages 1 and 2 are implemented after user feedback. Production B:/E:
acceptance has not been run. The 213-test MangaDL suite passes.

## Verification (2026-09-26)

- `.\.venv\Scripts\python.exe -m pytest modules/mangadl/tests -q --tb=line` — pass, 213 tests.
- `.\.venv\Scripts\python.exe -m compileall -q modules/mangadl/mangadl modules/mangadl/tests` — pass.
- `.\.venv\Scripts\python.exe -m ruff check` on all changed Python files — pass.
- `.\.venv\Scripts\python.exe -m ruff format --check` on the new scratch modules/tests — pass.
- `python -m mangadl run ... -S <scratch> -n -J` — pass; reports scratch partial, archive, state, and log roots plus canonical destination control paths; no files written.
- Read-only preview against `B:\Hent\hent1imageperpage` and `E:\.tmp\mangadl` — pass; reports eight existing B: partial owners. A real scratch run is intentionally blocked until those owners are resolved or deliberately migrated. No B:/E: files were changed.
- `git diff --check` — pass; Git only notes expected Windows LF/CRLF normalization warnings.

Broader `ruff check modules/mangadl/mangadl modules/mangadl/tests` finds a
pre-existing unrelated unused `json` import in `favorites.py:4`. It was not
changed for this feature. Black's broad check stalled on this machine and was
interrupted; Ruff formatting of the new files passed instead.

The prior module handoff was stale (feature branch and 1.17.0); current main began at 1.18.0. This plan updates the immediate handoff for the 1.19.0 scratch feature while retaining older plans as historical evidence.
