# Live SSE Deadline and Observation Validation Plan

**Goal:** Correct the live SSE observation loop so `--observe-seconds` strictly bounds total observation duration under all stream states (idle, periodic comments/pings, intermittent events, disconnections), closes connections cleanly, returns accurate coverage metadata without inventing reasoning tokens, and document the editable install metadata version difference.

**Architecture:**
- Make SSE stream reading interruptible at the monotonic observation deadline in `iter_sse_events()`.
- Dynamically update socket timeouts to the remaining duration before each readline operation on connected streams.
- Ensure deadline expiration breaks out of the event loop, cleanly closes `response`, and sets `observation_deadline_limited: true` without false reconnection gap accounting.
- Retain all accumulated partial observations (text/reasoning characters, delta counts, event timelines) while keeping reasoning token counts uninvented (`null`).
- Document the version difference between installed editable metadata (0.1.0) and current active package version (0.6.0).

**Tech Stack:** Python 3.11+, `urllib.request`, standard library `socket`, deterministic pytest fixtures.
