# LLM Monitor Documentation

## Overview

`llm_monitor` is a Python module in `MaxCarlson/scripts` providing read-only local LLM and OpenCode monitoring, diagnostic inspection, and an opt-in loopback inference gateway.

## Core Components

- `llm_monitor.cli`: Primary command-line interface (`llm-monitor`).
- `llm_monitor.config`: Persistent user configuration discovery, TOML/JSON parsing, and CLI precedence resolution.
- `llm_monitor.web`: Standalone local browser host and server lifecycle runner.
- `llm_monitor.server_lifecycle`: Instance registration, cryptographic challenge-response verification, graceful shutdown, and explicit force termination.
- `llm_monitor.inference_web`: FastAPI/ASGI web application for the browser overview.
- `llm_monitor.gateway`: Opt-in OpenAI-compatible inference gateway at `/v1/chat/completions`.
- `llm_monitor.inference_recording`: Asynchronous bounded recorder persisting requests and content to SQLite.
- `llm_monitor.storage`: SQLite telemetry store.

## Verification & Commands

```powershell
# Run module tests
$env:PYTHONPATH = "modules/llm_monitor"
python -m pytest modules/llm_monitor/tests

# Check formatting/linting
ruff check modules/llm_monitor
```
