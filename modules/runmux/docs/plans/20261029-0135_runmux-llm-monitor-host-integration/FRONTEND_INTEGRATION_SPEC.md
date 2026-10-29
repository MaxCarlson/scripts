# Runmux LLM Monitor Frontend Integration Specification (Stages 4 & 5)

**Document:** Frontend Workspace Architecture & Coordination Contract  
**Audience:** Runmux UI integration owner  
**Status:** Deferred / Blocked pending Phase 6C History Explorer (`a03b4fa6`) audit and integration.  

## 1. Concurrency Boundary & Conflict Prevention

Phase 6C History Explorer (`codex/runmux-6c-history-frontend-local-pilot-20261024`, commit `a03b4fa65d49bde59287dc4a246603f13a91b974`) modifies:
- `modules/runmux/src/runmux/web_static/index.html`
- `modules/runmux/src/runmux/web_static/assets/dashboard.js`
- `modules/runmux/src/runmux/web_static/assets/dashboard.css`
- `modules/runmux/tests/dashboard_test.js`
- `modules/runmux/tests/browser_e2e_test.js`

Per Stage 3 instructions ("Before modifying `web_static`, confirm Phase 6C History Explorer is integrated or that the designated integration owner has released those files. Do not reimplement Phase 6C or overwrite its work. If frontend ownership is still blocked, finish and publish Stages 1–2 independently, with their tests, then report the blocked frontend stage"), direct edits to `web_static/` are deferred to avoid collision with Phase 6C.

This document provides the complete, modular implementation blueprint for Stages 4 and 5 so the frontend workspace can be mounted immediately once Phase 6C is merged.

---

## 2. Modular Architecture (`assets/llm-monitor.js`)

The monitoring interface must live in a dedicated modular file:
`modules/runmux/src/runmux/web_static/assets/llm-monitor.js`

It exposes a single global namespace:
```javascript
window.RunmuxLLMMonitor = {
  start: function(containerElement, apiHelper) { ... },
  stop: function() { ... },
  onVisibilityChange: function(isVisible) { ... },
};
```

### Key Principles:
1. **Narrow Connection to Host:**
   Reuses Runmux's authenticated `api(path, options)` helper directly. Does not duplicate authentication, session cookie management, login, or logout logic.
2. **Safe DOM Rendering:**
   All provider-controlled strings (model names, provider URLs, session IDs, event messages, diagnostic text) MUST be rendered using `document.createTextNode` or `element.textContent`. Never interpolate provider strings into `innerHTML`, attributes, or CSS.
3. **Identity Tuple:**
   Session identity is always the pair `(provider_instance_id, session_id)`. Keys, DOM data attributes, and selection states must use this composite key.

---

## 3. UI Layout & Component Hierarchy

### 3.1 Top-Level Workspace Switch (`index.html`)
Alongside the existing process navigation in the header:
```html
<nav class="app-views-nav" role="tablist">
  <button id="view-tab-processes" class="app-view-tab active" role="tab" aria-selected="true" aria-controls="workspace">Processes</button>
  <button id="view-tab-llm-monitor" class="app-view-tab" role="tab" aria-selected="false" aria-controls="llm-monitor-workspace">LLM Monitor</button>
</nav>
```

### 3.2 Workspace Container
Under `#app-container`:
```html
<section id="llm-monitor-workspace" class="workspace-section" hidden aria-hidden="true">
  <div class="monitor-header">
    <div class="monitor-status-badge" id="monitor-status-badge">Checking...</div>
    <div class="monitor-summary-stats" id="monitor-summary-stats"></div>
  </div>
  <div class="monitor-layout">
    <aside class="monitor-sidebar" id="monitor-session-list"></aside>
    <main class="monitor-main" id="monitor-session-detail">
      <div id="monitor-detail-summary"></div>
      <div id="monitor-detail-timeline"></div>
      <div id="monitor-detail-alerts"></div>
      <div id="monitor-detail-hardware"></div>
    </main>
  </div>
</section>
```

---

## 4. Shared Bounded Refresh & Lifetime Management (Stage 5)

1. **Single Polling Schedule:**
   - Interval: 5.0 seconds (matching `refresh_interval_seconds` from `/api/llm-monitor/v1/status`).
   - Polls `/api/llm-monitor/v1/snapshot`.
   - Never create independent polling timers for sidebar, detail, timeline, and alerts.
2. **Lifecycle State Machine:**
   - **Idle/Logged-out:** Timer is `null`. No requests in flight.
   - **Login Succeeded:** Query `/api/llm-monitor/v1/status`. If `availability === "disabled"`, show disabled banner; do not poll.
   - **Workspace Visible (`#view-tab-llm-monitor` active):** Start 5.0s snapshot poll loop.
   - **Workspace Hidden (`#view-tab-processes` active):** Pause poll loop (`clearTimeout`).
   - **Lock / Logout:** Call `RunmuxLLMMonitor.stop()`, cancel in-flight abort controllers, clear cached session state.
3. **Detail & Timeline Fetching:**
   - On selecting a session `(provider_instance_id, session_id)`:
     - Fetch `/api/llm-monitor/v1/sessions/detail?provider_instance_id=...&session_id=...`.
     - Fetch initial timeline page `/api/llm-monitor/v1/sessions/timeline?...&limit=100`.
     - Fetch active alerts `/api/llm-monitor/v1/alerts?status=active&limit=50`.
   - Bounded "Load More" pagination: clicking appends next 100 events using `next_cursor`.
   - Race condition protection: Ignore detail/timeline replies if the user has switched selected session in the interim.
