# LLM Monitor Inference Web Implementation Plan

> **For agentic workers:** Phase A/B, the approved frontend workstream, Phase D, D.1, and D.2 are separately authorized checkpoints. Preserve the explicit opt-in and loopback-only gateway boundary. Do not merge into `main` or change inference-client configuration.

**Goal:** Add a standalone authenticated local web dashboard that discovers LM Studio inventory and shows truthful model and monitoring capability state without writing telemetry by default.

**Architecture:** Keep the existing OpenCode observability and SQLite models intact. Add inference-oriented contracts and a bounded in-memory service, use `LMStudioClient` for read-only inventory, and host versioned routes and packaged static assets through `web_ui_tools`. The browser reads cached service state; opening another tab must not create another provider collector.

**Tech Stack:** Python 3.11+ for `llm_monitor`; Python 3.10-compatible `web_ui_tools`; FastAPI/Uvicorn as optional LLM Monitor web dependencies; vanilla JavaScript/CSS; pytest.

**Spec:** The user-provided “LLM Monitor — Inference Observability Web UI” handoff, dated 2026-10-29, and approved visual and Phase D/D.1/D.2 follow-ons. Phase A/B, the approved UI, Phase D, and gateway performance qualification are complete for merge review.

## Global Constraints

- `llm_monitor` requires Python 3.11+; `web_ui_tools` and Runmux retain Python 3.10 compatibility.
- Startup without recording must not create or modify a telemetry database.
- Passive inventory must not be represented as individual request capture.
- No passive collector, persistent transcript storage, model load/unload, client reconfiguration, Runmux process control, or merge is in scope for D.1. The optional gateway is loopback-only and explicitly enabled; live test requests are synthetic and authorized.
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

## Approved frontend workstream (user-authorized follow-on)

The approved visual outline is the authority for the standalone dashboard shell, request explorer, transcript inspector, telemetry/timeline tabs, model/server views, responsive layout and keyboard behavior. Implement these frontend contracts against the existing authenticated API and deterministic test-only fixtures. Do not connect synthetic events to the normal production data path. Keep unavailable backend-dependent features visibly unavailable.

The concrete gap audit, implemented state, screenshots, interaction checks and backend dependencies are tracked in `FRONTEND_GAP_ANALYSIS.md`, `STATUS.md` and `checklist.md`. UI-1 through UI-5 are complete.

## Phase D — Explicitly authorized local gateway

The user has separately authorized Phase D on the existing feature branch. This authorization supersedes earlier Phase B/UI stop gates. Implement an optional, loopback-only OpenAI-compatible `/v1/chat/completions` gateway with a fixed loopback upstream, stable ingress UUIDs, bounded in-memory request/event retention, authenticated WebSocket observation, and no automatic client redirection. Ordinary `llm-monitor web` remains passive inventory-only. Do not add persistent transcript storage or other providers.

The implementation and evidence are tracked in `llm_monitor/gateway.py`, `tests/gateway_test.py`, `PHASE_D_VALIDATION.md`, and the genuine-request screenshot under `screenshots/`. The initial 3-sample +1.58 s result was not reproduced by the 40-group matched benchmark. A separate 20-group repeat showed occasional 2.9–3.4 s waits before upstream response headers. D.1 and D.2 evidence are in `PHASE_D1_VALIDATION.md` and `PHASE_D2_VALIDATION.md`.

## Phase D.1 — Gateway performance and transport hardening

The user authorized metadata-only profiling, controlled loopback benchmarks, transport/security hardening, and authenticated browser reconnect validation. The gateway now forwards upstream bytes incrementally even when SSE framing is fragmented, supports opt-in monotonic stage timing without retaining content, rejects cross-origin browser requests and non-JSON content, pins `localhost` validation to a loopback address, and represents upstream interruption as failure. The opt-in benchmark uses identical counterbalanced direct/minimal/observed requests and records only metadata. No transcript persistence or client reconfiguration is part of this phase.

The 40-group run was below the provisional 50 ms median target. A subsequent 20-group repeat exposed high variance and waits before upstream headers. D.1 localized these to the upstream wait interval, not gateway request parsing/dispatch, but did not identify their cause.

## Phase D.2 — Final gateway qualification

D.2 extends the existing metadata-only harness with paired triplet differences, bootstrap median intervals, tails/order reports, device-wide GPU samples, short/long/varied workloads, limited concurrency, and fresh-connection comparisons. The 20-triplet-per-mode principal comparison measured observed-minus-direct medians of −2.33 ms nonstreaming and +2.08 ms streaming; every output group matched, no paired added-latency event exceeded 100 ms, and no request exceeded one second. D.2 diagnostics did not reproduce the earlier multi-second stalls. Exact LM Studio scheduling/cache cause remains unknown because no live queue counter or per-request GPU attribution is available.

The real inference-client TCP disconnect cancelled the monitored request and closed its upstream stream. Previously validated observer-browser reconnect/snapshot behavior is preserved. Performance and functional gates are accepted for merge review under the D.2 acceptance criteria. A final alternating-prompt live run could not execute after the model was no longer confirmed loaded; the harness made no automatic load attempt. See `PHASE_D2_VALIDATION.md` and raw metadata artifacts. Do not merge as part of this qualification; the next implementation priority is GPU/per-request analytics and historical recording.
