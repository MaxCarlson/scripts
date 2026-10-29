# llm_monitor

Read-only monitoring for a running OpenCode server. The first MVP includes `status`, `sessions`, `watch`, and `gpu` commands. It does not start inference, change sessions, or write evidence.

Install from this directory with `python -m pip install -e .`, then run `llm-monitor --help` or `python -m llm_monitor --help`.

OpenCode defaults to `http://127.0.0.1:4096`. Use `-u/--url` to select another server and `-d/--directory` to send the `x-opencode-directory` header. Use `-f/--format json` for machine-readable output. `watch` emits one snapshot per interval; `-s/--session ID` watches one session and `-a/--all` discovers sessions each cycle.

Message polling is bounded to the newest 100 messages per cycle. The monitor keeps those messages plus newly observed tail messages in memory during a watch. If the initial response fills the limit, counts are explicitly marked as a recent-window count. No prompt or tool output is included in output.

GPU output is a point-in-time device measurement. When `resource_metrics` is installed, the command also reports per-process GPU memory where supported; device utilization is not attributed to a monitored session.

Sanitized acceptance fixtures in `tests/fixtures/` capture the final poll fields for the accepted Phase 2A 32K replay and the Runmux D5 Phase 2B 64K replay. Run-level cumulative token totals are stored separately from the last assistant message's per-inference token counts.
