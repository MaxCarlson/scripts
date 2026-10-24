# Stage 4 Migration Rehearsal Report

**Date:** 2026-10-24  
**Branch:** `shared-launchers-20261024-0925`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\shared-launchers-20261024-0925`  
**Target:** 168 Repository-Owned Wrappers in `bin/`  
**Status:** Rehearsal Completed & Verified (Real `bin/` directory remains 100% untouched pending approval)

---

## 1. Rehearsal Environment & Methodology

An automated, non-destructive migration rehearsal was executed using disposable native Windows directory trees (`tests/test_migration_rehearsal.py` and `tests/test_setup_integration.py`):
1. All 257 existing items in the live repository's `bin/` directory were replicated into disposable test workspaces.
2. The complete scan, classification, backup, dry-run, application, interrupted-run recovery, and rollback lifecycles were exercised against these test workspaces.
3. Argument-fidelity, stdio streaming, and exit-code propagation were verified across both `cmd.exe` and `pwsh` using native generated batch wrappers.

---

## 2. Wrapper Inventory & Signature Identification

The repository scan identified **168 repository-owned commands** across `modules/` and `pyscripts/`. The 257 files in `bin/` were classified by content signature:

| Category | File Count | Handling Rule | Verification Evidence |
| :--- | :---: | :--- | :--- |
| **Legacy Managed Wrappers** | **168** | Upgraded to unified v0.2.0 wrapper template | Matched known legacy signatures (`set "_V=%_B%..\.venv\Scripts"`, `set "_VENV_PY=`, `set "_PY_ABS=`). Safe to migrate. |
| **Unmanaged Custom Wrappers** | **10** | **Byte-for-byte preserved (Untouched)** | Verified in rehearsal test: `add_submodule`, `ai-cli-update`, `copyrsync`, `copyScreencapToObsidian`, `findLargestFile`, `listFiles`, `npmdocfix`, `ssh_connection_test`, `tmux_clone`, `tmux_watchdog`. Pre- and post-migration SHA-256 hashes matched identically. |
| **Obsolete Third-Party Wrappers** | **79** | **Untouched (Preserved)** | Third-party package wrappers created by historical `setup.py` looping over venv packages (`black.cmd`, `flask.cmd`, `coverage.cmd`, `fastapi.cmd`, etc.). Left unchanged; not overwritten or removed unless explicit `--cleanup` is specified. |
| **Total `bin/` Files** | **257** | — | **0 command name collisions or case-insensitivity clashes** detected across all repository-owned programs. |

---

## 3. Representative Before / After Diffs

### A. Console Script Wrapper (`mangadl.cmd`)
Eliminates PATH fallback loop and self-reference recursion; adds unified logging, manifest dispatch, and genuine exit-code return.

```diff
-@echo off
-setlocal
-set "_B=%~dp0"
-set "_V=%_B%..\.venv\Scripts"
-set "_T=%_V%\mangadl.exe"
-if exist "%_T%" (
-  "%_T%" %*
-  exit /b %ERRORLEVEL%
-)
-echo [WARN] mangadl not found in repo venv. Falling back to PATH.
-mangadl %*
+@rem scripts-toolkit-managed: v1
+@echo off
+setlocal
+set "_BIN=%~dp0"
+set "_ROOT=%_BIN%..\"
+set "_VENV_PY=%_ROOT%.venv\Scripts\python.exe"
+set "_MANIFEST=%_ROOT%scripts_manifest.json"
+if not exist "%_VENV_PY%" (
+  echo [ERROR] Python venv interpreter not found at %_VENV_PY% 1>&2
+  exit /b 127
+)
+"%_VENV_PY%" -m script_logging.launcher --manifest "%_MANIFEST%" --command "%~n0" --wrapper "%~f0" -- %*
+exit /b %ERRORLEVEL%
```

### B. Python File Wrapper (`append_clipboard.cmd`)
Eliminates machine-dependent absolute paths hardcoded into the wrapper; resolves dynamically relative to wrapper directory (`%~dp0..\`).

```diff
-@echo off
-setlocal
-set "_VENV_PY=C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe"
-set "_SCRIPT=C:\Users\mcarls\src\scripts\pyscripts\append_clipboard.py"
-if exist "%_VENV_PY%" ( 
-  "%_VENV_PY%" "%_SCRIPT%" %*
-  exit /b %ERRORLEVEL%
-)
-python "%_SCRIPT%" %*
+@rem scripts-toolkit-managed: v1
+@echo off
+setlocal
+set "_BIN=%~dp0"
+set "_ROOT=%_BIN%..\"
+set "_VENV_PY=%_ROOT%.venv\Scripts\python.exe"
+set "_MANIFEST=%_ROOT%scripts_manifest.json"
+if not exist "%_VENV_PY%" (
+  echo [ERROR] Python venv interpreter not found at %_VENV_PY% 1>&2
+  exit /b 127
+)
+"%_VENV_PY%" -m script_logging.launcher --manifest "%_MANIFEST%" --command "%~n0" --wrapper "%~f0" -- %*
+exit /b %ERRORLEVEL%
```

### C. Unmanaged Custom Wrapper (`add_submodule`)
```diff
# (NO CHANGES - Unmanaged user-created file preserved byte-for-byte)
```

### D. Obsolete Third-Party Wrapper (`black.cmd`)
```diff
# (NO CHANGES - Preserved untouched unless --cleanup is explicitly requested)
```

---

## 4. Rehearsal Verification Results

The automated rehearsal suite executed the following tests:
- **`test_disposable_rehearsal_full_workflow`**:
  - Full migration applied to disposable rehearsal directory.
  - 168 wrappers updated to current managed signature.
  - All 10 unmanaged custom scripts verified with 100% byte-for-byte SHA-256 hash preservation.
  - All 79 obsolete third-party wrappers verified with 100% byte-for-byte SHA-256 hash preservation.
  - Automated backup verified complete.
  - Idempotent re-run verified: 0 unnecessary file modifications when up-to-date.
  - Interrupted recovery tested: re-running migration after partial failure preserves original pre-migration baseline in backup.
  - Full rollback executed: all 257 files in disposable `bin/` restored to exact pre-migration state, verified with identical SHA-256 hashes across every file.
- **`test_rehearsal_cmd_and_powershell_execution`**:
  - Rehearsal wrapper executed under `cmd.exe`: verified spaces (`"with space"`), quotes (`"quotes\"inside"`), and Unicode (`"unicode_🚀_日本語"`).
  - Rehearsal wrapper executed under `pwsh`: verified PowerShell argument passing (`["first", "second with space", "🚀"]`).
  - Child failure code propagation: verified return code `42` propagates through wrapper without being masked.

---

## 5. Integration of Setup Entry Points

All four repository setup entry points have been updated to delegate wrapper generation to `launcher_generator`:
1. **`modules/setup.py` (`generate_console_proxies`)**: Employs `write_wrapper` and `is_managed_wrapper`, preserving any unmanaged user scripts and updating `scripts_manifest.json`.
2. **`pyscripts/setup.py` (`_make_windows_wrapper`, `_make_posix_wrapper`)**: Employs `write_wrapper` and `is_managed_wrapper`, preserving unmanaged scripts and synchronizing `scripts_manifest.json`.
3. **`bootstrap_latest.py` (`write_console_proxy`)**: Employs `generate_windows_wrapper` and `generate_posix_wrapper` while preserving strict `FileExistsError` missing-only creation semantics.
4. **`scripts_setup/setup_utils.py` (`_create_windows_cmd_wrapper`)**: Employs `write_wrapper` and `is_managed_wrapper`, eliminating legacy hardcoded Python path wrappers.

**CLI Compatibility:** All existing arguments (`--verbose`, `-v`, `--dry-run`, positional package lists) remain 100% compatible.

---

## 6. Commit Pollution Prevention

- `.gitignore` updated to ignore:
  - `.launcher_backup_*` (automatic migration snapshots)
  - `scripts_manifest.json` (repository command manifest generated dynamically)
- Production `C:\Users\mcarls\src\scripts\bin` remains 100% unmodified.
