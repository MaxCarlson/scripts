const API_ROOT = "/api/inference/v1";

export class ApiError extends Error {
  constructor(message, { status = 0 } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function loginWithCode(code) {
  const response = await fetch("/auth/login", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!response.ok) throw new ApiError("The login code was not accepted.", { status: response.status });
}

export async function logout() {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
}

export async function fetchSnapshot(signal) {
  const [status, servers, models, requestResult] = await Promise.all([
    getJson(`${API_ROOT}/status`, signal),
    getJson(`${API_ROOT}/servers`, signal),
    getJson(`${API_ROOT}/models`, signal),
    getJson(`${API_ROOT}/requests`, signal),
  ]);
  return { status, servers, models, requestResult };
}

export async function fetchHistory(params = {}, signal) {
  const query = new URLSearchParams();
  if (params.limit) query.set("limit", String(params.limit));
  if (params.offset) query.set("offset", String(params.offset));
  if (params.model_id && params.model_id !== "all") query.set("model_id", params.model_id);
  if (params.state && params.state !== "all") query.set("state", params.state);
  if (params.since) query.set("since", params.since);
  if (params.until) query.set("until", params.until);
  const qs = query.toString();
  const path = qs ? `${API_ROOT}/history?${qs}` : `${API_ROOT}/history`;
  return getJson(path, signal);
}

export async function fetchHistoryDetail(requestId, signal) {
  const encoded = encodeURIComponent(requestId);
  const result = await getJson(`${API_ROOT}/history/${encoded}`, signal);
  return result.request || null;
}

export async function fetchHistoryAnalytics(params = {}, signal) {
  const query = new URLSearchParams();
  if (params.server_instance_id) query.set("server_instance_id", params.server_instance_id);
  if (params.model_id && params.model_id !== "all") query.set("model_id", params.model_id);
  if (params.window_seconds) query.set("window_seconds", String(params.window_seconds));
  const qs = query.toString();
  const path = qs ? `${API_ROOT}/history/analytics?${qs}` : `${API_ROOT}/history/analytics`;
  return getJson(path, signal);
}

export async function fetchRecordingStatus(signal) {
  const result = await getJson(`${API_ROOT}/recording/status`, signal);
  return result.recording || null;
}

export async function fetchRequest(requestId, signal) {
  const encoded = encodeURIComponent(requestId);
  const result = await getJson(`${API_ROOT}/requests/${encoded}`, signal);
  return result.request || null;
}

async function getJson(path, signal) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("The local monitor API could not be reached.");
  }
  if (response.status === 401) throw new ApiError("The browser session has expired.", { status: 401 });
  if (!response.ok) throw new ApiError("The local monitor API returned an error.", { status: response.status });
  try {
    return await response.json();
  } catch {
    throw new ApiError("The local monitor API returned invalid JSON.", { status: response.status });
  }
}
