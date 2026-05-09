# Plan: ytaedl — Bug Fixes, Sub-subcommands, Multi-root, Defaults

## Context

Several bugs were found by inspecting live filesystem state, plus a batch of new feature requests around CLI organization and download-root management.

---

## Part 1 — Bug Fixes (3 confirmed)

### Bug 1: Partial dirs accumulate for "already" URLs

**Root cause** (`downloader.py::_run_one()`):
1. Line ~1144: `url_work_dir.mkdir()` + `write_partial_meta()` runs unconditionally
2. Line ~1162: simulate check fires → if duplicate, **early `return 0, {…, already: True}` exits the function**
3. Lines ~1504-1509: cleanup block `if rc == 0: shutil.rmtree(url_work_dir)` is **never reached** because the function already returned

This matches the observed state: 11 empty partial dirs in `emma_white/_partial/` with only `meta.json`, no `.part` files, because all those URLs were detected as duplicates via simulate check.

**Fix**: Add cleanup directly before the early return in the simulate block:
```python
if sim.is_duplicate:
    if not dry_run and url_work_dir.exists():
        try:
            shutil.rmtree(url_work_dir)
        except Exception:
            pass
    # ... emit events, then:
    return 0, {…}
```

**File**: `ytaedl/downloader.py`, inside `_run_one()` simulate-duplicate early return (~line 1162)

---

### Bug 2: `worker_slot` always 0 in `meta.json`

**Root cause**: `_run_one()` has `worker_slot: int = 0` as default. `main()` never passes a slot value. Manager never adds `--worker-slot N` to the worker command in `_start_worker()`.

**Fix**:
1. Add `-W/--worker-slot` flag to `downloader.py::make_parser()` (default 0, hidden from help with `argparse.SUPPRESS` so it doesn't clutter `ytaedl worker -h`)
2. In `downloader.py::main()`, pass `worker_slot=args.worker_slot` to `_run_one()`
3. In `manager.py::_start_worker()`, append `["-W", str(slot)]` to the cmd

**Note**: Short flag `-W` is currently used in manager for `--web-view`, but **not** in downloader. Check and use an available downloader short flag (lowercase `-w` is `--work-dir`... wait, we removed work_dir. Use `-W` which is free in downloader after cleanup).

**Files**: `ytaedl/downloader.py`, `ytaedl/manager.py::_start_worker()`

---

### Bug 3: `file_path` in `meta.json` shows temp single-URL file

**Root cause**: In `downloader.py::main()`, `url_file_path=str(urlfile.resolve())` is passed to `_run_one()`. In domain-index mode the manager passes a temp file like `tmp_urls/w07_154_3.txt` as the URL file (`-f`). The original URL file path comes via `-O/--archive-source-file`.

**Fix**: In `main()`, use `archive_source_file` (which already defaults to `urlfile` when not set):
```python
# archive_source_file = Path(args.archive_source_file) if set, else urlfile
url_file_path=str(archive_source_file.resolve()),
```

**File**: `ytaedl/downloader.py::main()`, the `_run_one()` call site

---

## Part 2 — `ytaedl run` Sub-subcommands

### New CLI shape

```
ytaedl run          [core flags]             # base manager run (no watcher/grid/webview/disable flags)
ytaedl run watcher  [core+watcher flags]     # auto-enables -w; watcher flags exposed
ytaedl run grid     [core+grid flags]        # auto-enables -X; grid flags exposed
ytaedl run webview  [core+webview flags]     # auto-enables -W; webview flags exposed
ytaedl run disable  [core+disable flags]     # expose disable/tuning flags
```

**Key behavior**: All commands above start the download manager. Sub-subcommands auto-enable a feature and expose its specific flags. Core flags are available on ALL variants.

**Breaking change**: The following flags are **removed from base `ytaedl run`** and **only accessible via their sub-subcommand**:

| Removed from base `run` | Moved to |
|---|---|
| `-w/--enable-mp4-watcher`, `-o`, `-k`, `-G`, `-F`, `-m`, `-T` | `ytaedl run watcher` |
| `-X/--yt-dlp-grid-search`, `-B`, `-V` | `ytaedl run grid` |
| `-W/--web-view`, `-Y` | `ytaedl run webview` |
| `-n/--no-extdl-fallback`, `-j`, `-J`, `-N`, `-K/--skip-simulate-check`, `--no-prioritize-partial` | `ytaedl run disable` |

`--show-bars` is removed entirely (always on).

### Help format: colored sections

`ytaedl run watcher -h` output shape:
```
usage: ytaedl run watcher [options]

Start download manager with MP4 watcher enabled.
(-w/--enable-mp4-watcher is active automatically.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  SUBCOMMAND run  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  -t THREADS, --threads ...
  -P PROXY ...
  ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ SUBCOMMAND watcher ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  -o {copy,move}, --mp4-operation ...
  -F FLOAT, --mp4-trigger-free-gb ...
  ...
```

Implemented via `ColoredSectionHelpFormatter` (custom `argparse.HelpFormatter`) in a new `ytaedl/_cli_help.py`. Section colors:
- run: bold blue (`\033[1;34m`)
- watcher: bold green (`\033[1;32m`)
- grid: bold yellow (`\033[1;33m`)
- webview: bold magenta (`\033[1;35m`)
- disable: bold red (`\033[1;31m`)

### Implementation approach

**`manager.py`**: Refactor `make_parser()` into group-adding helper functions:
- `_add_run_core_args(group)` — all core run flags (~30 flags)
- `_add_watcher_args(group)` — watcher-specific flags (7 flags)
- `_add_grid_args(group)` — grid flags (3 flags)
- `_add_webview_args(group)` — webview flags (2 flags)
- `_add_disable_args(group)` — disable/tuning flags (6 flags)

`make_parser()` is rewritten to call these helpers with regular argument groups. `run_main()` stays unchanged (parses args from make_parser()).

**`ytaedl/_cli_help.py`** (NEW):
- `ColoredSectionHelpFormatter` class
- `make_run_watcher_parser()`, `make_run_grid_parser()`, `make_run_webview_parser()`, `make_run_disable_parser()`
- Each combined parser uses `add_argument_group` with colored section names and calls the helper functions

**`ytaedl/cli.py`** updated dispatch:
```python
if subcommand == "run":
    if rest and rest[0] in ("watcher", "grid", "webview", "disable"):
        profile = rest.pop(0)
        return _run_with_profile(profile, rest)
    else:
        return run_main(rest)
```

`_run_with_profile(profile, args)`:
1. Parses `args` with the combined parser for that profile
2. Injects auto-enabled flags into namespace (e.g. `namespace.enable_mp4_watcher = True`)
3. Calls `run_main()` with the merged namespace directly (bypass argparse re-parse)

**Files changed**: `ytaedl/manager.py`, `ytaedl/cli.py`, `ytaedl/_cli_help.py` (new)

---

## Part 3 — Multiple `--download-root` + `--primary-root`

### Design

```
ytaedl run -P B:\stars\ -L D:\stars\ -L E:\stars\ -U D:\stars\
```

- `-L/--download-root` (repeatable, `action="append"`): roots checked for existing downloads before attempting any URL
- `-U/--primary-root` (new): where new downloads land when NOT using proxy (`-P`); also the watcher's move-to destination
- `-P/--proxy-dl-location` stays: temporary staging root; new downloads go here first; watcher moves to primary-root

**Without proxy**: new files go to `--primary-root`; all `-L` roots checked for dupes.
**With proxy**: new files go to `-P`; all `-L` roots checked for dupes; watcher moves to primary-root (or first `-L` if `--primary-root` not set).

### Changes required

**`downloader.py`**:
- `-o/--output-dir` now defaults to `primary_root / urlfile_stem`
- `canonical_out_dirs: List[Path]` replaces single `canonical_out_dir` throughout `_run_one()`
- `_simulate_check(url, canonical_out_dirs: List[Path])` — loop through all dirs for exact+stem check
- Destination-event duplicate check in `_run_one()` — loop through all canonical dirs
- Manager passes `-o` as primary-root-based path, plus a new flag `--extra-canonical-roots` (repeatable, hidden) for the additional roots

**`manager.py`**:
- `-L/--download-root`: `action="append"`, `default=None` (resolved to `["./stars"]` if empty)
- `-U/--primary-root` (new): single path, default = first `-L` root
- `_start_worker()`: computes canonical dir from primary-root; passes additional roots as extra hidden args to downloader
- Worker command: `-o <primary_root/stem> --extra-canonical-roots <root2/stem> --extra-canonical-roots <root3/stem>`

**Files changed**: `ytaedl/downloader.py`, `ytaedl/manager.py`

---

## Part 4 — Default Changes + Cleanup

### Changed defaults

| Flag | Old default | New default |
|---|---|---|
| `-D/--unique-domain-dls` | -1 (off) | 2 |
| `-v/--max-resolution` | None (no limit) | `"2k"` |
| `-a/--archive` | None | `"./archive"` |

### Removed flags

- `--show-bars` / `-b`: removed from `make_parser()` and all references. Progress bars always shown.

### Files changed
`ytaedl/manager.py` only (defaults and removal of `--show-bars`)

---

## Part 5 — UI NDJSON observation (no bug)

The verbose NDJSON shows `downloaded` bytes staying flat while `speed_bps` decays exponentially. This is the existing stall-detector's speed-clamping behavior working correctly for a slow/throttled connection. No bug.

---

## Part 6 — `scripts/stars/` and `NUL` Mystery

**Finding**: No ytaedl code creates `./stars/` or `_flattened/` relative to the scripts root. Default paths like `"./stars"` in `_default_outdir_for()` would only be used if ytaedl was invoked directly from that directory without `-L` override. The `NUL` file in git status is a Windows-reserved device name appearing as a file — likely from another tool or script, not ytaedl.

**Action**: No code change needed. Investigate independently: `git log -- NUL` and check recent shell history.

---

## Files Changed Summary

| File | Change |
|---|---|
| `ytaedl/downloader.py` | Bug 1 fix (partial dir cleanup); Bug 2 fix (`--worker-slot`); Bug 3 fix (file_path); multi-root canonical check in `_simulate_check()` and destination-event; `--extra-canonical-roots` hidden flag |
| `ytaedl/manager.py` | Bug 2 fix (pass slot to worker); sub-subcommand refactor (group helpers); `-L` repeatable; `-U/--primary-root`; default changes; remove `--show-bars` |
| `ytaedl/cli.py` | Dispatch for `run watcher/grid/webview/disable`; `_run_with_profile()` |
| `ytaedl/_cli_help.py` | NEW: `ColoredSectionHelpFormatter`; combined parsers for each profile |
| Tests | Update existing tests for multi-root; add tests for bugs 1-3; add tests for sub-subcommand parsers |

---

## Verification

```bash
pytest modules/ytaedl/tests/ -v                    # full suite
ytaedl run -h                                      # no watcher/grid/webview/disable flags
ytaedl run watcher -h                              # colored sections: run | watcher
ytaedl run grid -h                                 # colored sections: run | grid
ytaedl run disable -h                              # colored sections: run | disable
ytaedl run watcher -t 2 -P B:\test\ -F 50         # starts with watcher
ytaedl run -D 2 -v 2k -a ./archive -h             # new defaults visible
```

---

## Questions deferred (answered, not blocking)

- `ytaedl run cleanup -h` showing manager help is **expected** — "cleanup" is passed as an unknown arg to `run_main()` which shows run's help. Not a bug; the correct command is `ytaedl cleanup partial -h`.
- Colored terminal output: confirmed feasible on PowerShell (Windows 10+) with ANSI escape codes.

