# Status

Current milestone: 4 — documentation and final validation.

Milestones 1–3 are complete. Immutable models validate argument vectors, pane counts and layout names. `group_panes` preserves source order, produces composite titles, returns an empty plan for zero panes, and chooses the canonical layout for each produced tab. The typed protocol separates preview, request submission, and unknown child process state; preview operations deliberately omit process arguments. The Windows Terminal backend builds multi-tab operations for all four supported layouts, applies persistent titles, sets child working directories, targets requested windows, and reports failed/no-op/unknown states. A package-local Python relay receives base64url JSON so shell metacharacters, Unicode, semicolons, and cwd values reach the child unchanged without shell interpretation. Semicolons in tab titles and target window values are rejected because WT's CLI grammar cannot safely preserve them. The 2×2 layout uses documented `move-focus` navigation because the current command-line reference does not list `split-pane --target`. The complete package suite passes (40 tests) and Ruff passes.

The isolated worktree is based on `f57b22652dfc8cd67823a2a0d1d2792b3f09a320`. Microsoft's current Windows Terminal CLI docs and current command-line parser source were checked; the host's `wt.exe --help`/`--version` probe returned no captured output, so the installed version remains unknown. Package tests (40), Ruff, `git diff --check`, module discovery, module setup help, source import smoke, and wheel build/import checks passed. The wheel contains the pane relay and imports without `agent_continuity`. No launch plan or pane geometry smoke test was attempted; those behaviors remain unverified on an actual Windows Terminal window.

No launch plan was submitted and no pane geometry was observed. No `agent_continuity` files were changed.

## LLMD-40 focused PowerShell 7 follow-up (2026-11-27)

- Branch: `feature/terminal-workspace-control-20261127`, based on refreshed `origin/main` at
  `93c0f29788fe57e56df124f699ebbd4116a7b6a8`.
- Added `powershell_plan(target_window, cwd, title)` to produce an interactive `pwsh.exe -NoLogo -NoExit` tab plan
  for a stable named Windows Terminal window. Repeating the same target name routes later tabs to that window.
- Live qualification used Windows Terminal `1.25.3131.0` and PowerShell `7.6.1`. Run
  `codex-pwsh-native-20261127-9ef5656b` targeted two sequential tabs at one unique window name; both child receipts
  recorded the expected working directory and opaque arguments. The read-only Win32 snapshot captured visible window
  `HWND=39197146`, owner `WindowsTerminal.exe` PID `53736`, class `CASCADIA_HOSTING_WINDOW_CLASS`, and test tab title
  `codex-pwsh-native-20261127-9ef5656b-tab-2`. Follow-up run `codex-pwsh-helper-live-20261127-2b4dfef6` exercised
  the helper's literal `pwsh.exe` executable and recorded start and exit receipts for PowerShell PIDs `72468` and
  `78980` (both version `7.6.1`) in the same named target. The seven pre-existing `wslhost` PIDs were unchanged; no
  WSL window was selected or interacted with.
- ProcWatch source/tests confirm `PowerShell 7` is allowed by `smart` mode's existing interactive title rule, while
  `all-consoles` still suppresses it. No live ProcWatch guard was running at observation time; no production guard
  settings or bypasses were changed.
- Focused scope follows the user's clarification to prioritize opening PowerShell 7 tabs in the same Windows Terminal
  window. Broad geometry restoration, pane closure, managed process receipts, and provider-neutral restoration APIs
  remain outside this follow-up.
- Verification on this branch: Terminal Launcher full suite `43 passed` and Ruff clean; ProcWatch
  `tests/window_guard_test.py` `10 passed` and Ruff clean. The full ProcWatch suite had two unrelated failures: its
  legacy Windows PowerShell interactive-window integration timed out after 5 seconds (the test's `finally` terminated
  its child), and a Unicode subprocess assertion passed when rerun with `PYTHONUTF8=1`. Both failure implementations
  are unchanged from `origin/main`.
- Cleanup verification found no live test-child PIDs or uniquely named test windows. The final read-only Win32
  enumeration also found no visible Windows Terminal top-level windows; this task sent no close message or
  termination request to Windows Terminal, so the timing/cause of that final desktop state is unknown.
