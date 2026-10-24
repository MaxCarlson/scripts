"use strict";

const $ = (selector) => document.querySelector(selector);
const ACTIVE = new Set(["pending", "running", "paused"]);
const STATUS_CLASS = { pending: "pending", running: "running", paused: "paused", finished: "finished", failed: "failed", lost: "lost" };
const VIEW_LIMIT = 512 * 1024;

let runs = [];
let selectedId = null;
let selectionGeneration = 0;
let authGeneration = 0;
let outputCursor = null;
let listTimer = null;
let outputTimer = null;
let outputRequestGeneration = null;
let lastOutput = "";
let outputFinished = false;

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
  if (response.status === 401) throw new Error("locked");
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail || message; } catch { /* Keep the generic message. */ }
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
$("#process-search").addEventListener("input", renderRuns);
$("#clear-search").addEventListener("click", () => { $("#process-search").value = ""; renderRuns(); });
$("#scroll-output").addEventListener("click", scrollOutputToEnd);
$("#output-text").addEventListener("scroll", () => {
  const node = $("#output-text");
  if (node.scrollHeight - node.scrollTop - node.clientHeight > 40) $("#follow-output").checked = false;
});
document.querySelectorAll(".tab-button").forEach((button) => button.addEventListener("click", () => selectTab(button.dataset.tab)));
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
    renderRuns();
    if (selectedId && !runs.some((run) => run.id === selectedId)) clearSelection();
    else if (selectedId) await refreshSelected(selectionGeneration, selectedId);
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
  $("#active-count").textContent = `${runs.filter((run) => ACTIVE.has(run.status)).length}`;
  $("#total-count").textContent = `${runs.length}`;
  $("#completed-count").textContent = `${runs.filter((run) => !ACTIVE.has(run.status)).length}`;
  $("#clear-search").hidden = !query;
  $("#list-state").textContent = filtered.length ? "" : query ? "No process matches this search." : "No managed processes yet. Start one with runmux run.";
  for (const run of filtered) {
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
    const command = document.createElement("span");
    command.className = "row-command";
    command.textContent = run.command;
    const meta = document.createElement("span");
    meta.className = "row-meta";
    meta.textContent = `${formatRuntime(run.runtime_seconds)} · ${relativeTime(run.started_at || run.created_at)}`;
    main.append(title, command, meta);
    const badge = document.createElement("span");
    badge.className = `status-badge ${STATUS_CLASS[run.status] || ""}`;
    badge.textContent = run.status;
    row.append(dot, main, badge);
    list.append(row);
  }
}

async function selectRun(runId) {
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
  await Promise.all([refreshSelected(generation, runId), refreshOutput(generation, runId)]);
  if (isCurrentSelection(generation, runId) && !outputFinished) {
    outputTimer = setInterval(() => refreshOutput(generation, runId), 900);
  }
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
    if (chunk.reset) { lastOutput = chunk.text; outputCursor = chunk.cursor; }
    else { lastOutput += chunk.text; outputCursor = chunk.cursor; }
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

function selectTab(tab) {
  const outputSelected = tab === "output";
  $("#tab-output").classList.toggle("active", outputSelected);
  $("#tab-output").setAttribute("aria-selected", `${outputSelected}`);
  $("#tab-details").classList.toggle("active", !outputSelected);
  $("#tab-details").setAttribute("aria-selected", `${!outputSelected}`);
  $("#output-pane").hidden = !outputSelected;
  $("#details-pane").hidden = outputSelected;
}

function clearSelection() {
  invalidateSelection();
  selectedId = null;
  outputCursor = null;
  $("#run-inspector").hidden = true;
  $("#empty-inspector").hidden = false;
  renderRuns();
}

function invalidateSelection() {
  selectionGeneration += 1;
  clearInterval(outputTimer);
  outputTimer = null;
  outputRequestGeneration = null;
}

function isCurrentSelection(generation, runId) {
  return generation === selectionGeneration && runId === selectedId;
}

function scrollOutputToEnd() {
  const node = $("#output-text");
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
