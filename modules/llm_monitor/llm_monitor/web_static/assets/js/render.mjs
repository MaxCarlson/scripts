import { aggregateSummary, capabilityLabel, durationSeconds, formatDuration, formatTimestamp, safeCount, stateLabel, tokenMetric } from "./formatters.mjs";
import { isActive, requestKey, selectedRequest, visibleRequests } from "./state.mjs";
import { TranscriptView } from "./transcript.mjs";

const CAPABILITY_LABELS = {
  model_inventory: "Model inventory",
  aggregate_metrics: "Aggregate metrics",
  request_lifecycle: "Request lifecycle",
  structured_input: "Structured input",
  reasoning_text: "Reasoning stream",
  output_text: "Output stream",
  token_usage: "Token usage",
  request_timing: "Request timing",
  gpu_samples: "GPU samples",
  historical_content: "Historical content",
};

export function createRenderer() {
  const transcript = new TranscriptView(byId("transcript-content"));
  let lastSelectedKey = null;
  return {
    render(state) {
      renderHeader(state);
      renderSidebar(state);
      renderToolbar(state);
      renderKpis(state);
      renderRequestList(state);
      renderInspector(state, transcript, lastSelectedKey);
      lastSelectedKey = state.selectedRequestKey;
      renderGpu(state);
      renderCapabilities(state);
      renderModelCards(state);
      renderPage(state);
    },
    renderRequestEvent(state, event) {
      const key = requestKey(event.request || event);
      const lifecycle = ["request.started", "request.observed", "request.updated", "request.completed", "request.failed", "request.cancelled", "usage.reported", "telemetry.gap", "stream.interrupted"].includes(event.type);
      if (lifecycle) {
        renderHeader(state);
        renderKpis(state);
        renderRequestList(state);
      }
      if (key === state.selectedRequestKey || lastSelectedKey !== state.selectedRequestKey) {
        renderInspector(state, transcript, lastSelectedKey);
        lastSelectedKey = state.selectedRequestKey;
      }
    },
  };
}

function renderHeader(state) {
  const connected = state.servers.filter((server) => server.connection_state === "connected").length;
  const total = state.servers.length;
  const availability = state.transportStatus !== "connected" ? "degraded" : total === 0 ? "unavailable" : connected === total ? "connected" : connected > 0 ? "degraded" : "disconnected";
  const serverStatus = byId("server-status");
  serverStatus.dataset.state = availability;
  const statusText = state.transportStatus !== "connected" ? "Monitor API unavailable" : total === 0 ? "No server found" : connected === total ? "Server connected" : connected > 0 ? "Server degraded" : "Server disconnected";
  replaceText(serverStatus.querySelector("span:last-child"), statusText);
  text("server-count", state.transportStatus === "connected" ? `${connected}/${total} servers` : `${total} servers · stale`);
  text("sidebar-server-count", total ? String(total) : "0");
  text("refresh-time", state.status?.refreshed_at ? `Updated ${new Date(state.status.refreshed_at).toLocaleTimeString()}` : "Waiting for inventory");
  const recording = state.status?.recording || {};
  const metadata = recording.metadata === true;
  const content = recording.content === true;
  const recordStatus = metadata ? content ? "Recording content" : "Recording metadata" : "Recording off";
  text("header-recording", recordStatus);
  text("recording-status", `Metadata recording: ${metadata ? "enabled" : "disabled"} · Content recording: ${content ? "enabled" : "disabled"}`);
  text("sidebar-metadata-recording", `Metadata recording ${metadata ? "on" : "off"}`);
  text("sidebar-content-recording", `Content recording ${content ? "on" : "off"}`);
  const activeCount = state.requests.filter((request) => isActive(request.state)).length;
  const requestCount = byId("active-request-count");
  requestCount.hidden = activeCount === 0;
  requestCount.textContent = String(activeCount);
  const synthetic = state.requests.some((request) => request.source === "synthetic_fixture");
  byId("synthetic-badge").hidden = !synthetic;
}

function renderSidebar(state) {
  const list = byId("server-list");
  const focusedServer = document.activeElement?.dataset?.serverId;
  const oldButtons = new Map(Array.from(list.querySelectorAll("button[data-server-id]"), (button) => [button.dataset.serverId, button]));
  if (!state.servers.length) {
    list.replaceChildren(make("li", "sidebar-empty", "No local servers discovered"));
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const server of state.servers) {
    const id = server.server_instance_id || server.endpoint_id || "unknown-server";
    const button = oldButtons.get(id) || make("button", "server-item");
    button.type = "button";
    button.dataset.serverId = id;
    button.setAttribute("aria-pressed", String(state.selectedServerId === id));
    button.replaceChildren();
    const nameLine = make("span", "server-name-line");
    const indicator = make("span", "server-indicator");
    indicator.dataset.state = server.stale ? "stale" : server.connection_state || "unavailable";
    const provider = make("span", "", providerLabel(server.provider_type));
    nameLine.append(indicator, provider);
    button.append(nameLine, make("span", "server-endpoint", server.endpoint || "Endpoint unavailable"));
    const loaded = state.models.filter((model) => model.server_instance_id === id && model.state === "loaded").length;
    button.append(make("span", "server-meta", `${loaded} loaded model entries · ${server.stale ? "stale observation" : connectionLabel(server.connection_state)}`));
    fragment.append(button);
  }
  list.replaceChildren(fragment);
  if (focusedServer) list.querySelector(`[data-server-id="${CSS.escape(focusedServer)}"]`)?.focus({ preventScroll: true });
}

function renderToolbar(state) {
  const select = byId("model-filter");
  const current = state.selectedModelId;
  const options = [makeOption("all", "All monitored models")];
  for (const model of state.models) {
    const id = model.model_instance_id || model.provider_model_id;
    if (!id) continue;
    const suffix = model.state === "loaded" ? " · loaded" : " · not loaded";
    options.push(makeOption(id, `${model.name || model.provider_model_id || "Unknown model"}${suffix}`));
  }
  select.replaceChildren(...options);
  select.value = options.some((option) => option.value === current) ? current : "all";
  const auto = byId("follow-toggle");
  auto.classList.toggle("is-enabled", state.autoFollow);
  auto.setAttribute("aria-pressed", String(state.autoFollow));
  replaceText(auto.lastChild, state.autoFollow ? "Following live" : "Follow paused");
  const requestsPage = state.page === "requests";
  byId("reasoning-visible").checked = state.reasoningVisible;
  byId("transcript-follow").checked = state.transcriptFollow;
  text("page-title", requestsPage ? "Request stream" : "Local model activity");
  text("page-description", requestsPage ? "Search and inspect observed inference requests." : "Live requests, captured content, and model performance.");
  text("page-breadcrumb", requestsPage ? "REQUESTS" : "OVERVIEW");
  byId("kpi-grid").hidden = requestsPage;
  byId("bottom-grid").hidden = requestsPage;
}

function renderKpis(state) {
  const summary = aggregateSummary(state.requests, state.captureState, state.selectedModelId);
  text("kpi-requests", summary.requestCount);
  text("kpi-requests-note", summary.requestNote);
  setAverage("input", summary.input, "tokens");
  setAverage("reasoning", summary.reasoning, "reported samples");
  setAverage("output", summary.output, "tokens");
  if (summary.duration) {
    text("kpi-duration", formatDuration(summary.duration.value));
    text("kpi-duration-note", `Observed lifecycle · n=${summary.duration.samples}`);
  } else {
    text("kpi-duration", "—");
    text("kpi-duration-note", "Observed request lifecycle");
  }
  text("kpi-gpu", "—");
  const gpuSamples = Array.isArray(state.status?.hardware_samples) ? state.status.hardware_samples.map((sample) => sample.gpu_utilization_percent).filter((value) => Number.isFinite(value) && value >= 0 && value <= 100) : [];
  if (gpuSamples.length) {
    text("kpi-gpu", `${(gpuSamples.reduce((sum, value) => sum + value, 0) / gpuSamples.length).toFixed(1)}%`);
    text("kpi-gpu-note", `Device average · not per-request · n=${gpuSamples.length}`);
  } else text("kpi-gpu-note", "Device-level samples unavailable");
}

function setAverage(name, metric, unit) {
  text(`kpi-${name}`, metric ? Math.round(metric.value).toLocaleString() : "—");
  const noteId = `kpi-${name}-note`;
  text(noteId, metric ? `${unit} · n=${metric.samples}` : name === "reasoning" ? "Reported observations only" : "Reported completed requests");
}

function renderRequestList(state) {
  const requests = visibleRequests(state);
  const list = byId("request-list");
  const oldScrollTop = list.scrollTop;
  const focusedRequest = document.activeElement?.dataset?.requestKey;
  const shown = requests.slice(0, state.requestLimit);
  const fragment = document.createDocumentFragment();
  if (!requests.length) {
    const inventoryAvailable = state.status?.capabilities?.model_inventory?.state === "available";
    const captureUnavailable = state.captureState === "unavailable";
    const title = state.search || state.statusFilter !== "all" || state.selectedModelId !== "all" || state.selectedServerId !== "all"
      ? "No requests match these filters" : captureUnavailable && inventoryAvailable ? "No individual requests captured" : captureUnavailable ? "No inference server discovered" : "No requests observed";
    const detail = state.search || state.statusFilter !== "all" ? "Adjust search or filters to see other observed requests." : captureUnavailable && inventoryAvailable ? "Model inventory is available, but no supported request source is connected." : captureUnavailable ? "No model inventory or request source is available yet." : "Requests will appear here when an observation source reports them.";
    const empty = make("div", "request-empty");
    empty.append(make("span", "empty-symbol", "≋"), make("strong", "", title), make("p", "", detail));
    fragment.append(empty);
  } else {
    for (const request of shown) fragment.append(renderRequestRow(request, state));
  }
  list.replaceChildren(fragment);
  list.scrollTop = oldScrollTop;
  if (focusedRequest) list.querySelector(`[data-request-key="${CSS.escape(focusedRequest)}"]`)?.focus({ preventScroll: true });
  text("request-count", state.requestAvailability === "unavailable" || state.captureState === "unavailable" ? "Unavailable" : `${shown.length} of ${requests.length}`);
  text("request-list-status", state.captureState === "unavailable" ? "Request capture unavailable" : `${state.requests.length} in memory`);
  const clear = byId("clear-search");
  clear.hidden = !(state.search || state.statusFilter !== "all" || state.timeRange !== "all" || state.selectedModelId !== "all" || state.selectedServerId !== "all");
  const loadMore = byId("load-more-requests");
  loadMore.hidden = requests.length <= shown.length;
  loadMore.textContent = `Show ${Math.min(100, requests.length - shown.length)} more`;
  const active = state.captureState === "unavailable" ? "Unavailable" : "Observing";
  text("request-source-note", active === "Unavailable" ? "Individual request source unavailable" : `${active} · newest first`);
  document.querySelectorAll("[data-request-count]").forEach((node) => { node.textContent = state.captureState === "unavailable" ? "—" : String(state.requests.length); });
}

function renderRequestRow(request, state) {
  const key = requestKey(request);
  const row = make("button", "request-row");
  row.type = "button";
  row.role = "option";
  row.dataset.requestKey = key;
  row.setAttribute("aria-selected", String(key === state.selectedRequestKey));
  const top = make("span", "request-row-top");
  top.append(make("span", "request-id", shortId(request.request_id)), stateBadge(request.state, "request-state"));
  const preview = make("span", "request-preview", previewText(request));
  const bottom = make("span", "request-row-bottom");
  const metadata = make("span", "request-row-meta");
  metadata.append(make("span", "", formatShortTime(request.started_at)), make("span", "mono", `in ${safeCount(request.input_tokens)}`));
  if (request.coverage?.reasoning_text && request.coverage.reasoning_text !== "unavailable") metadata.append(make("span", "availability-mark", "Reasoning"));
  bottom.append(metadata, make("span", "mono", formatDuration(durationSeconds(request))));
  row.append(top, preview, bottom);
  return row;
}

function renderInspector(state, transcript, previousKey) {
  const request = selectedRequest(state);
  const empty = byId("inspector-content");
  const detail = byId("inspector-detail");
  empty.hidden = Boolean(request);
  detail.hidden = !request;
  byId("return-live").hidden = !request || state.autoFollow;
  if (!request) {
    transcript.clear("Transcript content is unavailable until a request is selected.");
    renderTabs(state.selectedTab, null);
    return;
  }
  const key = requestKey(request);
  text("inspector-heading-detail", shortId(request.request_id, 32));
  renderStateBadge("inspector-state", request.state);
  text("inspector-model", request.model_name || request.provider_model_id || "Model identity unavailable");
  text("inspector-started", formatTimestamp(request.started_at));
  text("inspector-source", sourceLabel(request.source));
  byId("inspector-gap").hidden = request.stream_gap !== true;
  setTokenMetric("detail-input", request, "input_tokens");
  setTokenMetric("detail-reasoning", request, "reasoning_tokens");
  text("detail-input-source", sourceLabel(tokenMetric(request, "input_tokens").source));
  text("detail-reasoning-source", tokenMetric(request, "reasoning_tokens").source.replaceAll("_", " "));
  setTokenMetric("detail-output", request, "output_tokens");
  text("detail-output-source", sourceLabel(tokenMetric(request, "output_tokens").source));
  text("detail-duration", formatDuration(durationSeconds(request)));
  text("detail-gpu", "—");
  const copy = byId("copy-request-id");
  copy.dataset.requestId = request.request_id;
  const transcriptContent = byId("transcript-content");
  if (key !== previousKey) transcriptContent.scrollTop = 0;
  transcript.update(request, { reasoningVisible: state.reasoningVisible, search: state.transcriptSearch, follow: state.transcriptFollow && isActive(request.state) });
  renderTabs(state.selectedTab, request);
}

function renderTabs(selected, request) {
  for (const tab of document.querySelectorAll(".inspector-tab")) {
    const active = tab.dataset.tab === selected;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  }
  for (const panel of document.querySelectorAll("[data-panel]")) panel.hidden = !request || panel.dataset.panel !== selected;
  if (selected === "telemetry" && request) renderTelemetry(request);
  if (selected === "timeline" && request) renderTimeline(request);
}

function renderTelemetry(request) {
  const metrics = [
    ["End-to-end duration", durationSeconds(request), "s", "observed lifecycle"],
    ["Time to first text", request.time_to_first_text_seconds, "s", request.time_to_first_text_source || "unavailable"],
    ["Queue duration", request.queue_seconds, "s", request.queue_source || "unavailable"],
    ["Prefill duration", request.prefill_seconds, "s", request.prefill_source || "unavailable"],
    ["Decode duration", request.decode_seconds, "s", request.decode_source || "unavailable"],
    ["Generation speed", request.generation_tokens_per_second, "tok/s", request.generation_speed_source || "unavailable"],
    ["Input tokens", request.input_tokens, "tokens", tokenMetric(request, "input_tokens").source, "input_tokens"],
    ["Reasoning tokens", request.reasoning_tokens, "tokens", tokenMetric(request, "reasoning_tokens").source, "reasoning_tokens"],
    ["Output tokens", request.output_tokens, "tokens", tokenMetric(request, "output_tokens").source, "output_tokens"],
    ["Cached input", request.cached_input_tokens, "tokens", request.cached_input_source || "unavailable"],
    ["Average GPU", request.gpu_average_percent, "%", request.gpu_scope || "unavailable"],
    ["Peak VRAM", request.gpu_peak_vram_bytes, "bytes", request.gpu_scope || "unavailable"],
  ];
  const grid = byId("telemetry-grid");
  grid.replaceChildren(...metrics.map(([label, value, unit, provenance, field]) => {
    const item = make("div", "telemetry-item");
    const display = field ? tokenMetric(request, field).value : formatMetric(value, unit);
    item.append(make("span", "", label), make("strong", "", unit === "tokens" && display !== "—" ? `${display} tokens` : display), make("small", "", sourceLabel(provenance)));
    return item;
  }));
  const coverage = request.coverage || {};
  const coverText = Object.entries(coverage).map(([key, value]) => `${key.replaceAll("_", " ")}: ${capabilityLabel(value).toLowerCase()}`).join(" · ") || "Coverage metadata unavailable";
  text("telemetry-provenance", `Source: ${sourceLabel(request.source)} · Observed: ${formatTimestamp(request.started_at)} · ${coverText}`);
}

function renderTimeline(request) {
  const list = byId("event-timeline");
  const events = Array.isArray(request.events) ? [...request.events].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0)) : [];
  if (!events.length) {
    list.replaceChildren(make("li", "content-unavailable", "No request event timeline is available from this source."));
    return;
  }
  list.replaceChildren(...events.map((event) => {
    const item = make("li", "timeline-event");
    const time = make("time", "", formatRelative(event.timestamp, request.started_at));
    if (event.timestamp) time.dateTime = event.timestamp;
    const body = make("div", "");
    body.append(make("strong", "", eventLabel(event.type)), make("p", "", event.summary || event.message || "Event details unavailable"));
    item.append(time, body);
    return item;
  }));
}

function renderGpu(state) {
  const samples = Array.isArray(state.status?.hardware_samples) ? state.status.hardware_samples : [];
  const chart = byId("gpu-chart");
  if (!samples.length) {
    chart.setAttribute("aria-label", "GPU activity samples unavailable");
    chart.replaceChildren(make("p", "chart-empty", "GPU samples are unavailable from the current monitor sources."));
    text("gpu-device", "Unavailable");
    text("gpu-average", "—");
    text("gpu-vram", "—");
    return;
  }
  const width = 420;
  const height = 82;
  const points = samples.map((sample, index) => ({ sample, index, value: sample.gpu_utilization_percent, timestamp: Date.parse(sample.timestamp || "") })).filter((point) => Number.isFinite(point.value) && point.value >= 0 && point.value <= 100);
  const values = points.map((point) => point.value);
  if (!values.length) return;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "gpu-svg");
  svg.setAttribute("role", "presentation");
  for (const y of [25, 50, 75]) {
    const line = document.createElementNS(svg.namespaceURI, "line");
    line.setAttribute("x1", "0"); line.setAttribute("x2", String(width)); line.setAttribute("y1", String(height * (1 - y / 100))); line.setAttribute("y2", String(height * (1 - y / 100))); line.setAttribute("stroke", "#2b3545"); line.setAttribute("stroke-dasharray", "3 5");
    svg.append(line);
  }
  let segment = [];
  let previous = null;
  const drawSegment = () => {
    if (!segment.length) return;
    const coordinates = segment.map((point) => `${samples.length === 1 ? width / 2 : point.index * width / (samples.length - 1)},${height - (point.value / 100) * height}`);
    if (coordinates.length === 1) {
      const circle = document.createElementNS(svg.namespaceURI, "circle");
      const [cx, cy] = coordinates[0].split(",");
      circle.setAttribute("cx", cx); circle.setAttribute("cy", cy); circle.setAttribute("r", "2.5"); circle.setAttribute("fill", "#76baff"); svg.append(circle);
    } else {
      const line = document.createElementNS(svg.namespaceURI, "polyline");
      line.setAttribute("points", coordinates.join(" ")); line.setAttribute("fill", "none"); line.setAttribute("stroke", "#76baff"); line.setAttribute("stroke-width", "2"); line.setAttribute("vector-effect", "non-scaling-stroke"); svg.append(line);
    }
  };
  for (const sample of samples.map((item, index) => ({ item, index, value: item.gpu_utilization_percent, timestamp: Date.parse(item.timestamp || "") }))) {
    const valid = Number.isFinite(sample.value) && sample.value >= 0 && sample.value <= 100;
    const gap = previous && Number.isFinite(sample.timestamp) && Number.isFinite(previous.timestamp) && sample.timestamp - previous.timestamp > 5000;
    if (!valid || gap) { drawSegment(); segment = []; }
    if (valid) segment.push({ index: sample.index, value: sample.value });
    previous = sample;
  }
  drawSegment();
  const timeSamples = samples.filter((sample) => Number.isFinite(Date.parse(sample.timestamp || "")));
  const axis = document.createElementNS(svg.namespaceURI, "text");
  const startLabel = timeSamples[0] ? new Date(timeSamples[0].timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "Time unavailable";
  const endLabel = timeSamples.at(-1) ? new Date(timeSamples.at(-1).timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
  axis.setAttribute("x", "0"); axis.setAttribute("y", "101"); axis.setAttribute("fill", "#6d7a8d"); axis.setAttribute("font-size", "8");
  axis.textContent = endLabel ? `${startLabel} — ${endLabel}` : startLabel;
  svg.append(axis);
  chart.replaceChildren(svg);
  chart.setAttribute("aria-label", `GPU activity samples, ${values.length} observations`);
  text("gpu-device", samples[0].device_name || "Device samples");
  text("gpu-average", `${(values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1)}% · n=${values.length}`);
  const vram = [...samples].reverse().find((sample) => Number.isFinite(sample.vram_used_bytes) && Number.isFinite(sample.vram_total_bytes));
  text("gpu-vram", Number.isFinite(vram.vram_used_bytes) && Number.isFinite(vram.vram_total_bytes) ? `${formatBytes(vram.vram_used_bytes)} / ${formatBytes(vram.vram_total_bytes)}` : "—");
}

function renderCapabilities(state) {
  const capabilities = state.status?.capabilities || {};
  for (const item of document.querySelectorAll("[data-capability]")) {
    const name = item.dataset.capability;
    const value = capabilities[name];
    const stateValue = typeof value === "string" ? value : value?.state || "unavailable";
    item.textContent = capabilityLabel(stateValue);
    item.dataset.state = stateValue;
  }
  const requestState = capabilities.request_lifecycle?.state || state.captureState;
  text("coverage-summary", requestState === "unavailable" ? "Inventory only" : capabilityLabel(requestState));
}

function renderModelCards(state) {
  const root = byId("model-cards");
  if (!root) return;
  const focusedModel = document.activeElement?.dataset?.modelId;
  if (!state.models.length) {
    root.replaceChildren(make("section", "panel page-empty", "No model inventory is available."));
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const model of state.models) {
    const card = make("article", "model-card");
    const top = make("div", "model-card-header");
    const heading = make("div", "");
    heading.append(make("h2", "", model.name || model.provider_model_id || "Unknown model"), make("p", "", model.provider_model_id || "Provider model ID unavailable"));
    top.append(heading, make("span", `state-badge ${model.state === "loaded" ? "" : ""}`, model.state === "loaded" ? "Loaded" : model.state === "not-loaded" ? "Not loaded" : "Unknown"));
    card.append(top);
    const server = state.servers.find((item) => item.server_instance_id === model.server_instance_id);
    card.append(make("p", "", `${providerLabel(server?.provider_type)} · ${server?.endpoint || "Server unavailable"}`));
    const list = document.createElement("dl");
    const contexts = Array.isArray(model.loaded_context_lengths) && model.loaded_context_lengths.length ? model.loaded_context_lengths.join(" / ") : Number.isSafeInteger(model.context_length) ? model.context_length.toLocaleString() : "Unavailable";
    const modelRequests = state.requests.filter((request) => request.provider_model_id === model.provider_model_id || request.model_instance_id === model.model_instance_id).length;
    const requestCount = state.captureState === "unavailable" ? "Unavailable" : String(modelRequests);
    const rows = [["Quantization", model.quantization || "Unavailable"], ["Loaded context", contexts], ["Maximum context", Number.isSafeInteger(model.max_context_length) ? model.max_context_length.toLocaleString() : "Unavailable"], ["Loaded instances", Number.isSafeInteger(model.loaded_instance_count) ? model.loaded_instance_count : "Unavailable"], ["Observed requests", requestCount]];
    for (const [label, value] of rows) list.append(make("dt", "", label), make("dd", "", String(value)));
    card.append(list);
    const button = make("button", "button button-primary", "View requests");
    button.type = "button"; button.dataset.modelId = model.model_instance_id || model.provider_model_id; button.dataset.action = "filter-model";
    card.append(button);
    fragment.append(card);
  }
  root.replaceChildren(fragment);
  if (focusedModel) root.querySelector(`[data-model-id="${CSS.escape(focusedModel)}"]`)?.focus({ preventScroll: true });
}

function renderPage(state) {
  const activePage = state.page === "requests" ? "overview" : state.page;
  for (const page of document.querySelectorAll("[data-view]")) page.hidden = page.dataset.view !== activePage;
  for (const link of document.querySelectorAll("[data-page]")) {
    const active = link.dataset.page === state.page;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
}

function stateBadge(state, className = "state-badge") {
  const badge = make("span", className, stateLabel(state));
  badge.dataset.state = isActive(state) ? "active" : String(state || "unknown").toLowerCase();
  return badge;
}

function renderStateBadge(id, state) {
  const badge = byId(id);
  badge.textContent = stateLabel(state);
  badge.dataset.state = isActive(state) ? "active" : String(state || "unknown").toLowerCase();
}

function setTokenMetric(id, request, field) {
  text(id, tokenMetric(request, field).value);
}

function previewText(request) {
  const input = (request.content || []).find((item) => ["user", "system", "developer"].includes(item.kind) && item.text);
  if (input) return input.text.replace(/\s+/g, " ").trim();
  return request.coverage?.structured_input === "rendered_only" ? "Input rendered by observation source" : "Input unavailable · metadata-only observation";
}

function sourceLabel(source) {
  return String(source || "unavailable").replaceAll("_", " ");
}

function providerLabel(provider) {
  return provider ? String(provider).toUpperCase() : "Inference server";
}

function connectionLabel(state) {
  return ({ connected: "connected", unavailable: "disconnected", discovering: "discovering" })[state] || "unknown";
}

function shortId(id, length = 18) {
  const value = String(id || "request unavailable");
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function formatShortTime(value) {
  const date = new Date(value || "");
  return Number.isNaN(date.getTime()) ? "Time unknown" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatMetric(value, unit) {
  if (!Number.isFinite(value) || value < 0) return "Unavailable";
  const textValue = unit === "bytes" ? formatBytes(value) : Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  return unit === "s" ? `${textValue}s` : unit === "tok/s" ? `${textValue} tok/s` : unit === "bytes" ? textValue : `${textValue} ${unit}`;
}

function formatBytes(value) {
  if (!Number.isFinite(value) || value < 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = value, index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
  return `${amount.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatRelative(value, origin) {
  const timestamp = Date.parse(value || "");
  const start = Date.parse(origin || "");
  if (!Number.isFinite(timestamp)) return "Time unavailable";
  const absolute = new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return Number.isFinite(start) ? `+${((timestamp - start) / 1000).toFixed(2)}s · ${absolute}` : absolute;
}

function eventLabel(type) {
  return String(type || "event").replaceAll(".", " ").replaceAll("_", " ");
}

function make(tag, className = "", value = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined && value !== null) element.textContent = String(value);
  return element;
}

function makeOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function replaceText(node, value) {
  if (node) node.textContent = value;
}

function text(id, value) {
  const node = byId(id);
  if (node) node.textContent = value === undefined || value === null ? "—" : String(value);
}

function byId(id) {
  return document.getElementById(id);
}
