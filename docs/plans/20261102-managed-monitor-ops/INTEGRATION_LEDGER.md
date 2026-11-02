# Integration Ledger — LLM Monitor & Agent Benchmark Managed Operations

## Pre-flight Interfaces & Shared Boundaries

| Source Component | Consuming Component | Interface / Shared State | Status / Ruling |
|---|---|---|---|
| `llm_monitor.server_lifecycle` | `llm_monitor.cli` | `ServerDescriptor`, `status_server`, `stop_server`, `restart_server` | Ruling: Extend existing lifecycle functions; add `restart_server`; maintain `-x/--execute` requirement on stop and restart. |
| `llm_monitor.server_lifecycle` | `llm_monitor.local_control` (Phase 02) | `instance_id`, `control_token`, SID-ACL named pipe / AF_UNIX | Ruling: Local control channel uses same instance identity and owner SID ACL. |
| `llm_monitor.local_client` (Phase 02) | `agent_benchmark.suite_monitor` | `ManagedMonitorClient` -> scoped read capabilities | Ruling: Scoped tokens expire in 60-300s, refreshed once on 401; no persistent session file generated. |
| `agent_benchmark.suite_doctor` (Phase 03) | `agent_benchmark.suite_cli` | `doctor` command parser and JSON schema | Ruling: `-F/--full` scoped strictly to `doctor`; preserves `-F/--llm-friendly` on other subcommands. |
| `agent_benchmark.suite_recovery` (Phase 04) | `agent_benchmark.suite_cli` | `-r/--recover-local` flag | Ruling: `-r` authorizes starting an absent managed Monitor once; `-x` required for inference; `plan` never infers. |

## Rulings Log
- **Ruling Phase 00-1**: Base commit selected as `109c7ad0edfb44b18e19505abf1def4ea58fac77` which includes the merged server lifecycle foundation (`server_lifecycle.py`, `web status`, `web stop`). We extend this existing foundation rather than reimplementing from scratch. Cost if wrong: Zero (this is the actual repository baseline).
- **Ruling Phase 00-2**: Format flag on `web`: support both `-f` and `-F` as `--format` aliases to prevent breaking either earlier scripts or new contracts. Cost if wrong: Minimal.
