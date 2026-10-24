# Stage 1 Implementation Plan: `compresser tui` Integration via `cli_tui`

**Date:** 2026-10-24  
**Branch:** `videocompress-20261024-0920`  
**Location:** `docs/plans/20261024-0920_video-compression/01_stage1_cli_tui_plan.md`  

## 1. Overview & Objectives

Stage 1 integrates the existing `modules/cli_tui` dashboard engine into `modules/compresser`, enabling `compresser tui` (and `-T`, `--tui`) for interactive terminal management of image compression operations (`inventory`, `plan`, `estimate`, `analyze`, `compare`, `preview`, `apply`, `recover`).

This stage also resolves the two concrete blockers identified in the handoff implementation plan:
1. **Windows Curses Platform Dependency**: Add `windows-curses>=2.4.1; sys_platform == 'win32'` to `modules/cli_tui/pyproject.toml` and provide graceful runtime fallback handling if curses is missing.
2. **Windows Process-Tree Termination**: Enhance `ProcessRunner.terminate()` and `ProcessRunner.kill()` in `modules/cli_tui/cli_tui/process_runner.py` to kill descendant process trees on Windows using `taskkill /PID <pid> /T` and `taskkill /F /T /PID <pid>`, preventing orphaned children (e.g. FFmpeg, worker processes).

## 2. Boundaries & Safety Gates

- **Zero Breakage of Existing Image Workflows**: All existing image compression subcommands and 517 tests must pass without alteration.
- **Zero Breakage of MangaDL**: `mangadl tui` and all 329 MangaDL tests must continue passing without regression.
- **Pre-normalization Routing**: In `modules/compresser/compresser/cli.py`, `tui` and `video` must be intercepted *before* image-only `normalize_compression_arguments(parsed)` is called.
- **No Menu Recursion**: Filter `tui` out of the introspected parser menu.

## 3. Implementation Steps

1. **Update `modules/cli_tui` Dependencies & Process Cleanup**:
   - `modules/cli_tui/pyproject.toml`: Add `windows-curses>=2.4.1; sys_platform == 'win32'`.
   - `modules/cli_tui/cli_tui/process_runner.py`: Add Windows process tree termination in `terminate()` and `kill()`.
   - `modules/cli_tui/cli_tui/app.py`: Add graceful error reporting if `curses` is unavailable.
2. **Implement `modules/compresser/compresser/tui.py`**:
   - `build_tui_app()`: Introspects `compresser` parser via `introspect_parser`, filters out `tui`, attaches post-run preview viewer for `preview` operation.
   - `launch_tui(argv=None)`: Runs `app.run()`.
3. **Route `tui` and `video` in `modules/compresser/compresser/cli.py`**:
   - Check `raw_argv` and `parsed.operation` before image normalization.
   - Attach `tui` subcommand to `build_parser()` so `compresser --help` and `compresser tui --help` work cleanly.
4. **Testing & Verification**:
   - Add unit tests for `compresser tui` and parser introspection.
   - Add unit test for Windows process tree termination in `cli_tui`.
   - Run `compresser`, `cli_tui`, `mangadl`, and `videocompress` test suites.
