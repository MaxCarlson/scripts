# Partial Safety and Merge Readiness Status

## State

S4 interactive cleanup and legacy archive reconciliation is implemented.
The 1.17.0 module suite and repository dispatcher validation are recorded
before commit. Source/log evidence shows
the accidental download was a valid broad collection expansion, not a worker
loop. The dashboard has a separate unbounded whole-log read on each render.

## Documentation Freshness

Score: **0/100 (healthy)** for 1.17.0 scope: README, project/plan handoffs,
status, checklist, CLI behavior, and version sources are synchronized. The root
validation manifest includes a mangadl target and its dispatcher run passes.

## Verification

- `python -m ruff check mangadl tests`: pass.
- `python -m compileall -q mangadl tests`: pass.
- `python -m pytest tests -q`: **170 passed**.
- `pwsh -NoProfile -File .\Invoke-Tests.ps1 -Target mangadl`: pass with
  editable dependency/package installs, compile, Ruff, CLI help, and 169 tests
  at that checkpoint.
- `pwsh -NoProfile -File .\Invoke-Tests.ps1 -Target mangadl -SkipBootstrap`:
  pass after the final CLI regression test, **170 passed**.
- Scripts-help registry tests: **42 passed** with basetemp
  `modules/mangadl/.pytest_tmp_root/scripts-help-registry`. Two earlier
  invocations without a known-writable basetemp failed before tests with
  `WinError 5`; no assertion failed.
- `git diff --check` and `git diff --cached --check`: pass, with only Git's
  existing LF-to-CRLF checkout warnings.
- Live-data read-only preview:
  `mangadl partials clean -d B:\Hent\tmphent3 -t fc7c3b753cc0 -F -j`
  later refused the active legacy owner by recent filesystem activity. Separate
  process inspection found gallery-dl PIDs 30028/14992 still writing the broad
  collection. No `B:` data was mutated.

## Next Action

User-run live acceptance remains: one ordinary gallery-dl series should confirm
direct destination-root layout plus responsive TUI/raw-log switching. The
legacy accidental partial must be stopped before archive-aware preview/apply.
S7
input-wide auth preflight is still blocked on the pre-existing S6 acceptance.
No live `B:` download, archive, state, or partial data has been mutated.
