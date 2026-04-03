# ytaedl Codex Status

This document is a handoff for another LLM or engineer. It summarizes the active ytaedl issues, the user's explicit requests, relevant repo context, and the code-level findings from the current investigation.

## Scope

Primary module:
- `modules/ytaedl`

Relevant files already inspected:
- `modules/ytaedl/claude-ytaedl-plans.md`
- `modules/ytaedl/ytaedl/manager.py`
- `modules/ytaedl/ytaedl/downloader.py`
- `modules/ytaedl/ytaedl/mp4_watcher.py`
- `modules/ytaedl/ytaedl/mp4_sync.py`
- `modules/ytaedl/tests/test_manager.py`
- `modules/ytaedl/tests/mp4_watcher_test.py`
- `modules/ytaedl/worker-06.txt`

## User Requirements

### 1. Keep the existing UI; do not rewrite from scratch
The user explicitly said:
- Do not start the UI from scratch.
- Use the existing, functioning UI.
- The UI uses `modules/termdash`.
- Ideally avoid modifying `modules/termdash`, but modifying it is acceptable if necessary and if existing users are not broken.

Interpretation:
- Changes should be incremental and local to ytaedl where possible.
- Any viewport/scrolling work should adapt the current UI behavior, not replace it with a new framework.

### 2. Small-screen behavior for the downloads UI
The user showed a small phone-screen rendering where only the bottom part of the downloads screen is visible. They want:
- On too-small screens, the UI should start by showing the top rows, not the bottom rows.
- The hotkeys should remain visible in the last row.
- The down-arrow key should scroll downward through the cut-off screen, pushing upper content out of view.
- The up-arrow key should scroll back upward.

Important:
- This request was about the existing downloads UI, not a new UI.
- The supplied example was from the downloads panel.
- The likely correct implementation is a viewport/sticky-footer behavior in `manager.py`.

### 3. The old `100%` / `99.90%` progress bug is still not fully fixed
The user clarified that the issue still exists.

Evidence file:
- `modules/ytaedl/worker-06.txt`

Observed behavior from that log:
- A URL reaches apparent completion:
  - `99.96% 4.99GiB/4.99GiB`
  - then repeated `100.00% 5.02GiB/5.02GiB`, `5.05GiB/5.05GiB`, etc.
- It later ends with:
  - `FINISH_BAD`
- Then the same URL immediately restarts:
  - another `START`
- After restart, progress remains effectively complete and continues increasing instead of resetting:
  - `100.00% 5.45GiB/5.45GiB`, `5.60GiB/5.60GiB`, etc.

User requirement:
- Ensure proper progress resets no matter how a download ends.
- This means both UI state and worker/downloader-emitted progress need scrutiny.

### 4. Watcher screen: better move/copy and collision visibility
The user wants the watcher screen to make it obvious:
- whether a move or copy actually happened
- whether there was already a file with the same name at the destination
- whether the transfer was replaced, skipped, or otherwise resolved

Clarification from user:
- The ability to set watcher `n` (max files to move/copy) is already implemented.
- Do not re-implement that feature.

### 5. `modules/aebndl_module` repo structure question
The user asked:
- `modules/aebndl_module` seems to want to be a submodule
- should it be brought into the repo as normal code, or added as a real submodule?

This is an open repo-management question, not yet resolved.

## Existing Plan Notes

The previous plan document is here:
- `modules/ytaedl/claude-ytaedl-plans.md`

Relevant items from it:
- fixed header / scrollable workers
- arrow key handling for small screens
- watcher panel improvements
- previous attempts to clamp >100% progress

Use that file for background, but prefer the user's later corrections in this document when there is any mismatch.

## Concrete Findings So Far

### Downloads/worker state in `manager.py`
Relevant area:
- `modules/ytaedl/ytaedl/manager.py`

Key observations:
- `WorkerState` stores:
  - `percent`
  - `speed_bps`
  - `eta_s`
  - `downloaded_bytes`
  - `total_bytes`
  - `url_index`
  - `url_current`
  - overlay state and timing
- `_reader(ws)` processes NDJSON worker events.
- On `event == "start"`, it resets progress fields.
- On `event == "finish"`, it also resets progress fields.
- Before this session's patch, `_assign(ws)` reset only:
  - `percent`
  - `speed_bps`
  - `eta_s`
  but did **not** reset:
  - `downloaded_bytes`
  - `total_bytes`
  - `url_t0`
  - `last_already`
  - overlay state

This was a real stale-state bug and could leak previous URL state into the next assignment/retry.

### Manager-side patch already applied
The following patch work has already been applied in `manager.py`:
- Added a local helper:
  - `_clear_worker_progress(ws)`
- `_clear_worker_progress(ws)` clears:
  - `percent`
  - `speed_bps`
  - `eta_s`
  - `downloaded_bytes`
  - `total_bytes`
- It is now called:
  - on worker `start`
  - on worker `finish`
  - on `aborted`
  - on `stalled`
  - on `deadline`
  - during `_assign(ws)` before reusing a worker
- `_assign(ws)` now also resets:
  - `url_t0`
  - `last_already`
  - `overlay_msg`
  - `overlay_since`

Why this matters:
- It guarantees manager-side UI state does not carry forward progress/size/ETA from a failed or previous attempt.

### Downloader-side progress clamping/reset finding
Relevant area:
- `modules/ytaedl/ytaedl/downloader.py`

Key observation:
- `_run_one(...)` tracks `last_progress` from worker tool output.
- Before this session's patch, `last_progress = evt` used the raw event.
- `_emit_json(...)` later emitted clamped progress in some paths, but the internal `last_progress` and periodic program-log output could still reflect unclamped or stale-looking values.

This matters because:
- `worker-06.txt` shows progress staying at `100.00%` and continuing to grow after a bad finish and restart.
- The periodic worker log could preserve the wrong internal progress view even when the UI is partially clamped.

### Downloader-side patch already applied
The following patch work has already been applied in `downloader.py`:
- In `_run_one(...)`, when `evt.get("event") == "progress"`:
  - `evt = _clamp_progress(evt)` now happens first
  - `last_progress = evt` now stores the clamped progress event

Why this matters:
- Program-log progress and downstream state now use clamped values earlier in the pipeline.
- This should reduce or eliminate raw `100%+` style state leakage.

### Watcher UI already has some collision counters
Relevant files:
- `modules/ytaedl/ytaedl/mp4_watcher.py`
- `modules/ytaedl/ytaedl/mp4_sync.py`
- `modules/ytaedl/ytaedl/manager.py`

Current watcher progress already exposes fields like:
- `copied_without_collision`
- `collisions`
- `replaced_dest`
- `kept_dest`
- `last_message`

Current watcher panel already shows a line similar to:
- copied with no collision count
- collision count
- replaced destination count
- kept destination count

But the user wants the presentation to be clearer and more explicit about:
- whether the action was copy or move
- whether something actually happened
- whether a same-name destination file existed
- what the conflict resolution was

### Watcher max-files control already exists
Important correction from the user:
- The watcher already supports setting the maximum number of files (`n`) from the screen.
- Do not spend time re-adding this.

## Open Work Remaining

### A. Verify the progress-reset fix against the actual failure path
What still needs verification:
- Whether the combined manager/downloader patches fully stop the stale-completion state seen in `worker-06.txt`
- Whether there are additional retry-path issues after `FINISH_BAD`
- Whether there are any other terminal worker events that should also clear state

Suggested validation:
- Reproduce with the same or similar URL that previously reached 100% then `FINISH_BAD`
- Confirm that after restart the UI does not continue from stale percent/bytes/ETA
- Confirm no worker row keeps stale totals from a previous attempt

### B. Implement the small-screen viewport behavior
Not yet implemented at the time of this handoff.

Desired behavior:
- Initial render on small screens shows the top of the downloads screen
- Hotkey row remains pinned to the bottom
- Up/down arrows scroll the non-footer content

Likely implementation location:
- `modules/ytaedl/ytaedl/manager.py`

Likely design:
- Build the screen as normal
- Apply a viewport slice before rendering
- Preserve the final hotkey row as a sticky footer
- Maintain per-panel scroll offset state
- Handle Windows arrow keys via `msvcrt.getwch()` special-key sequences (` `/`à` then `H`/`P`)

Important constraint:
- Do not rewrite the UI
- Adapt the existing implementation

### C. Improve watcher move/copy/conflict messaging
Not yet implemented at the time of this handoff.

Desired improvements:
- Make current operation explicit: copy vs move
- Show whether source cleanup happened or is expected
- Make same-name destination collisions explicit
- Make replacement vs skip explicit
- Make the "did anything actually happen?" state easy to read from the watcher panel/logs

Potential implementation points:
- `modules/ytaedl/ytaedl/manager.py` watcher panel rendering
- `modules/ytaedl/ytaedl/mp4_watcher.py` run summary / log strings
- `modules/ytaedl/ytaedl/mp4_sync.py` summary/result metadata if needed

Note:
- There is also a wording bug in watcher completion logging worth checking: the completion text should accurately say `copied` vs `moved` depending on operation.

### D. Decide what to do with `modules/aebndl_module`
Observed repo state:
- `modules/aebndl_module` is its own git repo (`git rev-parse --is-inside-work-tree` was true)
- It has a remote:
  - `git@github.com:MaxCarlson/aebn-vod-downloader-custom.git`
- It is **not** declared in the parent repo's `.gitmodules`
- Parent `.gitmodules` currently does not map `modules/aebndl_module`
- The nested repo currently has local modifications/untracked files

Interpretation:
- Right now it behaves like a nested repo but not a properly registered submodule.
- That is an awkward state.

Recommendation direction:
- If the intent is independent history + independent upstream sync, make it a real submodule.
- If the intent is tight local integration and frequent coordinated edits with ytaedl, vendor it into the main repo as normal code.
- Because it currently has its own remote and history, the cleaner default is probably: make it an explicit submodule, unless there is a strong reason to flatten it into the main repo.

## Version State

Version was bumped during this session to reflect the bug-fix work:
- `modules/ytaedl/pyproject.toml`: `1.5.4`
- `modules/ytaedl/ytaedl/__init__.py`: `1.5.4`

## Suggested Next Steps For The Next LLM

1. Verify the currently applied progress-reset changes in:
   - `modules/ytaedl/ytaedl/manager.py`
   - `modules/ytaedl/ytaedl/downloader.py`
2. Reproduce against the scenario represented by `modules/ytaedl/worker-06.txt`
3. If stale retry progress still appears, inspect deeper retry-path behavior in `downloader.py` and its parsed event source
4. Implement the small-screen sticky-footer viewport and up/down arrow scrolling in `manager.py`
5. Improve watcher panel wording and last-run/current-run visibility for:
   - copy vs move
   - same-name destination collisions
   - replaced vs kept destination behavior
6. Optionally add targeted tests for:
   - worker state reset on reassignment / finish / stalled / aborted / deadline
   - downloader progress clamping in retry paths
   - viewport slicing logic for small screens
   - watcher conflict/result text rendering

## Notes On Tooling / Environment

This session had repeated shell hangs on some PowerShell file reads in Windows 11.
Practical workaround that behaved better:
- use smaller, line-targeted searches (`rg -n -A/-B ...`)
- avoid broad `Get-Content` reads when possible

If continuing this work through Codex tools, prefer targeted reads and small edits.
