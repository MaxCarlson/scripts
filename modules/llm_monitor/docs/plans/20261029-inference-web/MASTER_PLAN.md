# LLM Monitor Inference Web Implementation Plan

> **For agentic workers:** Use the executing-plans skill to implement this plan task by task. Do not commit, push, merge, publish, start a gateway, or change inference-client configuration.

**Goal:** Add a standalone authenticated local web dashboard that discovers LM Studio inventory and shows truthful model and monitoring capability state without writing telemetry by default.

**Architecture:** Keep the existing OpenCode observability and SQLite models intact. Add inference-oriented contracts and a bounded in-memory service, use `LMStudioClient` for read-only inventory, and host versioned routes and packaged static assets through `web_ui_tools`. The browser reads cached service state; opening another tab must not create another provider collector.

**Tech Stack:** Python 3.11+ for `llm_monitor`; Python 3.10-compatible `web_ui_tools`; FastAPI/Uvicorn as optional LLM Monitor web dependencies; vanilla JavaScript/CSS; pytest.

**Spec:** The user-provided “LLM Monitor — Inference Observability Web UI” handoff, dated 2026-10-29. The accepted work boundary is Phase A plus Phase B, stopping at the Phase B gate.

## Global Constraints

- `llm_monitor` requires Python 3.11+; `web_ui_tools` and Runmux retain Python 3.10 compatibility.
- Startup without recording must not create or modify a telemetry database.
- Passive inventory must not be represented as individual request capture.
- No gateway, inference request, model load/unload, client reconfiguration, Runmux process control, commit, push, or merge is in scope.
- All monitoring routes and WebSockets use `web_ui_tools` authentication and protections.
- Existing `create_app` callers retain the `web_ui_session` cookie default.
- Provider and model labels are untrusted text and must be rendered as text, never HTML.
- Static assets must be included in an installed wheel; no runtime CDN dependency.
- Preserve existing OpenCode CLI behavior, telemetry schema v2, and Runmux routes.

## Review Focus

1. LM Studio endpoint unreachable or returning unsupported/malformed inventory: report unavailable; never substitute an empty healthy inventory.
2. Multiple loaded instances or conflicting contexts for one model: preserve ambiguity rather than implying one runtime configuration.
3. Missing request sources or data: label capability unavailable; do not fabricate requests, zero usage, or healthy alerts.
4. Untrusted provider-controlled model labels: render literally without HTML/script execution.
5. Two local applications sharing a hostname: isolated cookie names must not break existing callers or cross-authenticate applications.

## Phase A — Audit and evidence

- Reconcile the supplied baseline with current `main` and inspect active LLM Monitor handoffs, package contracts, tests, and recent history.
- Verify the `web_ui_tools` HTTP and WebSocket authentication/lifecycle behavior and Python compatibility.
- Review LM Studio's current primary documentation and inspect installed CLI help without issuing inference traffic.
- Record source-backed capabilities separately from empirical observations. Current provider runtime logs remain unvalidated unless an authorized safe event capture is available.
- Audit Runmux field/alert assumptions and the current Python 3.10 integration boundary before changing those surfaces.

## Phase B — Standalone MVP

### Task 1: Inference contracts and bounded memory

**Files:** `llm_monitor/inference_models.py`, `llm_monitor/live_store.py`, corresponding module tests and sanitized synthetic fixtures.

Define typed server, model-instance, capability and request-summary contracts with explicit `available`, `unavailable`, and source/provenance values. Add a bounded thread-safe in-memory snapshot store. The initial service stores inventory only; synthetic requests appear only in fixtures/tests and are never seeded into production state.

### Task 2: App-scoped web session cookies

**Files:** `modules/web_ui_tools/src/web_ui_tools/app.py`, `modules/web_ui_tools/tests/test_app.py`, and its README.

Add an optional validated session-cookie name to `create_app`, defaulting to `web_ui_session`, and use it consistently for HTTP, login/logout, and WebSocket authentication. Keep the module Python 3.10-compatible.

### Task 3: One LM Studio collector and versioned API

**Files:** `llm_monitor/inference_service.py`, `llm_monitor/inference_web.py`, `llm_monitor/web.py`, `llm_monitor/cli.py`, corresponding tests.

Probe only the configured/default LM Studio base URL using the existing GET-only `LMStudioClient`. A single service owns refresh cadence and cached inventory. Add authenticated GET routes below `/api/inference/v1` for status, servers, and models; return explicit coverage/capability fields and sanitized endpoint identity. Add `llm-monitor web` with loopback hosting, login code, port/endpoint options, and optional browser opening. Do not instantiate `TelemetryStore`.

### Task 4: Packaged overview UI

**Files:** `llm_monitor/web_static/index.html`, `assets/app.css`, `assets/app.js`, `pyproject.toml`, and UI/API tests.

Implement a compact dark overview with provider availability, selected model inventory, loaded-instance/context ambiguity, empty request state, and explicit passive-observation limitations. Use text nodes for dynamic values and same-origin authenticated fetches. Package the assets and declare web dependencies under an optional extra.

### Task 5: Preliminary compatibility review

Inspect and correct only verified source-level contract mismatches identified by the supplied handoff: Runmux token summary fields, context-utilization shape, model identity semantics, empty alerts, alert scoping, cookie isolation, and Python 3.10 optional-integration behavior. Preserve public APIs and add focused regression tests for every correction.

## Validation and gate

- Run focused tests for each changed module, then the full `llm_monitor` suite and relevant `web_ui_tools`/Runmux tests.
- Check CLI help and wheel contents; verify module import works without optional web dependencies.
- Test authenticated and unauthenticated HTTP and WebSocket access, cookie isolation, malformed/unavailable inventory, and literal rendering of hostile model labels.
- Confirm a web startup with mocked inventory leaves the configured/default database path absent and never imports/constructs `TelemetryStore`.
- Run the browser dashboard with synthetic fixture responses when browser automation is available; capture a screenshot and inspect it.
- Stop after the Phase B gate. Do not proceed to native log collection or the capture gateway in this work package.

## Explicitly deferred

LM Studio log-event capture, individual request reconstruction, reasoning/output capture, inference gateway, persistence/migration, Ollama/llama.cpp/vLLM, historical analytics, recording controls, and Runmux request-oriented integration remain future phases.
