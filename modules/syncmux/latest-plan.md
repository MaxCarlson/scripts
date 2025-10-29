# SyncMux — **Final LLM CLI Execution Plan** (Repo-Aware, Deterministic, Feature-Complete)

> This plan is written for an autonomous CLI LLM that can read/write the repo. It consolidates the original research, handoff notes, minimal plan, and the current repository snapshot (from `syncmux_module.txt`). Follow it **exactly**. When something doesn’t match, **fail fast with a clear diagnostic** instead of guessing.

---

## 0) Operating Rules (Do Not Violate)
1. **Interface freeze:** Only additive changes unless this plan explicitly says otherwise. Keep public CLIs, files, class/method names, and flags intact.
2. **Whole-file edits:** When you modify a file, output the **entire file** with **4-space indents**.
3. **Cross-platform:** Must run on **Windows 11 + PowerShell 7**, **WSL2/Ubuntu**, and **Termux**.
4. **Async-first:** No blocking network calls on the UI loop. Use **AsyncSSH** for SSH/tmux.
5. **CLI flags:** Every long flag must have a single-letter short alias (e.g., `-v` + `--version`, `-c` + `--config`).
6. **Security:** Never log secrets; if password auth is enabled, warn to set strict file perms.
7. **Tests:** Add/maintain `pytest` coverage; prefer pure unit tests and mark environment-sensitive tests as `@pytest.mark.optional` or guarded by `shutil.which("tmux")`.

---

## 1) Repo State You Must Expect (from uploaded bundle)
Key files present (non-exhaustive):
- `main.py` (runs `SyncMuxApp`)
- `pyproject.toml` (Poetry; console script points to `syncmux.__main__:main`)
- `config.yml.example`
- `syncmux/`
  - `app.py` (Textual app; vertical layout, focus set to host list on mount; filtering, sorting, auto-refresh; attach via `os.execvp`; `_get_ssh_command` with Windows special-casing)
  - `app.css` (mobile-first vertical layout; filter bar; indicators; log)
  - `config.py` (**Linux path only**; `load_config`, `save_config` without atomic write)
  - `connection.py` (AsyncSSH `ConnectionManager` with caching, 10s timeout)
  - `models.py` (Pydantic `Host`, `Session`)
  - `tmux_controller.py` (list/create/kill/exists; sanitize rules; `check_tmux_available`)
  - `widgets.py` (`HostWidget`/`SessionWidget` extend `ListItem`, expose `.host`/`.session`)
  - `screens.py` (`NewSessionScreen`, `RenameSessionScreen`, `ConfirmKillScreen`, `SessionInfoScreen`)
- `tests/` (multiple tests for models, config, controller, app, widgets, screens, platform, etc.)
- **Potential gap**: `syncmux/__main__.py` referenced by pyproject, but its content was not in the extracted file section. Ensure it exists and wires CLI flags/version.

**Consequence:** Many P0 items from earlier plans are already implemented (vertical layout, focus on host list, attach via `execvp`, ListItem usage). This plan focuses on **completing platform edges, CLI shape, robustness, atomicity, and test coverage**.

---

## 2) Top-Priority Deltas (Implement in Order)

### P0. Ensure CLI Entrypoint & Flags are Complete
- **File:** `syncmux/__main__.py` (create or reconcile)
- Provide argparse-based CLI with:
  - `-h, --help` (default)
  - `-v, --version` (print package version from metadata or `__init__.__version__`)
  - `-c, --config` (override config path; pass through into `load_config(config_path)`; default: platform path)
  - `-l, --log-level` (optional; `info|debug|warning|error`; default `info`)
  - No args → launch TUI.
- **Acceptance:** `python -m syncmux -h/-v` work; `syncmux -c <path>` uses that config at runtime.

### P0. Platform-Aware Config Paths + Atomic Saves
- **File:** `syncmux/config.py`
- Add platform detection:
  - **Linux/WSL/Termux:** `~/.config/syncmux/config.yml`
  - **Windows:** `%APPDATA%\syncmux\config.yml`
- Allow `load_config(config_path: Optional[Path] = None)` and `save_config(hosts, config_path: Optional[Path] = None)`.
- **Atomic write** in `save_config`:
  1. Write to `config.yml.tmp`
  2. `f.flush(); os.fsync(f.fileno())`
  3. `os.replace(tmp, final)`
- Validate YAML; raise `FileNotFoundError` with a **helpful message** if missing.
- **Acceptance:** On Windows, config is discovered in `%APPDATA%`; save is atomic; `--config` overrides both load/save.

### P0. Attach Handoff Robustness (Already Good—Add Fallbacks)
- **File:** `syncmux/app.py`
- `_get_ssh_command` already checks Windows `ssh.exe` (OpenSSH, then Git). Add **PATH fallback last** (already present).
- For Termux, current behavior (PATH `ssh`) is fine; keep `-t`.
- **Acceptance:** Attach works across platforms; if `ssh` not found, show user-friendly error and how to install (Windows optional feature/Git, Termux `pkg install openssh`, Ubuntu `sudo apt install openssh-client`).

### P1. Connection Manager Hardening
- **File:** `syncmux/connection.py`
- Keep caching & lock. Add:
  - **Host key policy:** respect default AsyncSSH behavior; if a host key check fails, raise with actionable message (do not auto-accept).
  - **Agent vs key vs password:** ensure:
    - `agent` → `agent_forwarding=True` (leave agent default True)
    - `key` → `client_keys=[expanded_path]` with `os.path.expanduser`
    - `password` → pass `password=...`
  - **Timeouts:** `connect_timeout=10`; make it constant or configurable via env `SYNCMUX_SSH_TIMEOUT`.
- **Acceptance:** Transient errors return consistent messages via `_get_error_message()`; no unhandled `asyncssh` exceptions leak.

### P1. Config “Add Host” Flow (TUI → YAML)
- **Files:** `syncmux/screens.py`, `syncmux/app.py`, `syncmux/config.py`
- There are dialogs for New/Rename/Confirm; add **Add-Host** screen *only if not present*:
  - Fields: `alias`, `hostname`, `port(22)`, `user`, `auth_method (agent|key|password)`, conditional `key_path|password`
  - Validate (+ sanitize alias); append to current config (`save_config`) using the same override path as runtime
  - **Atomic write** (from above); refresh hosts; select the new host; toast/log ✅
- Map to key: `h` (if `h` is currently “Help”, move help to `?`).
- **Acceptance:** Adding a host persists and immediately appears in Host list with a success toast.

### P1. Session Name Validation (Already Good—Enforce UI Errors)
- **Files:** `syncmux/tmux_controller.py`, `syncmux/screens.py`
- Validation rules exist (no empty; ≤100 chars; no `:` or `.`; only letters, digits, `_`, `-`, spaces; spaces → `_`).
- Ensure **New Session** screen surfaces errors inline (already present with `#error-message`).
- **Acceptance:** Invalid names never shell-escape into dangerous strings; errors are user-friendly toasts and inline.

---

## 3) Test Suite: Fill Gaps, Make Deterministic
Create or adjust tests to reflect new behavior (many already exist):

1. **CLI/Entrypoint** (`tests/test_cli.py`)
   - `python -m syncmux -h` returns 0
   - `python -m syncmux -v` prints semver
   - `syncmux -c <tmpfile>` launches app constructor with overridden path (mock `SyncMuxApp.run` to avoid UI)

2. **Config Paths** (`tests/test_config_paths.py`)
   - Parametrize `sys.platform` and env `%APPDATA%` to assert default path resolution on Windows vs Linux/Termux
   - `save_config` is atomic: write tmp + replace; simulate crash between write and replace (mock to verify that final does not corrupt)

3. **Connection Manager** (`tests/test_connection_manager_edges.py`)
   - Key/password/agent modes map to AsyncSSH parameters (patch `asyncssh.connect` and capture kwargs)
   - Timeout honored (env override)
   - Host key error surfaces friendly message

4. **Attach Command** (`tests/test_attach_cmd.py`)
   - `_get_ssh_command` platform matrix (Windows OpenSSH/Git/Path; Unix/Termux PATH) yields correct argv
   - If `ssh` missing everywhere (simulate), app logs and does not crash

5. **Add Host Flow** (`tests/test_add_host_screen.py`)
   - Screen validates fields, writes YAML atomically, refreshes host list, selects new host (mock `save_config`, then assert calls/order)

> Keep existing tests intact. Mark environment-dependent ones as optional using `pytest.importorskip` or a custom skip if `tmux` or `ssh` unavailable.

---

## 4) File-by-File Edit Directives (Anchored)

### 4.1 `syncmux/__main__.py` (Create/Reconcile)
- Provide `main()` with argparse:
  - `-v/--version`
  - `-c/--config` (Path)
  - `-l/--log-level` (info|debug|warning|error)
- Wire `config_path` into `SyncMuxApp` via environment or constructor arg (preferred: constructor arg).
- Print version from `syncmux.__init__.__version__` or package metadata fallback.

### 4.2 `syncmux/__init__.py`
- Add `__version__ = "0.1.0"` (or read from installed metadata where feasible).
- Keep it minimal.

### 4.3 `syncmux/config.py`
- Replace `CONFIG_PATH` constant with:
  - `def default_config_path() -> Path:` platform-aware
- Refactor:
  - `load_config(config_path: Optional[Path] = None) -> list[Host]`
  - `save_config(hosts: list[Host], config_path: Optional[Path] = None) -> None`
- Implement **atomic write**; create parent dirs; YAML dump with `sort_keys=False`.
- Raise `FileNotFoundError` with message that includes quick-start example.

### 4.4 `syncmux/app.py`
- Constructor: accept optional `config_path: Optional[Path] = None` (thread through to `load_config`/`save_config` and Add-Host flow).
- `_get_ssh_command`:
  - Order on Windows: `%SystemRoot%\System32\OpenSSH\ssh.exe` → `C:\Program Files\Git\usr\bin\ssh.exe` → `ssh` (PATH).
  - If missing, log ❌ + helpful install hints (platform-specific).
- `action_attach_session`:
  - Already uses `await self.app.exit()` then `os.execvp`; keep.
  - If command formation fails, **return** gracefully after logging.
- `action_show_help` (if `h` is repurposed): move to `?` keybinding (ensure listing shows it).
- Ensure any config save calls use the overridden path when present.

### 4.5 `syncmux/screens.py`
- Add **AddHostScreen** with responsive layout (single column, labels above inputs). Use same `#modal` container style as other screens.
- On submit:
  - Build `Host` model; update in-memory `hosts` then call `save_config()` (with app’s `config_path`), then refresh UI.
  - Show toast/log on success; inline errors for validation problems.

### 4.6 `syncmux/app.css`
- Keep vertical layout. Add/id strengthen:
  - `#modal { width: 100%; max-width: 40; margin: 0 1; }`
  - `.focused` cue for whichever ListView is active (border / shade)
  - Ensure filter and indicators remain compact in 40–60 cols

### 4.7 `pyproject.toml`
- Ensure console script points to `syncmux.__main__:main` (already present).
- If using version constant, keep Poetry version in sync with `__init__.__version__` **manually** (document in README).

---

## 5) Commands for the Agent (Run in CI/Locally)

### Linux/WSL2/Termux
```
python -m pip install -U pip && python -m pip install -e . && pytest -q
```

```
python -m syncmux -h && python -m syncmux -v
```

```
python -m syncmux
```

### Windows (PowerShell 7)
```
python -m pip install -U pip && python -m pip install -e . && pytest -q
```

```
python -m syncmux -h && python -m syncmux -v
```

```
python -m syncmux
```

---

## 6) Acceptance Checklist (Must All Pass)
- [ ] `python -m syncmux -h/-v` works; version printed; help lists short+long flags including `-c/--config`.
- [ ] Default config path resolves correctly on all platforms; `--config` overrides for both load/save.
- [ ] Config writes are **atomic**; no partial/corrupt files if interrupted.
- [ ] Attach flow performs a **true TTY handoff** using `os.execvp` and works on Windows/WSL2/Termux (with helpful install hints if `ssh` missing).
- [ ] Add-Host flow persists to YAML and live-refreshes the Host list with selection + success toast.
- [ ] Connection errors are consistently messaged; no raw AsyncSSH tracebacks leak.
- [ ] Tests pass (`pytest -q`), with environment-dependent tests skipped when tools not present.

---

## 7) Risk Notes & Contingencies
- **Textual API drift:** Current code uses `ListView.index` and `children` (already version-safe); if API changes again, add a `_get_highlighted(list_view)` helper with layered fallbacks.
- **AsyncSSH wheels on Termux:** If building is required, prompt user to `pkg install clang rust openssl-tool` (do **not** attempt at runtime).
- **Windows SSH location variability:** We already search OpenSSH and Git; PATH fallback final.

---

## 8) Minimal README Amendments (if needed)
- Document `--config` flag and platform default config paths.
- Add quick “first-run” snippet for creating a localhost entry.
- Warn about password auth and file permissions.

---

## 9) Final Deliverables
- **Updated files (full):**  
  `syncmux/__main__.py`, `syncmux/__init__.py`, `syncmux/config.py`, `syncmux/app.py`, `syncmux/screens.py` (if AddHost added), `syncmux/app.css`, plus **new tests** in `tests/` named above.
- **No partial snippets.** 4-space indents. Cross-file consistency (flags/help/docs/tests).

> If any expected symbol/file is missing or differs, **stop and emit**:  
> “Expected `<path or symbol>` not found. Found `<closest match>`. Aborting per interface-freeze rule.”

---
