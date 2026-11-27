# Post-P6 Installation and Global CLI Cutover Evidence Report

**Date (UTC):** 2026-11-19  
**Toolkit Repository (`MaxCarlson/llm-agent-toolkit`) Checkout:** `C:\Users\mcarls\src\llm-agent-toolkit`  
**Scripts Repository (`MaxCarlson/scripts`) Checkout:** `C:\Users\mcarls\src\scripts`  
**Pre-Cutover Baseline SHAs:**
- `MaxCarlson/llm-agent-toolkit` `main`: `1977b276b6b9834c79665515560ce5de59322b85`
- `MaxCarlson/scripts` `main`: `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`

---

## 1. Executive Summary

The operational transition from `MaxCarlson/scripts` to `MaxCarlson/llm-agent-toolkit` is complete across both repositories and the live workstation environment:

1. **Untouched Historical Source Directories:** All 23 transferred module source directories under `C:\Users\mcarls\src\scripts\modules\` remain 100% untouched on disk (0 files deleted, moved, or modified inside those 23 directories).
2. **Standalone Toolkit Desired-State Reconciler & Editable-by-Default Bootstrap (`MaxCarlson/llm-agent-toolkit`):**
   - Independent `.venv` at `C:\Users\mcarls\src\llm-agent-toolkit\.venv` (Python 3.12.10, `include-system-site-packages = false`).
   - Default profile for `setup.py`, `bootstrap.ps1`, and `bootstrap.sh` is `all` (23 toolkit-owned modules + root `llm-agent-toolkit` manager = 24 owned distributions, plus 2 pinned external archive dependencies `termdash` and `cross_platform`).
   - Default installation mode is **editable** (`pip install -e`) with **missing-only / verified-drift reconciliation** (`toolkit_cli/reconcile.py`).
   - Deterministic SHA-256 `pyproject.toml` packaging metadata fingerprinting (`toolkit_cli.metadata.packaging_fingerprint`) stored in `.toolkit/install-state.json` (schema v2) distinguishes ordinary Python file edits (which take effect live in editable mode without reinstallation) from packaging metadata changes (`[project]`, `[build-system]`, `[tool.setuptools]`).
   - Full CLI flag parity (short and long forms): `-p/--profile`, `-x/--execute`, `-N/--non-editable`, `-f/--force-reinstall`, `-R/--recover-venv`, `-P/--python`, `-G/--global-path`, `-M/--no-path`, `-U/--remove-path`, `-v/--verbose`.
3. **Global PATH & Launcher Cutover:**
   - `C:\Users\mcarls\src\llm-agent-toolkit\bin` (29 managed `.cmd` wrappers: 28 module console scripts + `llmtk`) is registered at the front of persistent Windows User `PATH` (`HKCU\Environment\Path` via `winreg`, with timestamped backup under `.toolkit/path-backups/`), ahead of `C:\Users\mcarls\AppData\Local\Programs\Python\Python312\Scripts` and `C:\Users\mcarls\src\scripts\bin`.
   - All 28 obsolete transferred CLI `.cmd` wrappers were backed up and removed from `C:\Users\mcarls\src\scripts\bin`.
   - All 29 toolkit CLI commands resolve globally to `C:\Users\mcarls\src\llm-agent-toolkit\bin\<cmd>.cmd` from outside both repositories (`C:\Users\mcarls`) in both the current session and fresh `pwsh -NoProfile` subprocesses.
4. **Scripts Uninstallation, Permanent Exclusion Boundary, & Cross-Environment Launcher Compatibility (`MaxCarlson/scripts`):**
   - Authoritative exclusion registry created at `scripts_setup/transferred_modules.py` and wired into `setup.py`, `modules/setup.py`, `modules/setup_utils/dependency_resolver.py`, `bootstrap_latest.py`, `scripts_setup/launcher_generator.py`, `scripts_setup/setup_skills.py`, and `modules/scripts_help/scripts_help/cli.py`.
   - All 23 transferred distributions were uninstalled from `C:\Users\mcarls\src\scripts\.venv` (plus 6 broken `~*bndl` leftover directories cleaned).
   - Two library-only distributions (`resource-metrics 0.3.0` and `script-logging 0.1.1`, neither of which has any CLI entry points) are required in-process by 8 remaining `scripts`-owned packages (`backup_module`, `compresser`, `rrbackup`, `runmux`, `sysmon`, `system_manager`, `vdedup`, `scheduler`) and were installed into `scripts/.venv` as non-editable built wheels from `C:\Users\mcarls\src\llm-agent-toolkit\modules\{resource_metrics,script_logging}`. Thus **0 of 23** transferred distributions in `scripts/.venv` point to `scripts/modules/*`, `pip check` in `scripts/.venv` exits `0` (`No broken requirements found.`), and all 8 in-process `scripts` consumers pass their CLI and pytest suites.
   - `scripts/bin` wrappers now invoke `script_logging.launcher` with `-I` (isolated from `PYTHONPATH=C:\Users\mcarls\src\scripts\modules`) via the toolkit `.venv` (or `scripts/.venv` fallback) and pass `--target-python "%_VENV_PY%"` so `scripts` targets execute under `scripts/.venv` while recording telemetry to the shared `InvocationStore`.

---

## 2. Authoritative 23 Transferred Module Mapping & Pre/Post Cutover Disposition

| # | Module Directory (`modules/<dir>`) | Distribution Name (`[project].name`) | Transferred CLI Commands (`console_scripts`) | `scripts/.venv` Pre-Cutover | `scripts/.venv` Post-Cutover | `llm-agent-toolkit/.venv` Post-Cutover |
|---|---|---|---|---|---|---|
| 1 | `agent_abilities` | `agent-abilities` | `abilities`, `agent-abilities` | Editable (`scripts/modules/agent_abilities`, `0.3.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/agent_abilities`, `0.3.0`) |
| 2 | `agent_benchmark` | `agent-benchmark` | `agent-bench`, `agent-benchmark`, `agent_benchmark` | Editable (`scripts/modules/agent_benchmark`, `1.20.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/agent_benchmark`, `1.28.0`) |
| 3 | `agent_memory` | `agent-memory` | `agent-memory` | Editable (`scripts/modules/agent_memory`, `0.5.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/agent_memory`, `0.6.0`) |
| 4 | `agent_skills` | `agent-skills` | `agent-skills`, `skills` | Editable (`scripts/modules/agent_skills`, `0.1.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/agent_skills`, `0.1.0`) |
| 5 | `agent_sync` | `agent-sync` | `agent-sync` | Editable (`scripts/modules/agent_sync`, `0.2.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/agent_sync`, `0.2.0`) |
| 6 | `agt` | `agt` | `agt` | Editable (`scripts/modules/agt`, `0.3.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/agt`, `0.3.0`) |
| 7 | `ai_orchestrator` | `ai_orchestrator` | `aio` | Editable (`scripts/modules/ai_orchestrator`, `0.2.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/ai_orchestrator`, `0.2.0`) |
| 8 | `benchmark_core` | `benchmark-core` | `benchmark-core`, `benchmark_core` | Editable (`scripts/modules/benchmark_core`, `0.3.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/benchmark_core`, `0.5.0`) |
| 9 | `interactive_reports` | `interactive-reports` | *(library-only)* | Editable (`scripts/modules/interactive_reports`, `0.1.1`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/interactive_reports`, `0.1.1`) |
| 10 | `knowledge_manager` | `knowledge_manager` | `km` | Editable (`scripts/modules/knowledge_manager`, `0.5.1`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/knowledge_manager`, `0.5.1`) |
| 11 | `llm-interface` | `api-parser` | `api-parser` | Editable (`scripts/modules/llm-interface`, `0.1.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/llm-interface`, `0.1.0`) |
| 12 | `llm-models` | `llm-models` | *(library-only)* | Editable (`scripts/modules/llm-models`, `0.2.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/llm-models`, `0.2.0`) |
| 13 | `llm-patcher` | `llm-patcher` | `llm-patcher` | Editable (`scripts/modules/llm-patcher`, `0.1.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/llm-patcher`, `0.1.0`) |
| 14 | `llm_local` | `llm-local` | *(library-only)* | Editable (`scripts/modules/llm_local`, `0.1.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/llm_local`, `0.1.0`) |
| 15 | `llm_monitor` | `llm-monitor` | `llm-monitor` | Editable (`scripts/modules/llm_monitor`, `0.8.3`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/llm_monitor`, `0.8.4`) |
| 16 | `lmstui` | `lmstui` | `lmc`, `lmst`, `lmstui` | Editable (`scripts/modules/lmstui`, `1.0.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/lmstui`, `1.0.0`) |
| 17 | `local_agent_bridge` | `local-agent-bridge` | `local-agent`, `local_agent` | Editable (`scripts/modules/local_agent_bridge`, `3.7.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/local_agent_bridge`, `3.10.0`) |
| 18 | `orchestrator_web_viewer` | `orchestrator-web-viewer` | `km-web`, `koweb` | Editable (`scripts/modules/orchestrator_web_viewer`, `0.2.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/orchestrator_web_viewer`, `0.2.1`) |
| 19 | `resource_coordinator` | `resource-coordinator` | `gpu-coordinator`, `rc`, `resource-coordinator` | Editable (`scripts/modules/resource_coordinator`, `1.0.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/resource_coordinator`, `1.0.0`) |
| 20 | `resource_metrics` | `resource-metrics` | *(library-only)* | Editable (`scripts/modules/resource_metrics`, `0.3.0`) | **Non-editable wheel from toolkit** (`0.3.0`, in-process compatibility for 7 `scripts` modules) | Editable (`llm-agent-toolkit/modules/resource_metrics`, `0.3.0`) |
| 21 | `script_logging` | `script-logging` | *(library-only)* | Editable (`scripts/modules/script_logging`, `0.1.0`) | **Non-editable wheel from toolkit** (`0.1.1`, in-process compatibility for `scheduler` & fallback launcher) | Editable (`llm-agent-toolkit/modules/script_logging`, `0.1.1`) |
| 22 | `web_ai_automator` | `web-ai-automator` | `web-ai-automator` | Editable (`scripts/modules/web_ai_automator`, `0.1.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/web_ai_automator`, `0.1.0`) |
| 23 | `web_ui_tools` | `web-ui-tools` | *(library-only)* | Editable (`scripts/modules/web_ui_tools`, `0.2.0`) | **Uninstalled** | Editable (`llm-agent-toolkit/modules/web_ui_tools`, `0.2.0`) |

### Documented Strict-Removal Exceptions in `scripts/.venv`
- **`resource-metrics` (`0.3.0`)** and **`script-logging` (`0.1.1`)** have **no CLI entry points** and were uninstalled from their legacy `scripts/modules/*` editable locations, then installed as non-editable distributions built from `C:\Users\mcarls\src\llm-agent-toolkit\modules\{resource_metrics,script_logging}` so that:
  1. Zero distributions in `scripts/.venv` reference `scripts/modules/<transferred>`.
  2. `pip check` in `scripts/.venv` passes with zero broken requirements (`backup-module`, `compresser`, `rrbackup`, `runmux`, `sysmon`, `system_manager`, `vdedup` require `resource-metrics`; `scheduler` requires `script-logging`).
  3. Even when `PYTHONPATH=C:\Users\mcarls\src\scripts\modules` is set in the user environment, `import resource_metrics` and `import script_logging` resolve to `scripts/.venv/Lib/site-packages` rather than failing on the outer `scripts/modules/<name>` directories as empty PEP 420 namespace packages.

---

## 3. Removed `scripts/bin` Wrappers (28 Managed `.cmd` Files)

All 28 transferred CLI wrappers in `C:\Users\mcarls\src\scripts\bin` were verified as `managed_current`, backed up prior to removal, and deleted from `C:\Users\mcarls\src\scripts\bin`:

`abilities.cmd`, `agent-abilities.cmd`, `agent-bench.cmd`, `agent-benchmark.cmd`, `agent_benchmark.cmd`, `agent-memory.cmd`, `agent-skills.cmd`, `agent-sync.cmd`, `agt.cmd`, `aio.cmd`, `api-parser.cmd`, `benchmark-core.cmd`, `benchmark_core.cmd`, `gpu-coordinator.cmd`, `km.cmd`, `km-web.cmd`, `koweb.cmd`, `llm-monitor.cmd`, `llm-patcher.cmd`, `lmc.cmd`, `lmst.cmd`, `lmstui.cmd`, `local-agent.cmd`, `local_agent.cmd`, `rc.cmd`, `resource-coordinator.cmd`, `skills.cmd`, `web-ai-automator.cmd`.

- **Preserved in `scripts/bin`**: 242 wrappers (including `termdash.cmd`, `scripts-help.cmd`, `compresser.cmd`, `sm.cmd`, `proc-stats.cmd`, `runmux.cmd`, `sysmon.cmd`, `video-dedupe.cmd`, `scheduler.cmd`, `mangadl.cmd`, `filter-prune.cmd`, and all 11 unmanaged custom wrappers).
- **`scripts_manifest.json`**: Regenerated with 151 `scripts`-owned commands and **0** transferred commands.

---

## 4. Executed Verification Evidence

### A. Toolkit Editable Bootstrap & Idempotent No-Op Second Run (`C:\Users\mcarls\src\llm-agent-toolkit`)
- **First run (`.\bootstrap.ps1 -x`)**:
  - Created `C:\Users\mcarls\src\llm-agent-toolkit\.venv` (Python 3.12.10), installed all 24 local distributions in **editable** mode plus pinned `termdash` (`2b070859d6670e185e0791efa8f4dd083473a6d2`) and `cross_platform` (`37d89136622d98c011a2bb9174332fa569650873`), generated all 29 managed launchers in `C:\Users\mcarls\src\llm-agent-toolkit\bin`, and added `C:\Users\mcarls\src\llm-agent-toolkit\bin` to the front of persistent Windows User `PATH`.
- **Second run (`.\bootstrap.ps1 -x`)**:
  - Output:
    ```text
    Install mode: editable
    Reconciliation summary (24 owned distributions): skip=24, install=0, reinstall=0, refresh=0, repair=0, missing-deps=0
    All 24 selected toolkit packages and 2 external dependencies are already satisfied (editable); skipping pip install.
    Profile: all; written
    Create: none
    Update: none
    Remove: none
    Toolkit bin: C:\Users\mcarls\src\llm-agent-toolkit\bin
    Configured on persistent PATH: yes
    Precedes competing bin dirs: yes
    Note: Windows User PATH already satisfies 'add' for C:\Users\mcarls\src\llm-agent-toolkit\bin.
    ```
  - Zero `pip install` commands executed; zero wrapper or PATH modifications performed.

### B. Global Command Resolution & `--help` Verification from `C:\Users\mcarls`
- Executed `llmtk diagnose -p all` from `C:\Users\mcarls`:
  - `source_checkout_is_installed: true`
  - `install_mode: editable`
  - `pip_check: exit 0 (No broken requirements found.)`
  - `unresolved_or_shadowed: 0` across all 29 toolkit commands (`llmtk` + 28 transferred module commands).
- Executed `where.exe` and `<cmd> --help` from `C:\Users\mcarls` for all 29 toolkit commands (`llmtk`, `abilities`, `agent-abilities`, `agent-bench`, `agent-benchmark`, `agent_benchmark`, `agent-memory`, `agent-skills`, `skills`, `agent-sync`, `agt`, `aio`, `api-parser`, `benchmark-core`, `benchmark_core`, `km`, `llm-monitor`, `llm-patcher`, `lmc`, `lmst`, `lmstui`, `local-agent`, `local_agent`, `km-web`, `koweb`, `gpu-coordinator`, `rc`, `resource-coordinator`, `web-ai-automator`): **29/29 resolved first to `C:\Users\mcarls\src\llm-agent-toolkit\bin\<cmd>.cmd` and exited `0`**.
- Spawned fresh `pwsh -NoProfile` subprocess reading persistent `User` and `Machine` `PATH` from registry and confirmed `Get-Command` resolves `agent-bench`, `local-agent`, `rc`, `km` to `C:\Users\mcarls\src\llm-agent-toolkit\bin\*.cmd` and `scripts-help`, `compresser` to `C:\Users\mcarls\src\scripts\bin\*.cmd`.

### C. Re-Running `scripts` Setup & Missing-Only Bootstrap Does Not Reinstall Transferred Modules
- Executed in `C:\Users\mcarls\src\scripts`:
  1. `python bootstrap_latest.py --dry-run` -> `Packages: 62 found, 0 missing`, `Console commands: 86 found, 0 missing proxies` (0 transferred modules or commands discovered).
  2. `python bootstrap_latest.py` -> `Summary: 0 missing package(s), 0 missing launcher(s), 155 existing launcher(s), 0 failure(s)`.
  3. `python modules/setup.py --scripts-dir C:\Users\mcarls\src\scripts --dotfiles-dir C:\Users\mcarls\dotfiles --bin-dir C:\Users\mcarls\src\scripts\bin --skip-reinstall` -> `Found 56 module(s) to process` (all 23 transferred modules skipped), 0 transferred wrappers recreated in `scripts/bin`.
  4. Post-rerun inventory check (`post_cutover_inventory.json`): **0** transferred CLI wrappers in `scripts/bin`, **0** editable installs from `scripts/modules/<transferred>` in `scripts/.venv`, `pip check` exit code `0`.

### D. Automated Test Suites Executed
- **`MaxCarlson/llm-agent-toolkit`**:
  - `tests/test_setup.py`, `tests/test_toolkit_installation_and_launchers.py`, `tests/test_reconcile_and_path.py`, `tests/test_credential_hygiene.py`, `modules/script_logging/tests/test_launcher.py`: **57 passed, 3 skipped (POSIX-only on Windows)**.
  - Includes disposable `.venv` end-to-end integration test (`test_disposable_venv_end_to_end_reconciliation_and_mode_transitions`) verifying fresh editable install, idempotent repeat run with zero `pip install` calls, live Python source edit without reinstall, interrupted install-state recovery, editable -> non-editable (`-N`) transition, and non-editable -> editable transition.
- **`MaxCarlson/scripts`**:
  - `scripts_setup/tests/transferred_modules_test.py`: **6 passed**
  - `modules/compresser/tests/cli_test.py`: **8 passed**
  - `modules/system_manager/tests/cli_test.py`: **18 passed**
  - `modules/scheduler/tests`: **130 passed**
  - `modules/scripts_help/tests`: **55 passed**
  - `modules/termdash/tests/cli_test.py`: **2 passed**
  - `modules/cross_platform/tests/clipboard_utils_test.py`: **12 passed**
