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
  window. The 2026-11-27 continuation below adds managed receipts without changing the ordinary unmanaged API.
- Verification on this branch: Terminal Launcher full suite `43 passed` and Ruff clean; ProcWatch
  `tests/window_guard_test.py` `10 passed` and Ruff clean. The full ProcWatch suite had two unrelated failures: its
  legacy Windows PowerShell interactive-window integration timed out after 5 seconds (the test's `finally` terminated
  its child), and a Unicode subprocess assertion passed when rerun with `PYTHONUTF8=1`. Both failure implementations
  are unchanged from `origin/main`.
- Cleanup verification at the end of the earlier PowerShell helper follow-up found no live test-child PIDs or
  uniquely named test windows. That stage sent no close message or termination request to Windows Terminal; its final
  empty enumeration predates the managed lifecycle desktop tests documented below.

## LLMD-40 managed lifecycle continuation (2026-11-27)

- Added optional `launch_managed()` with caller-supplied or generated launch identity, deterministic per-tab/pane IDs,
  bounded positive spawn acknowledgment, and separate request/spawn/readiness/exit/failure/unknown status.
- The pane relay persists PID plus Windows creation FILETIME and its own exact process identity. SQLite stores only
  opaque launch/pane IDs, a hash of the target window name, requested layout/indexes, process identities, timestamps,
  numeric exit codes, failure codes, and shutdown receipt flags. It does not persist argv, cwd, titles, environment,
  prompts, or credentials. Store schema adds missing relay identity columns for compatibility.
- `request_graceful_shutdown()` validates both exact child and owning relay identities before queueing. The owning relay
  revalidates the child and sends Ctrl+Break only to its process group; it never targets WindowsTerminal.exe. A live
  interactive PowerShell test showed Ctrl+Break delivery does not always close the shell. The API therefore reports
  request delivery separately from exit and makes no guaranteed-exit claim. The two test windows were closed with
  bounded WM_CLOSE sent only to their exact uniquely titled HWNDs after recording child identities; all test child
  processes exited. The Windows Terminal host process was left running.
- Native qualification used the installed package path `WindowsTerminal_1.25.3131.0` and PowerShell 7.6.1. Two
  separate launches to `codex-managed-pwsh-cc77590a1b` both received spawn receipts and used the same observed
  `CASCADIA_HOSTING_WINDOW_CLASS` HWND `595302` (owner PID `53736`); the tab title changed from
  `...-tab-1` to `...-tab-2`. This directly verifies the user's primary workflow: open pwsh tabs in the same named
  Windows Terminal window.
- Layout run `codex-layouts-de81d8eb` submitted single, two-column, three-left, and grid tabs in one dedicated window;
  all 10 child spawn receipts arrived and all 10 exit receipts were recorded. Win32 observed one dedicated HWND
  `18420420` with the requested final tab title. Read-only UI Automation run `codex-uia2-d34b98e9` exposed four
  `TabItem` names in the requested order. The UIA tree exposed generic pane containers but no stable per-terminal-pane
  controls; their reported rectangles were far outside desktop bounds, so pane grouping/orientation/geometry remain
  unsupported/unobserved. UIA inspection was read-only and did not inspect terminal text or send input.
- The first live managed attempt found the relay's relative import failed when Python executed `_pane_runner.py` as a
  script. A direct-script regression reproduced the `ImportError`; the relay now bootstraps the package root and the
  repeated live run produced all expected child start receipts. This is covered by the full package suite.
- Validation: Terminal Launcher full suite `57 passed`, Ruff clean. A wheel build passed and included both
  `terminal_launcher/managed.py` and `terminal_launcher/backends/_pane_runner.py`. ProcWatch default full suite had exactly one
  failure, `test_exec_success_nonzero_unicode_env_and_context`, on both the feature source and the exact
  `origin/main` (`93c0f29788fe57e56df124f699ebbd4116a7b6a8`) snapshot under the same environment; both full suites
  passed when rerun with temporary `PYTHONUTF8=1`. The focused window guard tests passed. ProcWatch package version
  remains `0.4.0` to match the shared help registry because this task adds no ProcWatch production behavior.

## Managed lifecycle transactional correction (2026-11-27)

- Work remains limited to `modules/terminal_launcher`; ProcWatch production code/configuration and dispatcher code are
  unchanged. The legacy store entry points remain available as compatibility wrappers; managed launch uses atomic
  full-plan reservation and per-pane relay claims.
- Launch state now distinguishes definite rejection from ambiguous submission. Start, spawn-failure, exit, and
  interruption receipts are conditional updates. Rejection only fails unclaimed panes, so late child receipts cannot be
  overwritten. A pane claim cannot be acquired twice; ambiguous/claimed panes are never automatically retried.
- Relays persist an at-most-once `delivering` transition before Ctrl+Break. If delivery is interrupted before its receipt,
  recovery reports ambiguity and never repeats the event. Ctrl+Break is documented as an interruption request, not
  guaranteed graceful shutdown. Relay polling is pane-specific with 50 ms to 1 s adaptive intervals.
- Full Terminal Launcher validation: `76 passed`, Ruff clean, wheel built and installed/imported in an isolated venv.
  Native PowerShell 7 idle-poll measurements (3-second children): 1 child = 6 queries/8.78 ms query time; 5 =
  30/37.48 ms; 20 = 120/278.96 ms. All 26 children recorded exit code 0.
- ProcWatch remained unchanged. Its full suite passed `68/68` with `PYTHONUTF8=1`; default passed `67/68`, with only
  `test_exec_success_nonzero_unicode_env_and_context` failing. The exact `origin/main` source archive at
  `ae04cbe08acaef235c9d0b1264fa3fdc3c2a4a57` reproduced the same default Unicode failure (`65/66`) and passed
  `66/66` with `PYTHONUTF8=1`; window guard tests passed `10/10`; Ruff is clean.
- `origin/main` later advanced to `a2c09bc5a666961359df8c04303105754f66486d`; `git diff ae04cbe..origin/main --
  modules/procwatch` is empty, so the ProcWatch baseline comparison covers the current ProcWatch source unchanged.
- No live Windows Terminal GUI test was added because this correction batch changes managed lifecycle/storage and relay
  semantics only. The already accepted named-window PowerShell qualification remains the desktop evidence; independent
  GUI review of this final correction SHA is still required before integration/merge.

## Relay caller identity tightening (2026-11-27)

- `claim_pane`, start/spawn-failure/exit receipts, interruption delivery, interruption finalization, and the deprecated
  delivery wrapper now require the actual calling process to match the stored relay PID and creation FILETIME. The
  deprecated `record_failure()` wrapper can only mark a pane claimed by its current owner; reserved panes cannot be
  failed by an unrelated caller.
- Regression covers supplying the correct stored relay identity from a different caller, including the compatibility
  delivery wrapper, and checks the receipt/failure entry points for the same spoofing bypass.
- Validation: Terminal Launcher `78 passed`, Ruff clean; wheel install smoke remains to be repeated on this exact
  correction revision. The feature worktree is ready for a refreshed-main integration candidate; no dispatcher files
  have been modified.
