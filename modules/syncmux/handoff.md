# SyncMux — LM Handoff Summary

Purpose: enable a new LM/engineer to resume work on the **SyncMux** Python TUI (Textual) app where the previous LM left off. This doc captures **current state**, **changes made**, **open bugs**, and **next actions with precise code touch-points**.

---

## 1) One-Sentence Overview

**SyncMux** is a Textual-based, cross-device **tmux** session manager with a config-driven host list, session browser, and actions (create/kill/rename/attach), optimized to be usable on **narrow Termux/Android terminals**.

---

## 2) How To Run (Termux or any shell)

- Ensure dependencies are installed (Textual, paramiko/asyncssh or whatever the project uses for SSH; the repo already contains code for connection management).
- Create minimal config (if not present):

    ```
    mkdir -p ~/.config/syncmux
    printf '%s\n' \
      'hosts:' \
      '  - alias: "localhost"' \
      '    hostname: "localhost"' \
      '    user: "<YOUR_USER>"' \
      '    auth_method: "agent"' \
      > ~/.config/syncmux/config.yml
    ```

- Run help / app:

    ```
    python -m syncmux -h
    python -m syncmux
    ```

Expected: app starts, shows a vertical, mobile-friendly layout; host list at top; compact status line; session pane; short log at bottom. With no SSHD running you’ll see a polite connection error, but the TUI should stay up.

---

## 3) Key Changes Already Implemented

### Crash & Architecture Fixes
- **Early-mount log crash**: `SyncMuxApp._log()` queried `#log-view` before widgets were ready.  
  **Fix**: made `_log()` defensive with a `try/except` around `self.query_one("#log-view", RichLog)` so startup watchers don’t explode.

- **ListView items**: `HostWidget` & `SessionWidget` now **inherit from `ListItem`** (not `Widget`) to be valid children of `ListView`.

- **CLI help**: Added argparse in `syncmux/syncmux/__main__.py` to support `-h/--help` and `-v/--version`.

### Mobile/Narrow Terminal UX
- Converted main layout to **vertical** stack for narrow screens:
  - `#main-container`: `layout: vertical`
  - `#host-list`: fixed **height ~6**, full width
  - `#session-panel`: fills remaining space
  - `#log-view`: **height ~5**
- Status indicators shortened (“Sort: Name”, “Refresh: OFF (P)”).
- Keybindings normalized to **lowercase** and expanded; added **visible feedback**:
  - `j/k` move with log arrows **↑/↓** and **notify()** to show toasts
  - `tab` switches focus (log + toast “HOSTS/SESSIONS list active”)
  - All actions log success/failure with ✅/❌, and short messages

### Config Bootstrapping
- Sample `~/.config/syncmux/config.yml` helps first-run succeed.

---

## 4) Current Behavior Snapshot

- App **starts without crashing**.
- Help works: `python -m syncmux -h`.
- TUI shows host list, status indicators, session list (empty without SSH), and logs.
- Logs show config load, refresh attempts, and connection errors (expected when no SSH server).
- On phones, **layout is legible**; toasts appear for many keypresses.

---

## 5) Known Issues (to fix first)

### P0 — List selection API mismatch (rename crash)
- **Crash** when pressing **`e` (rename)**:
  ```
  AttributeError: 'ListView' object has no attribute 'highlighted'
  ```
- Likely due to a **Textual API change**. In recent Textual versions, `ListView` no longer exposes `.highlighted`. Common replacements:
  - `list_view.index` (int), `list_view.children` (items), or
  - `list_view.get_highlighted()` / `list_view.highlighted_child` (version-dependent).
- Impact: several places assume `.highlighted` on **host** and **session** list views.

**Required change pattern** (example):
- Replace:
    ```
    item = session_list.highlighted
    ```
  With (one of):
    ```
    # Option A (newer Textual):
    item = session_list.highlighted_child

    # Option B (utility, version agnostic-ish):
    def _get_highlighted(list_view: ListView) -> Optional[ListItem]:
        try:
            return getattr(list_view, "highlighted_child", None) or \
                   getattr(list_view, "get_highlighted", lambda: None)()
        except Exception:
            idx = getattr(list_view, "index", None)
            children = list(list_view.children)
            return children[idx] if isinstance(idx, int) and 0 <= idx < len(children) else None
    ```
  Then dereference custom attributes set by your widgets:
    ```
    if isinstance(item, HostWidget):   host = item.host
    if isinstance(item, SessionWidget): session = item.session
    ```

> **Action**: audit **all** references to `.highlighted` in `app.py`; convert to a helper (`_get_highlighted(list_view)`) and call it everywhere.

---

### P0 — Focus & “No list focused” warnings
- On very narrow terminals, user pressed `j/k` and received “❌ No list focused” even though we try to focus host list on startup.
- Cause: focus set during boot may be lost after compose/mount/refresh, or not visually obvious.

**Actions**:
1. In `on_mount()` (or end of `compose()` if used), **explicitly**:
    - `host_list.focus()`
    - ensure a **selected row**: set `host_list.index = 0` when hosts exist
    - set `self.selected_host_alias = self.hosts[0].alias`
2. After any screen push/pop or async refresh, **re-assert** focus to the last intended list.
3. Add a **visible focus cue** via CSS classes (e.g., add/remove `.focused` on the ListView containers to invert border or dim the unfocused list).

---

### P1 — Dialog width on phones
- **New Session** modal is too wide in Termux; input text is off-screen.

**Actions**:
- Give the modal container an id/class (e.g., `#modal`), then in `app.css`:
    ```
    #modal {
        width: 100%;
        max-width: 40;
        margin: 0 1;
        border: solid $primary;
    }
    ```
- Prefer **single-column forms** with labels above inputs on narrow screens.

---

### P1 — Add Host “wizard” (usability)
User wants easy host setup **from the TUI**:
- Bind `h` to open a small form:
  - fields: **alias**, **hostname**, **port** (default 22), **user**, **auth_method** (`agent|password|key`), **password/key_path** conditional on auth
- On submit:
  - Validate, **append to `~/.config/syncmux/config.yml`**, reload hosts, select new host.
  - Log/Toast `✅ Host added: <alias>` or `❌ <reason>`.

> Keep label/field widths phone-friendly; reuse the same `#modal` rules.

---

## 6) Files & Touch-Points

### Python
- `syncmux/syncmux/app.py`
  - `_log()` made defensive (early mount)
  - Keybindings overhauled (lowercase, added toasts)
  - Focus switching logs/toasts
  - Selection & action flows log clearly
  - **TODO**: replace all `.highlighted` usage with version-safe helper; enforce initial focus/selection in `on_mount()`.
  - **TODO**: Add `h` Add-Host screen and write-back logic; narrow-screen modal sizing (with CSS id/class hooks).

- `syncmux/syncmux/widgets.py`
  - `HostWidget` and `SessionWidget` now **extend `ListItem`**
  - Ensure each exposes `.host` / `.session` attributes, used by actions.

- `syncmux/syncmux/__main__.py`
  - argparse-based `-h/--help` and `-v/--version` implemented.

- (If present) `syncmux/syncmux/config.py`
  - Loader reads `~/.config/syncmux/config.yml`, where an example exists at repo root.

### CSS
- `syncmux/syncmux/app.css`
  - **Vertical stack** for mobile: `#main-container { layout: vertical }`
  - `#host-list` height ~6, full width
  - `#session-panel` fills remaining space
  - `#log-view` height reduced to ~5
  - Compact status indicators (“Sort: …”, “Refresh: …”)
  - **TODO**: Add `#modal` sizing rules for dialogs; add a `.focused` cue for active ListView.

### Config
- `syncmux/config.yml.example` — reference file for user config.

---

## 7) Keybindings (current intent)

- **Navigation**: `j`/`k` (list up/down), `tab` (switch list), `enter` (select)
- **Sessions**: `n` (new), `d` (kill), `e` (rename), `i` (info)
- **Refresh**: `r` (current host), `a` (all)
- **Auto-refresh**: `p` toggle, `=` increase interval, `-` decrease
- **Filter**: `f` or `/` toggle
- **Help/Exit**: `h` or `?` (help), `q` (quit)
- **Planned**: `h` is repurposed in this handoff as **Add Host**; if there’s a conflict, move help to `?` only.

---

## 8) Acceptance Criteria (for this pass)

- App starts and is **fully navigable on Termux**.  
- Pressing `j/k` **moves selection** with visible focus cue; no “No list focused” warnings on first use.  
- **Rename (e)**, **Kill (d)**, **New (n)** **do not crash**; selection retrieval works with the installed Textual version.  
- **New Session** and **Add Host** dialogs are **readable** on a 40–60-column terminal (inputs visible while typing).  
- All actions emit a concise log line and (short-lived) toast.

---

## 9) Concrete Next Steps (ordered)

1. **Fix selection API**:
    - Create utility `_get_highlighted(list_view: ListView) -> Optional[ListItem]`.
    - Replace all `.highlighted` occurrences in `app.py` (rename/create/kill/select handlers, etc.).
    - Adjust references to `.host` / `.session` on returned item types.

2. **Enforce initial focus & selection**:
    - In `on_mount()`: focus `#host-list`; if hosts present, set `index=0`, set `self.selected_host_alias`, and log/notify ready message.
    - After `push_screen`/`pop_screen` or refresh, restore intended focus.

3. **Make modals responsive**:
    - Add `#modal` container; apply `max-width` and margins in CSS.
    - Ensure forms are single-column with labels above inputs; test in ~40 cols.

4. **Implement Add-Host flow (key `h`)**:
    - Lightweight screen with fields and validation.
    - Append to YAML and reload hosts atomically; handle errors with ❌ log/toast.

5. **Smoke tests & small unit tests**:
    - Add a minimal **pytest** for config parsing and the `_get_highlighted()` helper (mock `ListView` children).

---

## 10) Useful Repro Notes

- If you see connection errors on **localhost**: Termux’s `sshd` may not be running or is on a non-standard port. That’s expected; the TUI should **not crash** and should log the failure cleanly.
- The earlier crash stack shows the rename path; test with:
    - Start app → ensure focus on host list → press `e` (should prompt or warn gracefully), `n` (dialog should be narrow), `d` (confirm prompt shows and works without crashing).

---

## 11) Open Questions (nice-to-answer but not blockers)

- Exact **Textual** version? (Determines which ListView selection API is available out of the box.)
- SSH layer used (`asyncssh` vs. `paramiko` wrappers)? Affects error surfaces/messages and reconnection behavior.
- Desired persistence model for **recent selections / UI state** across runs?

---

## 12) Quick Inventory (paths touched)

- `syncmux/syncmux/app.py` — main app logic, keybindings, actions, logging/toasts, focus
- `syncmux/syncmux/widgets.py` — `HostWidget` / `SessionWidget` are `ListItem`s with `.host`/`.session`
- `syncmux/syncmux/app.css` — vertical layout, compact indicators, small log; **TODO: modal + focus styles**
- `syncmux/syncmux/__main__.py` — argparse help/version
- `syncmux/config.yml.example` — sample config
- `~/.config/syncmux/config.yml` — user config (created for localhost during debugging)

---

## 13) TL;DR for the next LM

1) Replace **`.highlighted`** with a **version-safe selection helper**, wire all selection sites to it.  
2) Force **initial focus** and **row selection** on host list; add visual **focus cue**.  
3) Make **modals responsive** for ~40-col terminals.  
4) Implement **Add Host** dialog + YAML append + live reload.  
5) Re-test `j/k`, `tab`, `enter`, `n/d/e/i`, `r/a/p/s/f`, `q`, and confirm **toasts + logs** appear and no crashes occur.

Once these are in, SyncMux should feel solid on Termux and desktop alike.
