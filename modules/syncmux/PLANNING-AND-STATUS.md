# SyncMux — Planning and Status Document

**Last Updated:** 2025-11-02

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Current Status](#current-status)
3. [Architecture & Design](#architecture--design)
4. [Implementation Roadmap](#implementation-roadmap)
5. [Known Issues](#known-issues)
6. [Testing Strategy](#testing-strategy)
7. [Platform-Specific Considerations](#platform-specific-considerations)
8. [Detailed Plans (Archive)](#detailed-plans-archive)

---

## Project Overview

**SyncMux** is a cross-platform, cross-device **tmux** session manager built with Python and Textual. It provides a unified TUI for managing tmux sessions across multiple hosts (Windows 11, WSL2, Termux/Android).

### Core Goals

- **Cross-device session browser**: Aggregate sessions from configured hosts into one unified view
- **Global switcher**: `prefix+w` feel across all machines
- **Session lifecycle**: Create, attach, kill, rename sessions
- **Config-driven**: YAML-based host configuration
- **Mobile-first**: Optimized for narrow terminals (Termux/Android)
- **Async-first**: Non-blocking UI using asyncio + AsyncSSH

### Key Technologies

- **TUI Framework**: Textual (asyncio-based)
- **SSH Layer**: AsyncSSH (native async)
- **Data Models**: Pydantic
- **Config**: YAML
- **Truth Model**: tmux servers are source of truth (no app-side cache)

---

## Current Status

### What's Working

- ✅ App starts without crashing
- ✅ Help/version flags work (`-h`, `-v`)
- ✅ Vertical layout for mobile (narrow terminals)
- ✅ Host list displays configured hosts
- ✅ Session list shows tmux sessions
- ✅ Basic navigation (`j`/`k`, `tab`, `enter`)
- ✅ Refresh functionality (`r`, `ctrl+r`)
- ✅ Logging/status messages
- ✅ Connection manager with caching
- ✅ `HostWidget` and `SessionWidget` extend `ListItem`
- ✅ Attach via `os.execvp` (true TTY handoff)

### What's In Progress

- 🚧 **First-run wizard not launching** (user reports config error shown instead)
- 🚧 Platform-aware config paths (Windows vs Linux/Termux)
- 🚧 Add Host flow (TUI → YAML persistence)
- 🚧 Atomic config saves

### What's Not Started

- ⏸️ CLI flag for custom config path (`-c/--config`)
- ⏸️ Log level flag (`-l/--log-level`)
- ⏸️ Session info dialog (`i` key)
- ⏸️ Comprehensive test coverage

---

## Architecture & Design

### Architectural Principles

1. **Asynchronicity**: Fully async event-driven model (asyncio)
2. **Modularity**: Separated concerns (TUI, logic, communication, config)
3. **State-as-Truth**: Remote tmux servers are canonical source
4. **Cross-Platform Fidelity**: Consistent experience across all targets

### Data Models

```python
# Host model
Host(BaseModel):
    alias: str
    hostname: str
    port: int = 22
    user: str
    auth_method: Literal['password', 'key', 'agent']
    key_path: Optional[str] = None
    password: Optional[str] = None

# Session model
Session(BaseModel):
    id: str
    name: str
    windows: int
    attached: int
    created_at: datetime
```

### Key Components

- **`app.py`**: Main Textual app, keybindings, UI state
- **`config.py`**: Config loading/saving, platform path detection
- **`connection.py`**: AsyncSSH connection manager with caching
- **`tmux_controller.py`**: tmux command abstraction (`list/create/kill/exists`)
- **`widgets.py`**: `HostWidget`, `SessionWidget` (extend `ListItem`)
- **`screens.py`**: Modal dialogs (New/Rename/Confirm/Info)
- **`models.py`**: Pydantic data models

### UI Layout

```
┌─────────────────────────────────────┐
│ Header                              │
├─────────────────────────────────────┤
│ Host List (fixed height ~6)         │
├─────────────────────────────────────┤
│ Session Panel (flexible)            │
│  - Sessions for selected host       │
│  - Window info, attach status       │
├─────────────────────────────────────┤
│ Log View (height ~5)                │
│  - Status messages                  │
│  - Connection errors                │
└─────────────────────────────────────┘
```

### Keybindings

- **Navigation**: `j`/`k` (up/down), `tab` (switch list), `enter` (select/attach)
- **Sessions**: `n` (new), `d` (kill), `e` (rename), `i` (info)
- **Refresh**: `r` (current host), `ctrl+r` (all hosts)
- **Filter**: `f` or `/` (toggle filter)
- **Help/Quit**: `?` (help), `q` (quit)
- **Add Host**: `h` (TUI wizard) — _planned_

---

## Implementation Roadmap

### Phase 1: Core Stability (Priority 0)

#### P0.1: CLI Entrypoint & Flags
**File**: `syncmux/__main__.py`

- [ ] `-h, --help`: Show help
- [ ] `-v, --version`: Print version
- [ ] `-c, --config PATH`: Override config path
- [ ] `-l, --log-level LEVEL`: Set log level (info|debug|warning|error)
- [ ] No args: Launch TUI

**Acceptance**: `python -m syncmux -h/-v` work; `--config` overrides for load/save

#### P0.2: Platform-Aware Config Paths
**File**: `syncmux/config.py`

- [ ] Detect platform (Windows/Linux/Termux)
- [ ] Default paths:
  - Linux/WSL/Termux: `~/.config/syncmux/config.yml`
  - Windows: `%APPDATA%\syncmux\config.yml`
- [ ] `load_config(config_path: Optional[Path] = None)`
- [ ] `save_config(hosts, config_path: Optional[Path] = None)`
- [ ] **Atomic write**: temp file → flush/fsync → replace
- [ ] Helpful error if config missing

**Acceptance**: Config discovered on all platforms; saves are atomic; no corrupt files

#### P0.3: First-Run Wizard
**Files**: `syncmux/app.py`, `syncmux/screens.py`

- [x] Check if config exists on startup
- [ ] If missing, launch wizard screen (not just show error)
- [ ] Wizard prompts for:
  - Host alias
  - Hostname/IP
  - Port (default 22)
  - Username
  - Auth method (agent/key/password)
  - Conditional: key path or password
- [ ] Save to config
- [ ] Load config and continue to main UI

**Acceptance**: First run without config launches wizard; user can add host interactively

#### P0.4: Attach Handoff Robustness
**File**: `syncmux/app.py`

- [x] `_get_ssh_command` detects platform
- [x] Windows: Check OpenSSH, then Git, then PATH
- [ ] Show user-friendly error if `ssh` not found
- [ ] Include install hints per platform
- [x] Use `-t` flag for TTY allocation
- [x] Use `os.execvp` for process replacement

**Acceptance**: Attach works on all platforms; helpful errors if `ssh` missing

### Phase 2: UX Enhancements (Priority 1)

#### P1.1: Connection Manager Hardening
**File**: `syncmux/connection.py`

- [x] Connection caching & lock
- [ ] Respect host key policy (don't auto-accept)
- [ ] Auth method handling:
  - `agent`: `agent_forwarding=True`
  - `key`: `client_keys=[expanded_path]`
  - `password`: `password=...`
- [ ] Configurable timeout (env: `SYNCMUX_SSH_TIMEOUT`)
- [ ] Consistent error messages via `_get_error_message()`

**Acceptance**: Auth works for all methods; transient errors are user-friendly

#### P1.2: Add Host Flow (TUI → YAML)
**Files**: `syncmux/screens.py`, `syncmux/app.py`, `syncmux/config.py`

- [ ] Create `AddHostScreen` modal
- [ ] Fields: alias, hostname, port, user, auth_method, conditional key_path/password
- [ ] Validate input
- [ ] Append to config (atomic save)
- [ ] Refresh host list
- [ ] Select new host
- [ ] Toast/log success

**Acceptance**: Adding host persists and appears immediately with success toast

#### P1.3: Session Name Validation
**Files**: `syncmux/tmux_controller.py`, `syncmux/screens.py`

- [x] Validation rules exist (no empty, ≤100 chars, no `:` or `.`)
- [ ] Enforce in UI (inline errors)
- [ ] Sanitize spaces → underscores

**Acceptance**: Invalid names never escape to shell; errors are inline and friendly

#### P1.4: Dialog Responsiveness (Mobile)
**File**: `syncmux/app.css`

- [ ] Add `#modal` container with:
  - `width: 100%; max-width: 40;`
  - Single-column forms (labels above inputs)
- [ ] Test in ~40-60 column terminals

**Acceptance**: All dialogs readable on narrow screens

---

## Known Issues

### Critical (P0)

#### Issue 1: First-Run Wizard Not Launching
**Severity**: P0
**Status**: 🚧 In Progress
**Description**: When running `syncmux` for the first time without a config file, the app shows a config error message instead of launching the first-run wizard as described in the error message itself.

**Expected Behavior**: App should detect missing config and launch an interactive wizard to help user add their first host.

**Current Behavior**: Error dialog shown, but wizard doesn't start.

**Files Involved**:
- `syncmux/app.py` (startup logic)
- `syncmux/config.py` (config detection)
- `syncmux/screens.py` (wizard screen, if exists)

**Next Steps**:
1. Investigate startup flow in `app.py`
2. Check if wizard screen exists
3. Implement config existence check
4. Launch wizard if config missing

---

#### Issue 2: List Selection API Mismatch (Rename Crash)
**Severity**: P0
**Status**: ⏸️ Not Started
**Description**: Pressing `e` (rename) crashes with `AttributeError: 'ListView' object has no attribute 'highlighted'`.

**Root Cause**: Textual API change; `ListView.highlighted` no longer exists.

**Solution**: Replace all `.highlighted` references with version-safe helper:
```python
def _get_highlighted(list_view: ListView) -> Optional[ListItem]:
    try:
        return getattr(list_view, "highlighted_child", None) or \
               getattr(list_view, "get_highlighted", lambda: None)()
    except Exception:
        idx = getattr(list_view, "index", None)
        children = list(list_view.children)
        return children[idx] if isinstance(idx, int) and 0 <= idx < len(children) else None
```

**Files Involved**: `syncmux/app.py` (all selection handlers)

---

#### Issue 3: Focus & "No List Focused" Warnings
**Severity**: P0
**Status**: ⏸️ Not Started
**Description**: On narrow terminals, `j/k` keypresses result in "No list focused" warnings even though focus is set on startup.

**Root Cause**: Focus lost after compose/mount/refresh.

**Solution**:
1. In `on_mount()`: explicitly focus `#host-list` and set `index=0`
2. After screen push/pop or refresh, restore focus
3. Add visual focus cue (CSS `.focused` class)

**Files Involved**: `syncmux/app.py`, `syncmux/app.css`

---

### Medium Priority (P1)

#### Issue 4: Dialog Width on Phones
**Severity**: P1
**Status**: ⏸️ Not Started
**Description**: New Session modal too wide in Termux; input text off-screen.

**Solution**: Add `#modal` CSS rules (see P1.4 above)

**Files Involved**: `syncmux/app.css`, `syncmux/screens.py`

---

## Testing Strategy

### Unit Tests

#### Config Tests (`tests/test_config.py`)
- [ ] Platform path resolution (parametrize `sys.platform`)
- [ ] Atomic save (verify tmp → replace)
- [ ] Config validation (good/bad YAML)
- [ ] Missing file error message

#### Models Tests (`tests/test_models.py`)
- [x] Host model validation
- [x] Session model validation
- [ ] Auth method constraints

#### TmuxController Tests (`tests/test_tmux_controller.py`)
- [x] Parse `list-sessions` output
- [x] Handle empty sessions
- [x] Session name validation
- [ ] Malformed output handling

#### ConnectionManager Tests (`tests/test_connection.py`)
- [ ] Connection caching
- [ ] Auth method mapping (agent/key/password)
- [ ] Timeout handling
- [ ] Host key error messages

### Integration Tests

#### CLI Tests (`tests/test_cli.py`)
- [ ] `-h/--help` returns 0
- [ ] `-v/--version` prints version
- [ ] `-c/--config` overrides path

#### Attach Command Tests (`tests/test_attach.py`)
- [ ] `_get_ssh_command` platform matrix
- [ ] Windows: OpenSSH → Git → PATH
- [ ] Unix/Termux: PATH
- [ ] Error handling if `ssh` missing

#### Add Host Flow Tests (`tests/test_add_host.py`)
- [ ] Screen validates fields
- [ ] Atomic YAML write
- [ ] Host list refresh
- [ ] New host selected

### Test Coverage Goals

- **Target**: 80%+ line coverage
- **Critical paths**: 100% (config load/save, attach, connection)
- **Environment-dependent**: Mark with `pytest.mark.optional`

---

## Platform-Specific Considerations

### Windows 11 (PowerShell 7)

**Dependencies**:
- Python: Microsoft Store or python.org
- OpenSSH: Built-in (check `%SystemRoot%\System32\OpenSSH\ssh.exe`)
- Git: Optional (provides fallback `ssh.exe`)
- Terminal: Windows Terminal (recommended for Textual)

**Config Path**: `%APPDATA%\syncmux\config.yml`

**SSH Command**:
1. Check `C:\Windows\System32\OpenSSH\ssh.exe`
2. Check `C:\Program Files\Git\usr\bin\ssh.exe`
3. Fallback to PATH `ssh`

**Special Considerations**:
- Requires `pywin32` for Pageant support
- Use `os.path.expandvars()` for `%APPDATA%`

### WSL2 (Ubuntu)

**Dependencies**:
- Python: Pre-installed or `sudo apt install python3 python3-pip python3-venv`
- SSH: `sudo apt install openssh-client`
- Build tools: `sudo apt install build-essential libffi-dev python3-dev`

**Config Path**: `~/.config/syncmux/config.yml`

**SSH Command**: `ssh` from PATH with `-t` flag

**Special Considerations**:
- Network access from Termux may require port forwarding on Windows host
- Use `netsh` for port forwarding rules

### Termux (Android)

**Dependencies**:
- Python: `pkg install python openssh`
- Build tools: `pkg install build-essential libffi openssl-tool rust`
- uv: `pkg install uv` (optional, faster than pip)

**Config Path**: `~/.config/syncmux/config.yml`

**SSH Command**: `ssh` from PATH with `-t` flag

**Special Considerations**:
- Native extensions may require compilation (slow on phones)
- Hardlink warnings are harmless (Android filesystem limitation)
- Set `UV_LINK_MODE=copy` to suppress warnings
- Terminal width typically 40-60 columns

---

## Detailed Plans (Archive)

### Minimal Plan Summary

**Goal**: Fast, minimal cross-device tmux session switcher

**MVP Scope**:
1. Cross-device session browser (tree view)
2. Global switcher (`prefix+w` feel)
3. Session lifecycle (create/kill)
4. Config-driven hosts
5. No app-side cache (tmux is truth)

**Non-Goals (MVP)**:
- Auto discovery
- File transfer
- Window/pane migration
- Multiplexed shared sessions
- SSH tunnel management

**Key tmux Commands**:
```bash
# List sessions
tmux list-sessions -F "#{session_id}|#{session_name}|#{session_windows}|#{session_attached}|#{session_created}"

# Create (detached)
tmux new-session -d -s "<name>"

# Kill
tmux kill-session -t "<target>"

# Exists
tmux has-session -t "<name>"
```

**Attach Flow**:
1. Get target host + session
2. Exit Textual app (`await self.app.exit()`)
3. Build command: `['ssh', 'user@host', '-p', 'port', '-t', 'tmux', 'attach-session', '-t', 'session']`
4. Replace process: `os.execvp(cmd[0], cmd)`

---

### Handoff Summary (from Previous LM)

**What Was Done**:
- Fixed early-mount log crash (`_log()` defensive)
- `HostWidget` & `SessionWidget` now extend `ListItem`
- Added argparse CLI (`-h`, `-v`)
- Converted layout to vertical (mobile-first)
- Status indicators shortened
- Keybindings normalized (lowercase, visible feedback)
- Sample config bootstrapping

**Current Behavior**:
- App starts without crashing
- Help works
- TUI shows host/session lists, status, logs
- Mobile layout legible

**Required Changes (from handoff)**:
1. Replace `.highlighted` with version-safe helper
2. Enforce initial focus on host list
3. Make modals responsive (~40 cols)
4. Implement Add-Host dialog

---

### Architecture Deep Dive

**Technology Stack Rationale**:

| Criterion | Textual | prompt-toolkit | AsyncSSH | Paramiko |
|-----------|---------|----------------|----------|----------|
| Model | Async (asyncio) | Sync | Async (asyncio) | Sync |
| I/O Performance | Excellent (non-blocking) | Poor (blocking) | Excellent (non-blocking) | Poor (thread pool needed) |
| Dev Experience | High (declarative, CSS) | Moderate (imperative) | High (async/await) | Moderate (verbose) |

**State-as-Truth Philosophy**:
- Remote tmux servers are canonical source
- No local cache (no sync issues)
- Query on demand via `list-sessions -F`
- Parse structured output
- Re-render UI from fresh data

**State-Driven UI Pattern**:
```python
class SyncMuxApp(App):
    hosts: var[list[Host]] = reactive()
    sessions: var[dict] = reactive({})
    selected_host_alias: var[Optional[str]] = reactive(None)

    def watch_sessions(self):
        # Auto-triggered when sessions changes
        # Update SessionListView
        pass
```

**Unidirectional Data Flow**:
1. User action / background task
2. Backend updates reactive state
3. Watch method triggered
4. UI widgets updated

---

## Next Actions (Immediate)

### High Priority (Do Now)

1. **Investigate first-run wizard issue** (Current focus)
   - Read `syncmux/app.py` startup logic
   - Check if wizard screen exists
   - Implement missing wizard or fix trigger

2. **Fix list selection API** (P0)
   - Implement `_get_highlighted()` helper
   - Replace all `.highlighted` references

3. **Enforce initial focus** (P0)
   - Set focus + index in `on_mount()`
   - Add visual focus cue (CSS)

### Medium Priority (Next)

4. **Add CLI flags** (P0)
   - `-c/--config` override
   - `-l/--log-level` setting

5. **Platform-aware config paths** (P0)
   - Detect Windows vs Linux
   - Use appropriate default path

6. **Add Host wizard** (P1)
   - Create `AddHostScreen`
   - Implement atomic save

### Low Priority (Later)

7. **Comprehensive tests** (P1)
   - Unit tests for all modules
   - Integration tests for CLI/attach
   - 80%+ coverage

8. **Modal responsiveness** (P1)
   - CSS for narrow terminals
   - Single-column forms

---

## References & Resources

### Documentation
- [Textual Docs](https://textual.textualize.io/)
- [AsyncSSH Docs](https://asyncssh.readthedocs.io/)
- [tmux Formats Wiki](https://github.com/tmux/tmux/wiki/Formats)

### Repository Structure
```
syncmux/
├── __init__.py
├── app.py              # Main Textual app
├── app.css             # Styling
├── config.py           # Config load/save
├── connection.py       # AsyncSSH manager
├── models.py           # Pydantic models
├── tmux_controller.py  # tmux command abstraction
├── widgets.py          # Custom widgets
└── screens.py          # Modal dialogs
```

### Example Config
```yaml
# ~/.config/syncmux/config.yml (Linux/WSL/Termux)
# %APPDATA%\syncmux\config.yml (Windows)
hosts:
  - alias: "localhost"
    hostname: "localhost"
    user: "mcarls"
    auth_method: "agent"

  - alias: "dev-box"
    hostname: "192.168.1.100"
    port: 2222
    user: "devops"
    auth_method: "key"
    key_path: "~/.ssh/id_ed25519"

  - alias: "legacy"
    hostname: "legacy.internal"
    user: "admin"
    auth_method: "password"
    password: "INSECURE_PASSWORD"  # Use with caution
```

---

## Progress Tracking

### Milestone 1: Core Stability ⏳ In Progress
- [x] App startup without crashes
- [x] Basic navigation
- [x] Session listing
- [x] Connection manager
- [ ] First-run wizard (🚧 In Progress)
- [ ] CLI flags
- [ ] Platform-aware config
- [ ] List selection fix

### Milestone 2: Feature Complete ⏸️ Not Started
- [ ] Add Host wizard
- [ ] Connection hardening
- [ ] Session info dialog
- [ ] Filter functionality
- [ ] Auto-refresh toggle

### Milestone 3: Production Ready ⏸️ Not Started
- [ ] Comprehensive tests
- [ ] Error handling
- [ ] Documentation
- [ ] Cross-platform validation

---

**End of Planning Document**
