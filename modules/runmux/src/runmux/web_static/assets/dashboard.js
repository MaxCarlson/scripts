"use strict";

const $ = (selector) => document.querySelector(selector);
const STATUS_CLASS = { pending: "pending", running: "running", paused: "paused", finished: "finished", failed: "failed", killed: "killed", lost: "lost" };
const STATUS_ORDER = ["running", "pending", "paused", "failed", "killed", "lost", "finished"];
const STATUS_LABEL = { running: "Running", pending: "Waiting", paused: "Paused", failed: "Failed", killed: "Killed", lost: "Disconnected", finished: "Completed" };
const STATUS_VALUES = ["pending", "running", "paused", "finished", "failed", "killed", "lost"];
const WORKSPACE_STORAGE_KEY = "runmux-workspace-v1";
const PROCESS_PAGE_SIZE = 100;
const EXPLORER_MIN_WIDTH = 220;
const EXPLORER_MAX_WIDTH = 480;
const STATUS_SORT_ORDER = ["running", "pending", "paused", "failed", "killed", "lost", "finished"];
const VIEW_LIMIT = 512 * 1024;
const OVERVIEW_MODE_STORAGE_KEY = "runmux-overview-mode-v1";
const OVERVIEW_MODES = ["minimal", "inline", "dashboard", "expanded"];
const TELEMETRY_INTERVAL_MS = 1800;
const HOST_TELEMETRY_INTERVAL_MS = 5400;
let overviewMode = "inline";
let telemetryTimer = null;
let telemetryRequestId = 0;
let telemetryInFlightId = 0;
let telemetryAbortController = null;
let lastHostSampleTime = 0;
let cachedHostStats = null;
let lifecycleInFlightRunId = null;
let pendingConfirmAction = null;
let systemCapabilities = null;

let runs = [];
let selectedId = null;
let openRunIds = [];
const collapsedGroups = new Set();
let selectionGeneration = 0;
let authGeneration = 0;
let outputCursor = null;
let listTimer = null;
let outputTimer = null;
let outputRequestGeneration = null;
let lastOutput = "";
let outputFinished = false;
let outputPendingCarriageReturn = false;
let terminalSocket = null;
let terminalStatus = null;
let terminalInstance = null;
let terminalFitAddon = null;
let terminalResizeObserver = null;
let terminalReconnectTimer = null;
const TERMINAL_SCROLLBACK = 5000;
let newProcessOpen = false;
let launchPending = false;
let launchDefaultCwd = "";
let groupingMode = "status";
let statusFilter = "";
let sortMode = "recent";
let processPage = 0;
let explorerWidth = 300;
let explorerCollapsed = false;
let explorerResizeActive = false;
let workspaceRestored = false;
let savedRunViews = { openRunIds: [], selectedId: null };
let searchQuery = "";
let tabScrollTarget = null;
const MAX_SEARCH_MATCHES = 10000;
const MAX_RENDER_LINES = 2000;
const MAX_RENDER_MATCHES = 500;
let outputSearchQuery = "";
let outputSearchCase = false;
let outputSeverityFilter = "all";
let outputFilteredLines = [];
let outputTotalLineCount = 0;
let outputMatches = [];
let outputActiveMatchIndex = -1;
let outputSearchError = null;
let outputTruncated = false;

function clampExplorerWidth(value) {
  return Math.max(EXPLORER_MIN_WIDTH, Math.min(EXPLORER_MAX_WIDTH, Math.round(value)));
}

function loadWorkspacePreferences() {
  let saved = null;
  try {
    saved = JSON.parse(globalThis.sessionStorage?.getItem(WORKSPACE_STORAGE_KEY) || "null");
  } catch { /* Invalid or unavailable session storage uses defaults. */ }
  if (!saved || saved.version !== 1 || typeof saved !== "object") return;
  if (["status", "none"].includes(saved.groupingMode)) groupingMode = saved.groupingMode;
  if (saved.statusFilter === "" || STATUS_VALUES.includes(saved.statusFilter)) statusFilter = saved.statusFilter;
  if (["recent", "started", "name", "duration", "status"].includes(saved.sortMode)) sortMode = saved.sortMode;
  if (typeof saved.searchQuery === "string") searchQuery = saved.searchQuery.slice(0, 512);
  if (Number.isInteger(saved.processPage) && saved.processPage >= 0 && saved.processPage < 100000) processPage = saved.processPage;
  if (Number.isFinite(saved.explorerWidth)) explorerWidth = clampExplorerWidth(saved.explorerWidth);
  explorerCollapsed = saved.explorerCollapsed === true;
  if (Array.isArray(saved.collapsedGroups)) {
    for (const status of saved.collapsedGroups) if (STATUS_VALUES.includes(status)) collapsedGroups.add(status);
  }
  if (Array.isArray(saved.openRunIds)) {
    savedRunViews.openRunIds = [...new Set(saved.openRunIds.filter((id) => typeof id === "string" && id.length <= 128))].slice(0, 64);
  }
  if (typeof saved.selectedId === "string" && saved.selectedId.length <= 128) savedRunViews.selectedId = saved.selectedId;
}

function persistWorkspaceState() {
  searchQuery = $("#process-search").value.slice(0, 512);
  const state = {
    version: 1,
    groupingMode,
    statusFilter,
    sortMode,
    searchQuery,
    processPage,
    collapsedGroups: [...collapsedGroups],
    explorerWidth,
    explorerCollapsed,
    openRunIds: openRunIds.slice(-64),
    selectedId,
  };
  try { globalThis.sessionStorage?.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(state)); }
  catch { /* Storage is a convenience; the workspace remains usable without it. */ }
}

function restoreRunViews() {
  const validIds = new Set(runs.map((run) => run.id));
  openRunIds = [...new Set(savedRunViews.openRunIds.filter((id) => validIds.has(id)))];
  const selected = savedRunViews.selectedId && openRunIds.includes(savedRunViews.selectedId)
    ? savedRunViews.selectedId
    : openRunIds.at(-1) || null;
  savedRunViews = { openRunIds: [], selectedId: null };
  workspaceRestored = true;
  return selected;
}

loadWorkspacePreferences();
loadOverviewMode();

function applyWorkspacePreferencesToControls() {
  $("#process-search").value = searchQuery;
  $("#process-grouping").value = groupingMode;
  $("#process-status-filter").value = statusFilter;
  $("#process-sort").value = sortMode;
}

function applyExplorerLayout() {
  const workspace = $(".workspace");
  workspace.style.setProperty?.("--explorer-width", `${explorerWidth}px`);
  if (!workspace.style.setProperty) workspace.style["--explorer-width"] = `${explorerWidth}px`;
  workspace.classList.toggle("explorer-collapsed", explorerCollapsed);
  const toggle = $("#explorer-toggle");
  toggle.setAttribute("aria-expanded", `${!explorerCollapsed}`);
  toggle.setAttribute("aria-label", explorerCollapsed ? "Expand process explorer" : "Collapse process explorer");
  toggle.title = explorerCollapsed ? "Expand process explorer" : "Collapse process explorer";
  $("#explorer-splitter").setAttribute("aria-valuenow", `${explorerWidth}`);
}

function resizeExplorerBy(delta) {
  explorerWidth = clampExplorerWidth(explorerWidth + delta);
  applyExplorerLayout();
  persistWorkspaceState();
}

function toggleExplorerCollapsed() {
  explorerCollapsed = !explorerCollapsed;
  applyExplorerLayout();
  persistWorkspaceState();
}

function runTimestamp(run, key) {
  const value = key === "started" ? run.started_at || run.created_at : run.created_at;
  const timestamp = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function compareRuns(left, right) {
  let comparison = 0;
  if (sortMode === "name") comparison = (left.name || left.command || "").localeCompare(right.name || right.command || "", undefined, { sensitivity: "base" });
  else if (sortMode === "started") comparison = runTimestamp(right, "started") - runTimestamp(left, "started");
  else if (sortMode === "duration") comparison = (Number(right.runtime_seconds) || 0) - (Number(left.runtime_seconds) || 0);
  else if (sortMode === "status") {
    const leftIndex = STATUS_SORT_ORDER.indexOf(left.status);
    const rightIndex = STATUS_SORT_ORDER.indexOf(right.status);
    comparison = (leftIndex < 0 ? STATUS_SORT_ORDER.length : leftIndex) - (rightIndex < 0 ? STATUS_SORT_ORDER.length : rightIndex);
  } else comparison = runTimestamp(right, "created") - runTimestamp(left, "created");
  return comparison || `${left.id}`.localeCompare(`${right.id}`);
}

function filteredRuns() {
  const query = $("#process-search").value.trim().toLowerCase();
  return runs.filter((run) => {
    if (statusFilter && run.status !== statusFilter) return false;
    const searchable = `${run.name || ""} ${run.command || ""} ${run.status || ""} ${run.id || ""}`.toLowerCase();
    return !query || searchable.includes(query);
  }).sort(compareRuns);
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
  if (response.status === 401) throw new Error("locked");
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const detail = (await response.json()).detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) {
        message = detail.map((item) => `${(item.loc || []).slice(1).join(".") || "request"}: ${item.msg}`).join("; ");
      }
    } catch { /* Keep the generic message. */ }
    const err = new Error(message);
    err.status = response.status;
    throw err;
  }
  return response;
}

function showLogin(message = "") {
  authGeneration += 1;
  invalidateSelection();
  clearInterval(listTimer);
  listTimer = null;
  $("#dashboard").hidden = true;
  $("#login-view").hidden = false;
  $("#login-error").textContent = message;
  $("#login-code").focus();
}

function showDashboard() {
  $("#login-view").hidden = true;
  $("#dashboard").hidden = false;
  refreshCapabilities();
}

async function refreshCapabilities() {
  try {
    const response = await api("/api/capabilities");
    systemCapabilities = await response.json();
    if (selectedId) {
      updateLifecycleControls(getRun(selectedId));
    }
  } catch {
    // If not reachable or unauthorized, keep systemCapabilities as null
  }
  return systemCapabilities;
}

function setSystemCapabilities(caps) {
  systemCapabilities = caps;
}

function isPauseResumeSupported() {
  if (systemCapabilities && typeof systemCapabilities.supports_pause_resume === "boolean") {
    return systemCapabilities.supports_pause_resume;
  }
  return false;
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-error").textContent = "";
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: $("#login-code").value }),
    });
    if (!response.ok) throw new Error("That code was not accepted. Check the launching terminal and try again.");
    $("#login-code").value = "";
    showDashboard();
    await refreshRuns();
    listTimer = setInterval(refreshRuns, 4000);
  } catch (error) {
    if (error.message === "locked") showLogin("Session expired. Enter the current terminal login code again.");
    else $("#login-error").textContent = error.message;
  }
});

$("#logout-button").addEventListener("click", async () => {
  authGeneration += 1;
  invalidateSelection();
  clearInterval(listTimer);
  listTimer = null;
  try { await fetch("/auth/logout", { method: "POST", credentials: "same-origin", cache: "no-store" }); }
  finally { showLogin("This browser session is locked."); }
});
$("#refresh-button").addEventListener("click", refreshRuns);
$("#new-process-empty-button").addEventListener("click", openNewProcess);
$("#new-process-empty-workspace").addEventListener("click", openNewProcess);
$("#cancel-launch").addEventListener("click", closeNewProcess);
$("#launch-form").addEventListener("submit", submitLaunch);
$("#process-search").addEventListener("input", () => { processPage = 0; persistWorkspaceState(); renderRuns(); });
$("#process-grouping").addEventListener("change", () => {
  groupingMode = $("#process-grouping").value === "none" ? "none" : "status";
  processPage = 0;
  persistWorkspaceState();
  renderRuns();
});
$("#process-status-filter").addEventListener("change", () => {
  const value = $("#process-status-filter").value;
  statusFilter = STATUS_VALUES.includes(value) ? value : "";
  processPage = 0;
  persistWorkspaceState();
  renderRuns();
});
$("#process-sort").addEventListener("change", () => {
  const value = $("#process-sort").value;
  sortMode = ["recent", "started", "name", "duration", "status"].includes(value) ? value : "recent";
  processPage = 0;
  persistWorkspaceState();
  renderRuns();
});
$("#clear-search").addEventListener("click", () => { $("#process-search").value = ""; processPage = 0; persistWorkspaceState(); renderRuns(); });
$("#process-previous-page").addEventListener("click", () => { processPage = Math.max(0, processPage - 1); persistWorkspaceState(); renderRuns(); });
$("#process-next-page").addEventListener("click", () => { processPage += 1; persistWorkspaceState(); renderRuns(); });
$("#explorer-toggle").addEventListener("click", toggleExplorerCollapsed);
$("#copy-run-id").addEventListener("click", () => copyRunField("#detail-id", "Run ID"));
$("#copy-run-pid").addEventListener("click", () => copyRunField("#detail-pid", "PID"));
$("#copy-run-command").addEventListener("click", () => copyRunField("#detail-command", "Executable name"));
$("#explorer-splitter").addEventListener("pointerdown", (event) => {
  explorerResizeActive = true;
  event.currentTarget.setPointerCapture?.(event.pointerId);
  event.preventDefault();
});
document.addEventListener("pointermove", (event) => {
  if (!explorerResizeActive) return;
  const bounds = $(".workspace").getBoundingClientRect();
  explorerWidth = clampExplorerWidth(event.clientX - bounds.left);
  applyExplorerLayout();
});
document.addEventListener("pointerup", () => {
  if (!explorerResizeActive) return;
  explorerResizeActive = false;
  persistWorkspaceState();
});
$("#explorer-splitter").addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft") { event.preventDefault(); resizeExplorerBy(-16); }
  else if (event.key === "ArrowRight") { event.preventDefault(); resizeExplorerBy(16); }
  else if (event.key === "Home") { event.preventDefault(); explorerWidth = EXPLORER_MIN_WIDTH; applyExplorerLayout(); persistWorkspaceState(); }
  else if (event.key === "End") { event.preventDefault(); explorerWidth = EXPLORER_MAX_WIDTH; applyExplorerLayout(); persistWorkspaceState(); }
});
applyWorkspacePreferencesToControls();
applyExplorerLayout();
applyOverviewModeUI();
setupModeListeners();
setupOutputSearchListeners();
setupLifecycleListeners();

if (typeof document !== "undefined" && document.addEventListener) {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopTelemetryPolling();
    } else if (selectedId && overviewMode !== "minimal") {
      startTelemetryPolling();
      refreshTelemetry(selectionGeneration, selectedId);
    }
  });
}
$("#scroll-output").addEventListener("click", scrollOutputToEnd);
$("#output-text").addEventListener("scroll", () => {
  const node = $("#output-text");
  if (node.scrollHeight - node.scrollTop - node.clientHeight > 40) $("#follow-output").checked = false;
});
document.querySelectorAll(".tab-button").forEach((button) => button.addEventListener("click", () => selectTab(button.dataset.tab)));
$("#terminal-control-button").addEventListener("click", toggleTerminalControl);
$("#terminal-lock-button").addEventListener("click", requestTerminalLock);
document.addEventListener("keydown", (event) => {
  if (document.activeElement && (document.activeElement.closest?.("#terminal-pane") || document.activeElement.id === "terminal-container")) {
    return;
  }
  const terminalActive = !$("#terminal-pane")?.hidden;
  if (terminalActive) return;

  if ((event.ctrlKey || event.metaKey) && event.key === "f" && !event.altKey && !event.shiftKey) {
    const outputActive = !$("#output-pane")?.hidden;
    if (outputActive) {
      event.preventDefault();
      const input = $("#output-search-query");
      if (input) {
        input.focus();
        if (typeof input.select === "function") input.select();
      }
      return;
    }
  }

  if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault(); $("#process-search").focus();
  }
  if (event.key === "Escape" && document.activeElement === $("#process-search")) {
    $("#process-search").value = ""; renderRuns(); $("#process-search").blur();
  }
  if (event.altKey && (event.key === "m" || event.key === "M")) {
    event.preventDefault();
    cycleOverviewMode();
  }
});

async function refreshRuns() {
  if (systemCapabilities === null) refreshCapabilities();
  const requestGeneration = authGeneration;
  try {
    const response = await api("/api/runs");
    const nextRuns = await response.json();
    if (requestGeneration !== authGeneration) return;
    const seenIds = new Set();
    runs = nextRuns.filter((run) => {
      if (!run || typeof run.id !== "string" || seenIds.has(run.id)) return false;
      seenIds.add(run.id);
      return true;
    });
    $("#last-updated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    $("#connection-state").className = "connection-state connected";
    $("#connection-state").lastElementChild.textContent = "Registry connected";
    let restoredRunId = null;
    if (!workspaceRestored) restoredRunId = restoreRunViews();
    openRunIds = openRunIds.filter((runId) => runs.some((run) => run.id === runId));
    if (selectedId && !runs.some((run) => run.id === selectedId)) {
      const fallbackId = openRunIds[openRunIds.length - 1] || null;
      if (fallbackId) await selectRun(fallbackId);
      else clearSelection();
      return;
    }
    renderRuns();
    renderWorkspaceTabs();
    renderWorkspaceView();
    if (restoredRunId) {
      await selectRun(restoredRunId);
      return;
    }
    persistWorkspaceState();
    if (selectedId) await refreshSelected(selectionGeneration, selectedId);
  } catch (error) {
    if (requestGeneration !== authGeneration) return;
    if (error.message === "locked") { showLogin("Session expired. Enter the current terminal login code again."); return; }
    $("#connection-state").className = "connection-state error";
    $("#connection-state").lastElementChild.textContent = "Registry unavailable · retrying";
    $("#list-state").textContent = "Could not reach the local run registry. It will retry automatically.";
  }
}

function renderRuns() {
  const filtered = filteredRuns();
  const pageCount = Math.max(1, Math.ceil(filtered.length / PROCESS_PAGE_SIZE));
  processPage = Math.max(0, Math.min(processPage, pageCount - 1));
  const visible = filtered.slice(processPage * PROCESS_PAGE_SIZE, (processPage + 1) * PROCESS_PAGE_SIZE);
  const list = $("#process-list");
  list.replaceChildren();
  $("#process-count").textContent = `${filtered.length}`;
  const query = $("#process-search").value.trim();
  $("#clear-search").hidden = !query;
  $("#list-state").textContent = filtered.length ? "" : runs.length ? "No processes match these filters." : "No managed processes yet.";
  $("#new-process-empty-button").hidden = Boolean(query || statusFilter) || runs.length > 0;
  $("#process-pagination").hidden = filtered.length <= PROCESS_PAGE_SIZE;
  $("#process-page-state").textContent = `${processPage + 1} / ${pageCount}`;
  $("#process-previous-page").disabled = processPage === 0;
  $("#process-next-page").disabled = processPage >= pageCount - 1;

  if (groupingMode === "status") {
    const statuses = [...new Set(visible.map((run) => run.status))].sort((left, right) => {
      const leftIndex = STATUS_ORDER.indexOf(left);
      const rightIndex = STATUS_ORDER.indexOf(right);
      return (leftIndex < 0 ? STATUS_ORDER.length : leftIndex) - (rightIndex < 0 ? STATUS_ORDER.length : rightIndex)
        || left.localeCompare(right);
    });
    for (const status of statuses) {
      const groupRuns = visible.filter((run) => run.status === status);
      const group = document.createElement("details");
      group.className = "process-group";
      group.open = !collapsedGroups.has(status);
      group.addEventListener("toggle", () => {
        if (group.open) collapsedGroups.delete(status);
        else collapsedGroups.add(status);
        persistWorkspaceState();
      });
      const heading = document.createElement("summary");
      heading.className = "group-heading";
      const headingLabel = document.createElement("span");
      headingLabel.textContent = STATUS_LABEL[status] || status;
      const count = document.createElement("span");
      count.className = "group-count";
      count.textContent = `${groupRuns.length}`;
      heading.append(headingLabel, count);
      group.append(heading);
      for (const run of groupRuns) group.append(createProcessRow(run));
      list.append(group);
    }
  } else {
    for (const run of visible) list.append(createProcessRow(run));
  }
  persistWorkspaceState();
}

function createProcessRow(run) {
  const row = document.createElement("button");
  const displayName = run.name || run.command || "Unnamed process";
  const shortId = `${run.id}`.slice(-6);
  row.type = "button";
  row.className = `process-row${run.id === selectedId ? " selected" : ""}`;
  row.title = `${displayName} · ${run.id}`;
  row.setAttribute("aria-current", run.id === selectedId ? "true" : "false");
  row.addEventListener("click", () => selectRun(run.id));
  const dot = document.createElement("span");
  dot.className = `row-dot ${STATUS_CLASS[run.status] || ""}`;
  const main = document.createElement("span");
  main.className = "row-main";
  const title = document.createElement("span");
  title.className = "row-title";
  title.textContent = displayName;
  title.title = displayName;
  const command = document.createElement("span");
  command.className = "row-command";
  command.textContent = run.command || "";
  command.title = run.command || "";
  const meta = document.createElement("span");
  meta.className = "row-meta";
  meta.textContent = `${formatRuntime(run.runtime_seconds)} · ${relativeTime(run.started_at || run.created_at)} · ${shortId}`;
  main.append(title, command, meta);
  const badge = document.createElement("span");
  badge.className = `status-badge ${STATUS_CLASS[run.status] || ""}`;
  badge.textContent = STATUS_LABEL[run.status] || run.status;
  row.append(dot, main, badge);
  return row;
}

function renderWorkspaceTabs() {
  const tabs = $("#workspace-tabs");
  const previousScrollLeft = Number(tabs.scrollLeft) || 0;
  tabs.replaceChildren();
  const openedRuns = openRunIds.map((runId) => runs.find((run) => run.id === runId)).filter(Boolean);
  let scrollTargetElement = null;
  tabs.hidden = false;
  for (const run of openedRuns) {
    const tab = document.createElement("div");
    tab.className = `workspace-tab${run.id === selectedId ? " active" : ""}`;
    const activate = document.createElement("button");
    activate.type = "button";
    activate.className = "workspace-tab-select";
    activate.setAttribute("role", "tab");
    activate.setAttribute("aria-selected", `${run.id === selectedId}`);
    const displayName = run.name || run.command || "Unnamed process";
    activate.title = `${displayName} · ${run.id}`;
    activate.setAttribute("aria-label", `Open ${displayName}, run ${run.id}`);
    activate.setAttribute("aria-controls", "run-inspector");
    activate.addEventListener("click", () => selectRun(run.id));
    const dot = document.createElement("span");
    dot.className = `row-dot ${STATUS_CLASS[run.status] || ""}`;
    const label = document.createElement("span");
    label.className = "workspace-tab-label";
    label.textContent = displayName;
    const identity = document.createElement("span");
    identity.className = "workspace-tab-id";
    identity.textContent = `${run.id}`.slice(-6);
    activate.append(dot, label, identity);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "workspace-tab-close";
    close.setAttribute("aria-label", `Close ${displayName} run ${run.id} view`);
    close.title = "Close view";
    close.textContent = "×";
    close.addEventListener("click", () => closeWorkspaceTab(run.id));
    tab.append(activate, close);
    tabs.append(tab);
    if (tabScrollTarget === run.id) scrollTargetElement = tab;
  }
  const addTab = document.createElement("button");
  addTab.type = "button";
  addTab.className = `workspace-add-tab${newProcessOpen ? " active" : ""}`;
  addTab.setAttribute("role", "tab");
  addTab.setAttribute("aria-label", "New Process");
  addTab.setAttribute("aria-selected", `${newProcessOpen}`);
  addTab.title = "New Process";
  addTab.textContent = "+";
  addTab.addEventListener("click", openNewProcess);
  tabs.append(addTab);
  if (tabScrollTarget === "new-process") addTab.scrollIntoView({ block: "nearest", inline: "nearest" });
  else if (scrollTargetElement) scrollTargetElement.scrollIntoView({ block: "nearest", inline: "nearest" });
  else tabs.scrollLeft = previousScrollLeft;
  tabScrollTarget = null;
  persistWorkspaceState();
}

function renderWorkspaceView() {
  $("#new-process-view").hidden = !newProcessOpen;
  $("#empty-inspector").hidden = newProcessOpen || Boolean(selectedId);
  $("#run-inspector").hidden = newProcessOpen || !selectedId;
}

async function openNewProcess() {
  newProcessOpen = true;
  tabScrollTarget = "new-process";
  closeTerminal();
  selectTab("output");
  renderWorkspaceTabs();
  renderWorkspaceView();
  $("#launch-error").hidden = true;
  if (!launchDefaultCwd) {
    try {
      const response = await api("/api/launch-defaults");
      const defaults = await response.json();
      launchDefaultCwd = defaults.cwd;
      if (!$("#launch-cwd").value) $("#launch-cwd").value = launchDefaultCwd;
      $("#launch-default-note").textContent = `Defaults to ${launchDefaultCwd}`;
    } catch (error) {
      $("#launch-default-note").textContent = "Could not load the default directory. Enter a working directory to continue.";
      if (error.message === "locked") showLogin("Session expired. Enter the current terminal login code again.");
    }
  } else {
    if (!$("#launch-cwd").value) $("#launch-cwd").value = launchDefaultCwd;
    $("#launch-default-note").textContent = `Defaults to ${launchDefaultCwd}`;
  }
  $("#launch-program").focus();
}

function closeNewProcess() {
  if (launchPending) return;
  newProcessOpen = false;
  renderWorkspaceTabs();
  renderWorkspaceView();
}

async function submitLaunch(event) {
  event.preventDefault();
  if (launchPending) return;
  const program = $("#launch-program").value.trim();
  if (!program) {
    $("#launch-error").textContent = "Enter a command to launch.";
    $("#launch-error").hidden = false;
    $("#launch-program").focus();
    return;
  }
  const argumentText = $("#launch-arguments").value;
  const argumentsList = argumentText === "" ? [] : argumentText.split("\n").map((value) => value.replace(/\r$/, ""));
  launchPending = true;
  $("#launch-submit").disabled = true;
  $("#cancel-launch").disabled = true;
  $("#launch-pending").hidden = false;
  $("#launch-error").hidden = true;
  try {
    const response = await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        program,
        arguments: argumentsList,
        name: $("#launch-name").value.trim() || null,
        cwd: $("#launch-cwd").value.trim() || null,
      }),
    });
    const run = await response.json();
    newProcessOpen = false;
    runs = runs.filter((item) => item.id !== run.id).concat(run);
    selectedId = null;
    renderRuns();
    await selectRun(run.id);
  } catch (error) {
    if (error.message === "locked") {
      showLogin("Session expired. Enter the current terminal login code again.");
    } else {
      $("#launch-error").textContent = error.message || "Could not launch this process. Check the command and working directory.";
      $("#launch-error").hidden = false;
    }
  } finally {
    launchPending = false;
    $("#launch-submit").disabled = false;
    $("#cancel-launch").disabled = false;
    $("#launch-pending").hidden = true;
    renderWorkspaceTabs();
    renderWorkspaceView();
  }
}

function closeWorkspaceTab(runId) {
  const index = openRunIds.indexOf(runId);
  if (index < 0) return;
  openRunIds.splice(index, 1);
  if (selectedId === runId) {
    const nextId = openRunIds[Math.min(index, openRunIds.length - 1)];
    if (nextId) {
      selectedId = null;
      return selectRun(nextId);
    } else {
      clearSelection();
      return;
    }
  }
  renderRuns();
  renderWorkspaceTabs();
  persistWorkspaceState();
}


function loadOverviewMode() {
  try {
    const saved = globalThis.localStorage?.getItem(OVERVIEW_MODE_STORAGE_KEY);
    if (saved && OVERVIEW_MODES.includes(saved)) {
      overviewMode = saved;
    } else {
      overviewMode = "inline";
    }
  } catch {
    overviewMode = "inline";
  }
  if (typeof window !== "undefined") {
    window.overviewMode = overviewMode;
    window.setOverviewMode = setOverviewMode;
    window.cycleOverviewMode = cycleOverviewMode;
  }
}

function applyOverviewModeUI() {
  const inspector = $("#run-inspector");
  if (!inspector) return;
  OVERVIEW_MODES.forEach((m) => inspector.classList.remove(`mode-${m}`));
  inspector.classList.add(`mode-${overviewMode}`);

  const modeButtons = {
    minimal: $("#mode-btn-a"),
    inline: $("#mode-btn-b"),
    dashboard: $("#mode-btn-c"),
    expanded: $("#mode-btn-d"),
  };
  for (const [m, btn] of Object.entries(modeButtons)) {
    if (!btn) continue;
    const active = m === overviewMode;
    btn.setAttribute("aria-pressed", String(active));
    btn.classList.toggle("active", active);
  }

  const inlineEl = $("#inline-telemetry");
  const panelEl = $("#telemetry-panel");
  const hostSection = $("#host-telemetry-section");

  if (inlineEl) inlineEl.hidden = overviewMode !== "inline";
  if (panelEl) panelEl.hidden = overviewMode !== "dashboard" && overviewMode !== "expanded";
  if (hostSection) hostSection.hidden = overviewMode !== "expanded";
}

function setOverviewMode(mode) {
  if (!OVERVIEW_MODES.includes(mode)) return;
  overviewMode = mode;
  if (typeof window !== "undefined") {
    window.overviewMode = overviewMode;
  }
  try {
    globalThis.localStorage?.setItem(OVERVIEW_MODE_STORAGE_KEY, mode);
  } catch { /* Non-sensitive persistence convenience */ }
  applyOverviewModeUI();

  if (selectedId) {
    if (overviewMode === "minimal") {
      stopTelemetryPolling();
    } else {
      startTelemetryPolling();
      refreshTelemetry(selectionGeneration, selectedId);
    }
  }
}

function cycleOverviewMode() {
  const cycleMap = {
    minimal: "inline",
    inline: "dashboard",
    dashboard: "expanded",
    expanded: "minimal",
  };
  setOverviewMode(cycleMap[overviewMode] || "inline");
}

function formatPercent(val) {
  if (val == null || typeof val !== "number" || isNaN(val)) return "—";
  return `${val.toFixed(1)}%`;
}

function formatBytes(bytes) {
  if (bytes == null || typeof bytes !== "number" || isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
}

function formatBytesRate(rate) {
  if (rate == null || typeof rate !== "number" || isNaN(rate)) return "—";
  if (rate === 0) return "0 B/s";
  if (rate < 1024) return `${rate.toFixed(0)} B/s`;
  if (rate < 1024 * 1024) return `${(rate / 1024).toFixed(1)} KiB/s`;
  return `${(rate / (1024 * 1024)).toFixed(1)} MiB/s`;
}

function parseTelemetryTimestamp(val) {
  if (!val) return null;
  if (typeof val === "number" && !isNaN(val)) return val > 1e11 ? val : val * 1000;
  if (typeof val === "string") {
    const ms = Date.parse(val);
    return isNaN(ms) ? null : ms;
  }
  return null;
}

function renderTelemetry(processStats, hostStats = null) {
  if (!processStats) return;

  const banner = $("#telemetry-status-banner");
  if (banner) {
    const sampleMs = parseTelemetryTimestamp(processStats.sampled_at);
    if (processStats.unavailable) {
      banner.hidden = false;
      banner.textContent = `Process inactive: ${processStats.unavailable}`;
    } else if (sampleMs !== null && (Date.now() - sampleMs > 6000)) {
      const ageSec = Math.round((Date.now() - sampleMs) / 1000);
      banner.hidden = false;
      banner.textContent = `Stale telemetry (${ageSec}s ago)`;
    } else {
      banner.hidden = true;
    }
  }

  // Rate fields: null vs 0 vs number
  const isBaselineOrUnavailable = processStats.unavailable != null || processStats.cpu_percent == null;
  const cpuText = isBaselineOrUnavailable ? "—" : formatPercent(processStats.cpu_percent);
  const rssText = processStats.unavailable != null ? "—" : formatBytes(processStats.rss_bytes);
  const procCount = processStats.unavailable != null ? "—" : (processStats.process_count ?? "—");
  const threadCount = processStats.unavailable != null ? "—" : (processStats.thread_count ?? "—");

  // Mode B Inline Elements
  const inlineCpu = $("#val-inline-cpu");
  if (inlineCpu) inlineCpu.textContent = cpuText;
  const inlineRss = $("#val-inline-rss");
  if (inlineRss) inlineRss.textContent = rssText;
  const inlineProcs = $("#val-inline-procs");
  if (inlineProcs) inlineProcs.textContent = `${procCount}p / ${threadCount}t`;

  // Mode C / D Process Cards
  const cardCpuVal = $("#card-cpu-val");
  if (cardCpuVal) cardCpuVal.textContent = cpuText;
  const cardCpuSub = $("#card-cpu-sub");
  if (cardCpuSub) {
    if (processStats.unavailable) {
      cardCpuSub.textContent = processStats.unavailable;
    } else if (processStats.cpu_percent == null) {
      cardCpuSub.textContent = "Baseline pending (first sample)";
    } else if (processStats.cpu_count > 1 && processStats.cpu_percent_normalized != null) {
      cardCpuSub.textContent = `${formatPercent(processStats.cpu_percent_normalized)} norm (${processStats.cpu_count} cores)`;
    } else {
      cardCpuSub.textContent = `${processStats.cpu_count || 1} core(s)`;
    }
  }

  const cardRssVal = $("#card-rss-val");
  if (cardRssVal) cardRssVal.textContent = rssText;
  const cardRssSub = $("#card-rss-sub");
  if (cardRssSub) cardRssSub.textContent = processStats.unavailable ? "Process exited" : "Resident physical memory";

  const cardTreeVal = $("#card-tree-val");
  if (cardTreeVal) cardTreeVal.textContent = isBaselineOrUnavailable && processStats.process_count == null ? "—" : `${procCount} procs · ${threadCount} threads`;
  const cardTreeSub = $("#card-tree-sub");
  if (cardTreeSub) cardTreeSub.textContent = processStats.unavailable ? "Process tree terminated" : "Living processes in tree";

  const cardIoVal = $("#card-io-val");
  if (cardIoVal) {
    if (processStats.unavailable || (processStats.read_bytes_per_second == null && processStats.write_bytes_per_second == null)) {
      cardIoVal.textContent = "—";
    } else {
      cardIoVal.textContent = `↓ ${formatBytesRate(processStats.read_bytes_per_second)} · ↑ ${formatBytesRate(processStats.write_bytes_per_second)}`;
    }
  }
  const cardIoSub = $("#card-io-sub");
  if (cardIoSub) {
    if (processStats.unavailable) {
      cardIoSub.textContent = "Process I/O ended";
    } else if (processStats.total_read_bytes != null || processStats.total_write_bytes != null) {
      cardIoSub.textContent = `Total: ↓ ${formatBytes(processStats.total_read_bytes)} · ↑ ${formatBytes(processStats.total_write_bytes)}`;
    } else {
      cardIoSub.textContent = "Read / write throughput";
    }
  }

  // 5. Correct GPU attribution distinction: null = Unavailable, 0 = 0 B, >0 = formatted
  const cardGpuProcVal = $("#card-gpu-proc-val");
  const cardGpuProcSub = $("#card-gpu-proc-sub");
  if (cardGpuProcVal) {
    if (processStats.unavailable) {
      cardGpuProcVal.textContent = "—";
      if (cardGpuProcSub) cardGpuProcSub.textContent = "Process inactive";
    } else if (processStats.gpu_memory_bytes == null) {
      cardGpuProcVal.textContent = "Unavailable";
      if (cardGpuProcSub) cardGpuProcSub.textContent = "No GPU attribution data";
    } else if (processStats.gpu_memory_bytes === 0) {
      cardGpuProcVal.textContent = "0 B";
      if (cardGpuProcSub) cardGpuProcSub.textContent = "Verified zero GPU memory";
    } else {
      cardGpuProcVal.textContent = formatBytes(processStats.gpu_memory_bytes);
      if (cardGpuProcSub) cardGpuProcSub.textContent = "Attributed compute VRAM";
    }
  }

  // Mode D Host & Hardware Cards
  if (hostStats) {
    const cardHostCpuVal = $("#card-host-cpu-val");
    if (cardHostCpuVal) cardHostCpuVal.textContent = formatPercent(hostStats.cpu_percent);
    const cardHostCpuSub = $("#card-host-cpu-sub");
    if (cardHostCpuSub) cardHostCpuSub.textContent = `${hostStats.cpu_count || 1} logical cores total`;

    const cardHostRamVal = $("#card-host-ram-val");
    if (cardHostRamVal) cardHostRamVal.textContent = `${formatBytes(hostStats.memory_used_bytes)} / ${formatBytes(hostStats.memory_total_bytes)}`;
    const cardHostRamSub = $("#card-host-ram-sub");
    if (cardHostRamSub) cardHostRamSub.textContent = `${formatPercent(hostStats.memory_percent)} system utilized`;

    const cardHostNetVal = $("#card-host-net-val");
    if (cardHostNetVal) {
      if (hostStats.net_read_bytes_per_second == null && hostStats.net_write_bytes_per_second == null) {
        cardHostNetVal.textContent = "—";
      } else {
        cardHostNetVal.textContent = `↓ ${formatBytesRate(hostStats.net_read_bytes_per_second)} · ↑ ${formatBytesRate(hostStats.net_write_bytes_per_second)}`;
      }
    }
    const cardHostNetSub = $("#card-host-net-sub");
    if (cardHostNetSub) cardHostNetSub.textContent = "Host-wide network delta";

    const cardGpuDevVal = $("#card-gpu-dev-val");
    const cardGpuDevSub = $("#card-gpu-dev-sub");
    if (hostStats.gpu_devices == null) {
      if (cardGpuDevVal) cardGpuDevVal.textContent = "Unavailable";
      if (cardGpuDevSub) cardGpuDevSub.textContent = "Host GPU metrics unavailable";
    } else if (Array.isArray(hostStats.gpu_devices) && hostStats.gpu_devices.length > 0) {
      const dev = hostStats.gpu_devices[0];
      if (cardGpuDevVal) cardGpuDevVal.textContent = `${dev.name || ("GPU " + dev.index)}: ${dev.load != null ? dev.load + "% load" : "—"}`;
      if (cardGpuDevSub) cardGpuDevSub.textContent = `${formatBytes(dev.memory_used)} / ${formatBytes(dev.memory_total)} · ${dev.temperature != null ? dev.temperature + "°C" : "—"}`;
    } else {
      if (cardGpuDevVal) cardGpuDevVal.textContent = "No GPU detected";
      if (cardGpuDevSub) cardGpuDevSub.textContent = "NVIDIA SMI or device unavailable";
    }
  }

  // 4. Correct terminal state check: only stop polling if run is genuinely terminal
  const isTerminalRun = processStats && (
    ["finished", "failed", "killed", "lost"].includes(processStats.status) ||
    processStats.unavailable === "run is finished" ||
    processStats.unavailable === "process exited"
  );
  if (isTerminalRun) {
    stopTelemetryPolling();
  }
}

function startTelemetryPolling() {
  stopTelemetryPolling();
  if (overviewMode === "minimal" || !selectedId || (typeof document !== "undefined" && document.hidden)) return;
  telemetryTimer = setInterval(() => {
    if (!document.hidden && selectedId && overviewMode !== "minimal") {
      refreshTelemetry(selectionGeneration, selectedId);
    }
  }, TELEMETRY_INTERVAL_MS);
}

function stopTelemetryPolling() {
  telemetryRequestId++;
  telemetryInFlightId = 0;
  if (telemetryTimer) {
    clearInterval(telemetryTimer);
    telemetryTimer = null;
  }
  if (telemetryAbortController) {
    try { telemetryAbortController.abort(); } catch {}
    telemetryAbortController = null;
  }
}

async function refreshTelemetry(generation = selectionGeneration, runId = selectedId) {
  if (!runId || !isCurrentSelection(generation, runId) || overviewMode === "minimal" || (typeof document !== "undefined" && document.hidden)) return;
  if (telemetryInFlightId !== 0) return;

  const currentRequestId = ++telemetryRequestId;
  telemetryInFlightId = currentRequestId;

  if (telemetryAbortController) {
    try { telemetryAbortController.abort(); } catch {}
  }
  const controller = new AbortController();
  telemetryAbortController = controller;
  const signal = controller.signal;

  try {
    let procStats = null;
    let hostStats = cachedHostStats;

    // 2. Correct polling overhead: Only query /api/telemetry (all active runs) every 5.4s in Mode D
    const now = Date.now();
    const shouldFetchHost = overviewMode === "expanded" && (!cachedHostStats || (now - lastHostSampleTime >= HOST_TELEMETRY_INTERVAL_MS));

    if (shouldFetchHost) {
      const [pRes, hRes] = await Promise.all([
        api(`/api/runs/${encodeURIComponent(runId)}/telemetry`, { signal }),
        api("/api/telemetry", { signal }),
      ]);
      if (!isCurrentSelection(generation, runId) || currentRequestId !== telemetryRequestId) return;
      procStats = await pRes.json();
      const hData = await hRes.json();
      hostStats = hData?.host || null;
      cachedHostStats = hostStats;
      lastHostSampleTime = Date.now();
    } else {
      const pRes = await api(`/api/runs/${encodeURIComponent(runId)}/telemetry`, { signal });
      if (!isCurrentSelection(generation, runId) || currentRequestId !== telemetryRequestId) return;
      procStats = await pRes.json();
    }

    if (!isCurrentSelection(generation, runId) || currentRequestId !== telemetryRequestId) return;
    renderTelemetry(procStats, hostStats);
  } catch (error) {
    if (!isCurrentSelection(generation, runId) || currentRequestId !== telemetryRequestId) return;
    if (error.name === "AbortError") return;
    if (error.message === "locked") {
      showLogin("Session expired. Enter the current terminal login code again.");
      return;
    }
    const banner = $("#telemetry-status-banner");
    if (banner) {
      banner.hidden = false;
      banner.textContent = "Telemetry temporarily unavailable.";
    }
  } finally {
    // 3. Fix request cancellation races: only clear in-flight ID if this request is still the active one
    if (telemetryInFlightId === currentRequestId) {
      telemetryInFlightId = 0;
    }
  }
}

function setupModeListeners() {
  $("#mode-btn-a")?.addEventListener("click", () => setOverviewMode("minimal"));
  $("#mode-btn-b")?.addEventListener("click", () => setOverviewMode("inline"));
  $("#mode-btn-c")?.addEventListener("click", () => setOverviewMode("dashboard"));
  $("#mode-btn-d")?.addEventListener("click", () => setOverviewMode("expanded"));
  $("#mode-cycle-btn")?.addEventListener("click", () => cycleOverviewMode());
}

async function selectRun(runId) {
  newProcessOpen = false;
  if (selectedId === runId) {
    renderWorkspaceTabs();
    renderWorkspaceView();
    return;
  }
  if (!openRunIds.includes(runId)) openRunIds.push(runId);
  tabScrollTarget = runId;
  invalidateSelection();
  const generation = selectionGeneration;
  selectedId = runId;
  outputCursor = null;
  lastOutput = "";
  outputFinished = false;
  outputTruncated = false;
  outputMatches = [];
  outputActiveMatchIndex = -1;
  outputSearchError = null;
  computeOutputSearchAndFilter();
  $("#output-text").textContent = "";
  $("#output-state").textContent = "Loading process output…";
  $("#output-state").hidden = false;
  $("#empty-inspector").hidden = true;
  $("#run-inspector").hidden = false;
  renderRuns();
  renderWorkspaceTabs();
  persistWorkspaceState();
  applyOverviewModeUI();
  await Promise.all([
    refreshSelected(generation, runId),
    refreshOutput(generation, runId),
    overviewMode !== "minimal" ? refreshTelemetry(generation, runId) : Promise.resolve(),
  ]);
  if (isCurrentSelection(generation, runId) && !outputFinished) {
    outputTimer = setInterval(() => refreshOutput(generation, runId), 900);
  }
  if (isCurrentSelection(generation, runId) && overviewMode !== "minimal") {
    startTelemetryPolling();
  }
  if (isCurrentSelection(generation, runId) && !$("#terminal-pane").hidden) connectTerminal(generation, runId);
}

async function refreshSelected(generation = selectionGeneration, runId = selectedId) {
  if (!runId || !isCurrentSelection(generation, runId)) return;
  try {
    const response = await api(`/api/runs/${encodeURIComponent(runId)}`);
    const run = await response.json();
    if (!isCurrentSelection(generation, runId)) return;
    const displayName = run.name || run.command || "Unnamed process";
    $("#selected-name").textContent = displayName;
    $("#selected-identity").textContent = `RUN ${run.id}`;
    $("#selected-command").textContent = run.command;
    $("#selected-status").className = `status-badge ${STATUS_CLASS[run.status] || ""}`;
    $("#selected-status").textContent = STATUS_LABEL[run.status] || run.status;
    $("#detail-id").textContent = run.id;
    $("#detail-pid").textContent = run.pid == null ? "—" : `${run.pid}`;
    $("#detail-exit").textContent = run.exit_code == null ? "—" : `${run.exit_code}`;
    $("#detail-runtime").textContent = formatRuntime(run.runtime_seconds);
    $("#detail-started").textContent = formatDate(run.started_at || run.created_at);
    $("#detail-ended").textContent = formatDate(run.ended_at);
    $("#detail-started").title = relativeTime(run.started_at || run.created_at);
    $("#detail-ended").title = run.ended_at ? relativeTime(run.ended_at) : "Not ended";
    $("#detail-command").textContent = run.command || "—";
    $("#detail-connection").textContent = run.connection === "disconnected" ? "Supervisor disconnected" : run.connection === "connected" ? "Supervisor connected" : "Not checked";
    $("#copy-run-id").disabled = !run.id;
    $("#copy-run-pid").disabled = run.pid == null;
    $("#copy-run-command").disabled = !run.command;
    reconcileRunSummary(run);
    updateLifecycleControls(run);
    const warning = $("#run-warning");
    warning.hidden = run.connection !== "disconnected";
    warning.textContent = run.connection === "disconnected" ? "Supervisor is unreachable. Showing the last recorded status and available log output." : "";
  } catch (error) {
    if (!isCurrentSelection(generation, runId)) return;
    if (error.message === "locked") { showLogin("Session expired. Enter the current terminal login code again."); return; }
    $("#run-warning").hidden = false;
    $("#run-warning").textContent = "Process details are temporarily unavailable. Retrying on the next refresh.";
  }
}

function reconcileRunSummary(run) {
  const index = runs.findIndex((item) => item.id === run.id);
  if (index < 0) return;
  runs[index] = { ...runs[index], ...run };
  renderRuns();
  renderWorkspaceTabs();
}

async function copyRunField(selector, label) {
  const value = $(selector).textContent;
  if (!value || value === "—") return;
  try {
    await navigator.clipboard.writeText(value);
    $("#details-copy-status").textContent = `${label} copied.`;
  } catch {
    $("#details-copy-status").textContent = "Clipboard access is unavailable; select the value to copy it.";
  }
}

function createTextNode(text) {
  if (typeof document.createTextNode === "function") {
    return document.createTextNode(text);
  }
  return { textContent: text, nodeType: 3 };
}

function appendChildNode(parent, child) {
  if (typeof parent.appendChild === "function") parent.appendChild(child);
  else if (typeof parent.append === "function") parent.append(child);
  else if (Array.isArray(parent.children)) parent.children.push(child);
}

function formatByteSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.round(bytes / 1024)} KiB`;
}

function classifyLogLine(line) {
  if (!line || typeof line !== "string") return "other";
  const trimmed = line.trim();
  if (!trimmed) return "other";

  const jsonMatch = trimmed.match(/"(?:level|lvl|severity)"\s*:\s*"(fatal|critical|error|warn(?:ing)?|info|notice|debug|trace)"/i);
  if (jsonMatch) return normalizeSeverityLevel(jsonMatch[1]);

  const kvMatch = trimmed.match(/\b(?:level|lvl|severity)=(?:"?)(fatal|critical|error|warn(?:ing)?|info|notice|debug|trace)(?:"?)(?:\s|$)/i);
  if (kvMatch) return normalizeSeverityLevel(kvMatch[1]);

  const delimMatch = trimmed.match(/\s+[-|]\s+(FATAL|CRITICAL|ERROR|WARN(?:ING)?|INFO|NOTICE|DEBUG|TRACE)\s+[-|]\s+/i);
  if (delimMatch) return normalizeSeverityLevel(delimMatch[1]);

  const bracketMatch = trimmed.match(/\[(?:[^\]]*\s)?(FATAL|CRITICAL|ERROR|WARN(?:ING)?|INFO|NOTICE|DEBUG|TRACE)(?:\s[^\]]*|:[^\]]*)?\]/i);
  if (bracketMatch) return normalizeSeverityLevel(bracketMatch[1]);

  const startMatch = trimmed.match(/^(?:(?:\d{4}[-/]\d{2}[-/]\d{2}[T\s][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?|[\w.-]+)[:\s]+)?(FATAL|CRITICAL|ERROR|WARN(?:ING)?|INFO|NOTICE|DEBUG|TRACE)(?::|\s|$)/i);
  if (startMatch) {
    const token = startMatch[1];
    if (token === token.toUpperCase() || startMatch[0].endsWith(":") || startMatch[0].includes(":")) {
      return normalizeSeverityLevel(token);
    }
  }

  return "other";
}

function normalizeSeverityLevel(level) {
  const lower = level.toLowerCase();
  if (lower === "fatal" || lower === "critical" || lower === "error") return "error";
  if (lower === "warn" || lower === "warning") return "warn";
  if (lower === "info" || lower === "notice") return "info";
  if (lower === "debug" || lower === "trace") return "debug";
  return "other";
}

function matchesSeverityFilter(lineSeverity, filterValue) {
  if (!filterValue || filterValue === "all") return true;
  if (filterValue === "error") return lineSeverity === "error";
  if (filterValue === "warn") return lineSeverity === "warn" || lineSeverity === "error";
  if (filterValue === "info") return lineSeverity === "info";
  if (filterValue === "debug") return lineSeverity === "debug";
  if (filterValue === "other") return lineSeverity === "other";
  return true;
}

function computeOutputSearchAndFilter() {
  const query = outputSearchQuery.trim();
  const caseSensitive = outputSearchCase;
  const filter = outputSeverityFilter;

  const rawLines = lastOutput ? lastOutput.split("\n") : [];
  outputTotalLineCount = rawLines.length;

  const lineRecords = [];
  for (let i = 0; i < rawLines.length; i++) {
    const text = rawLines[i];
    const severity = classifyLogLine(text);
    if (matchesSeverityFilter(severity, filter)) {
      lineRecords.push({ originalIndex: i, text, severity });
    }
  }
  outputFilteredLines = lineRecords;

  let regex = null;
  outputSearchError = null;
  if (query) {
    // Literal search: safely escape all regex meta-characters.
    // Guaranteed linear time O(N) execution; 100% immune to catastrophic backtracking.
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    regex = new RegExp(escaped, caseSensitive ? "gu" : "gui");
  }

  outputMatches = [];
  let isCapped = false;
  if (regex && !outputSearchError) {
    for (let li = 0; li < lineRecords.length; li++) {
      const lineRec = lineRecords[li];
      regex.lastIndex = 0;
      let match;
      while ((match = regex.exec(lineRec.text)) !== null) {
        if (match[0].length === 0) {
          regex.lastIndex++;
          continue;
        }
        outputMatches.push({
          matchIndex: outputMatches.length,
          lineIndex: li,
          start: match.index,
          end: match.index + match[0].length,
          text: match[0],
        });
        if (outputMatches.length >= MAX_SEARCH_MATCHES) {
          isCapped = true;
          break;
        }
      }
      if (isCapped) break;
    }
  }

  if (outputMatches.length === 0) {
    outputActiveMatchIndex = -1;
  } else if (outputActiveMatchIndex < 0 || outputActiveMatchIndex >= outputMatches.length) {
    outputActiveMatchIndex = 0;
  }

  let startLineIndex = 0;
  let endLineIndex = lineRecords.length;
  if (lineRecords.length > MAX_RENDER_LINES) {
    if (outputActiveMatchIndex >= 0 && outputMatches[outputActiveMatchIndex]) {
      const targetLine = outputMatches[outputActiveMatchIndex].lineIndex;
      const half = Math.floor(MAX_RENDER_LINES / 2);
      startLineIndex = Math.max(0, targetLine - half);
      endLineIndex = Math.min(lineRecords.length, startLineIndex + MAX_RENDER_LINES);
      if (endLineIndex === lineRecords.length) {
        startLineIndex = Math.max(0, endLineIndex - MAX_RENDER_LINES);
      }
    } else {
      startLineIndex = Math.max(0, lineRecords.length - MAX_RENDER_LINES);
      endLineIndex = lineRecords.length;
    }
  }

  updateOutputSearchUI(outputTotalLineCount, lineRecords.length, isCapped, startLineIndex, endLineIndex);
  renderOutputDOM(lineRecords, outputMatches, outputActiveMatchIndex, startLineIndex, endLineIndex);
}

function updateOutputSearchUI(totalLines, visibleLines, isCapped = false, startLineIndex = 0, endLineIndex = visibleLines) {
  const query = outputSearchQuery.trim();
  const searchCountEl = $("#output-search-count");
  const scopeNoteEl = $("#output-scope-note");
  const clearBtn = $("#output-search-clear");
  const prevBtn = $("#output-search-prev");
  const nextBtn = $("#output-search-next");

  const bufferBytes = new TextEncoder().encode(lastOutput || "").length;
  const sizeLabel = formatByteSize(bufferBytes);
  const tailSuffix = outputTruncated ? "tail · earlier output omitted" : "buffer";
  const isPartiallyDisplayed = (startLineIndex > 0 || endLineIndex < visibleLines);

  if (scopeNoteEl) {
    if (isPartiallyDisplayed) {
      const displayedCount = endLineIndex - startLineIndex;
      if (outputSeverityFilter !== "all") {
        scopeNoteEl.textContent = `Showing lines ${(startLineIndex + 1).toLocaleString()}–${endLineIndex.toLocaleString()} of ${visibleLines.toLocaleString()} lines (${displayedCount.toLocaleString()} displayed · loaded ${tailSuffix})`;
      } else {
        scopeNoteEl.textContent = `Loaded ${tailSuffix}: ${totalLines.toLocaleString()} lines · ${sizeLabel} (displaying lines ${(startLineIndex + 1).toLocaleString()}–${endLineIndex.toLocaleString()})`;
      }
    } else {
      if (outputSeverityFilter !== "all") {
        scopeNoteEl.textContent = `Showing ${visibleLines.toLocaleString()} of ${totalLines.toLocaleString()} lines (loaded ${tailSuffix})`;
      } else {
        scopeNoteEl.textContent = `Loaded ${tailSuffix}: ${totalLines.toLocaleString()} lines · ${sizeLabel}`;
      }
    }
  }

  if (clearBtn) clearBtn.hidden = !query;

  if (outputSearchError) {
    if (searchCountEl) {
      searchCountEl.textContent = outputSearchError;
      searchCountEl.className = "output-search-count has-error";
    }
    if (prevBtn) prevBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = true;
  } else if (!query) {
    if (searchCountEl) {
      searchCountEl.textContent = "No query";
      searchCountEl.className = "output-search-count";
    }
    if (prevBtn) prevBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = true;
  } else if (outputMatches.length === 0) {
    if (searchCountEl) {
      searchCountEl.textContent = `0 matches (loaded ${tailSuffix})`;
      searchCountEl.className = "output-search-count";
    }
    if (prevBtn) prevBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = true;
  } else {
    const cappedNote = isCapped ? "+" : "";
    const partialNote = isPartiallyDisplayed ? ` · lines ${(startLineIndex + 1).toLocaleString()}–${endLineIndex.toLocaleString()} displayed` : "";
    if (searchCountEl) {
      searchCountEl.textContent = `${(outputActiveMatchIndex + 1).toLocaleString()} of ${outputMatches.length.toLocaleString()}${cappedNote} (loaded ${tailSuffix}${partialNote})`;
      searchCountEl.className = "output-search-count has-matches";
    }
    if (prevBtn) prevBtn.disabled = false;
    if (nextBtn) nextBtn.disabled = false;
  }
}

function renderOutputDOM(lineRecords, matches, activeMatchIndex, startLineIndex = 0, endLineIndex = lineRecords.length) {
  const container = $("#output-text");
  if (!container) return;

  const query = outputSearchQuery.trim();
  const filter = outputSeverityFilter;

  if (!query && filter === "all") {
    container.textContent = lastOutput;
    return;
  }

  if (lineRecords.length === 0) {
    container.textContent = "";
    return;
  }

  const effectiveStart = Math.max(0, Math.min(startLineIndex, lineRecords.length));
  const effectiveEnd = Math.max(effectiveStart, Math.min(endLineIndex, lineRecords.length));

  // Collect matches that fall in the displayed range [effectiveStart, effectiveEnd)
  const matchesByLine = new Map();
  for (let i = 0; i < matches.length; i++) {
    const m = matches[i];
    if (m.lineIndex >= effectiveStart && m.lineIndex < effectiveEnd) {
      if (!matchesByLine.has(m.lineIndex)) matchesByLine.set(m.lineIndex, []);
      matchesByLine.get(m.lineIndex).push(m);
    }
  }

  // Bound highlighted match DOM elements to MAX_RENDER_MATCHES, ensuring active match is always included
  const highlightedMatchIndices = new Set();
  if (activeMatchIndex >= 0) highlightedMatchIndices.add(activeMatchIndex);
  for (let i = 0; i < matches.length; i++) {
    if (highlightedMatchIndices.size >= MAX_RENDER_MATCHES) break;
    const m = matches[i];
    if (m.lineIndex >= effectiveStart && m.lineIndex < effectiveEnd) {
      highlightedMatchIndices.add(m.matchIndex);
    }
  }

  const nodes = [];
  let activeElement = null;

  for (let li = effectiveStart; li < effectiveEnd; li++) {
    const lineRec = lineRecords[li];
    const lineMatches = matchesByLine.get(li);

    const lineSpan = document.createElement("span");
    lineSpan.className = "output-line";

    if (!lineMatches || lineMatches.length === 0) {
      appendChildNode(lineSpan, createTextNode(lineRec.text));
    } else {
      let lastPos = 0;
      for (let mi = 0; mi < lineMatches.length; mi++) {
        const m = lineMatches[mi];
        if (m.start > lastPos) {
          appendChildNode(lineSpan, createTextNode(lineRec.text.slice(lastPos, m.start)));
        }
        const isActive = (m.matchIndex === activeMatchIndex);
        if (highlightedMatchIndices.has(m.matchIndex)) {
          const mark = document.createElement("mark");
          mark.className = "output-match" + (isActive ? " active-match" : "");
          appendChildNode(mark, createTextNode(m.text));
          if (isActive) {
            mark.id = "active-output-match";
            activeElement = mark;
          }
          appendChildNode(lineSpan, mark);
        } else {
          appendChildNode(lineSpan, createTextNode(m.text));
        }
        lastPos = m.end;
      }
      if (lastPos < lineRec.text.length) {
        appendChildNode(lineSpan, createTextNode(lineRec.text.slice(lastPos)));
      }
    }

    nodes.push(lineSpan);
    if (li < effectiveEnd - 1) {
      nodes.push(createTextNode("\n"));
    }
  }

  if (typeof container.replaceChildren === "function") {
    container.replaceChildren(...nodes);
  } else {
    container.textContent = "";
    for (const node of nodes) appendChildNode(container, node);
  }

  if (activeElement && typeof activeElement.scrollIntoView === "function") {
    activeElement.scrollIntoView({ block: "nearest", behavior: "auto" });
  }
}

function nextOutputMatch() {
  if (outputMatches.length === 0) return;
  outputActiveMatchIndex = (outputActiveMatchIndex + 1) % outputMatches.length;
  onMatchNavigated();
}

function prevOutputMatch() {
  if (outputMatches.length === 0) return;
  outputActiveMatchIndex = (outputActiveMatchIndex - 1 + outputMatches.length) % outputMatches.length;
  onMatchNavigated();
}

function onMatchNavigated() {
  const followCheckbox = $("#follow-output");
  if (followCheckbox) followCheckbox.checked = false;

  const lineRecords = outputFilteredLines;
  let startLineIndex = 0;
  let endLineIndex = lineRecords.length;
  if (lineRecords.length > MAX_RENDER_LINES) {
    if (outputActiveMatchIndex >= 0 && outputMatches[outputActiveMatchIndex]) {
      const targetLine = outputMatches[outputActiveMatchIndex].lineIndex;
      const half = Math.floor(MAX_RENDER_LINES / 2);
      startLineIndex = Math.max(0, targetLine - half);
      endLineIndex = Math.min(lineRecords.length, startLineIndex + MAX_RENDER_LINES);
      if (endLineIndex === lineRecords.length) {
        startLineIndex = Math.max(0, endLineIndex - MAX_RENDER_LINES);
      }
    } else {
      startLineIndex = Math.max(0, lineRecords.length - MAX_RENDER_LINES);
      endLineIndex = lineRecords.length;
    }
  }

  updateOutputSearchUI(outputTotalLineCount, lineRecords.length, false, startLineIndex, endLineIndex);
  renderOutputDOM(lineRecords, outputMatches, outputActiveMatchIndex, startLineIndex, endLineIndex);
}

function clearOutputSearch() {
  outputSearchQuery = "";
  outputSearchError = null;
  outputMatches = [];
  outputActiveMatchIndex = -1;
  const input = $("#output-search-query");
  if (input) input.value = "";
  computeOutputSearchAndFilter();
  if (input && typeof input.focus === "function") input.focus();
}

function setupOutputSearchListeners() {
  const queryInput = $("#output-search-query");
  if (queryInput) {
    queryInput.addEventListener("input", () => {
      outputSearchQuery = queryInput.value;
      computeOutputSearchAndFilter();
    });
    queryInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (event.shiftKey) prevOutputMatch();
        else nextOutputMatch();
      } else if (event.key === "Escape") {
        event.preventDefault();
        clearOutputSearch();
        if (typeof queryInput.blur === "function") queryInput.blur();
      }
    });
  }

  const caseBtn = $("#output-search-case");
  if (caseBtn) {
    caseBtn.addEventListener("click", () => {
      outputSearchCase = !outputSearchCase;
      caseBtn.setAttribute("aria-pressed", `${outputSearchCase}`);
      computeOutputSearchAndFilter();
    });
  }

  const clearBtn = $("#output-search-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      clearOutputSearch();
    });
  }

  const prevBtn = $("#output-search-prev");
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      prevOutputMatch();
    });
  }

  const nextBtn = $("#output-search-next");
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      nextOutputMatch();
    });
  }

  const filterSelect = $("#output-severity-filter");
  if (filterSelect) {
    filterSelect.addEventListener("change", () => {
      outputSeverityFilter = filterSelect.value;
      computeOutputSearchAndFilter();
    });
  }
}

async function refreshOutput(generation = selectionGeneration, runId = selectedId) {
  if (!runId || !isCurrentSelection(generation, runId) || outputRequestGeneration === generation) return;
  outputRequestGeneration = generation;
  try {
    const params = new URLSearchParams({ limit: "65536" });
    if (outputCursor) params.set("cursor", outputCursor);
    const response = await api(`/api/runs/${encodeURIComponent(runId)}/output?${params}`);
    const chunk = await response.json();
    if (!isCurrentSelection(generation, runId)) return;
    outputFinished = Boolean(chunk.finished && chunk.at_end);
    outputTruncated = Boolean(chunk.truncated);
    if (chunk.reset) {
      lastOutput = "";
      outputPendingCarriageReturn = false;
      outputCursor = chunk.cursor;
    }
    lastOutput += normalizeOutputLineBreaks(chunk.text, Boolean(chunk.finished && chunk.at_end));
    outputCursor = chunk.cursor;
    if (lastOutput.length > VIEW_LIMIT) {
      const characters = Array.from(lastOutput);
      if (characters.length > VIEW_LIMIT) lastOutput = characters.slice(-VIEW_LIMIT).join("");
    }
    computeOutputSearchAndFilter();
    $("#output-note").textContent = chunk.truncated ? "Latest 64 KiB shown · earlier output omitted" : "";
    $("#output-state").hidden = Boolean(lastOutput);
    if (chunk.state === "missing" || chunk.state === "inaccessible") {
      $("#output-state").textContent = chunk.message || "Output is not available.";
      $("#output-state").hidden = false;
    } else if (!lastOutput) {
      $("#output-state").textContent = chunk.finished ? "This process has no captured output." : "Waiting for process output…";
      $("#output-state").hidden = false;
    }
    if (chunk.truncated && !$("#output-state").hidden) $("#output-state").textContent = "Showing the latest bounded output. Earlier log content was omitted.";
    if (chunk.text) $("#output-activity").classList.add("visible");
    else $("#output-activity").classList.remove("visible");
    if ($("#follow-output").checked) scrollOutputToEnd();
    if (outputFinished && outputTimer) { clearInterval(outputTimer); outputTimer = null; }
  } catch (error) {
    if (!isCurrentSelection(generation, runId)) return;
    if (error.message === "locked") { showLogin("Session expired. Enter the current terminal login code again."); return; }
    $("#output-state").textContent = "Output temporarily unavailable. Retrying…";
    $("#output-state").hidden = false;
  } finally {
    if (outputRequestGeneration === generation) outputRequestGeneration = null;
  }
}

function normalizeOutputLineBreaks(text, flushPendingCarriageReturn = false) {
  let normalized = "";
  if (outputPendingCarriageReturn) {
    normalized += "\n";
    if (text.startsWith("\n")) text = text.slice(1);
    outputPendingCarriageReturn = false;
  }
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character !== "\r") {
      normalized += character;
      continue;
    }
    if (index + 1 < text.length) {
      if (text[index + 1] === "\n") index += 1;
      normalized += "\n";
    } else if (flushPendingCarriageReturn) {
      normalized += "\n";
    } else {
      outputPendingCarriageReturn = true;
    }
  }
  if (flushPendingCarriageReturn && outputPendingCarriageReturn) {
    normalized += "\n";
    outputPendingCarriageReturn = false;
  }
  return normalized;
}

function terminalReplayMessage(truncated) {
  return truncated ? "Earlier terminal output was truncated; this screen may be incomplete." : "";
}

function selectTab(tab) {
  const outputSelected = tab === "output";
  const terminalSelected = tab === "terminal";
  $("#tab-output").classList.toggle("active", outputSelected);
  $("#tab-output").setAttribute("aria-selected", `${outputSelected}`);
  $("#tab-terminal").classList.toggle("active", terminalSelected);
  $("#tab-terminal").setAttribute("aria-selected", `${terminalSelected}`);
  $("#tab-details").classList.toggle("active", !outputSelected && !terminalSelected);
  $("#tab-details").setAttribute("aria-selected", `${!outputSelected && !terminalSelected}`);
  $("#output-pane").hidden = !outputSelected;
  $("#terminal-pane").hidden = !terminalSelected;
  $("#details-pane").hidden = outputSelected || terminalSelected;
  $(".follow-toggle").hidden = !outputSelected;
  if (terminalSelected && selectedId) connectTerminal(selectionGeneration, selectedId);
  else closeTerminal();
}

function clearSelection() {
  invalidateSelection();
  newProcessOpen = false;
  selectedId = null;
  openRunIds = [];
  outputCursor = null;
  lastOutput = "";
  outputTruncated = false;
  outputMatches = [];
  outputActiveMatchIndex = -1;
  outputSearchError = null;
  computeOutputSearchAndFilter();
  $("#run-inspector").hidden = true;
  $("#empty-inspector").hidden = false;
  updateLifecycleControls(null);
  closeLifecycleConfirm();
  clearLifecycleFeedback();
  renderRuns();
  renderWorkspaceTabs();
  persistWorkspaceState();
}

function invalidateSelection() {
  selectionGeneration += 1;
  clearInterval(outputTimer);
  outputTimer = null;
  outputRequestGeneration = null;
  closeTerminal();
  stopTelemetryPolling();
}

function isCurrentSelection(generation, runId) {
  return generation === selectionGeneration && runId === selectedId;
}

function scrollOutputToEnd() {
  const node = $("#output-text");
  $("#follow-output").checked = true;
  node.scrollTop = node.scrollHeight;
}

function formatRuntime(value) {
  if (!Number.isFinite(value)) return "—";
  const seconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString();
}

function relativeTime(value) {
  if (!value) return "time unknown";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).valueOf()) / 1000));
  return seconds < 60 ? "just now" : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : `${Math.floor(seconds / 3600)}h ago`;
}

function ensureTerminal() {
  if (terminalInstance) return terminalInstance;
  const TerminalConstructor = globalThis.Terminal?.Terminal || globalThis.Terminal;
  const FitAddonConstructor = globalThis.FitAddon?.FitAddon;
  if (!TerminalConstructor || !FitAddonConstructor) {
    $("#terminal-message").hidden = false;
    $("#terminal-message").textContent = "The bundled terminal renderer could not be loaded. Refresh the page to retry.";
    return null;
  }
  terminalInstance = new TerminalConstructor({
    cursorBlink: false,
    convertEol: true,
    scrollback: TERMINAL_SCROLLBACK,
    fontFamily: '"Cascadia Code", "Cascadia Mono", Consolas, monospace',
    fontSize: 12,
    theme: { background: "#080c13", foreground: "#c6d1dc", cursor: "#51d6bd", selectionBackground: "#245a59" },
  });
  terminalFitAddon = new FitAddonConstructor();
  terminalInstance.loadAddon(terminalFitAddon);
  terminalInstance.open($("#terminal-container"));
  terminalInstance.onData(sendTerminalInput);
  terminalInstance.onResize(({ rows, cols }) => {
    if (terminalInputAllowed() && terminalSocket.readyState === 1) {
      sendTerminalMessage({ type: "resize", rows, columns: cols });
    }
  });
  if (globalThis.ResizeObserver) {
    terminalResizeObserver = new ResizeObserver(() => fitTerminal());
    terminalResizeObserver.observe($("#terminal-container"));
  } else if (globalThis.addEventListener) {
    globalThis.addEventListener("resize", fitTerminal);
  }
  fitTerminal();
  return terminalInstance;
}

function fitTerminal() {
  if (!terminalFitAddon || $("#terminal-pane").hidden) return;
  try { terminalFitAddon.fit(); } catch { /* The panel may be hidden during a layout change. */ }
}

function connectTerminal(generation = selectionGeneration, runId = selectedId) {
  if (!runId || !isCurrentSelection(generation, runId) || $("#terminal-pane").hidden) return;
  if (terminalSocket?.readyState === 0 || terminalSocket?.readyState === 1) return;
  if (!ensureTerminal()) return;
  clearTimeout(terminalReconnectTimer);
  terminalReconnectTimer = null;
  terminalStatus = null;
  updateTerminalControls();
  $("#terminal-message").hidden = true;
  $("#terminal-state").textContent = "Connecting to supervisor…";

  const scheme = globalThis.location?.protocol === "https:" ? "wss:" : "ws:";
  const host = globalThis.location?.host || "localhost";
  const socket = new WebSocket(`${scheme}//${host}/api/runs/${encodeURIComponent(runId)}/terminal`);
  terminalSocket = socket;
  socket.binaryType = "arraybuffer";
  socket.addEventListener("open", () => {
    if (terminalSocket !== socket || !isCurrentSelection(generation, runId)) return;
    $("#terminal-state").textContent = "Connected · read only";
    updateTerminalControls();
    fitTerminal();
  });
  socket.addEventListener("message", (event) => {
    if (terminalSocket !== socket || !isCurrentSelection(generation, runId)) return;
    if (event.data instanceof ArrayBuffer) {
      terminalInstance.write(new Uint8Array(event.data), () => {
        if (socket.readyState === 1) sendTerminalMessage({ type: "ack" }, socket);
      });
      return;
    }
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "status") {
      terminalStatus = message;
      renderTerminalStatus(message);
    } else if (message.type === "output_reset") {
      terminalInstance.reset();
      const replayMessage = terminalReplayMessage(message.truncated);
      $("#terminal-message").hidden = !replayMessage;
      $("#terminal-message").textContent = replayMessage;
    } else if (message.type === "output_state") {
      $("#terminal-message").hidden = false;
      $("#terminal-message").textContent = message.message || "Terminal output is unavailable.";
    } else if (message.type === "error") {
      $("#terminal-message").hidden = false;
      $("#terminal-message").textContent = message.message || "Terminal connection failed.";
      if (message.message === "This run has already finished.") $("#terminal-control-button").disabled = true;
    }
  });
  socket.addEventListener("close", (event) => {
    if (terminalSocket !== socket) return;
    terminalSocket = null;
    terminalStatus = null;
    updateTerminalControls();
    if (!isCurrentSelection(generation, runId)) return;
    if (event.code === 4401) {
      showLogin("Session expired. Enter the current terminal login code again.");
      return;
    }
    if (event.code === 4404) {
      $("#terminal-state").textContent = "Run is no longer available";
      return;
    }
    $("#terminal-state").textContent = "Disconnected · reconnecting…";
    terminalReconnectTimer = setTimeout(() => connectTerminal(generation, runId), 1000);
  });
  socket.addEventListener("error", () => {
    if (terminalSocket === socket) $("#terminal-state").textContent = "Connection interrupted";
  });
}

function renderTerminalStatus(status) {
  const button = $("#terminal-control-button");
  const lockButton = $("#terminal-lock-button");
  button.disabled = status.finished === true;
  button.textContent = status.mode === "interact" ? "Release control" : "Request control";
  lockButton.hidden = status.mode !== "interact" || status.session_holds_lock;
  if (status.finished) {
    $("#terminal-state").textContent = "Process finished · read only";
  } else if (status.mode !== "interact") {
    $("#terminal-state").textContent = "Connected · read only";
  } else if (status.session_holds_lock) {
    $("#terminal-state").textContent = "Input lock held · terminal input enabled";
    terminalInstance.options.cursorBlink = true;
    fitTerminal();
    sendTerminalMessage({ type: "resize", rows: terminalInstance.rows, columns: terminalInstance.cols });
  } else if (status.session_queue_position) {
    $("#terminal-state").textContent = `Waiting for input lock · position ${status.session_queue_position}`;
    terminalInstance.options.cursorBlink = false;
  } else {
    $("#terminal-state").textContent = "Control attached · request the input lock to type";
    terminalInstance.options.cursorBlink = false;
  }
  updateTerminalControls();
}

function updateTerminalControls() {
  const connected = terminalSocket?.readyState === 1;
  $("#terminal-control-button").disabled = !connected || terminalStatus?.finished === true;
  $("#terminal-lock-button").disabled = !connected || terminalStatus?.finished === true || terminalStatus?.mode !== "interact";
}

function toggleTerminalControl() {
  if (terminalSocket?.readyState !== 1) return;
  if (terminalStatus?.mode === "interact") {
    sendTerminalMessage({ type: "control", enabled: false });
    $("#terminal-state").textContent = "Releasing input control…";
  } else {
    sendTerminalMessage({ type: "control", enabled: true });
    $("#terminal-state").textContent = "Requesting input control…";
  }
}

function requestTerminalLock() {
  if (terminalSocket?.readyState === 1 && terminalStatus?.mode === "interact") {
    sendTerminalMessage({ type: "lock" });
    $("#terminal-state").textContent = "Requesting supervisor input lock…";
  }
}

function sendTerminalMessage(value, socket = terminalSocket) {
  if (socket?.readyState === 1) socket.send(JSON.stringify(value));
}

function terminalInputAllowed() {
  return terminalSocket?.readyState === 1
    && terminalStatus?.mode === "interact"
    && terminalStatus.session_holds_lock === true;
}

function sendTerminalInput(value) {
  if (!terminalInputAllowed()) return false;
  terminalSocket.send(new TextEncoder().encode(value));
  return true;
}

function closeTerminal() {
  clearTimeout(terminalReconnectTimer);
  terminalReconnectTimer = null;
  const socket = terminalSocket;
  terminalSocket = null;
  terminalStatus = null;
  updateTerminalControls();
  if (socket && (socket.readyState === 0 || socket.readyState === 1)) socket.close(1000, "terminal view closed");
}

function getRun(id) {
  if (!id) return null;
  return runs.find((r) => r.id === id) || null;
}

function updateLifecycleControls(run) {
  const stopBtn = $("#action-stop-btn");
  const killBtn = $("#action-kill-btn");
  const restartBtn = $("#action-restart-btn");
  const duplicateBtn = $("#action-duplicate-btn");
  const pauseBtn = $("#action-pause-btn");

  if (!stopBtn || !killBtn || !restartBtn || !duplicateBtn) return;

  if (!run || !run.id) {
    stopBtn.disabled = true;
    killBtn.disabled = true;
    restartBtn.disabled = true;
    duplicateBtn.disabled = true;
    if (pauseBtn) {
      pauseBtn.disabled = true;
      pauseBtn.textContent = "Pause";
      pauseBtn.setAttribute("data-action", "pause");
      pauseBtn.className = "lifecycle-btn lifecycle-btn-pause";
      pauseBtn.title = "Pause process";
    }
    return;
  }

  const isTerminal = ["finished", "failed", "killed", "lost"].includes(run.status);
  const isInFlight = lifecycleInFlightRunId === run.id;

  if (isInFlight) {
    stopBtn.disabled = true;
    killBtn.disabled = true;
    restartBtn.disabled = true;
    duplicateBtn.disabled = true;
    if (pauseBtn) pauseBtn.disabled = true;
    return;
  }

  // Stop & Kill
  if (isTerminal) {
    stopBtn.disabled = true;
    stopBtn.title = "Process is already terminated";
    killBtn.disabled = true;
    killBtn.title = "Process is already terminated";
  } else {
    stopBtn.disabled = false;
    stopBtn.title = `Gracefully stop ${run.name || run.command} (${run.id})`;
    killBtn.disabled = false;
    killBtn.title = `Force kill ${run.name || run.command} (${run.id})`;
  }

  // Restart: allowed only for terminal processes
  if (isTerminal) {
    restartBtn.disabled = false;
    restartBtn.title = `Restart ${run.name || run.command} as a new process`;
  } else {
    restartBtn.disabled = true;
    restartBtn.title = "Cannot restart an active process. Stop the run first before restarting, or duplicate it.";
  }

  // Duplicate: allowed for both active and terminal processes
  duplicateBtn.disabled = false;
  duplicateBtn.title = `Duplicate ${run.name || run.command} as a new parallel process`;

  // Pause & Resume: state and platform aware
  if (pauseBtn) {
    const isPaused = run.status === "paused";
    const actionLabel = isPaused ? "Resume" : "Pause";
    const actionVerb = isPaused ? "resume" : "pause";
    pauseBtn.textContent = actionLabel;
    pauseBtn.setAttribute("data-action", actionVerb);
    pauseBtn.className = `lifecycle-btn ${isPaused ? "lifecycle-btn-resume" : "lifecycle-btn-pause"}`;

    if (isTerminal) {
      pauseBtn.disabled = true;
      pauseBtn.title = "Process is already terminated";
    } else if (!isPauseResumeSupported()) {
      pauseBtn.disabled = true;
      const platformLabel = systemCapabilities?.platform === "win32" ? "Windows" : "this platform";
      pauseBtn.title = `${actionLabel} is not supported on ${platformLabel}`;
    } else {
      pauseBtn.disabled = false;
      pauseBtn.title = `${actionLabel} process ${run.name || run.command} (${run.id})`;
    }
  }
}

function showLifecycleConfirm(action, run) {
  if (!run || !run.id) return;
  pendingConfirmAction = {
    action,
    runId: run.id,
    force: action === "kill",
    displayName: run.name || run.command || "Unnamed process",
    generation: selectionGeneration,
  };

  const modal = $("#lifecycle-confirm-modal");
  const title = $("#confirm-modal-title");
  const desc = $("#confirm-modal-desc");
  const nameEl = $("#confirm-run-name");
  const idEl = $("#confirm-run-id");
  const noteEl = $("#confirm-warning-note");
  const submitBtn = $("#confirm-submit-btn");

  if (!modal) return;

  if (nameEl) nameEl.textContent = run.name || run.command || "Unnamed process";
  if (idEl) idEl.textContent = run.id;

  if (action === "kill") {
    if (title) title.textContent = "Confirm Force Kill Process";
    if (desc) desc.textContent = "Are you sure you want to force kill this process? Any unsaved in-memory state will be lost immediately.";
    if (noteEl) noteEl.textContent = "Kill defaults to forced termination (taskkill /F on Windows, SIGKILL on POSIX).";
    if (submitBtn) {
      submitBtn.textContent = "Kill Process";
      submitBtn.className = "modal-btn modal-btn-danger";
    }
  } else {
    if (title) title.textContent = "Confirm Stop Process";
    if (desc) desc.textContent = "Are you sure you want to stop this process? A graceful shutdown signal will be sent to the process.";
    if (noteEl) noteEl.textContent = "Stop defaults to graceful termination (Ctrl-Break/close on Windows, SIGTERM on POSIX).";
    if (submitBtn) {
      submitBtn.textContent = "Stop Process";
      submitBtn.className = "modal-btn modal-btn-warning";
    }
  }

  modal.hidden = false;
  const cancelBtn = $("#confirm-cancel-btn");
  if (cancelBtn && typeof cancelBtn.focus === "function") {
    cancelBtn.focus();
  }
}

function closeLifecycleConfirm() {
  pendingConfirmAction = null;
  const modal = $("#lifecycle-confirm-modal");
  if (modal) modal.hidden = true;
}

async function submitLifecycleConfirm() {
  if (!pendingConfirmAction) return;
  const target = pendingConfirmAction;
  closeLifecycleConfirm();

  // Guard against stale selection changes while modal was open
  if (target.runId !== selectedId || target.generation !== selectionGeneration) {
    return;
  }

  await executeLifecycleAction(target.action, target.runId, { force: target.force });
}

function showLifecycleFeedback(type, message) {
  const banner = $("#lifecycle-feedback");
  if (!banner) return;
  banner.className = `lifecycle-feedback feedback-${type}`;
  banner.replaceChildren();

  const msgSpan = document.createElement("span");
  msgSpan.textContent = message;

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "lifecycle-feedback-close";
  closeBtn.setAttribute("aria-label", "Dismiss feedback");
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", () => {
    banner.hidden = true;
  });

  banner.append(msgSpan, closeBtn);
  banner.hidden = false;
}

function clearLifecycleFeedback() {
  const banner = $("#lifecycle-feedback");
  if (banner) {
    banner.hidden = true;
    banner.replaceChildren();
  }
}

async function executeLifecycleAction(action, runId, options = {}) {
  if (!runId || lifecycleInFlightRunId) return;

  lifecycleInFlightRunId = runId;
  const generation = selectionGeneration;
  const currentRun = getRun(runId);
  const displayName = currentRun?.name || currentRun?.command || runId;

  updateLifecycleControls(currentRun);

  const actionVerb = action === "stop" ? "Stopping"
    : action === "kill" ? "Killing"
    : action === "restart" ? "Restarting"
    : action === "duplicate" ? "Duplicating"
    : action === "resume" ? "Resuming"
    : "Pausing";

  showLifecycleFeedback("in-flight", `${actionVerb} process ${displayName} (${runId})…`);

  try {
    let payload = null;
    if (action === "stop") {
      payload = { force: options.force === true };
    } else if (action === "kill") {
      payload = { force: options.force !== false };
    } else if (action === "restart" || action === "duplicate") {
      payload = { force_color: null };
    }

    const fetchOptions = {
      method: "POST",
    };
    if (payload !== null) {
      fetchOptions.headers = { "Content-Type": "application/json" };
      fetchOptions.body = JSON.stringify(payload);
    }

    const response = await api(`/api/runs/${encodeURIComponent(runId)}/${action}`, fetchOptions);
    const data = await response.json();

    if (data.status === "terminating") {
      showLifecycleFeedback("pending", `Termination requested for ${displayName} (${runId}); process shutdown is in progress.`);
    } else if (data.status === "already_terminated") {
      showLifecycleFeedback("pending", data.message || `Process ${displayName} (${runId}) is already terminated.`);
    } else if (data.status === "already_paused") {
      showLifecycleFeedback("pending", data.message || `Process ${displayName} (${runId}) is already paused.`);
    } else if (data.status === "already_running") {
      showLifecycleFeedback("pending", data.message || `Process ${displayName} (${runId}) is already running.`);
    } else {
      const pastTense = action === "stop" ? "stopped"
        : action === "kill" ? "killed"
        : action === "restart" ? "restarted"
        : action === "duplicate" ? "duplicated"
        : action === "resume" ? "resumed"
        : "paused";
      showLifecycleFeedback("success", data.message || `${displayName} ${pastTense} successfully.`);
    }

    if (action === "restart" || action === "duplicate") {
      const newRunId = data.new_run_id;
      await refreshRuns();
      if (newRunId) {
        if (!openRunIds.includes(newRunId)) {
          openRunIds.push(newRunId);
        }
        if (isCurrentSelection(generation, runId)) {
          await selectRun(newRunId);
        } else {
          renderWorkspaceTabs();
        }
      }
    } else {
      await refreshRuns();
      if (isCurrentSelection(generation, runId)) {
        await refreshSelected(generation, runId);
      }
    }
  } catch (error) {
    if (error.message === "locked") {
      showLogin("Session expired. Enter the current terminal login code again.");
      return;
    }
    const status = error.status;
    let errorMsg = error.message;
    if (status === 404) {
      errorMsg = `Process '${runId}' not found in registry (may have been deleted or invalid Run ID).`;
    } else if (status === 501) {
      errorMsg = error.message || "Pause/resume is not supported on Windows.";
    } else if (status === 503) {
      errorMsg = `Supervisor unreachable: ${error.message}`;
    }
    showLifecycleFeedback("error", errorMsg);
  } finally {
    lifecycleInFlightRunId = null;
    if (isCurrentSelection(generation, runId)) {
      updateLifecycleControls(getRun(selectedId));
    }
  }
}

function setupLifecycleListeners() {
  const stopBtn = $("#action-stop-btn");
  if (stopBtn) {
    stopBtn.addEventListener("click", () => {
      const run = getRun(selectedId);
      if (run) showLifecycleConfirm("stop", run);
    });
  }

  const killBtn = $("#action-kill-btn");
  if (killBtn) {
    killBtn.addEventListener("click", () => {
      const run = getRun(selectedId);
      if (run) showLifecycleConfirm("kill", run);
    });
  }

  const restartBtn = $("#action-restart-btn");
  if (restartBtn) {
    restartBtn.addEventListener("click", () => {
      const run = getRun(selectedId);
      if (run) executeLifecycleAction("restart", run.id);
    });
  }

  const duplicateBtn = $("#action-duplicate-btn");
  if (duplicateBtn) {
    duplicateBtn.addEventListener("click", () => {
      const run = getRun(selectedId);
      if (run) executeLifecycleAction("duplicate", run.id);
    });
  }

  const pauseBtn = $("#action-pause-btn");
  if (pauseBtn) {
    pauseBtn.addEventListener("click", () => {
      const run = getRun(selectedId);
      if (run) {
        const action = run.status === "paused" ? "resume" : "pause";
        executeLifecycleAction(action, run.id);
      }
    });
  }

  const confirmCancel = $("#confirm-cancel-btn");
  if (confirmCancel) confirmCancel.addEventListener("click", closeLifecycleConfirm);

  const confirmClose = $("#confirm-modal-close");
  if (confirmClose) confirmClose.addEventListener("click", closeLifecycleConfirm);

  const confirmSubmit = $("#confirm-submit-btn");
  if (confirmSubmit) confirmSubmit.addEventListener("click", submitLifecycleConfirm);

  if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !$("#lifecycle-confirm-modal")?.hidden) {
        closeLifecycleConfirm();
      }
    });
  }
}
