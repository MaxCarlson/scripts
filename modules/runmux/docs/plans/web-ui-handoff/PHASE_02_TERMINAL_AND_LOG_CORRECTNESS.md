# Runmux Web UI — Phase 2 Agent Handoff: Terminal and Log Correctness

**Phase ID:** RUNMUX-WEB-P2  
**Status:** Investigation and repair specification; do not assume root cause  
**Priority:** **P0** output correctness, then **P1** reliability  
**Primary backlog:** T01–T07, S08, S10  
**Prerequisites:** Isolated processes and captured reproducible test output.

## 1. Objective

Make Runmux's browser Output and Terminal views trustworthy for both ordinary line-oriented logs and full-screen/interactive TUIs. The current screenshots show output from MangaDL and `file-util` that is poorly aligned, interleaved, or visually garbled. Diagnose precisely where fidelity is lost before changing the renderer, transport, or storage model.

This is an **independent correctness phase**, not permission to rebuild already-implemented browser PTY control, rewrite the terminal, or implement all enhanced log features. The current xterm.js WebSocket viewer/interact attachments and supervisor FIFO input lock already exist; preserve them.

## 2. Observed symptoms and boundaries

- `file-util` Output screen shows flattened multi-column directory listings with apparent cursor/line update artifacts.
- MangaDL Output view shows progress/status text merging into large runs of repeatedly overwritten numbers.
- MangaDL Terminal view looks closer to a terminal application but still shows layout/truncation/alignment concerns.
- The browser has Output, Terminal, Details tabs; a Follow toggle; `Jump to latest`; and for at least one lost run a message that only the last 64 KiB is present and earlier output is omitted.

**Not yet known:** raw bytes vs stripped ANSI, whether PTY rows/columns match browser cells, whether logs are persisted as terminal byte streams, whether Unicode width is respected, whether carriage returns/replay are being interpreted, or whether browser font/CSS causes any observed issue.

## 3. Diagnostic matrix: identify failures by layer

1. **Producer:** Determine whether the application itself detects a terminal and changes output format, uses curses/Rich/Textual, emits progress bars with `\r`, or writes separate streams.
2. **PTY or pipe:** Determine whether Runmux starts programs attached to a PTY or captures stdout/stderr separately; record initial rows/columns, resize messages, encoding and terminal type.
3. **Storage:** Inspect whether Runmux persists raw bytes, decoded text, terminal snapshots, ANSI-stripped lines, or a bounded tail. Determine what information is irretrievably lost at capture/storage time.
4. **Transport:** Verify framing, ordering, chunk boundaries, reconnect behavior, and whether carriage returns/escape sequences survive the API/stream protocol.
5. **Browser display:** Inspect Output text viewer versus terminal emulator, monospaced cell geometry, soft wrapping, Unicode width, terminal emulation version/settings, container sizing, and resize propagation.
6. **History/replay:** Determine whether a persisted tail starts mid-control-sequence or after terminal state was established. A correct terminal **frame** may require a snapshot/full replay rather than processing an arbitrary late byte fragment.

Record a minimal reproduction and which layer demonstrably causes each symptom. Avoid fixing everything with ad hoc ANSI stripping, which may help simple logs but break TUIs.

## 4. Intended separation of viewer semantics

**Output viewer**: An append-only/history-oriented view, suitable for searching and following log output. May intentionally normalize carriage returns or display raw lines depending on an explicit policy. Must never imply that it reconstructs an interactive TUI accurately when it does not.

**Terminal viewer**: A terminal-emulator-style screen supporting cursor motion, erasure, styles, Unicode cell width, resizes, scrolling region behavior and terminal redraws as supported by the actual PTY/capture contract. Viewing is read-only by default. The **existing** authenticated browser can request an interactive attachment, but it may send input only while the Runmux supervisor grants that attachment the input lock. Preserve this implemented behavior and verify it in regression tests.

Do not let a viewer-specific `pause`, `clear` or `follow` control alter the underlying process or delete persisted logs.

## 5. Deliverables in scope

- Evidence-based defect analysis with precise reproduction steps for at least one ordinary logger and one TUI-like application.
- Minimal corrective changes at the layer where corruption originates; tests that catch the original issues.
- Correct terminal size propagation or documented fixed-size limitations, subject to existing interface constraints.
- Stable behavior for ANSI sequences, carriage-return progress updates, Unicode and long lines, using existing terminal primitives where suitable.
- Bounded history/replay and client memory/DOM usage; clear indication when old output is unavailable or truncated.
- Reliable follow-tail behavior that suspends when a user scrolls up and resumes on request.
- Graceful reconnect handling and explicit errors without resetting a supervised process.

## 6. Tests and validation

Construct synthetic fixtures rather than launching user jobs. Include:

| Fixture | What must be checked |
|---|---|
| Plain multiline log | Ordering, line breaks, scrolling, safe display |
| `\r` progress rewrites | Output policy documented; Terminal redraw visually correct |
| ANSI erase/move/color | Emulated screen correct; no escape fragments on screen |
| Unicode wide characters and emoji | Cell widths/layout do not drift unexpectedly |
| Long unbroken paths/commands | No app-level page overflow; understandable scroll/wrap policy |
| Large sustained output | Bounded browser memory, reconnect, responsive UI |
| Resize sequence | TUI receives correct columns/rows or limitation explained |
| Truncated replay tail | No false claim of faithful reconstructed historical screen |
| Completed/lost process | Logs remain accessible according to actual retention |
| Malicious text/escape payload | Safe text/terminal display, no injected HTML/JS |

If screenshot or golden-frame testing is practical, include representative viewport comparisons and reference browser width/font settings. Distinguish automated assertions from visual/manual review.

## 7. Explicit deferrals

Do not include regex search, severity counts, per-stream tab UI, multi-pane layouts, replay of unavailable history, event timelines, a replacement PTY/input-ownership architecture, or host telemetry here unless necessary to fix a validated regression. Route these to Phases 4 or 6.

## 8. Acceptance criteria

- [ ] A minimal reproducible example isolates the observed Output/Terminal anomalies.
- [ ] Terminal view accurately renders representative supported TUI operations at the tested terminal dimensions.
- [ ] Ordinary log output remains usable and readable.
- [ ] Follow behavior does not fight user scrolling; display pause does not pause the process.
- [ ] Truncation, recovery and unsupported replay cases are explicit.
- [ ] Rendering remains bounded and secure under long-running output.
- [ ] No real user registry/process/state was modified during validation.

## 9. Agent deliverables and assignment

Provide: source-flow diagram (producer → PTY/capture → storage → API → client), identified root causes, narrow change plan, regression fixtures, test outcomes, screenshots where meaningful, and branch/PR references.

> Investigate and implement **RUNMUX-WEB-P2** from `PHASE_02_TERMINAL_AND_LOG_CORRECTNESS.md`. Use synthetic line-output, carriage-return, ANSI and TUI programs in an isolated Runmux registry. Explain *where* corruption originates before selecting a fix. Preserve Output and Terminal as distinct views, do not introduce process mutation or speculative log architecture, and report exact validated behavior and limitations.
