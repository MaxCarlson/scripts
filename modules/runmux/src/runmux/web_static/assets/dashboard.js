"use strict";

const $ = (selector) => document.querySelector(selector);
const STATUS_CLASS = { pending: "pending", running: "running", paused: "paused", finished: "finished", failed: "failed", lost: "lost" };
const STATUS_ORDER = ["running", "pending", "paused", "failed", "lost", "finished"];
const STATUS_LABEL = { running: "Running", pending: "Waiting", paused: "Paused", failed: "Failed", lost: "Disconnected", finished: "Completed" };
const VIEW_LIMIT = 512 * 1024;

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
    throw new Error(message);
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
$("#process-search").addEventListener("input", renderRuns);
$("#clear-search").addEventListener("click", () => { $("#process-search").value = ""; renderRuns(); });
$("#scroll-output").addEventListener("click", scrollOutputToEnd);
$("#output-text").addEventListener("scroll", () => {
  const node = $("#output-text");
  if (node.scrollHeight - node.scrollTop - node.clientHeight > 40) $("#follow-output").checked = false;
});
document.querySelectorAll(".tab-button").forEach((button) => button.addEventListener("click", () => selectTab(button.dataset.tab)));
$("#terminal-control-button").addEventListener("click", toggleTerminalControl);
$("#terminal-lock-button").addEventListener("click", requestTerminalLock);
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault(); $("#process-search").focus();
  }
  if (event.key === "Escape" && document.activeElement === $("#process-search")) {
    $("#process-search").value = ""; renderRuns(); $("#process-search").blur();
  }
});

async function refreshRuns() {
  const requestGeneration = authGeneration;
  try {
    const response = await api("/api/runs");
    const nextRuns = await response.json();
    if (requestGeneration !== authGeneration) return;
    runs = nextRuns;
    $("#last-updated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    $("#connection-state").className = "connection-state connected";
    $("#connection-state").lastElementChild.textContent = "Registry connected";
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
  const query = $("#process-search").value.trim().toLowerCase();
  const filtered = runs.filter((run) => `${run.name} ${run.command} ${run.status} ${run.id}`.toLowerCase().includes(query));
  const list = $("#process-list");
  list.replaceChildren();
  $("#process-count").textContent = `${filtered.length}`;
  $("#clear-search").hidden = !query;
  $("#list-state").textContent = filtered.length ? "" : query ? "No process matches this search." : "No managed processes yet.";
  $("#new-process-empty-button").hidden = Boolean(query) || runs.length > 0;
  const statuses = [...new Set(filtered.map((run) => run.status))].sort((left, right) => {
    const leftIndex = STATUS_ORDER.indexOf(left);
    const rightIndex = STATUS_ORDER.indexOf(right);
    return (leftIndex < 0 ? STATUS_ORDER.length : leftIndex) - (rightIndex < 0 ? STATUS_ORDER.length : rightIndex)
      || left.localeCompare(right);
  });
  for (const status of statuses) {
    const groupRuns = filtered.filter((run) => run.status === status);
    const group = document.createElement("details");
    group.className = "process-group";
    group.open = !collapsedGroups.has(status);
    group.addEventListener("toggle", () => {
      if (group.open) collapsedGroups.delete(status);
      else collapsedGroups.add(status);
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
    for (const run of groupRuns) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = `process-row${run.id === selectedId ? " selected" : ""}`;
      row.setAttribute("aria-current", run.id === selectedId ? "true" : "false");
      row.addEventListener("click", () => selectRun(run.id));
      const dot = document.createElement("span");
      dot.className = `row-dot ${STATUS_CLASS[run.status] || ""}`;
      const main = document.createElement("span");
      main.className = "row-main";
      const title = document.createElement("span");
      title.className = "row-title";
      title.textContent = run.name || run.command || "Unnamed process";
      title.title = run.name || run.command || "Unnamed process";
      const command = document.createElement("span");
      command.className = "row-command";
      command.textContent = run.command;
      command.title = run.command;
      const meta = document.createElement("span");
      meta.className = "row-meta";
      meta.textContent = `${formatRuntime(run.runtime_seconds)} · ${relativeTime(run.started_at || run.created_at)}`;
      main.append(title, command, meta);
      const badge = document.createElement("span");
      badge.className = `status-badge ${STATUS_CLASS[run.status] || ""}`;
      badge.textContent = run.status;
      row.append(dot, main, badge);
      group.append(row);
    }
    list.append(group);
  }
}

function renderWorkspaceTabs() {
  const tabs = $("#workspace-tabs");
  tabs.replaceChildren();
  const openedRuns = openRunIds.map((runId) => runs.find((run) => run.id === runId)).filter(Boolean);
  tabs.hidden = false;
  for (const run of openedRuns) {
    const tab = document.createElement("div");
    tab.className = `workspace-tab${run.id === selectedId ? " active" : ""}`;
    const activate = document.createElement("button");
    activate.type = "button";
    activate.className = "workspace-tab-select";
    activate.setAttribute("role", "tab");
    activate.setAttribute("aria-selected", `${run.id === selectedId}`);
    activate.title = run.name || run.command || "Unnamed process";
    activate.addEventListener("click", () => selectRun(run.id));
    const dot = document.createElement("span");
    dot.className = `row-dot ${STATUS_CLASS[run.status] || ""}`;
    const label = document.createElement("span");
    label.className = "workspace-tab-label";
    label.textContent = run.name || run.command || "Unnamed process";
    activate.append(dot, label);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "workspace-tab-close";
    close.setAttribute("aria-label", `Close ${run.name || run.command || "process"} view`);
    close.title = "Close view";
    close.textContent = "×";
    close.addEventListener("click", () => closeWorkspaceTab(run.id));
    tab.append(activate, close);
    tabs.append(tab);
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
}

function renderWorkspaceView() {
  $("#new-process-view").hidden = !newProcessOpen;
  $("#empty-inspector").hidden = newProcessOpen || Boolean(selectedId);
  $("#run-inspector").hidden = newProcessOpen || !selectedId;
}

async function openNewProcess() {
  newProcessOpen = true;
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
}

async function selectRun(runId) {
  newProcessOpen = false;
  if (selectedId === runId) {
    renderWorkspaceTabs();
    renderWorkspaceView();
    return;
  }
  if (!openRunIds.includes(runId)) openRunIds.push(runId);
  invalidateSelection();
  const generation = selectionGeneration;
  selectedId = runId;
  outputCursor = null;
  lastOutput = "";
  outputFinished = false;
  $("#output-text").textContent = "";
  $("#output-state").textContent = "Loading process output…";
  $("#output-state").hidden = false;
  $("#empty-inspector").hidden = true;
  $("#run-inspector").hidden = false;
  renderRuns();
  renderWorkspaceTabs();
  await Promise.all([refreshSelected(generation, runId), refreshOutput(generation, runId)]);
  if (isCurrentSelection(generation, runId) && !outputFinished) {
    outputTimer = setInterval(() => refreshOutput(generation, runId), 900);
  }
  if (isCurrentSelection(generation, runId) && !$("#terminal-pane").hidden) connectTerminal(generation, runId);
}

async function refreshSelected(generation = selectionGeneration, runId = selectedId) {
  if (!runId || !isCurrentSelection(generation, runId)) return;
  try {
    const response = await api(`/api/runs/${encodeURIComponent(runId)}`);
    const run = await response.json();
    if (!isCurrentSelection(generation, runId)) return;
    $("#selected-name").textContent = run.name || run.command || "Unnamed process";
    $("#selected-command").textContent = run.command;
    $("#selected-status").className = `status-badge ${STATUS_CLASS[run.status] || ""}`;
    $("#selected-status").textContent = run.status;
    $("#detail-id").textContent = run.id;
    $("#detail-pid").textContent = run.pid == null ? "—" : `${run.pid}`;
    $("#detail-exit").textContent = run.exit_code == null ? "—" : `${run.exit_code}`;
    $("#detail-runtime").textContent = formatRuntime(run.runtime_seconds);
    $("#detail-started").textContent = formatDate(run.started_at || run.created_at);
    $("#detail-ended").textContent = formatDate(run.ended_at);
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
    $("#output-text").textContent = lastOutput;
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
  $("#run-inspector").hidden = true;
  $("#empty-inspector").hidden = false;
  renderRuns();
  renderWorkspaceTabs();
}

function invalidateSelection() {
  selectionGeneration += 1;
  clearInterval(outputTimer);
  outputTimer = null;
  outputRequestGeneration = null;
  closeTerminal();
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
