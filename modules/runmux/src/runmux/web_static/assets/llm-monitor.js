"use strict";

(() => {
  const DEFAULT_POLL_INTERVAL_MS = 5000;
  const TIMELINE_PAGE_LIMIT = 50;
  const ALERTS_LIMIT = 50;

  let container = null;
  let api = null;
  let isVisible = false;
  let isPolling = false;
  let pollTimer = null;
  let pollIntervalMs = DEFAULT_POLL_INTERVAL_MS;
  let abortController = null;
  let detailAbortController = null;
  let requestGeneration = 0;

  let monitorStatus = null;
  let snapshotData = null;
  let selectedSessionTuple = null; // { provider_instance_id, session_id }
  let selectedDetail = null;
  let selectedTimelineEvents = [];
  let timelineNextCursor = null;
  let timelineLoading = false;
  let detailLoading = false;
  let detailError = null; // { type: "404" | "503" | "generic", message: string }

  function formatTimestamp(value) {
    if (!value || typeof value !== "string") return "—";
    try {
      const date = new Date(value);
      return Number.isFinite(date.getTime()) ? date.toLocaleString() : String(value);
    } catch {
      return String(value);
    }
  }

  function formatNumber(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "—";
    return value.toLocaleString();
  }

  function formatTokens(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "—";
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
    return String(value);
  }

  function formatCumulativeTokens(summary) {
    const tokens = summary && summary.cumulative_tokens;
    if (!tokens || typeof tokens !== "object") return "Token counts unavailable";
    const labels = [["input", "Input"], ["output", "Output"], ["reasoning", "Reasoning"]];
    const available = labels.filter(([key]) => Number.isFinite(tokens[key]) && tokens[key] >= 0);
    if (available.length === 0) return "Token counts unavailable";
    return labels.map(([key, label]) => {
      const value = Number.isFinite(tokens[key]) && tokens[key] >= 0 ? formatTokens(tokens[key]) : "—";
      return `${label} ${value}`;
    }).join(" · ");
  }

  function makeEl(tag, className, textContent) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (textContent != null) el.textContent = textContent;
    return el;
  }

  function renderStatusBadge(status) {
    const badge = makeEl("div", "monitor-status-pill");
    if (!status) {
      badge.classList.add("checking");
      badge.textContent = "Checking status…";
      return badge;
    }

    const rawAvail = String(status.availability || "unknown");
    const avail = rawAvail.toLowerCase().replace(/[^a-z0-9_-]/g, "-");
    badge.classList.add(avail);
    if (avail === "available") {
      const provider = status.configured_provider || "Provider";
      badge.textContent = `Connected · ${provider}`;
    } else if (avail === "disabled") {
      badge.textContent = "Disabled";
    } else {
      const reason = status.reason_code ? ` (${status.reason_code})` : "";
      badge.textContent = `Unavailable${reason}`;
    }
    return badge;
  }

  function renderHeader() {
    const header = makeEl("header", "monitor-header");

    const brand = makeEl("div", "monitor-brand");
    const title = makeEl("h2", "monitor-title", "LLM Observability");
    const badge = renderStatusBadge(monitorStatus);
    badge.id = "monitor-status-pill";
    brand.append(title, badge);

    const stats = makeEl("div", "monitor-header-stats");
    stats.id = "monitor-header-stats";
    updateHeaderStats(stats);

    header.append(brand, stats);
    return header;
  }

  function updateHeaderStats(containerEl) {
    const statsEl = containerEl || document.getElementById("monitor-header-stats");
    if (!statsEl) return;
    statsEl.replaceChildren();

    if (!snapshotData || !snapshotData.system) {
      if (monitorStatus && monitorStatus.availability === "disabled") {
        statsEl.append(makeEl("span", "muted small-text", "Monitoring disabled by host configuration"));
      } else {
        statsEl.append(makeEl("span", "muted small-text", "Awaiting telemetry snapshot…"));
      }
      return;
    }

    const sys = snapshotData.system || {};
    const sessions = Array.isArray(snapshotData.sessions) ? snapshotData.sessions : [];
    const models = Array.isArray(sys.session_model_identities)
      ? sys.session_model_identities
      : (Array.isArray(sys.loaded_models) ? sys.loaded_models : []);

    const sessPill = makeEl("span", "stat-pill");
    sessPill.append(makeEl("strong", null, String(sessions.length)), " sessions");

    const modelsPill = makeEl("span", "stat-pill");
    modelsPill.append(makeEl("strong", null, String(models.length)), " model identities observed in sessions");

    statsEl.append(sessPill, modelsPill);

    if (snapshotData.hardware && Array.isArray(snapshotData.hardware.devices)) {
      for (const dev of snapshotData.hardware.devices) {
        if (dev && dev.name) {
          const hwPill = makeEl("span", "stat-pill hardware-pill", dev.name);
          statsEl.append(hwPill);
        }
      }
    }
  }

  function renderSidebar() {
    const sidebar = makeEl("aside", "monitor-sidebar");
    const heading = makeEl("div", "monitor-sidebar-heading");
    const headingTitle = makeEl("h3", null, "Active & Recorded Sessions");
    const countBadge = makeEl("span", "count-pill", "0");
    countBadge.id = "monitor-session-count";
    heading.append(headingTitle, countBadge);

    const list = makeEl("div", "monitor-session-list");
    list.id = "monitor-session-list";
    list.setAttribute("role", "list");

    sidebar.append(heading, list);
    return sidebar;
  }

  function updateSessionList() {
    const listEl = document.getElementById("monitor-session-list");
    const countEl = document.getElementById("monitor-session-count");
    if (!listEl) return;

    if (monitorStatus && monitorStatus.availability === "disabled") {
      listEl.replaceChildren();
      const disabledMsg = makeEl("div", "monitor-empty-state");
      disabledMsg.append(
        makeEl("p", "strong", "LLM Monitor Disabled"),
        makeEl("p", "muted", "Set RUNMUX_LLM_MONITOR_ENABLED=1 on the server to enable read-only monitoring.")
      );
      listEl.append(disabledMsg);
      if (countEl) countEl.textContent = "0";
      return;
    }

    const sessions = (snapshotData && Array.isArray(snapshotData.sessions)) ? snapshotData.sessions : [];
    if (countEl) countEl.textContent = String(sessions.length);

    listEl.replaceChildren();

    if (sessions.length === 0) {
      const empty = makeEl("div", "monitor-empty-state");
      empty.append(
        makeEl("p", "muted", "No active or recorded LLM sessions reported by provider.")
      );
      listEl.append(empty);
      return;
    }

    for (const session of sessions) {
      if (!session || !session.session_id) continue;
      const card = makeEl("div", "monitor-session-card");
      card.setAttribute("role", "listitem");
      card.dataset.providerInstanceId = session.provider_instance_id || "";
      card.dataset.sessionId = session.session_id;

      const isSelected = selectedSessionTuple &&
        selectedSessionTuple.provider_instance_id === (session.provider_instance_id || "") &&
        selectedSessionTuple.session_id === session.session_id;

      if (isSelected) {
        card.classList.add("selected");
      }

      const cardHead = makeEl("div", "session-card-head");
      const idEl = makeEl("span", "session-id-text", session.session_id);
      idEl.title = session.session_id;

      const rawStatus = String(session.state || session.status || "active");
      const statusText = rawStatus.toLowerCase();
      const statusClass = statusText.replace(/[^a-z0-9_-]/g, "-");
      const statusPill = makeEl("span", `session-status-pill ${statusClass}`, statusText);
      cardHead.append(idEl, statusPill);

      const cardBody = makeEl("div", "session-card-body");
      const modelName = session.model || session.model_id || "default";
      const modelEl = makeEl("span", "session-model-name", modelName);

      const tokensEl = makeEl("span", "session-tokens-count", formatCumulativeTokens(session));
      cardBody.append(modelEl, tokensEl);

      card.append(cardHead, cardBody);

      card.addEventListener("click", () => {
        selectSession(session.provider_instance_id || "", session.session_id);
      });

      listEl.append(card);
    }
  }

  function renderMain() {
    const main = makeEl("main", "monitor-main");
    main.id = "monitor-main";

    const empty = makeEl("div", "monitor-main-empty");
    empty.id = "monitor-main-empty";
    empty.append(
      makeEl("div", "empty-icon", "◉"),
      makeEl("h3", null, "Select an LLM Session"),
      makeEl("p", "muted", "Choose a session from the sidebar to inspect token usage, model configuration, hardware state, and chronological event diagnostics.")
    );

    const detailContainer = makeEl("div", "monitor-detail-content");
    detailContainer.id = "monitor-detail-content";
    detailContainer.hidden = true;

    main.append(empty, detailContainer);
    return main;
  }

  async function selectSession(providerInstanceId, sessionId) {
    if (selectedSessionTuple &&
        selectedSessionTuple.provider_instance_id === providerInstanceId &&
        selectedSessionTuple.session_id === sessionId) {
      return;
    }

    selectedSessionTuple = { provider_instance_id: providerInstanceId, session_id: sessionId };
    selectedDetail = null;
    selectedTimelineEvents = [];
    timelineNextCursor = null;
    detailLoading = true;
    detailError = null;

    updateSessionList();
    renderSessionDetailView();

    await fetchSessionDiagnostics(providerInstanceId, sessionId);
  }

  async function fetchSessionDiagnostics(providerInstanceId, sessionId) {
    const currentGeneration = ++requestGeneration;
    if (detailAbortController) {
      detailAbortController.abort();
    }
    detailAbortController = new AbortController();
    const signal = detailAbortController.signal;

    detailLoading = true;
    detailError = null;

    try {
      // 1. Fetch Session Detail
      const detailParams = new URLSearchParams({
        provider_instance_id: providerInstanceId,
        session_id: sessionId,
      });
      const detailRes = await api(`/api/llm-monitor/v1/sessions/detail?${detailParams.toString()}`, { signal });
      const detailData = await detailRes.json();

      if (currentGeneration !== requestGeneration) return;
      selectedDetail = detailData.detail || detailData;
      detailLoading = false;
    } catch (err) {
      if (signal.aborted || currentGeneration !== requestGeneration) return;
      detailLoading = false;
      if (err && err.message === "locked") {
        globalThis.showLogin?.("Session expired. Enter the current terminal login code again.");
        return;
      }
      if (err.status === 404) {
        detailError = { type: "404", message: "LLM session not found or expired from provider." };
      } else if (err.status === 503) {
        detailError = { type: "503", message: "Provider is offline or unreachable. Detailed diagnostics unavailable." };
      } else {
        detailError = { type: "generic", message: err.message || "Failed to load session details." };
      }
    }

    renderSessionDetailView();

    // 2. Fetch Timeline & Alerts in parallel if detail succeeded
    if (!detailError && currentGeneration === requestGeneration) {
      await Promise.all([
        fetchTimelinePage(providerInstanceId, sessionId, null, currentGeneration, signal),
        fetchAlerts(currentGeneration, signal),
      ]);
    }
  }

  async function fetchTimelinePage(providerInstanceId, sessionId, cursor, generation, signal) {
    timelineLoading = true;
    try {
      const params = new URLSearchParams({
        provider_instance_id: providerInstanceId,
        session_id: sessionId,
        limit: String(TIMELINE_PAGE_LIMIT),
      });
      if (cursor) params.set("cursor", cursor);

      const res = await api(`/api/llm-monitor/v1/sessions/timeline?${params.toString()}`, { signal });
      const data = await res.json();

      if (generation !== requestGeneration) return;

      const events = Array.isArray(data.events) ? data.events : (Array.isArray(data.items) ? data.items : []);
      if (cursor) {
        selectedTimelineEvents = selectedTimelineEvents.concat(events);
      } else {
        selectedTimelineEvents = events;
      }
      timelineNextCursor = data.next_cursor || null;
      timelineLoading = false;
      renderTimelineSection();
    } catch {
      if (generation === requestGeneration) {
        timelineLoading = false;
        renderTimelineSection();
      }
    }
  }

  async function fetchAlerts(generation, signal) {
    try {
      const params = new URLSearchParams({
        status: "active",
        limit: String(ALERTS_LIMIT),
        provider_instance_id: selectedSessionTuple.provider_instance_id,
        session_id: selectedSessionTuple.session_id,
      });
      const res = await api(`/api/llm-monitor/v1/alerts?${params.toString()}`, { signal });
      const data = await res.json();
      if (generation !== requestGeneration) return;
      const alerts = Array.isArray(data.alerts) ? data.alerts : [];
      const scopedAlerts = alerts.filter((alert) =>
        alert && alert.session_id === selectedSessionTuple.session_id &&
        alert.provider_instance_id === selectedSessionTuple.provider_instance_id
      );
      renderAlertsSection(scopedAlerts, data.availability);
    } catch {
      // Non-fatal, keep existing
    }
  }

  function renderSessionDetailView() {
    const emptyEl = document.getElementById("monitor-main-empty");
    const contentEl = document.getElementById("monitor-detail-content");
    if (!emptyEl || !contentEl) return;

    if (!selectedSessionTuple) {
      emptyEl.hidden = false;
      contentEl.hidden = true;
      contentEl.replaceChildren();
      return;
    }

    emptyEl.hidden = true;
    contentEl.hidden = false;
    contentEl.replaceChildren();

    if (detailLoading) {
      const loading = makeEl("div", "monitor-loading-box");
      loading.append(makeEl("div", "spinner"), makeEl("p", null, "Loading session diagnostics…"));
      contentEl.append(loading);
      return;
    }

    if (detailError) {
      const errType = String(detailError.type || "error").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
      const errBox = makeEl("div", `monitor-error-box ${errType}`);
      errBox.append(
        makeEl("h4", null, detailError.type === "404" ? "Session Missing" : "Provider Unavailable"),
        makeEl("p", null, detailError.message)
      );
      contentEl.append(errBox);
      return;
    }

    const detail = selectedDetail || {};
    const summary = detail.summary || detail;

    // 1. Overview Card
    const overviewCard = makeEl("section", "monitor-card overview-card");
    const overviewHead = makeEl("div", "card-header");
    overviewHead.append(makeEl("h3", null, "Session Summary"));
    overviewCard.append(overviewHead);

    const grid = makeEl("div", "detail-grid");

    // Session ID
    const sessIdItem = makeEl("div", "detail-item");
    sessIdItem.append(makeEl("span", "detail-label", "SESSION ID"));
    const sessIdRow = makeEl("div", "detail-value-row");
    sessIdRow.append(makeEl("code", null, selectedSessionTuple.session_id));
    const copyBtn = makeEl("button", "copy-button", "Copy");
    copyBtn.type = "button";
    copyBtn.addEventListener("click", () => {
      navigator.clipboard?.writeText(selectedSessionTuple.session_id);
      copyBtn.textContent = "Copied!";
      setTimeout(() => { copyBtn.textContent = "Copy"; }, 1500);
    });
    sessIdRow.append(copyBtn);
    sessIdItem.append(sessIdRow);

    // Model
    const modelItem = makeEl("div", "detail-item");
    modelItem.append(makeEl("span", "detail-label", "MODEL"));
    modelItem.append(makeEl("code", null, summary.model || summary.model_id || "—"));

    // State
    const stateItem = makeEl("div", "detail-item");
    stateItem.append(makeEl("span", "detail-label", "STATUS"));
    const rawState = String(summary.state || summary.status || "active");
    const stateClass = rawState.toLowerCase().replace(/[^a-z0-9_-]/g, "-");
    stateItem.append(makeEl("span", `status-badge ${stateClass}`, rawState));

    // Context utilization
    const utilItem = makeEl("div", "detail-item");
    utilItem.append(makeEl("span", "detail-label", "CONTEXT UTILIZATION"));
    let utilVal = "—";
    const contextSamples = Array.isArray(detail.context_utilization) ? detail.context_utilization : [];
    const latestMeasuredContext = [...contextSamples].reverse().find((sample) =>
      sample && sample.status === "observed" && Number.isFinite(sample.utilization_percent)
    );
    if (latestMeasuredContext) utilVal = `${latestMeasuredContext.utilization_percent.toFixed(1)}%`;
    else if (typeof detail.context_utilization === "number") {
      utilVal = `${(detail.context_utilization * 100).toFixed(1)}%`;
    } else if (detail.context_utilization && typeof detail.context_utilization.utilization_ratio === "number") {
      utilVal = `${(detail.context_utilization.utilization_ratio * 100).toFixed(1)}%`;
    } else if (detail.context_utilization && typeof detail.context_utilization.ratio === "number") {
      utilVal = `${(detail.context_utilization.ratio * 100).toFixed(1)}%`;
    }
    utilItem.append(makeEl("code", null, utilVal));

    // Tokens
    const tokItem = makeEl("div", "detail-item");
    tokItem.append(makeEl("span", "detail-label", "TOKENS"));
    tokItem.append(makeEl("code", null, formatCumulativeTokens(summary)));

    // Provider Instance
    const provItem = makeEl("div", "detail-item");
    provItem.append(makeEl("span", "detail-label", "PROVIDER INSTANCE"));
    provItem.append(makeEl("code", null, selectedSessionTuple.provider_instance_id || "—"));

    grid.append(sessIdItem, modelItem, stateItem, utilItem, tokItem, provItem);
    overviewCard.append(grid);
    contentEl.append(overviewCard);

    // 2. Hardware Section
    const hwCard = makeEl("section", "monitor-card hardware-card");
    hwCard.id = "monitor-detail-hardware";
    const hwHead = makeEl("div", "card-header");
    hwHead.append(makeEl("h3", null, "Hardware Metrics"));
    hwCard.append(hwHead);
    const hwBody = makeEl("div", "card-body");
    renderHardwareContent(hwBody);
    hwCard.append(hwBody);
    contentEl.append(hwCard);

    // 3. Alerts Section
    const alertsCard = makeEl("section", "monitor-card alerts-card");
    alertsCard.id = "monitor-detail-alerts";
    const alertsHead = makeEl("div", "card-header");
    alertsHead.append(makeEl("h3", null, "Active Alerts"));
    alertsCard.append(alertsHead);
    const alertsBody = makeEl("div", "card-body");
    alertsBody.id = "monitor-alerts-list";
    alertsBody.append(makeEl("p", "muted", "Checking persisted alerts…"));
    alertsCard.append(alertsBody);
    contentEl.append(alertsCard);

    // 4. Timeline Section
    const timelineCard = makeEl("section", "monitor-card timeline-card");
    timelineCard.id = "monitor-detail-timeline";
    const tlHead = makeEl("div", "card-header");
    tlHead.append(makeEl("h3", null, "Chronological Event Timeline"));
    timelineCard.append(tlHead);
    const tlBody = makeEl("div", "card-body");
    tlBody.id = "monitor-timeline-list";
    timelineCard.append(tlBody);
    contentEl.append(timelineCard);

    renderTimelineSection();
  }

  function renderHardwareContent(targetEl) {
    targetEl.replaceChildren();
    const hw = (snapshotData && snapshotData.hardware) || null;
    if (!hw || !Array.isArray(hw.devices) || hw.devices.length === 0) {
      targetEl.append(makeEl("p", "muted", "Point-in-time hardware telemetry unavailable or not configured."));
      return;
    }

    const grid = makeEl("div", "hardware-grid");
    for (const dev of hw.devices) {
      if (!dev) continue;
      const devCard = makeEl("div", "hardware-device-box");
      devCard.append(makeEl("strong", "device-name", dev.name || "GPU Device"));

      const metricsList = makeEl("ul", "device-metrics-list");

      if (dev.vram_used_bytes != null && dev.vram_total_bytes != null) {
        const usedGb = (dev.vram_used_bytes / (1024 ** 3)).toFixed(1);
        const totalGb = (dev.vram_total_bytes / (1024 ** 3)).toFixed(1);
        const li = makeEl("li", null, `VRAM: ${usedGb} / ${totalGb} GB`);
        metricsList.append(li);
      }

      const util = dev.utilization_pct != null ? dev.utilization_pct : dev.gpu_utilization_percent;
      if (util != null) {
        const li = makeEl("li", null, `Utilization: ${util}%`);
        metricsList.append(li);
      }

      const temp = dev.temperature_c != null ? dev.temperature_c : dev.temperature_celsius;
      if (temp != null) {
        const li = makeEl("li", null, `Temperature: ${temp}°C`);
        metricsList.append(li);
      }

      devCard.append(metricsList);
      grid.append(devCard);
    }
    targetEl.append(grid);
  }

  function renderAlertsSection(alerts, availability = "available") {
    const alertsBody = document.getElementById("monitor-alerts-list");
    if (!alertsBody) return;
    alertsBody.replaceChildren();

    if (!Array.isArray(alerts) || alerts.length === 0) {
      const message = availability === "unavailable"
        ? "Persisted alerts are unavailable; system health is unknown."
        : "No persisted alert records for this session; system health is unknown.";
      alertsBody.append(makeEl("p", "muted", message));
      return;
    }

    const list = makeEl("ul", "alerts-list");
    for (const alert of alerts) {
      const rawSev = String(alert.severity || "info");
      const sevClass = rawSev.toLowerCase().replace(/[^a-z0-9_-]/g, "-");
      const item = makeEl("li", `alert-item severity-${sevClass}`);
      const head = makeEl("div", "alert-head");
      head.append(
        makeEl("span", "alert-severity", (alert.severity || "INFO").toUpperCase()),
        makeEl("time", "alert-time", formatTimestamp(alert.timestamp || alert.created_at))
      );
      const msg = makeEl("p", "alert-message", alert.message || alert.title || "Alert triggered");
      item.append(head, msg);
      list.append(item);
    }
    alertsBody.append(list);
  }

  function renderTimelineSection() {
    const tlBody = document.getElementById("monitor-timeline-list");
    if (!tlBody) return;
    tlBody.replaceChildren();

    if (selectedTimelineEvents.length === 0) {
      tlBody.append(makeEl("p", "muted", timelineLoading ? "Loading timeline events…" : "No historical events recorded for this session."));
      return;
    }

    const list = makeEl("ol", "timeline-event-list");
    for (const evt of selectedTimelineEvents) {
      if (!evt) continue;
      const li = makeEl("li", "timeline-event-item");

      const head = makeEl("div", "event-header");
      const eventType = evt.event_type || evt.type || "event";
      head.append(
        makeEl("span", "event-type-pill", eventType),
        makeEl("time", "event-time", formatTimestamp(evt.timestamp || evt.created_at))
      );

      const body = makeEl("div", "event-body");
      const summaryText = typeof evt.summary === "string" ? evt.summary : (
        typeof evt.message === "string" ? evt.message : (
          evt.data ? JSON.stringify(evt.data) : ""
        )
      );
      if (summaryText) {
        body.append(makeEl("p", "event-summary", summaryText));
      }

      li.append(head, body);
      list.append(li);
    }
    tlBody.append(list);

    if (timelineNextCursor) {
      const paginationBox = makeEl("div", "timeline-pagination");
      const loadMoreBtn = makeEl("button", "primary-button compact", timelineLoading ? "Loading…" : "Load More Events");
      loadMoreBtn.type = "button";
      loadMoreBtn.disabled = timelineLoading;
      loadMoreBtn.addEventListener("click", () => {
        if (!timelineLoading && selectedSessionTuple) {
          fetchTimelinePage(
            selectedSessionTuple.provider_instance_id,
            selectedSessionTuple.session_id,
            timelineNextCursor,
            requestGeneration,
            detailAbortController?.signal
          );
        }
      });
      paginationBox.append(loadMoreBtn);
      tlBody.append(paginationBox);
    }
  }

  async function pollSnapshot() {
    if (!isVisible || isPolling || !api) return;
    if (monitorStatus && monitorStatus.availability === "disabled") return;

    isPolling = true;
    abortController = new AbortController();

    try {
      const res = await api("/api/llm-monitor/v1/snapshot", { signal: abortController.signal });
      const data = await res.json();
      snapshotData = data.snapshot || data;

      if (data.availability && monitorStatus) {
        monitorStatus.availability = data.availability;
        const badge = document.getElementById("monitor-status-pill");
        if (badge) {
          const newBadge = renderStatusBadge(monitorStatus);
          badge.className = newBadge.className;
          badge.textContent = newBadge.textContent;
        }
      }

      updateHeaderStats();
      updateSessionList();

      if (selectedSessionTuple) {
        const hwEl = document.getElementById("monitor-detail-hardware");
        if (hwEl) {
          const hwBody = hwEl.querySelector(".card-body");
          if (hwBody) renderHardwareContent(hwBody);
        }
      }
    } catch (err) {
      if (abortController && !abortController.signal.aborted) {
        if (err && err.message === "locked") {
          globalThis.showLogin?.("Session expired. Enter the current terminal login code again.");
          return;
        }
      }
    } finally {
      isPolling = false;
      if (isVisible && (!monitorStatus || monitorStatus.availability !== "disabled")) {
        pollTimer = setTimeout(pollSnapshot, pollIntervalMs);
      }
    }
  }

  async function initStatus() {
    try {
      const res = await api("/api/llm-monitor/v1/status");
      monitorStatus = await res.json();
      if (monitorStatus.refresh_interval_seconds && typeof monitorStatus.refresh_interval_seconds === "number") {
        pollIntervalMs = Math.max(2000, monitorStatus.refresh_interval_seconds * 1000);
      }
      const badge = document.getElementById("monitor-status-pill");
      if (badge) {
        const newBadge = renderStatusBadge(monitorStatus);
        badge.className = newBadge.className;
        badge.textContent = newBadge.textContent;
      }
      updateHeaderStats();
      updateSessionList();
    } catch (err) {
      if (err && err.message === "locked") {
        globalThis.showLogin?.("Session expired. Enter the current terminal login code again.");
      }
    }
  }

  function start(targetContainer, apiHelper) {
    if (!targetContainer || !apiHelper) return;
    container = targetContainer;
    api = apiHelper;

    container.replaceChildren();
    container.classList.add("llm-monitor-workspace");

    const header = renderHeader();
    const layout = makeEl("div", "monitor-layout");
    const sidebar = renderSidebar();
    const main = renderMain();

    layout.append(sidebar, main);
    container.append(header, layout);

    initStatus().then(() => {
      if (isVisible) {
        pollSnapshot();
      }
    });
  }

  function stop() {
    isVisible = false;
    isPolling = false;
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    if (detailAbortController) {
      detailAbortController.abort();
      detailAbortController = null;
    }
    requestGeneration++;
    selectedSessionTuple = null;
    selectedDetail = null;
    selectedTimelineEvents = [];
    timelineNextCursor = null;
    snapshotData = null;
    monitorStatus = null;

    if (container) {
      container.replaceChildren();
    }
  }

  function onVisibilityChange(visible) {
    const nextVisible = Boolean(visible);
    if (isVisible === nextVisible) return;
    isVisible = nextVisible;

    if (isVisible) {
      if (pollTimer) clearTimeout(pollTimer);
      pollSnapshot();
    } else {
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
      if (detailAbortController) {
        detailAbortController.abort();
        detailAbortController = null;
      }
    }
  }

  function getStatus() {
    return monitorStatus;
  }

  function getSelectedSession() {
    return selectedSessionTuple ? { ...selectedSessionTuple } : null;
  }

  globalThis.RunmuxLLMMonitor = Object.freeze({
    start,
    stop,
    onVisibilityChange,
    getStatus,
    getSelectedSession,
    selectSession,
  });
})();
