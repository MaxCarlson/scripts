# Partial Safety and Merge Readiness Status

## State

S4 interactive cleanup and legacy archive reconciliation is implemented. The
accidental download was a valid broad collection expansion, not a worker loop.
The broad-collection guard, bounded dashboard log reader, interactive partial
browser, and archive-aware legacy reconciliation are all present in 1.17.0.

## Documentation Freshness

Score: **0/100 (healthy)** after this sync. Before correction it was **60/100
(needs review)** because README and code described 1.17.0 while project/plan
handoffs and validation counts still described the 1.16.0 baseline.

## Verification

- `python -m ruff check mangadl tests`: pass.
- `python -m compileall -q mangadl tests`: pass.
- `python -m pytest tests -q`: **182 passed** after the original stashed S4
  implementation was restored.
- `pwsh -NoProfile -File .\Invoke-Tests.ps1 -Target mangadl`: pass with
  editable dependency/package installs, compile, Ruff, CLI help, and 169 tests
  at that checkpoint.
- `pwsh -NoProfile -File .\Invoke-Tests.ps1 -Target mangadl -SkipBootstrap`:
  pass on the final 1.17.0 tree, **182 passed**, including compile, Ruff, and
  CLI help contract checks.
- Scripts-help registry tests: **42 passed** with basetemp
  `modules/mangadl/.pytest_tmp_root/scripts-help-registry`. Two earlier
  invocations without a known-writable basetemp failed before tests with
  `WinError 5`; no assertion failed.
- `git diff --check` and `git diff --cached --check`: pass, with only Git's
  existing LF-to-CRLF checkout warnings.
- Latest live-data read-only preview:
  `mangadl partials clean -d B:\Hent\tmphent3 -t fc7c3b753cc0 -F -j`
  reported 41,957 files and 17,073,852,121 bytes; status remained `dry-run`
  and no archive was supplied or mutated.
- Live network acceptance downloaded chapter 0 into an isolated destination:
  42 distinct images, 1,300,372 bytes, all under `Like No Other\c000`, with no
  gallery-dl category wrapper.
- A live TTY chapter run accepted `l`, `r`, and `l` while downloading, moving
  through activity log, raw backend log, and the worker view without freezing;
  the run completed successfully.
- A current four-URL/four-worker acceptance completed 4/4 chapters with 702
  images and 22,438,146 bytes, without retry or authentication failure.

## Next Action

The ordinary gallery-dl layout and responsive TUI/raw-log checks now pass. The
legacy accidental partial can be reconciled against an explicit archive or
cleaned with `--files-only`, but applying either deletion remains an explicit
user decision. The user explicitly deferred S7 and its potentially large
complete-series gate to a follow-up branch and approved the final merge on
2026-09-21. No live `B:` archive, state, or partial data has been mutated.
