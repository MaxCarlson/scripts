# Partial Safety and Merge Readiness Status

## State

S4 interactive cleanup and legacy archive reconciliation is now active after
the user extended the merge boundary. The previously committed baseline passed
(`158 passed`). Source/log evidence shows
the accidental download was a valid broad collection expansion, not a worker
loop. The dashboard has a separate unbounded whole-log read on each render.

## Documentation Freshness

Score: **0/100 (healthy)** for 1.16.0 scope: README, project/plan handoffs,
status, checklist, CLI behavior, and version sources are synchronized. The root
validation manifest includes a mangadl target and its dispatcher run passes.

Alert/task: the new interactive UI and legacy reconciliation behavior must be
documented in README and handoffs and versioned before the next commit. S4 and
its checklist are the concrete documentation task.

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
  reported 34,220 files and 13,694,065,861 bytes; status remained `dry-run`,
  with zero archive mutation because this legacy partial has no manifest.

## Next Action

User-run live acceptance remains: one ordinary gallery-dl series should confirm
direct destination-root layout plus responsive TUI/raw-log switching. The
legacy accidental partial can be previewed with `--files-only`, but applying
that deletion and any archive repair remains an explicit user decision. S7
input-wide auth preflight is still blocked on the pre-existing S6 acceptance.
No live `B:` download, archive, state, or partial data has been mutated.
