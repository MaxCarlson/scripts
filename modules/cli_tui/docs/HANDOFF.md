# CLI TUI Consolidation Handoff

Last updated: 2026-10-23

## Current State

- Branch: `codex/cli-tui-consolidation-20261023`
- Worktree: `C:\Users\mcarls\src\scripts\.worktrees\cli-tui-consolidation`
- Base: `main` at `da5da8f0a1691895a19b9828c09a9c5f14606503`
- Scope: `modules/cli_tui/` only; the two source worktrees remain untouched.

The integration keeps the argparse behavior, lazy package imports, parser-only
import boundary, and existing `CliTuiApp`/`ProcessRunner` interfaces from
`codex/runmux-tui-integration`. It keeps that branch's layout payload and saved
running-pane transcript format for compatibility.

From `codex/cli-tui-layout-output-capture`, it adopts explicit layout read and
write errors, strict JSON validation, visible corrupt-layout recovery, and an
atomic process snapshot/subscription seam. Output capture writes on a worker
thread with a 256-chunk bounded queue. If the writer falls behind, capture
stops, unsubscribes, retains the partial log, and reports that it may be
incomplete; subprocess output continues without waiting for the destination.
Capture close waits at most 0.5 seconds for the writer, then reports possible
incomplete output and lets TUI shutdown continue.

The `OutputFileCapture` class retains its one-path constructor, `attach`,
`write_snapshot`, and `write_chunk` methods. Existing `subscribe_output` methods
remain available. Console capture follows current output and later commands,
and removes per-process subscriptions when commands complete or capture ends.

## Verification

- From the integration worktree root, `$env:PYTHONPATH='modules'; python -m pytest -p no:cacheprovider -o addopts='' modules/cli_tui/tests -q` — 105 passed.
- With `$env:PYTHONPATH='modules;modules\mangadl;modules\compresser;modules\termdash'`, `python -m pytest -p no:cacheprovider -o addopts='' modules/mangadl/tests/tui_test.py modules/mangadl/tests/cli_structure_test.py modules/mangadl/tests/cli_test.py -q` — 51 passed.
- With `$env:PYTHONPATH='modules;modules\cli_tui;C:\Users\mcarls\.codex\worktrees\59dc\scripts\modules\runmux\src'`, Runmux branch `test_tui.py` and `test_tui_adapter.py` — 23 passed against this `cli_tui` source.
- `python -m ruff check --no-cache modules/cli_tui` — passed.
- `git diff --check` — passed.

The parser import-boundary test is included in the full `cli_tui` run. Validation
was performed on Windows 11 / Python 3.12. Windows Terminal interaction and
WSL2/Linux tests were not performed. Headless tests cover layout save/restore,
quit flows, output capture, queue backpressure, error reporting, cleanup, and
the existing application behavior.

## Next Action

Complete manual Windows TUI acceptance for layout save/restore, normal and force
quit, output capture, and existing app behavior. Merge into `main` and source
worktree cleanup remain separate.
