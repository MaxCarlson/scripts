# Approved UI Gap Analysis and Resul

**Baseline:** `cbe67c6168188a0a5e61de2013f442c775e75acb`
**Design authority:** [`docs/APPROVED_VISUAL_OUTLINE.md`](../../APPROVED_VISUAL_OUTLINE.md)
**Implementation:** Standalone frontend only; authenticated host and existing API contracts retained. No passive collectors, gateway, or persistence changes.

## 1. Already implemented and matching

| Area | Relevant files | Result / dependency / verification |
|---|---|---|
| Authenticated same-origin host, protected read API, packaged static assets | `llm_monitor/inference_web.py`, `web.py`, `web_static/index.html`, `pyproject.toml` | Retained. The UI continues to use the app-scoped cookie and CSP-compatible external assets. Existing status/server/model/request snapshot API remains the only production data source. |
| Provider inventory and truthful missing-data behavior | `inference_service.py`, `inference_models.py`, `assets/js/api.mjs`, `assets/js/render.mjs` | Real server/model inventory remains provider-sourced. Requests, GPU, recording actions, history, alerts, and live stream are never seeded from fixtures or displayed as collected telemetry when unavailable. |
| Safe text rendering and local privacy boundary | `assets/js/render.mjs`, `assets/js/transcript.mjs`, `assets/js/app.mjs` | Dynamic model and transcript values render via text nodes. UI preferences contain no transcript or credentials. Authentication expiry clears in-memory display state. |
| Reduced-motion and responsive behavior foundation | `assets/app.css`, `index.html` | Retained and expanded for horizontal desktop navigation, tablet/mobile stacking, visible focus, and smaller workspaces. |

## 2. Implemented but requiring visual or interaction changes (changes completed)

| Area | Relevant files | Changes | Tests / evidence |
|---|---|---|---|
| Shell, navigation, density and palette | `web_static/index.html`, `assets/app.css`, `assets/js/app.mjs`, `assets/js/render.mjs` | Replaced sparse overview with compact top bar, 172px desktop navigation/server rail, approved blue-gray palette, Overview/Requests/Models/History/Alerts routes, status indicators, and responsive navigation. | Browser screenshots at 1920×1080, 1440×900, 1280×800, 768×1024 and 390×844. |
| Overview KPIs and two-column explorer | `index.html`, `assets/app.css`, `assets/js/render.mjs`, `assets/js/formatters.mjs` | Added six model KPI cards; searchable newest-first request rail beside the selected-request inspector; exact, estimated, and unavailable usage presentation; bounded 100-row pagination over a 500-request client window. | Fixture-backed browser rendering and missing/provenance metric assertions. |
| Request inspector and transcript | `index.html`, `assets/js/transcript.mjs`, `assets/js/render.mjs`, `assets/js/state.mjs` | Added five request metric cards, ordered input/reasoning/output/tool segments, safe copy/search/collapse controls, reasoning visibility, auto-follow, and targeted segment updates that preserve DOM nodes and scroll intent. | Browser checks for reasoning visibility, stable segment node under appended delta, and selected-request stability. |
| Telemetry, timeline, GPU and coverage | `index.html`, `assets/js/render.mjs`, `assets/app.css` | Added provenance-aware Telemetry and Event Timeline tabs; GPU samples render with explicit gaps and device-level attribution scope; capability matrix reports unavailable values honestly. | Telemetry/timeline screenshots and no-data/disconnected states. |
| Model/server selection and secondary pages | `assets/js/app.mjs`, `assets/js/state.mjs`, `assets/js/render.mjs`, `index.html` | Added model/server selectors, model cards, and History/Alerts views with explicit empty/unavailable states. | Model, History, Alerts and disconnected screenshots; interaction checks for filters. |
| Keyboard/accessibility and incremental state contract | `assets/js/app.mjs`, `assets/js/state.mjs`, `assets/js/transcript.mjs`, `tests/standalone_web_ui_test.js` | Added semantic navigation/tabs, keyboard shortcuts, status announcements, visible focus, stable identity, sequence deduplication/gap marking, and an event adapter contract for future same-origin event transport. | Node contract tests and browser interaction checks. No production WebSocket/event endpoint exists. |

## 3. Not implemented (backend-dependent, intentionally deferred)

| Feature | Frontend state | Required backend contract to replace fixture/empty states |
|---|---|---|
| Real request list, details and transcript content | Renderer/state contract implemented; production API currently returns no captured requests. | Request summaries keyed by server/model/request identity; ordered content segments with source, completeness, truncation and timestamps; stable detail retrieval. |
| Live reasoning/output stream and replay | `applyRequestEvent` supports ordered deltas, duplicate suppression, gaps, interruptions and metadata updates. The custom event adapter is not connected to production transport. | Authenticated event stream with monotonically increasing sequence/revision, replay cursor/snapshot reconciliation, cancellation/failure lifecycle and per-request capture provenance. |
| Request analytics and per-request metrics | Six KPI and inspector slots are implemented; missing values stay unavailable. | Provider-reported/estimated usage source and accounting convention, request timing boundaries and bounded aggregate endpoints with denominators. |
| Time-aligned GPU/VRAM | Chart and attribution labels are implemented; no device samples are fabricated by production mode. | Timestamped device/process samples, device identity, scope and maximum-gap metadata. |
| Historical requests, alerts/coverage and recording controls | Navigation/views show truthful unavailable or no-history states. Recording indicators are read-only status. | Historical request/content query, alert and collection-gap APIs, plus explicit authenticated recording-policy read/mutation operations and retention status. |

## Visual review and intentional differences

Screenshots are stored in [`screenshots/`](screenshots/). The approved desktop composition, six KPIs, two-column stream/inspector, three inspector tabs, model cards, and bottom telemetry panels are present. Mobile uses horizontal navigation and vertically stacked panels so both request selection and inspection remain reachable without page-wide horizontal overflow. Lower GPU/coverage panels require vertical scrolling at 1440×900, matching the compact workspace density.

Browser fixture screenshots carry a visible **UI test fixture** badge and use synthetic-only records. The regular application never loads `tests/fixtures/ui_scenario_v1.json`; its source remains the authenticated inventory-only API. The visual fixture therefore validates component presentation, not real request collection or reasoning capture.
