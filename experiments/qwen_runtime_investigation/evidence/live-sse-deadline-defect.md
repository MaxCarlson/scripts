# LLM Monitor live SSE observation deadline issue

Status: suspected defect documented for the separate LLM Monitor maintainer. No Monitor implementation change was made in this investigation.

## Reproduction and impact

With OpenCode 1.19.3 running on the isolated endpoint `http://127.0.0.1:4196`, `llm-monitor live --url http://127.0.0.1:4196 --project-directory <exact-project> --session <session-id> --trial-id <trial-id> --observe-seconds 40 --format json` connected to the event stream but remained blocked after the 40-second observation window while the server kept the SSE response open. The command had to be interrupted. It did not establish that no events existed; it left incremental SSE coverage unverified. Persisted Monitor history remains a usable fallback.

## Source evidence

The imported Monitor source was `modules/llm_monitor/llm_monitor/live.py` from main, version 0.6.0 (the venv distribution metadata is stale at 0.1.0). In `OpenCodeSSEClient.events()`, lines 745–770 compute a monotonic deadline and bound `urlopen`'s initial timeout by the remaining duration. After connecting, the generator yields `__connected__`, then calls `yield from iter_sse_events(response)`. The deadline is checked only after that iterator returns. If the response remains open and the iterator is waiting for an event, control cannot reach the deadline check. The socket timeout did not bound the observed total command duration in this reproduction.

## Suggested maintainer fix and acceptance check

Make the stream read itself interruptible at the monotonic observation deadline; on expiry close the response and return a final snapshot with explicit deadline/coverage status. Add a local fake SSE server that sends the headers and then holds the connection open without events. Assert the client returns within a small tolerance of `observe_seconds`, closes the response, and marks the interval as observation-deadline-limited rather than claiming complete event coverage. Also retain a test where deltas arrive before the deadline.

The separate Monitor developer's identity/contact was not available through the configured coordination route during this investigation. This file is the concise relay artifact; the user can forward it without exposing prompts or raw reasoning.
