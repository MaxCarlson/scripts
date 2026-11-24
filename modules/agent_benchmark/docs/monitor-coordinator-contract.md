# Monitor–Coordinator–Benchmark Contract

This contract applies to monitored local Harbor agents (`qwen-coder`, `opencode`, and `opencode-v2`). The Monitor status route is authenticated and versioned at `/api/inference/v1/status`.

## Evidence stages

1. **Pre-dispatch qualification:** The benchmark reads the Monitor's effective `gateway_enabled` and `gateway_upstream`, managed `runtime_identity` (`instance_id`, `config_fingerprint`, gateway settings, and Monitor origin), and `coordinator_readiness`. The Monitor makes a read-only GET to `/_coordinator/status` with a 750 ms timeout and without proxy environment settings. It exposes only a bounded readiness summary and safe runtime identity fields.
2. **Per-request admission:** The configured gateway upstream must be the loopback Resource Coordinator on port 1235. The Coordinator enforces admission when each inference request reaches it. A readiness GET does not establish admission for a future request, and the benchmark does not require it before dispatch.
3. **Post-execution evidence:** The benchmark observes new Monitor request IDs around the task and verifies durable recording when recording is enabled. It rechecks both runtime identities and routing after execution; a Monitor or Coordinator replacement/configuration change invalidates the task's monitoring evidence. Full request-to-Coordinator admission correlation remains deferred.

The consumer rejects legacy Monitor schemas for monitored local routes, direct `:1234` bypasses, conflicting upstream values, disabled gateways, incomplete or contradictory identities, stale/missing Monitor observation or service-refresh timestamps, unavailable Coordinator status, and active maintenance, recovery, restart inhibition, or gaming restrictions. Qualification timestamps must be timezone-aware, current, and no more than 30 seconds old. No missing timestamp is synthesized. Coordinator safety fields that are absent or unknown fail closed.

Cloud-agent Monitor observation and non-monitored direct local operation keep their existing paths. Recording mode checks remain in force. Offline monitored study preparation remains available, while study dispatch still requires the existing run-bound network receipt.

## Offline regression commands

From the repository root, with module dependencies installed:

```powershell
pytest modules/agent_benchmark/tests/suite_monitor_test.py modules/agent_benchmark/tests/harbor_runner_test.py -p no:cacheprovider -q
pytest modules/llm_monitor/tests/inference_web_test.py modules/llm_monitor/tests/server_lifecycle_test.py -p no:cacheprovider -q
ruff check modules/agent_benchmark/agent_benchmark/suite_monitor.py modules/agent_benchmark/agent_benchmark/harbor/runner.py modules/agent_benchmark/agent_benchmark/suite.py modules/agent_benchmark/tests/suite_monitor_test.py modules/agent_benchmark/tests/harbor_runner_test.py modules/llm_monitor/llm_monitor/inference_web.py modules/llm_monitor/llm_monitor/web.py modules/llm_monitor/tests/inference_web_test.py
```

The producer/consumer regression uses in-process FastAPI clients and mocked Coordinator responses. It does not start a service, create a Docker container, connect to LM Studio, or run inference.

## Separately authorized, non-inference qualification

Use these read-only checks before considering any inference dispatch:

```powershell
docker info
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:1235/_coordinator/status' -TimeoutSec 2
```

Read the authenticated Monitor status with the managed local capability mechanism (for example, `agent-bench suite doctor --llm-monitor` with the selected Monitor URL). From an already-present approved Harbor worker image, make a one-shot GET to `http://host.docker.internal:1235/_coordinator/status` and `/v1/models`, using a bounded timeout. Confirm the Coordinator's runtime identity and readiness restrictions match the host-side status. Do not send a chat/completions request during qualification. This assignment did not run these host/Docker checks.
