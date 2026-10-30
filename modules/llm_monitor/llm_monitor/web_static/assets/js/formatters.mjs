import { isActive } from "./state.mjs";

export function safeCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? new Intl.NumberFormat().format(value) : "—";
}

export function average(values) {
  const valid = values.filter((value) => Number.isFinite(value) && value >= 0);
  return valid.length ? { value: valid.reduce((sum, value) => sum + value, 0) / valid.length, samples: valid.length } : null;
}

export function durationSeconds(request, now = Date.now()) {
  const start = Date.parse(request.started_at || "");
  const end = Date.parse(request.ended_at || "");
  if (!Number.isFinite(start)) return null;
  if (Number.isFinite(end)) return Math.max(0, (end - start) / 1000);
  if (isActive(request.state)) return Math.max(0, (now - start) / 1000);
  return null;
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.floor(seconds % 60)}s`;
}

export function formatTimestamp(value) {
  const date = new Date(value || "");
  return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString([], { dateStyle: "medium", timeStyle: "medium" });
}

export function stateLabel(state) {
  const value = String(state || "unknown").toLowerCase();
  return ({ active: "Generating", running: "Generating", generating: "Generating", queued: "Queued", completed: "Complete", complete: "Complete", failed: "Failed", cancelled: "Cancelled", canceled: "Cancelled", observed: "Observed" })[value] || "Unknown";
}

export function capabilityLabel(value) {
  const state = typeof value === "string" ? value : value?.state;
  return ({ available: "Available", streaming: "Streaming", completion_only: "Completion only", rendered_only: "Rendered only", partial: "Partial", unavailable: "Unavailable" })[state] || "Unavailable";
}

export function tokenMetric(request, field) {
  const value = request?.[field];
  const source = request?.[`${field}_source`] || request?.usage_source || request?.coverage?.token_usage || "source_unspecified";
  if (!Number.isSafeInteger(value) || value < 0) return { value: "—", source: "unavailable" };
  return { value: source === "estimated" ? `~${safeCount(value)}` : safeCount(value), source };
}

export function aggregateSummary(requests, captureState, selectedModelId = "all") {
  const subset = requests.filter((request) => selectedModelId === "all" || (request.model_instance_id || request.provider_model_id) === selectedModelId);
  if (captureState === "unavailable" && subset.length === 0) {
    return { requestCount: "—", requestNote: "No request source connected", input: null, reasoning: null, output: null, duration: null };
  }
  const completed = subset.filter((request) => ["completed", "complete"].includes(String(request.state).toLowerCase()));
  const measured = (field) => average(completed.filter((request) => tokenMetric(request, field).source === "provider_reported").map((request) => request[field]));
  return {
    requestCount: captureState === "unavailable" ? "—" : safeCount(subset.length),
    requestNote: captureState === "unavailable" ? "Request history unavailable" : `${subset.length} observed requests · in-memory window`,
    input: measured("input_tokens"),
    reasoning: average(completed.filter((request) => tokenMetric(request, "reasoning_tokens").source === "provider_reported").map((request) => request.reasoning_tokens)),
    output: measured("output_tokens"),
    duration: average(completed.map((request) => durationSeconds(request)).filter((value) => value !== null)),
  };
}
