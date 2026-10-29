# Live SSE Deadline Validation Report

**Date:** 2026-10-29  
**Branch:** `fix/llm-monitor-live-sse-deadline-20261029`  
**Base:** `origin/main` (`e9a5e788`)

## Root Cause Analysis

When running `llm-monitor live` with `--observe-seconds`:
1. **Unbounded Inner Loop:** `OpenCodeSSEClient.events()` computed a monotonic deadline and called `yield from iter_sse_events(response)`. Control did not return to the caller's deadline check until `iter_sse_events()` completed its iteration.
2. **Comment Ingestion Stall:** Inside `iter_sse_events()`, lines starting with `:` (SSE keepalive comments / heartbeats) resulted in `continue` without yielding or checking the deadline. Because periodic heartbeats from the server kept resetting the socket timeout, the loop ran indefinitely and never exited.
3. **Mismatched Read Timeout & Erroneous Gap Accounting:** On an idle connection, the initial connection timeout (`min(self.timeout, remaining)`) was used. When socket inactivity triggered `TimeoutError`, it was caught and erroneously classified as a network failure (`error="connection_failed"` and `reconnection_gaps += 1`), prompting reconnection retries rather than recognizing that the configured observation duration had completed.

## Resolution

1. **Interruptible Iteration with Monotonic Deadline:** `iter_sse_events()` now accepts `deadline: float | None`. Before each `stream.readline()`, `_set_stream_timeout()` updates the underlying socket timeout to the remaining duration `max(0.001, deadline - time.monotonic())`.
2. **Clean Timeout and Boundary Handling:** When `(TimeoutError, socket.timeout)` occurs near or at the deadline, or when comments/frames are parsed after the deadline, `iter_sse_events()` yields any pending frame and breaks out of the loop cleanly.
3. **Guaranteed Socket Closure:** `events()` wraps `iter_sse_events()` in `try ... finally: response.close()`, guaranteeing immediate socket closure without waiting for additional server events.
4. **Accurate Coverage Metadata:** When an observation terminates at the deadline, `observation_deadline_limited` is set to `True`, `"observation_deadline_limited"` is recorded in `warnings`, and `coverage` is set to `"incomplete"`. Partial observations (characters, delta counts, event timeline) are preserved, while `current_reasoning_tokens` remains `None` without inventing missing tokens.
5. **Reconnection Safeguards:** If disconnection occurs when the deadline is reached, retries are skipped and the client exits cleanly.

## Version Reconciliation (0.6.0 vs 0.1.0)

- `modules/llm_monitor/llm_monitor/__init__.py` and `pyproject.toml` define version `0.6.0`.
- The shared virtual environment `.venv` contains `llm_monitor-0.1.0.dist-info` and `__editable__.llm_monitor-0.1.0.pth` dating from initial repository setup when the module was created at version `0.1.0`.
- Because modern setuptools editable installations persist static metadata into `site-packages/*.dist-info/METADATA`, commands inspecting package distribution metadata (such as `importlib.metadata.version('llm-monitor')` or `pip list`) reflect the version at installation time (0.1.0) until reinstalled (`pip install -e modules/llm_monitor --no-deps`), while direct Python imports load the actual source code (`modules/llm_monitor/llm_monitor`), which reports `__version__ = "0.6.0"`.

## Verification Evidence

1. **Deterministic Regression Tests (`tests/live_test.py`):**
   - `test_idle_connected_sse_stream_respects_observe_seconds_deadline_and_closes`: Verified client exits within ~0.4s and closes connection; `reconnection_gaps == 0`.
   - `test_sse_stream_with_periodic_comments_respects_observe_seconds_deadline`: Verified client does not hang on keepalive comments and exits within ~0.4s.
   - `test_sse_stream_with_intermittent_events_respects_deadline_and_preserves_partials`: Verified partial delta events and text are retained while tokens remain uninvented (`None`).
   - `test_sse_stream_disconnection_before_deadline_records_gap_and_reconnects`: Verified network drops before deadline record gaps and retry.
   - `test_sse_stream_disconnect_at_deadline_exits_cleanly_without_reconnect`: Verified disconnect at deadline avoids redundant reconnect attempts.
2. **Suite Status:** 131 passed, 1 skipped (POSIX permissions on Windows).
3. **Live Server Verification:** Performed read-only 3-second observation on live OpenCode 1.19.3 instance at `http://127.0.0.1:4196`. Verified connection, 1 frame received, clean exit at deadline with `observation_deadline_limited: true`, 0 reconnection gaps, and no hanging.
