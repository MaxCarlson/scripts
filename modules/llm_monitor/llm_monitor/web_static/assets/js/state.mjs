const MAX_REQUESTS = 500;

export function createState() {
  return {
    page: "overview",
    transportStatus: "disconnected",
    status: null,
    servers: [],
    models: [],
    requests: [],
    requestAvailability: "unavailable",
    captureState: "unavailable",
    selectedRequestKey: null,
    selectedModelId: "all",
    selectedServerId: "all",
    selectedTab: "transcript",
    autoFollow: true,
    transcriptFollow: true,
    reasoningVisible: true,
    search: "",
    timeRange: "all",
    requestLimit: 100,
    transcriptSearch: "",
    statusFilter: "all",
    requestGap: false,
  };
}

export function requestKey(request) {
  return [request.server_instance_id || "unknown-server", request.model_instance_id || request.provider_model_id || "unknown-model", request.request_id || "unknown-request"].join("::");
}

export function mergeSnapshot(state, { status, servers, models, requestResult }) {
  const previous = new Map(state.requests.map((request) => [requestKey(request), request]));
  const incoming = Array.isArray(requestResult?.requests) ? requestResult.requests : [];
  const merged = incoming.map((request) => mergeRequest(previous.get(requestKey(request)), request));
  const requests = merged.sort(compareNewest).slice(0, MAX_REQUESTS);
  const selectedStillListed = requests.some((request) => requestKey(request) === state.selectedRequestKey);
  const selectedCached = previous.get(state.selectedRequestKey);
  if (!selectedStillListed && selectedCached && requests.length < MAX_REQUESTS) requests.push(selectedCached);

  const next = {
    ...state,
    status: status || state.status,
    transportStatus: "connected",
    servers: Array.isArray(servers?.servers) ? servers.servers : state.servers,
    models: Array.isArray(models?.models) ? models.models : state.models,
    requests,
    requestAvailability: requestResult?.availability || "unavailable",
    captureState: requestResult?.capture_state || "unavailable",
    requestGap: state.requestGap || requestResult?.gap === true,
  };
  const newest = newestRequest(visibleRequests(next));
  if (next.autoFollow && newest) next.selectedRequestKey = requestKey(newest);
  else if (!next.selectedRequestKey && newest) next.selectedRequestKey = requestKey(newest);
  return next;
}

export function selectRequest(state, key) {
  const request = state.requests.find((item) => requestKey(item) === key);
  if (!request) return state;
  const newest = newestRequest(state.requests);
  return {
    ...state,
    selectedRequestKey: key,
    autoFollow: Boolean(newest && requestKey(newest) === key && isActive(request.state)),
  };
}

export function followLatest(state) {
  const newest = newestRequest(visibleRequests(state));
  return { ...state, autoFollow: true, selectedRequestKey: newest ? requestKey(newest) : null };
}

export function applyRequestEvent(state, event) {
  if (!event || typeof event !== "object" || typeof event.type !== "string") return state;
  const identity = event.request || event;
  if (typeof identity.request_id !== "string" || !identity.request_id) return state;
  const key = requestKey(identity);
  const index = state.requests.findIndex((request) => requestKey(request) === key);
  let request = index >= 0 ? state.requests[index] : null;
  if (!request && event.type !== "request.started" && event.type !== "request.observed") return state;
  if (!request) request = { ...identity, request_id: identity.request_id, content: [], coverage: {}, last_sequence: null };

  const sequence = Number.isSafeInteger(event.sequence) && event.sequence >= 0 ? event.sequence : null;
  if (sequence !== null && request.last_sequence !== null && sequence <= request.last_sequence) return state;
  const hasGap = sequence !== null && request.last_sequence !== null && sequence > request.last_sequence + 1;
  let updated = { ...request, content: Array.isArray(request.content) ? [...request.content] : [], coverage: { ...(request.coverage || {}) } };
  if (hasGap || event.type === "telemetry.gap" || event.type === "stream.interrupted") updated = { ...updated, stream_gap: true };
  if (event.type === "stream.interrupted" && isActive(updated.state)) updated = { ...updated, state: "unknown" };

  if (event.type === "request.started" || event.type === "request.observed") {
    updated = { ...updated, ...identity, state: identity.state || "active" };
  } else if (event.type === "request.updated") {
    updated = { ...updated, ...(event.payload || {}) };
  } else if (event.type === "reasoning.delta" || event.type === "output.delta" || event.type === "tool_call.delta") {
    const kind = event.type === "reasoning.delta" ? "reasoning" : event.type === "tool_call.delta" ? "tool_call" : "assistant";
    const delta = typeof event.delta === "string" ? event.delta : "";
    if (delta) updated = appendContentDelta(updated, kind, event.role || "assistant", delta, sequence, event.timestamp);
  } else if (event.type === "usage.reported") {
    const usage = event.payload && typeof event.payload === "object" ? event.payload : {};
    updated = { ...updated, ...usage, usage_source: event.source || "provider_reported" };
  } else if (event.type === "request.completed" || event.type === "request.failed" || event.type === "request.cancelled") {
    updated = { ...updated, state: event.type.slice("request.".length), ended_at: event.timestamp || updated.ended_at, finish_reason: event.finish_reason || null };
  }
  if (sequence !== null) updated.last_sequence = sequence;

  const requests = [...state.requests];
  if (index >= 0) requests[index] = updated;
  else requests.unshift(updated);
  requests.sort(compareNewest);
  const next = { ...state, requests: requests.slice(0, MAX_REQUESTS), requestGap: state.requestGap || hasGap };
  if (state.autoFollow) {
    const latest = newestRequest(visibleRequests(next));
    if (latest) next.selectedRequestKey = requestKey(latest);
  }
  return next;
}

export function visibleRequests(state) {
  const query = state.search.trim().toLocaleLowerCase();
  return state.requests.filter((request) => {
    if (state.selectedModelId !== "all" && (request.model_instance_id || request.provider_model_id) !== state.selectedModelId) return false;
    if (state.selectedServerId !== "all" && request.server_instance_id !== state.selectedServerId) return false;
    if (state.timeRange !== "all") {
      const started = Date.parse(request.started_at || "");
      const windowMs = state.timeRange === "15m" ? 15 * 60_000 : state.timeRange === "1h" ? 60 * 60_000 : 24 * 60 * 60_000;
      if (!Number.isFinite(started) || Date.now() - started > windowMs || started > Date.now()) return false;
    }
    if (state.statusFilter === "active" && !isActive(request.state)) return false;
    if (state.statusFilter !== "all" && state.statusFilter !== "active" && request.state !== state.statusFilter) return false;
    if (!query) return true;
    const text = [request.request_id, request.provider_model_id, request.model_name, ...(request.content || []).map((segment) => segment.text || "")].join(" ").toLocaleLowerCase();
    return text.includes(query);
  });
}

export function selectedRequest(state) {
  return state.requests.find((request) => requestKey(request) === state.selectedRequestKey) || null;
}

export function isActive(value) {
  return ["active", "running", "queued", "generating", "in_progress"].includes(String(value || "").toLowerCase());
}

export function newestRequest(requests) {
  if (!requests.length) return null;
  return requests.find((request) => isActive(request.state)) || requests[0];
}

function mergeRequest(previous, incoming) {
  if (!previous) {
    const sequences = Array.isArray(incoming.events) ? incoming.events.map((event) => event.sequence).filter(Number.isSafeInteger) : [];
    return { ...incoming, content: Array.isArray(incoming.content) ? incoming.content.map((segment) => ({ ...segment })) : [], last_sequence: incoming.last_sequence ?? (sequences.length ? Math.max(...sequences) : null) };
  }
  const incomingContent = Array.isArray(incoming.content) ? incoming.content : [];
  const content = incomingContent.length ? mergeSegments(previous.content || [], incomingContent) : previous.content || [];
  return { ...previous, ...incoming, content, stream_gap: previous.stream_gap || incoming.stream_gap === true };
}

function mergeSegments(previous, incoming) {
  const byKey = new Map(previous.map((segment, index) => [segment.segment_id || `${segment.kind || "other"}:${segment.role || ""}:${segment.sequence ?? index}`, segment]));
  const incomingKeys = new Set();
  const merged = incoming.map((segment, index) => {
    const key = segment.segment_id || `${segment.kind || "other"}:${segment.role || ""}:${segment.sequence ?? index}`;
    incomingKeys.add(key);
    const old = byKey.get(key);
    if (!old || typeof segment.text !== "string" || segment.text.length >= (old.text || "").length) return { ...segment };
    return old;
  });
  for (const [key, segment] of byKey) {
    if (!incomingKeys.has(key) && segment.source === "stream_event") merged.push(segment);
  }
  return merged;
}

function appendContentDelta(request, kind, role, delta, sequence, timestamp) {
  const content = [...request.content];
  const last = content.at(-1);
  if (last && last.kind === kind && last.role === role && !last.truncated) {
    content[content.length - 1] = { ...last, text: `${last.text || ""}${delta}`, sequence: sequence ?? last.sequence, observed_at: timestamp || last.observed_at, streaming: true };
  } else {
    content.push({ kind, role, text: delta, sequence, observed_at: timestamp || null, streaming: true, source: "stream_event" });
  }
  return { ...request, content };
}

function compareNewest(a, b) {
  const aTime = Date.parse(a.started_at || "") || 0;
  const bTime = Date.parse(b.started_at || "") || 0;
  return bTime - aTime;
}
