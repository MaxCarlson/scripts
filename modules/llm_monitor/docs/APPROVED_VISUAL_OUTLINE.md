# LLM Monitor Web UI — Approved Visual Implementation Handoff

**Project:** `MaxCarlson/scripts`
**Target:** `modules/llm_monitor/`
**Reference UI:** Previously approved interactive “LLM Monitor — Interactive Web UI Mockup” in this conversation
**Reviewed repository commit:** `33040f00e7324d7b6ac02eae4d2e7f6ac281e667`
**Document status:** Frontend design specification and implementation handoff
**Scope:** Frontend implementation, browser integration, component behavior, visual validation
**Out of scope:** Building inference collectors, implementing the inference gateway, changing existing Runmux process managemen

---

## 1. Implementation objective

Reproduce the approved LLM Monitor mockup as a functional, standalone web interface using the existing `web_ui_tools` framework.

The new dashboard must preserve the layout, visual hierarchy, interaction patterns, colors, typography and information density of the approved mockup.

The central workflow is:

1. Select a model or view all monitored models.
2. Observe a continuously updating list of inference requests.
3. Click a request to inspect its input, reasoning and output.
4. Follow a running request as additional content arrives.
5. Switch between transcript, telemetry and event-timeline views.
6. Inspect aggregate token, timing and GPU statistics.
7. Navigate to historical requests, including those from unloaded models.
8. Inspect recording status, observability capabilities and monitoring gaps.

The page should feel like a specialized developer observability application, not a generic business dashboard.

**Visual priority:** Keep the request stream and the transcript inspector visible simultaneously on desktop.

The user should never need to navigate away from the request stream merely to read the current model output.

---

## 2. Source inspection findings

### 2.1 `web_ui_tools`

Reviewed:

- `modules/web_ui_tools/src/web_ui_tools/app.py`
- `modules/web_ui_tools/src/web_ui_tools/terminal.py`
- `modules/web_ui_tools/README.md`
- `modules/web_ui_tools/pyproject.toml`
- `modules/web_ui_tools/tests/test_app.py`

The framework provides:

- FastAPI application construction.
- An application-supplied `/api` router.
- Static asset hosting.
- Local login-code exchange.
- HttpOnly browser-session cookies.
- Same-origin checks.
- Trusted-host validation.
- Protected WebSocket connections.
- Security headers and cache restrictions.
- Loopback-only Uvicorn server construction.

**Recommendation:** Use this framework without introducing React, Next.js or another independent server framework.

Its existing static-asset model supports a modular vanilla JavaScript frontend.

The frontend must use external JavaScript and CSS files. The framework's default Content Security Policy does not permit the inline scripts used in the original interactive prototype.

Do not weaken the CSP just to make the prototype code run unchanged.

### 2.2 Runmux frontend

Reviewed:

- `modules/runmux/src/runmux/web_static/index.html`
- `modules/runmux/src/runmux/web_static/assets/dashboard.css`
- `modules/runmux/src/runmux/web_static/assets/dashboard.js`
- `modules/runmux/src/runmux/web_static/assets/llm-monitor.js`
- `modules/runmux/docs/web-ui-visual-design-ux-implementation-specification.md`

Runmux already establishes useful conventions for:

- Dark-mode palettes and compact typography.
- Panel borders and selected-item styling.
- Connection and lifecycle indicators.
- Searchable navigation.
- Tabbed detail views.
- Bounded pagination.
- Request cancellation using `AbortController`.
- Preventing stale asynchronous responses from overwriting newer selections.
- Empty and disconnected states.
- Responsive layouts.
- Browser preference persistence.

These should guide the standalone implementation.

The existing `llm-monitor.js` is an OpenCode session-inspection view, not a complete local inference-request explorer.

Do not duplicate that script unchanged.

### 2.3 Existing frontend tests

Reviewed:

- `modules/runmux/tests/dashboard_test.js`
- `modules/runmux/tests/llm_monitor_view_test.js`
- `modules/runmux/tests/llm_monitor_browser_e2e_test.js`
- `modules/web_ui_tools/tests/test_app.py`

The repository uses Node-based frontend tests, deterministic DOM simulations, synthetic server fixtures and browser-level testing.

The standalone frontend should follow these testing patterns.

Keep tests isolated from real user inference services and production telemetry files.

---

## 3. Visual reference and overall composition

The approved mockup is the visual source of truth.

### 3.1 Desktop layou

Use the following hierarchy:

**Global header**

- Product mark and application name.
- Small “OBSERVABILITY” subtitle.
- Demonstration/connection status where appropriate.
- Discovered server status.
- Recording state.

**Application body**

A fixed-width left navigation sidebar and a flexible main content area.

**Main content**

- Page title and description.
- Model selector and live-view controls.
- Six compact statistics cards.
- Main two-column investigation workspace.
- Bottom GPU activity and capture-status panels.

**Investigation workspace**

Left: continuously updated request stream.

Right: selected request inspector with transcript, telemetry and timeline tabs.

The layout should correspond to this structure:

| Region | Position | Function |
|---|---|---|
| Global header | Entire top | Product identity, connections, recording |
| Sidebar | Left, fixed width | Overview, Requests, Models, History, Alerts, Servers |
| Page toolbar | Main content top | Title, model selector, live/record controls |
| Statistics | Main content, below toolbar | Six model-level KPIs |
| Request stream | Main workspace left | Scrollable request list |
| Inspector | Main workspace right | Selected request and content |
| GPU telemetry | Below workspace, left | GPU/VRAM chart and metrics |
| Capture status | Below workspace, right | Provider capability and retention state |

**Do not move the request inspector into a modal or separate page in the desktop layout.**

The request stream and inspector are the defining visual elements.

---

## 4. Design system

Use a small dedicated set of CSS custom properties within the standalone application.

### 4.1 Approved palette

The approved interactive mockup uses the following approximate values.

| Token | Value | Purpose |
|---|---|---|
| `--lm-bg` | `#0D1119` | Main background |
| `--lm-panel` | `#151B26` | Cards and panels |
| `--lm-panel-raised` | `#1C2431` | Raised panel surfaces |
| `--lm-border` | `#2B3545` | Dividers and panel outlines |
| `--lm-text` | `#E7EDF6` | Primary text |
| `--lm-muted` | `#94A2B5` | Secondary information |
| `--lm-blue` | `#76BAFF` | Selection, input, live activity |
| `--lm-green` | `#65D9AE` | Completed states and output |
| `--lm-purple` | `#C5A7FF` | Reasoning |
| `--lm-orange` | `#F4C27D` | Warnings |
| `--lm-red` | `#F08E99` | Failures |

These tokens should be the starting point, even though Runmux's existing stylesheet uses somewhat different semantic colors.

Preserve the approved mockup's slightly cooler, blue-gray surfaces rather than mixing both palettes arbitrarily.

### 4.2 Typography

Use the browser's system sans-serif stack for UI text.

Use a monospace stack for request IDs, token values, structured inputs, reasoning, output, timing values and diagnostic records.

Suggested scale:

| Element | Size |
|---|---|
| Main page title | 20px |
| Product name | 15px |
| Section heading | 13px |
| Standard UI text | 12–13px |
| Request summaries | 11px |
| Secondary metadata | 10–11px |
| Eyebrow/section labels | 10px |
| KPI values | 20px |
| Request metric values | 14px |
| Transcript content | 11.5–12px monospace, line-height 1.6–1.7 |

Do not use oversized dashboard typography that displaces important request information.

Transcript text must remain readable at ordinary desktop viewing distances; provide an accessible font-size preference if needed.

### 4.3 Spacing and borders

- Main content padding: approximately 17px.
- Panel-to-panel gap: approximately 10–14px.
- Panel border radius: 8–9px.
- Controls: 6–7px radius.
- Card internal padding: 10–14px.
- Thin, low-contrast borders.
- Minimal shadows.
- Hover effects limited to background/border changes.
- Selection indicated by a more visible background and a narrow blue leading border.

Use a consistent 4px-based spacing scale.

### 4.4 Color semantics

Use blue for input and active selection, purple for exposed reasoning content, green for output/completion, orange for caution and red for errors.

Statuses must also contain text/icons; never rely on color alone.

Avoid decorative animations other than small loading/live indicators.

Support `prefers-reduced-motion`.

---

## 5. Responsive geometry

### 5.1 Standard desktop

At approximately 1440px viewport width:

- Sidebar: 172px.
- Main content: remaining width.
- Six KPI cards in one row.
- Request stream: approximately 34% of investigation workspace.
- Inspector: approximately 66%.
- Bottom panels: 55% GPU / 45% capture status.
- Main investigation workspace minimum height: approximately 510px.

Use CSS Grid with proportions equivalent to the approved mockup's `0.9fr / 1.75fr` split.

Both columns require `min-width: 0` to prevent long text from expanding the layout.

### 5.2 Large and ultrawide displays

At 1920px and wider, preserve density rather than stretching transcript lines to extreme lengths.

Prefer:

- Optional resizable request-stream width.
- Inspector content with a comfortable maximum line length.
- Larger historical charts where additional width is useful.
- No unnecessary increase in font size.
- Independently scrollable panels.

At ultrawide resolutions, allowing the inspector to contain a main transcript plus a supplementary telemetry rail is a future enhancement, not a requirement for the initial implementation.

Do not change the desktop navigation model merely because additional width is available.

### 5.3 Intermediate widths

At approximately 1050px or narrower:

- KPI cards may wrap into three columns.
- Reduce sidebar width.
- Compact toolbar labels.
- Keep request stream and inspector side-by-side while usable.

### 5.4 Tablet/mobile widths

At approximately 740px or narrower:

- Convert the left sidebar to a compact horizontal navigation.
- Stack request stream above the inspector.
- Keep the request list independently scrollable.
- Stack bottom panels vertically.
- Allow the inspector tabs to scroll horizontally.

At very narrow widths, reduce KPI cards to two columns as necessary.

Do not allow the inspector to become a tiny, unreadable right column.

### 5.5 Scrolling

Desktop scrolling must be carefully isolated:

- Request list scrolls independently.
- Inspector transcript scrolls independently.
- Long input/reasoning/output sections can scroll internally when expanded.
- Main page may scroll vertically when panels exceed viewport height.
- Tab navigation and selected request metadata remain visible while reading lengthy content where practical.

Avoid nested scroll areas unless they serve a clear purpose.

---

## 6. Header specification

The header should remain compact, approximately 55–60px tall.

Left side:

- Square blue-tinted product mark containing “M”.
- “LLM Monitor” in semibold text.
- Small uppercase subtitle: “OBSERVABILITY”.

Right side:

- Server connection status.
- Count of connected/discovered servers.
- Recording status.
- Optional settings and authentication controls.

Use distinct states:

- Connected
- Discovering
- Degraded
- Disconnected
- Recording
- Recording disabled

A successfully running web server is not equivalent to successful connection to an inference server.

Do not present those as one status.

Do not include fabricated activity indicators in the real application.

---

## 7. Sidebar specification

### 7.1 Primary navigation

Navigation entries:

1. Overview
2. Requests
3. Models
4. History
5. Alerts

The initial selected page is Overview.

Each entry should have a small icon and clear text.

The active entry uses a muted blue background and brighter text.

The Requests entry may display the number of currently active requests.

The Alerts entry may display a grounded count of active alerts.

### 7.2 Server lis

Under a “SERVERS” section, display discovered inference servers.

Each server item contains:

- Provider name
- Sanitized endpoin
- Connection indicator
- Loaded-model coun
- Status

Clicking a server filters the relevant workspace.

A disconnected server remains visible as stale for an appropriate period rather than disappearing abruptly.

### 7.3 Storage section

At the bottom of the sidebar, show:

- In-memory monitoring state.
- Whether metadata recording is enabled.
- Whether full-content recording is enabled.
- Optional current retention policy.

This section should be compact and informational.

It must not imply that live monitoring automatically persists transcripts.

---

## 8. Model toolbar

The main workspace begins with a small uppercase breadcrumb, prominent page title and brief description.

Right-aligned controls:

**Model selector**

- All monitored models.
- Current loaded models.
- Historical models where appropriate.
- Display model name and relevant instance identity.
- Avoid merging distinct loaded instances with incompatible configurations.

**Auto-follow**

- Enabled by default when following the newest active request.
- Disabled automatically when the user selects an older request.
- Can be re-enabled explicitly.

**Recording**

- Off by default.
- Must reflect actual backend recording policy.
- Clicking opens a clear recording-control interaction.
- Distinguish metadata recording and full-content recording.

Changing model selection must not stop backend collection.

---

## 9. Six statistics cards

Preserve the approved mockup's six-card row.

| Card | Primary value | Secondary label |
|---|---|---|
| Requests | Count | Selected model/time window |
| Average input tokens | Numeric average | Eligible completed requests |
| Average reasoning tokens | Numeric average | Reported observations only |
| Average output tokens | Numeric average | Eligible completed requests |
| Average duration | Seconds | Request lifecycle duration |
| Average GPU / VRAM | GPU average | Memory measurement and scope |

### 9.1 Data requirements

Each aggregate must have:

- Source.
- Time window.
- Eligible sample count.
- Availability status.
- Appropriate units.

Missing measurements must display an unavailable indicator, not zero.

Reasoning averages must not treat missing values as zero.

A GPU average based on hardware samples overlapping requests must be labeled accordingly and must not imply exclusive per-request attribution.

### 9.2 Live updating

Update values when the backing telemetry changes, preferably through shared state.

Avoid rebuilding the entire page for every model token.

Use stable, tabular numeric formatting to minimize visual jitter.

---

## 10. Request stream — primary interaction

The left main panel is a vertically scrollable, newest-first request list.

### 10.1 Panel header

Title: “Request stream”

Right side: compact live/connection indicator.

Below: search/filter input.

### 10.2 Individual request row

Every row should contain:

**Top line**

- Short request identifier, such as `#0418`.
- State: Generating, Complete, Failed, Cancelled, Unknown.

**Middle line**

- One-line request preview where input capture exists.
- Otherwise a useful placeholder, such as “Input unavailable · metadata-only observation”.

**Bottom metadata**

- Start time.
- Input-token count.
- Duration or running elapsed time.
- Reasoning availability indicator.

An active request should be visually distinct but should not be permanently selected if the user chooses another request.

### 10.3 Request ordering

Default: newest first.

Support:

- Model filter.
- Server filter.
- Status filter.
- Time range.
- Text search over captured content when permitted.
- Explicit sort selection if eventually needed.

For high-volume histories, implement paginated or virtualized rendering.

Do not render thousands of complete request records into the DOM at once.

### 10.4 Selection behavior

Clicking a request:

1. Marks the row selected.
2. Updates the right inspector.
3. Cancels or invalidates obsolete detail fetches.
4. Opens the request's most recently selected inspector tab where appropriate.
5. Disables automatic selection movement if the request is not the newest/current active request.

An arriving new request must not steal focus from a manually selected old request.

Maintain request identity using server/model/request identifiers rather than display position.

### 10.5 Real-time behavior

While following the active request:

- Update the running duration.
- Update reported token counts when received.
- Append exposed reasoning and output deltas.
- Update state on completion/failure.
- Preserve visible scroll position according to follow settings.

Do not scroll the request rail automatically if the user has scrolled away from the newest item and explicitly disabled follow.

---

## 11. Request inspector — primary content area

The inspector occupies the right side of the main workspace.

### 11.1 Header

Display:

- Full or abbreviated request ID.
- Current lifecycle state.
- Model name/configuration.
- Request start time.
- Capture source/mode.

Provide a copy-ID action.

### 11.2 Mini statistics

Preserve five compact metric cards:

1. Input tokens
2. Reasoning tokens
3. Output tokens
4. Duration
5. Average sampled GPU utilization

During active streaming, token counts may be unavailable until final provider usage arrives.

Do not increment exact token counts using arbitrary characters-per-token guesses.

If an estimate is available, label it as estimated and distinguish it from provider-reported counts.

### 11.3 Inspector tabs

Use three primary tabs:

- Transcrip
- Telemetry
- Event timeline

A separate control on the right toggles reasoning-content visibility.

Tabs must retain the selected request and update without navigating to a new browser page.

### 11.4 Transcript view

Preserve the approved prototype's three principal visual sections:

**Input**

Blue-accented header.

Display the input messages sent to the model in their original order, including system/developer/user/assistant/tool roles when captured.

Support structured message lists, not just one flattened prompt string.

**Reasoning**

Purple-accented header.

Display exposed model reasoning, separate from ordinary output.

Support incremental deltas.

If reasoning is not exposed, explicitly state that it is unavailable from the observation source.

Missing reasoning content must not be interpreted as proof that no reasoning occurred.

**Output**

Green-accented header.

Display the generated answer and any structured tool calls where supported.

Support incremental streaming and terminal completion state.

### 11.5 Transcript rendering

Use monospaced or code-friendly typography for structured content.

Support:

- Expand/collapse.
- Copy.
- Select text.
- Text search.
- Large-content truncation notices.
- Optional safe Markdown presentation.
- Plain-text fallback.
- Visible streaming cursor.
- Separate scrolling and auto-follow.

Treat all captured model text as untrusted.

Do not render raw provider-controlled HTML using `innerHTML`.

Use safe DOM text nodes or properly sanitized Markdown.

### 11.6 Transcript availability

Handle these cases separately:

- Live content available.
- Completed content available.
- Input rendered-only from a model log.
- Reasoning text unavailable.
- Usage metadata available but content unavailable.
- Content evicted from memory.
- Content not persisted.
- Partial stream with a disconnect gap.
- Request still running.
- Request failed or cancelled.

An old request's metadata should remain usable even if its full text was not retained.

---

## 12. Telemetry tab

This view is a dense collection of detailed request measurements.

Suggested grid:

- End-to-end duration.
- Time to first token.
- Queue duration.
- Prefill duration.
- Decode duration.
- Generation tokens/second.
- Input tokens.
- Reasoning tokens.
- Output tokens.
- Cached input tokens.
- Average GPU utilization.
- Peak GPU utilization.
- Average VRAM.
- Peak VRAM.
- Request outcome.
- Source/capture quality.

Use three columns on desktop, collapsing to two or one when necessary.

Values should have clear units.

Where metrics are inferred, calculated or source-specific, provide explanatory labels/tooltips.

Add a small provenance section identifying the actual provider/source, observed time and coverage.

---

## 13. Event timeline tab

Display a chronological sequence of request-related events.

Initial implementation may use a vertically stacked event list matching the mockup.

Possible events:

- Request observed.
- Model selected.
- Request queued.
- Prompt processing started.
- First reasoning delta.
- First output delta.
- Tool call emitted.
- Usage reported.
- Request completed.
- Request failed/cancelled.
- Monitoring gap.

Show relative timing and absolute timestamps where available.

For measured intervals, a later enhanced view may include horizontal duration bars.

Never invent phase durations from generic response timestamps.

The timeline should allow inspection of corresponding transcript segments when event-to-content references exist.

---

## 14. Bottom GPU and capture panels

### 14.1 GPU panel

The left lower panel displays:

- Device name.
- A compact GPU activity line chart.
- Average GPU utilization.
- VRAM used / total.
- Optional historical sampling window.
- Measurement scope.

Use lightweight SVG or Canvas for time series, with local assets only.

Include a clear note that device-level measurements overlapping requests are not necessarily exclusive to the selected model.

The chart should have a consistent time axis and distinguish unavailable intervals from zero values.

### 14.2 Capture/status panel

The right lower panel displays:

- Model metadata availability.
- Structured input capture.
- Reasoning stream availability.
- Output stream availability.
- Usage/timing availability.
- KV/prefix cache metrics.
- Recording state.
- Telemetry source and completeness.

Use concise, readable labels such as:

- Available
- Streaming
- Completion only
- Partial
- Not instrumented
- Unavailable
- Recording disabled

This panel is essential because the product combines passive and fully captured observations.

It should prevent users from mistaking a lack of telemetry for a lack of model activity.

---

## 15. Models and Servers page

This page uses a grid of compact server/model cards.

Each model card should show:

- Model name.
- Provider/server.
- Loaded or historical state.
- Quantization.
- Effective configured context.
- Request count.
- Average request duration.
- Available usage statistics.
- Memory allocation where defensibly attributable.
- Last observation time.

Selecting a model opens the Requests workspace filtered to that model.

Group models under the server or instance that actually hosted them.

Do not merge historical configurations with current configurations without preserving their identity.

For a previously used but unloaded model, show a historical label rather than pretending it is still running.

---

## 16. History page

The History page allows searching and inspecting previous request records across models.

Provide:

- Model selector.
- Server selector.
- Time-range selector.
- Recording mode/coverage information.
- Request table or list.
- Request detail navigation.
- Optional aggregate charts.

Table columns should include model, request identifier, observation time, state, duration, tokens and content availability.

Clicking a record should open the same inspector used for live requests.

Use one request-inspector implementation for live and historical data.

A historical request can have three distinct states:

- Metadata and transcript available.
- Metadata only.
- Content partially retained.

Do not claim that missing historical content can be reconstructed.

---

## 17. Alerts and Coverage page

Separate alerts from collection coverage.

Include:

- Active diagnostic findings.
- Provider disconnects.
- Request failures.
- Collector errors.
- Telemetry gaps.
- Missing capture capabilities.
- Hardware warnings.
- Recording/storage failures.

Each finding should include severity, classification, source and time.

Use neutral empty states.

“No active alerts recorded” is not equivalent to “The model is healthy”.

When a monitoring source is unavailable, show an explanatory status instead of an empty dashboard.

---

## 18. Frontend state architecture

Do not implement the application as one large JavaScript file containing rendering, networking, storage and all interactions.

Use distinct responsibilities.

### 18.1 State domains

**Navigation state**

- Current page.
- Active model/server filter.
- Selected request identity.
- Inspector tab.
- Search/filter preferences.

**Live transport state**

- Connected/reconnecting/disconnected.
- Last successful event.
- Last acknowledged sequence.
- Missing-event/gap state.

**Request state**

- Request summaries.
- Selected request detail.
- Content segments.
- Token usage.
- Lifecycle state.
- Telemetry provenance.

**View preferences**

- Auto-follow request selection.
- Auto-scroll transcript.
- Reasoning visibility.
- Sidebar preference.
- Request rail width.
- Last selected inspector tab.

**Recording state**

- Actual metadata-recording status.
- Actual content-recording status.
- Retention policy.
- Pending recording action/error.

### 18.2 Persistent browser preferences

Persist harmless UI preferences only.

Do not persist:

- API credentials.
- Login codes.
- Raw prompts.
- Reasoning content.
- Model outputs.
- Sensitive tool arguments.

Use application-specific preference keys that cannot collide with Runmux storage keys.

### 18.3 Update strategy

Prefer an authenticated WebSocket for incremental events with an initial authenticated snapshot.

Event updates should carry:

- Request identity.
- Event type.
- Monotonic sequence/revision.
- Source timestamp.
- Payload or content delta.
- Coverage state where relevant.

On reconnect, use a snapshot or replay mechanism to reconcile state.

Avoid assuming that WebSocket delivery is lossless.

Do not refresh the entire transcript DOM on each token.

---

## 19. Proposed source structure

The following structure is a recommendation, not a claim that these files already exist.

| Proposed path | Responsibility |
|---|---|
| `llm_monitor/web.py` | Standalone application construction |
| `llm_monitor/web_api.py` | Authenticated API routes |
| `llm_monitor/web_static/index.html` | Application shell |
| `web_static/assets/styles/tokens.css` | Scoped design tokens |
| `web_static/assets/styles/layout.css` | Responsive shell and workspace |
| `web_static/assets/styles/components.css` | Cards, controls, lists and states |
| `web_static/assets/styles/transcript.css` | Transcript-specific styling |
| `web_static/assets/js/app.js` | Application bootstrap |
| `web_static/assets/js/api.js` | Authenticated fetch and stream client |
| `web_static/assets/js/store.js` | Frontend state container |
| `web_static/assets/js/router.js` | Workspace navigation |
| `web_static/assets/js/components/` | Reusable presentation components |
| `web_static/assets/js/views/overview.js` | Main activity workspace |
| `web_static/assets/js/views/requests.js` | Request explorer |
| `web_static/assets/js/views/models.js` | Model/server view |
| `web_static/assets/js/views/history.js` | Historical browser |
| `web_static/assets/js/views/alerts.js` | Alerts and coverage |
| `web_static/assets/js/views/inspector.js` | Shared request inspector |
| `web_static/assets/js/formatters.js` | Formatting and source-aware metrics |

Use native browser ES modules unless repository review identifies a strong need for a frontend bundler.

No React or heavyweight dashboard framework is required by the approved design.

Package all assets with the installed Python distribution.

Do not depend on a CDN at runtime.

---

## 20. Browser API requirements

The frontend should consume an inference-oriented API distinct from the existing Runmux OpenCode session API.

Suggested routes:

| Route | Frontend consumer |
|---|---|
| `GET /api/inference/v1/status` | Header, sidebar, capture status |
| `GET /api/inference/v1/servers` | Server navigation |
| `GET /api/inference/v1/models` | Model selector and model page |
| `GET /api/inference/v1/requests` | Request stream/history |
| `GET /api/inference/v1/requests/{id}` | Request inspector |
| `GET /api/inference/v1/requests/{id}/content` | Transcript tab |
| `GET /api/inference/v1/requests/{id}/events` | Timeline |
| `GET /api/inference/v1/analytics` | Summary cards |
| `GET /api/inference/v1/hardware` | GPU panel |
| `GET /api/inference/v1/coverage` | Capture/coverage page |
| `GET /api/inference/v1/recording` | Recording status |
| `WS /api/inference/v1/stream` | Live request updates |

Backend ownership may adjust names, but the frontend must not guess or hardcode undocumented provider-specific data shapes.

Before integration, agree on the request identity, token accounting, content-segment and coverage schemas.

A frontend normalization layer should validate incoming data and preserve missing values as unavailable.

Do not treat data supplied by synthetic fixtures as proof of real collector functionality.

---

## 21. Authentication and host integration

Use `web_ui_tools.create_app`.

The existing framework protects routes under `/api`, so all sensitive data and control APIs must stay under this prefix.

The public static page must never embed collected content or credentials.

After login, the frontend should fetch the initial snapshot and establish the authenticated live connection.

WebSocket reconnect and authentication expiry must be handled separately.

### 21.1 Cookie namespace issue

The reviewed framework uses the fixed cookie name `web_ui_session`.

Because cookies are scoped by host rather than port, a standalone LLM Monitor and Runmux served on the same local hostname can interfere with each other's session cookies.

Investigate an optional per-application cookie-name parameter in `web_ui_tools`.

Preserve the original default and update both HTTP and WebSocket authentication paths consistently.

Add regression tests for two independent applications served under the same hostname.

Do not weaken the existing origin checks.

### 21.2 Recording actions

Recording is an external state change, not merely a UI preference.

The Record control must reflect the backend result.

Do not optimistically display “Recording” before an authorized recording operation succeeds.

Use explicit confirmation for enabling persistent full-content capture.

### 21.3 CSP and source safety

The original interactive prototype contains inline styling, scripts and demo-oriented HTML construction. These were appropriate for the mockup but are not production-ready.

Move implementation into packaged external assets.

Avoid raw HTML insertion of model-controlled content.

Keep sensitive transcript API responses non-cacheable.

---

## 22. Empty, partial and failure states

Every major workspace must support the following conditions.

### No inference server discovered

Show a clear empty state explaining that monitoring is running but no supported endpoint is reachable.

Provide a safe indication of the known endpoints checked.

### Provider discovered, no requests visible

Show available inventory and capability status.

Explain if individual request events are unsupported.

Do not fabricate request rows.

### Provider disconnected

Preserve the last known model/request state with stale indicators.

Show a gap in the observation period.

Do not continue incrementing a request's verified running duration after its state becomes unknown.

### Request selected, content unavailable

Preserve request metadata and show an explanatory content-unavailable message.

### Live request stream interrupted

Keep existing text and show a visible stream-gap indicator.

Do not pretend later deltas form a complete transcript if events were missed.

### Historical request without recorded conten

Show metadata and clearly identify that the full transcript was not retained.

### No GPU metrics

Show hardware telemetry as unavailable without disabling request inspection.

### Authentication expired

Stop sensitive stream updates, clear protected content from visible application state where feasible, and return to the login view.

---

## 23. Accessibility and keyboard controls

Use semantic navigation, buttons, inputs and tables.

Implement visible keyboard focus.

Recommended shortcuts, when focus is not inside an editable field:

| Shortcut | Action |
|---|---|
| `/` | Focus request search |
| `↑` / `↓` | Navigate requests when the list is focused |
| `Enter` | Inspect highlighted request |
| `Esc` | Close an expanded menu/search state |
| `L` | Return to latest/live request |
| `F` | Toggle auto-follow |
| `R` | Toggle reasoning visibility when the inspector is active |
| `?` | Show keyboard help |

Avoid browser-critical shortcuts.

Tabs should expose appropriate selected state and keyboard semantics.

Live text updates must not continuously overwhelm screen-reader announcements.

Use a restrained status announcement area for meaningful lifecycle changes instead.

Do not use rapid animations for streaming cursors.

---

## 24. Visual and interaction tests

Use deterministic synthetic fixtures containing:

- Two discovered servers.
- One actively generating request.
- Several completed requests.
- A failed/cancelled request.
- A request with reasoning text.
- A request with no exposed reasoning.
- A request with unavailable input.
- An unloaded historical model.
- GPU telemetry samples.
- A provider disconnect/gap.
- Recording-disabled state.

Synthetic fixtures must be labeled in developer documentation and never mistaken for real production measurements.

### 24.1 Component tests

Cover:

- Correct request selection.
- No selection stealing when new requests arrive.
- Auto-follow enable/disable.
- Model filtering.
- Search and pagination.
- Inspector tab switching.
- Reasoning show/hide.
- Append-only streaming rendering.
- Missing token metrics.
- Unknown/error states.
- Historical request navigation.
- Recording status.
- Safe text rendering.

### 24.2 Browser-level validation

Use headless Chromium where available.

Required viewport checks:

- 1920×1080 desktop.
- 1440×900 desktop.
- 1280×800 compact desktop.
- 768×1024 tablet.
- 390×844 mobile.
- An ultrawide desktop viewport, if supported by the test environment.

Capture screenshots of:

- Initial Overview.
- Active reasoning stream.
- Completed request.
- Telemetry tab.
- Timeline tab.
- Model cards.
- History.
- Alerts.
- Empty server state.
- Disconnected source state.

Compare each with the approved visual reference.

Browser snapshots alone are insufficient; test core interactions and rendering safety.

### 24.3 Visual acceptance

The implemented UI must preserve:

- Compact top header.
- Dark blue-gray surfaces.
- Narrow left navigation.
- Six statistics cards.
- Two-column request/investigation workspace.
- Blue input, purple reasoning and green output sections.
- Five per-request metric cards.
- Three inspector tabs.
- Bottom GPU and capture panels.
- Responsive mobile stacking.
- High information density without clutter.

Major layout deviations require explicit design approval.

---

## 25. Implementation sequence

### UI-1 — Foundation and static fidelity

Build:

- Standalone HTML shell.
- External CSS design system.
- Header.
- Sidebar.
- Page toolbar.
- KPI cards.
- Request rail.
- Inspector.
- GPU and capture panels.

Populate with deterministic synthetic fixtures.

**Acceptance:** The initial 1440px desktop view faithfully resembles the approved prototype.

Do not connect the frontend to real inference services in this stage.

### UI-2 — Navigation and behavior

Implement:

- Page navigation.
- Model selection.
- Request selection.
- Search/filtering.
- Inspector tabs.
- Reasoning visibility.
- Auto-follow.
- Responsive layout.
- Keyboard controls.

**Acceptance:** All interactive elements work against fixtures without unnecessary full-page rerenders.

### UI-3 — API and live state

Implement:

- Authenticated API client.
- Request summary/detail adapters.
- Live WebSocket updates.
- Reconciliation/reconnect.
- Incremental transcript rendering.
- Capability-aware states.
- Provider/hardware measurements.

**Acceptance:** A synthetic streaming provider can produce realistic live updates without corrupting selection or scroll state.

### UI-4 — Historical and recording views

Implement:

- History navigation.
- Paginated records.
- Historical transcript inspector.
- Recording status/actions.
- Retention/capture indicators.
- Cross-model history.

**Acceptance:** Recorded and unrecorded content states are distinguished correctly.

### UI-5 — Visual refinement and validation

Perform:

- Screenshot comparisons.
- Responsive fixes.
- Keyboard/accessibility tests.
- Long-transcript performance tests.
- Browser authentication tests.
- CSP and XSS regression tests.
- Installed-wheel asset checks.

**Acceptance:** The UI is visually coherent, responsive, and compatible with the standalone authenticated host.

---

## 26. Explicit implementation instructions

1. Use the previously approved interactive LLM Monitor mockup as the visual reference.
2. Inspect the latest repository state before modifying files.
3. Preserve existing LLM Monitor and Runmux public contracts.
4. Keep the new standalone frontend independently usable without Runmux.
5. Reuse `web_ui_tools` authentication and hosting.
6. Use application-specific, modular frontend source files.
7. Avoid heavyweight frontend dependencies without demonstrated need.
8. Implement the static design using synthetic data before integrating live sources.
9. Keep the request stream and inspector simultaneously visible on desktop.
10. Never invent unsupported telemetry.
11. Treat reasoning/input/output content as potentially sensitive and untrusted.
12. Keep the viewer's follow state independent of backend collection.
13. Ensure full-content persistence remains separately opt-in.
14. Add automated tests and browser visual validation.
15. Record implementation decisions and deviations in the project documentation.

Do not modify Runmux's process-management UI as part of this handoff.

A minimal, backward-compatible `web_ui_tools` security improvement is acceptable if independently tested.

---

## 27. Required agent deliverables

At the end of each UI phase, report:

- Baseline branch/commit.
- Files created/modified.
- Components implemented.
- API contracts consumed.
- Behaviors implemented.
- Tests executed and actual results.
- Browser screenshots.
- Comparison with approved mockup.
- Responsive/accessibility issues.
- Security findings.
- Unimplemented UI features.
- Required backend dependencies.
- Recommended next UI phase.

For visual changes, screenshots and direct browser inspection should be treated as required validation evidence wherever the environment supports them.

Do not claim pixel-perfect fidelity without a reference comparison.

---

## 28. Definition of frontend completion

The frontend is complete when a user can open standalone LLM Monitor, select a local model, observe its request stream, inspect a current request, read exposed reasoning/output live, inspect request usage and timing, view relevant GPU statistics, browse previous model activity, and understand the status of recording and telemetry coverage.

The interface must handle missing or incomplete data without misleading the user and remain visually faithful to the approved dark observability workspace.

**The approved mockup is the design baseline. Backend capability determines which real values can be populated, not whether the core UI structure should be implemented.**\n