import { fetchSnapshot, fetchHistory, fetchHistoryDetail, updateRecordingMode, loginWithCode, logout, ApiError } from "./api.mjs";
import { createRenderer } from "./render.mjs";
import { applyRequestEvent, createState, followLatest, requestKey, selectRequest, visibleRequests, mergeSnapshot } from "./state.mjs";
import { stateLabel } from "./formatters.mjs";

const PREF_KEY = "llm-monitor-ui-v1";
const REFRESH_MS = 2500;
const loginPanel = byId("login-panel");
const loginForm = byId("login-form");
const loginCode = byId("login-code");
const loginError = byId("login-error");
const dashboard = byId("dashboard");
const renderer = createRenderer();
let state = createState();
let pollTimer = null;
let polling = false;
let transcriptTextScale = 1;
let eventSocket = null;
let eventReconnectTimer = null;
const preferences = readPreferences();
state = { ...state, ...preferences };

function byId(id) { return document.getElementById(id); }

function render() { renderer.render(state); }

function persistPreferences() {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify({
      autoFollow: state.autoFollow,
      transcriptFollow: state.transcriptFollow,
      reasoningVisible: state.reasoningVisible,
      selectedTab: ["transcript", "telemetry", "timeline"].includes(state.selectedTab) ? state.selectedTab : "transcript",
    }));
  } catch { /* Preferences are optional and contain no telemetry. */ }
}

function readPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem(PREF_KEY) || "{}");
    return {
      autoFollow: value.autoFollow !== false,
      transcriptFollow: value.transcriptFollow !== false,
      reasoningVisible: value.reasoningVisible !== false,
      selectedTab: ["transcript", "telemetry", "timeline"].includes(value.selectedTab) ? value.selectedTab : "transcript",
    };
  } catch { return {}; }
}

function setLoginError(message) {
  loginError.textContent = message;
  loginError.hidden = false;
}

function clearSensitiveState() {
  state = createState();
  renderer.render(state);
}

function lockDashboard(message = "") {
  if (pollTimer !== null) window.clearTimeout(pollTimer);
  pollTimer = null;
  if (eventReconnectTimer !== null) window.clearTimeout(eventReconnectTimer);
  eventReconnectTimer = null;
  if (eventSocket) eventSocket.close();
  eventSocket = null;
  dashboard.hidden = true;
  loginPanel.hidden = false;
  loginCode.value = "";
  clearSensitiveState();
  if (message) setLoginError(message);
}

async function login(code) {
  loginError.hidden = true;
  try {
    await loginWithCode(code);
    loginPanel.hidden = true;
    dashboard.hidden = false;
    await refresh();
    connectEvents();
    scheduleRefresh();
  } catch {
    setLoginError("Login failed. Check the code printed by the local monitor process.");
  }
}

function scheduleRefresh() {
  if (pollTimer !== null) window.clearTimeout(pollTimer);
  if (!dashboard.hidden) pollTimer = window.setTimeout(refresh, REFRESH_MS);
}

async function refresh() {
  if (polling || dashboard.hidden) return;
  polling = true;
  try {
    const snapshot = await fetchSnapshot();
    const priorStates = new Map(state.requests.map((request) => [requestKey(request), request.state]));
    state = mergeSnapshot(state, snapshot);
    render();
    const changed = state.requests.find((request) => priorStates.has(requestKey(request)) && priorStates.get(requestKey(request)) !== request.state);
    if (changed) announce(`${changed.request_id} ${stateLabel(changed.state)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      lockDashboard("Your local browser session expired. Enter the startup code again.");
      return;
    }
    state = { ...state, transportStatus: "disconnected", servers: state.servers.map((server) => ({ ...server, stale: true })) };
    render();
    const message = byId("provider-message");
    message.hidden = false;
    message.textContent = "The authenticated monitor API is temporarily unavailable. Last observed data is marked stale; request collection has not been stopped.";
  } finally {
    polling = false;
    scheduleRefresh();
  }
}


function historyTimeFilterToSince(timeFilter) {
  if (!timeFilter || timeFilter === "all") return null;
  const now = Date.now();
  const ms = timeFilter === "15m" ? 15 * 60_000 : timeFilter === "1h" ? 60 * 60_000 : 24 * 60 * 60_000;
  return new Date(now - ms).toISOString();
}

async function loadHistory() {
  try {
    const res = await fetchHistory({
      server_instance_id: state.historyServerFilter,
      model_id: state.historyModelFilter,
      state: state.historyStatusFilter,
      since: historyTimeFilterToSince(state.historyTimeFilter),
    });
    state = {
      ...state,
      historyRequests: res.requests || [],
      historyTotalCount: res.total_count || 0,
      historyAvailability: res.availability || "available",
    };
    if (state.historyRequests.length > 0 && !state.selectedHistoryRequestId) {
      await chooseHistoryRequest(state.historyRequests[0].request_id);
    } else if (state.selectedHistoryRequestId) {
      const exists = state.historyRequests.some((r) => r.request_id === state.selectedHistoryRequestId);
      if (exists) {
        await chooseHistoryRequest(state.selectedHistoryRequestId);
      } else if (state.historyRequests.length > 0) {
        await chooseHistoryRequest(state.historyRequests[0].request_id);
      } else {
        state = { ...state, selectedHistoryRequestId: null, selectedHistoryDetail: null };
        render();
      }
    } else {
      render();
    }
  } catch (err) {
    console.error("Failed to load history", err);
  }
}

async function chooseHistoryRequest(requestId) {
  state = { ...state, selectedHistoryRequestId: requestId };
  try {
    const detail = await fetchHistoryDetail(requestId);
    state = { ...state, selectedHistoryDetail: detail };
  } catch (err) {
    console.error("Failed to fetch history detail", err);
  }
  render();
}

function navigate(page) {
  const supported = ["overview", "requests", "models", "history", "alerts"];
  state = { ...state, page: supported.includes(page) ? page : "overview" };
  if (location.hash !== `#${state.page}`) history.replaceState(null, "", `#${state.page}`);
  if (state.page === "history") {
    loadHistory();
  }
  render();
  byId("main-content").focus({ preventScroll: true });
}

function chooseRequest(key) {
  state = selectRequest(state, key);
  if (state.page !== "overview" && state.page !== "requests") state = { ...state, page: "overview" };
  render();
  persistPreferences();
}

function updateVisibleSelection() {
  const visible = visibleRequests(state);
  if (state.autoFollow && visible.length) state = { ...state, selectedRequestKey: requestKey(visible[0]) };
  else if (state.selectedRequestKey && !visible.some((request) => requestKey(request) === state.selectedRequestKey)) state = { ...state, selectedRequestKey: visible[0] ? requestKey(visible[0]) : null };
  render();
}

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  login(loginCode.value);
});

byId("logout-button").addEventListener("click", async () => {
  try { await logout(); } finally { lockDashboard(); }
});

for (const link of document.querySelectorAll("[data-page]")) {
  link.addEventListener("click", (event) => { event.preventDefault(); navigate(link.dataset.page); });
}

window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));

byId("model-filter")?.addEventListener("change", (event) => {
  state = { ...state, selectedModelId: event.target.value, requestLimit: 100 };
  updateVisibleSelection();
});

const comboboxTrigger = byId("model-select-trigger");
const comboboxPopup = byId("model-select-popup");

function openCombobox() {
  if (!comboboxPopup || !comboboxTrigger) return;
  comboboxPopup.hidden = false;
  comboboxTrigger.setAttribute("aria-expanded", "true");
  const selectedOpt = comboboxPopup.querySelector('[aria-selected="true"]') || comboboxPopup.querySelector(".combobox-option");
  if (selectedOpt) selectedOpt.focus();
}

function closeCombobox() {
  if (!comboboxPopup || !comboboxTrigger) return;
  comboboxPopup.hidden = true;
  comboboxTrigger.setAttribute("aria-expanded", "false");
}

function selectComboboxOption(val) {
  state = { ...state, selectedModelId: val, requestLimit: 100 };
  const hiddenSelect = byId("model-filter");
  if (hiddenSelect) hiddenSelect.value = val;
  closeCombobox();
  updateVisibleSelection();
  comboboxTrigger?.focus();
}

if (comboboxTrigger) {
  comboboxTrigger.addEventListener("click", () => {
    if (comboboxPopup.hidden) openCombobox();
    else closeCombobox();
  });

  comboboxTrigger.addEventListener("keydown", (e) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      openCombobox();
    }
  });
}

if (comboboxPopup) {
  comboboxPopup.addEventListener("click", (e) => {
    const opt = e.target.closest(".combobox-option[data-value]");
    if (opt) selectComboboxOption(opt.dataset.value);
  });

  comboboxPopup.addEventListener("keydown", (e) => {
    const options = Array.from(comboboxPopup.querySelectorAll(".combobox-option"));
    if (!options.length) return;
    const currentIndex = options.indexOf(document.activeElement);

    if (e.key === "ArrowDown") {
      e.preventDefault();
      const nextIndex = currentIndex < options.length - 1 ? currentIndex + 1 : 0;
      options[nextIndex]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prevIndex = currentIndex > 0 ? currentIndex - 1 : options.length - 1;
      options[prevIndex]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      options[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      options[options.length - 1]?.focus();
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (document.activeElement?.dataset?.value) {
        selectComboboxOption(document.activeElement.dataset.value);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeCombobox();
      comboboxTrigger?.focus();
    } else if (e.key === "Tab") {
      closeCombobox();
    }
  });
}

document.addEventListener("click", (e) => {
  if (!e.target.closest("#model-combobox")) {
    closeCombobox();
  }
});

const recordingModeBtn = byId("recording-mode-btn");
const recordingConfirmDialog = byId("recording-confirm-dialog");
const recordingConfirmCancel = byId("recording-confirm-cancel");
const recordingConfirmAccept = byId("recording-confirm-accept");

if (recordingModeBtn) {
  recordingModeBtn.addEventListener("click", async () => {
    const recStatus = state.status?.recording;
    const currentMode = recStatus?.mode || (recStatus?.enabled ? "metadata" : "disabled");
    const isRecDisabled = currentMode === "off" || currentMode === "disabled" || !recStatus?.metadata;

    if (isRecDisabled) {
      if (typeof window !== "undefined" && typeof window.alert === "function") {
        window.alert(
          "Inference recording is disabled on this server instance.\n\n" +
          "To enable SQLite request history and content persistence, start LLM Monitor with the -R or --record-inferences flag."
        );
      }
      return;
    }

    if (currentMode === "metadata") {
      if (recordingConfirmDialog?.showModal) {
        recordingConfirmDialog.showModal();
      } else {
        const ok = window.confirm("Enable Full Content Recording? This persists complete user prompts, reasoning, and model outputs to SQLite.");
        if (ok) {
          try {
            await updateRecordingMode("content");
            await refresh();
          } catch (err) {
            console.error("Failed to enable content recording", err);
          }
        }
      }
    } else {
      try {
        await updateRecordingMode("metadata");
        await refresh();
      } catch (err) {
        console.error("Failed to switch recording to metadata", err);
      }
    }
  });
}

if (recordingConfirmCancel && recordingConfirmDialog) {
  recordingConfirmCancel.addEventListener("click", () => {
    recordingConfirmDialog.close();
  });
}

if (recordingConfirmAccept && recordingConfirmDialog) {
  recordingConfirmAccept.addEventListener("click", async () => {
    recordingConfirmDialog.close();
    try {
      await updateRecordingMode("content");
      await refresh();
    } catch (err) {
      console.error("Failed to enable content recording", err);
    }
  });
}

byId("server-list").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-server-id]");
  if (!button) return;
  state = { ...state, selectedServerId: state.selectedServerId === button.dataset.serverId ? "all" : button.dataset.serverId, requestLimit: 100 };
  updateVisibleSelection();
});

byId("request-search").addEventListener("input", (event) => {
  state = { ...state, search: event.target.value, requestLimit: 100 };
  updateVisibleSelection();
});

byId("status-filter").addEventListener("change", (event) => {
  state = { ...state, statusFilter: event.target.value, requestLimit: 100 };
  updateVisibleSelection();
});

byId("time-filter").addEventListener("change", (event) => {
  state = { ...state, timeRange: event.target.value, requestLimit: 100 };
  updateVisibleSelection();
});

byId("request-list").addEventListener("click", (event) => {
  const row = event.target.closest("button[data-request-key]");
  if (row) chooseRequest(row.dataset.requestKey);
});

byId("request-list").addEventListener("keydown", (event) => {
  if (!(["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key))) return;
  event.preventDefault();
  const requests = visibleRequests(state);
  if (!requests.length) return;
  let index = requests.findIndex((request) => requestKey(request) === state.selectedRequestKey);
  if (event.key === "Home") index = 0;
  else if (event.key === "End") index = requests.length - 1;
  else index = Math.max(0, Math.min(requests.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
  chooseRequest(requestKey(requests[index]));
  byId("request-list").querySelector(`[data-request-key="${CSS.escape(requestKey(requests[index]))}"]`)?.focus();
});

byId("clear-search").addEventListener("click", () => {
  state = { ...state, search: "", statusFilter: "all", timeRange: "all", selectedModelId: "all", selectedServerId: "all", requestLimit: 100 };
  byId("request-search").value = "";
  byId("status-filter").value = "all";
  byId("time-filter").value = "all";
  byId("model-filter").value = "all";
  updateVisibleSelection();
});

byId("load-more-requests").addEventListener("click", () => {
  state = { ...state, requestLimit: state.requestLimit + 100 };
  render();
});

byId("follow-toggle").addEventListener("click", () => {
  state = state.autoFollow ? { ...state, autoFollow: false } : followLatest(state);
  persistPreferences();
  render();
});

byId("return-live").addEventListener("click", () => {
  state = followLatest(state);
  persistPreferences();
  render();
});

document.querySelectorAll(".inspector-tabs").forEach((tablist) => {
  tablist.addEventListener("click", (event) => {
    const tab = event.target.closest("button[data-tab]");
    if (!tab) return;
    state = { ...state, selectedTab: tab.dataset.tab };
    persistPreferences();
    render();
  });
  tablist.addEventListener("keydown", (event) => {
    const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!keys.includes(event.key)) return;
    const tabs = [...tablist.querySelectorAll("[role=tab]")];
    const index = tabs.indexOf(document.activeElement);
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    event.preventDefault();
    tabs[nextIndex].focus();
    tabs[nextIndex].click();
  });
});

byId("reasoning-visible").addEventListener("change", (event) => {
  state = { ...state, reasoningVisible: event.target.checked };
  persistPreferences();
  render();
});

byId("transcript-search").addEventListener("input", (event) => {
  state = { ...state, transcriptSearch: event.target.value };
  render();
});

byId("transcript-follow").addEventListener("change", (event) => {
  state = { ...state, transcriptFollow: event.target.checked };
  persistPreferences();
});

byId("copy-request-id").addEventListener("click", async (event) => {
  const id = event.currentTarget.dataset.requestId;
  if (!id) return;
  try {
    await navigator.clipboard.writeText(id);
    event.currentTarget.textContent = "Copied";
    window.setTimeout(() => { event.currentTarget.textContent = "Copy ID"; }, 900);
  } catch { event.currentTarget.textContent = "Unavailable"; }
});

byId("increase-text").addEventListener("click", () => {
  transcriptTextScale = Math.min(1.4, transcriptTextScale + .1);
  document.documentElement.style.setProperty("--transcript-scale", String(transcriptTextScale));
});

byId("keyboard-help").addEventListener("click", (event) => {
  if (event.target.closest("[data-close-help]")) byId("keyboard-help").close();
});

byId("model-cards").addEventListener("click", (event) => {
  const button = event.target.closest("[data-action=filter-model]");
  if (!button) return;
  state = { ...state, selectedModelId: button.dataset.modelId, requestLimit: 100 };
  navigate("overview");
  updateVisibleSelection();
});

document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
  const target = event.target;
  const editing = target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
  if (event.key === "Escape") {
    const dialog = byId("keyboard-help");
    if (dialog?.open) dialog.close();
    else if (document.activeElement === byId("request-search") && state.search) {
      state = { ...state, search: "" }; byId("request-search").value = ""; updateVisibleSelection();
    }
    return;
  }
  if (editing) return;
  if (event.key === "/") { event.preventDefault(); byId("request-search").focus(); }
  else if (event.key.toLowerCase() === "l") { state = followLatest(state); render(); }
  else if (event.key.toLowerCase() === "f") { state = state.autoFollow ? { ...state, autoFollow: false } : followLatest(state); render(); persistPreferences(); }
  else if (event.key.toLowerCase() === "r" && state.selectedRequestKey) { state = { ...state, reasoningVisible: !state.reasoningVisible }; byId("reasoning-visible").checked = state.reasoningVisible; render(); persistPreferences(); }
  else if (event.key === "?") byId("keyboard-help")?.showModal();
});

function ingestRequestEvent(event) {
  const before = state;
  state = applyRequestEvent(state, event);
  if (state === before) return false;
  renderer.renderRequestEvent(state, event);
  if (["request.started", "request.completed", "request.failed", "request.cancelled", "stream.interrupted"].includes(event.type)) {
    const request = state.requests.find((item) => requestKey(item) === requestKey(event.request || event));
    if (request) announce(`${request.request_id} ${event.type === "stream.interrupted" ? "stream interrupted" : stateLabel(request.state)}`);
  }
  return true;
}

function connectEvents() {
  if (dashboard.hidden || eventSocket) return;
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  eventSocket = new WebSocket(`${scheme}//${location.host}/api/inference/v1/stream`);
  eventSocket.onmessage = (message) => {
    try {
      const data = JSON.parse(message.data);
      if (data && data.type === "hardware.sample" && data.sample) {
        handleHardwareSample(data.sample);
        return;
      }
      ingestRequestEvent(data);
    } catch { /* Ignore malformed observer events. */ }
  };
  eventSocket.onclose = () => {
    eventSocket = null;
    if (dashboard.hidden) return;
    eventReconnectTimer = window.setTimeout(async () => {
      eventReconnectTimer = null;
      await refresh();
      connectEvents();
    }, 1500);
  };
  eventSocket.onerror = () => eventSocket?.close();
}

function handleHardwareSample(sample) {
  if (!state.status) state.status = {};
  if (!Array.isArray(state.status.hardware_samples)) state.status.hardware_samples = [];
  state.status.hardware_samples.push(sample);
  if (state.status.hardware_samples.length > 60) {
    state.status.hardware_samples.shift();
  }
  renderer.renderHardware(state);
}

function announce(message) {
  const region = byId("announcements");
  region.textContent = message;
  window.setTimeout(() => { if (region.textContent === message) region.textContent = ""; }, 1800);
}

window.addEventListener("llm-monitor-request-event", (event) => ingestRequestEvent(event.detail));
window.addEventListener("llm-monitor-auth-expired", () => lockDashboard("Your local browser session expired. Enter the startup code again."));

const initialPage = location.hash.slice(1);
if (["overview", "requests", "models", "history", "alerts"].includes(initialPage)) state.page = initialPage;

byId("history-refresh-btn")?.addEventListener("click", () => loadHistory());
byId("history-server-filter")?.addEventListener("change", (e) => {
  state = { ...state, historyServerFilter: e.target.value };
  loadHistory();
});
byId("history-model-filter")?.addEventListener("change", (e) => {
  state = { ...state, historyModelFilter: e.target.value };
  loadHistory();
});
byId("history-time-filter")?.addEventListener("change", (e) => {
  state = { ...state, historyTimeFilter: e.target.value };
  loadHistory();
});
byId("history-status-filter")?.addEventListener("change", (e) => {
  state = { ...state, historyStatusFilter: e.target.value };
  loadHistory();
});
byId("history-requests-list")?.addEventListener("click", (e) => {
  const card = e.target.closest("[data-request-id]");
  if (card && card.dataset.requestId) chooseHistoryRequest(card.dataset.requestId);
});

if (state.page === "history") loadHistory();
render();
