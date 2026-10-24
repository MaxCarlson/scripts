"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function element(tagName = "div") {
  const listeners = new Map();
  const classes = new Set();
  return {
    tagName,
    children: [],
    attributes: {},
    dataset: {},
    hidden: false,
    _textContent: undefined,
    get textContent() {
      if (this._textContent !== undefined) return this._textContent;
      if (this.children.length > 0) {
        return this.children.map((c) => (typeof c === "string" ? c : c.textContent || "")).join("");
      }
      return "";
    },
    set textContent(val) {
      this._textContent = val;
      this.children = [];
    },
    value: "",
    checked: true,
    get className() {
      return [...classes].join(" ");
    },
    set className(val) {
      classes.clear();
      if (val) val.split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    },
    scrollHeight: 0,
    scrollTop: 0,
    clientHeight: 0,
    style: {},
    lastElementChild: { textContent: "" },
    classList: {
      add(...cs) { cs.forEach((c) => classes.add(c)); },
      remove(...cs) { cs.forEach((c) => classes.delete(c)); },
      toggle(c, force) {
        if (force === undefined) {
          if (classes.has(c)) { classes.delete(c); return false; }
          classes.add(c); return true;
        }
        if (force) { classes.add(c); return true; }
        classes.delete(c); return false;
      },
      contains(c) { return classes.has(c); },
    },
    addEventListener(name, handler) { listeners.set(name, handler); },
    dispatch(name, ...args) { listeners.get(name)?.(...args); },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    getAttribute(name) { return this.attributes[name] ?? null; },
    append(...children) { this._textContent = undefined; this.children.push(...children); },
    appendChild(child) { this._textContent = undefined; this.children.push(child); },
    replaceChildren(...children) { this._textContent = undefined; this.children = [...children]; },
    focus() {},
    blur() {},
    select() {},
    scrollIntoView() {},
    closest() { return null; },
  };
}

function dashboardHarness(storageData = new Map(), localData = new Map()) {
  const elements = new Map();
  const intervals = new Map();
  const requests = [];
  let nextInterval = 1;
  const document = {
    visibilityState: "visible",
    activeElement: { tagName: "BODY" },
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, element());
      return elements.get(selector);
    },
    querySelectorAll() { return []; },
    createElement(tagName) { return element(tagName); },
    createTextNode(text) { return { textContent: text, nodeType: 3 }; },
    addEventListener() {},
  };
  const fetch = (url) => {
    const pending = deferred();
    requests.push({ url: `${url}`, ...pending });
    return pending.promise;
  };
  const context = {
    document,
    fetch,
    AbortController,
    navigator: { clipboard: { writeText: async () => {} } },
    sessionStorage: {
      getItem(key) { return storageData.get(key) ?? null; },
      setItem(key, value) { storageData.set(key, `${value}`); },
      removeItem(key) { storageData.delete(key); },
    },
    localStorage: {
      getItem(key) { return localData.get(key) ?? null; },
      setItem(key, value) { localData.set(key, `${value}`); },
      removeItem(key) { localData.delete(key); },
      clear() { localData.clear(); },
    },
    TextEncoder,
    URLSearchParams,
    setInterval(callback, delay) {
      const id = nextInterval++;
      intervals.set(id, { callback, delay });
      return id;
    },
    clearInterval(id) { intervals.delete(id); },
    setTimeout(callback, delay) { return { callback, delay }; },
    clearTimeout() {},
    Date,
    console,
  };
  const source = fs.readFileSync(path.join(__dirname, "../src/runmux/web_static/assets/dashboard.js"), "utf8");
  vm.runInNewContext(`${source}\nglobalThis.__dashboard = {
    selectRun, clearSelection, refreshOutput, showLogin, terminalInputAllowed, sendTerminalInput, closeTerminal,
    renderRuns, renderWorkspaceTabs, closeWorkspaceTab, openNewProcess, submitLaunch, refreshSelected, refreshRuns,
    persistWorkspaceState, restoreRunViews, toggleExplorerCollapsed, resizeExplorerBy,
    getRun(id) { return runs.find((run) => run.id === id); },
    runCount() { return runs.length; },
    openRunIds() { return openRunIds; },
    explorerWidth() { return explorerWidth; },
    explorerCollapsed() { return explorerCollapsed; },
    updateTerminalControls,
    terminalReplayMessage,
    setRuns(value) { runs = value; },
    setTerminalTestState(socket, status) { terminalSocket = socket; terminalStatus = status; },
    classifyLogLine,
    normalizeSeverityLevel,
    matchesSeverityFilter,
    computeOutputSearchAndFilter,
    nextOutputMatch,
    prevOutputMatch,
    clearOutputSearch,
    setupOutputSearchListeners,
    getOutputMatches: () => outputMatches,
    getOutputActiveMatchIndex: () => outputActiveMatchIndex,
    getOutputSearchError: () => outputSearchError,
    getOutputSearchQuery: () => outputSearchQuery,
    setOutputSearchQuery: (q) => { outputSearchQuery = q; if ($("#output-search-query")) $("#output-search-query").value = q; computeOutputSearchAndFilter(); },
    setOutputSearchCase: (c) => { outputSearchCase = c; if ($("#output-search-case")) $("#output-search-case").setAttribute("aria-pressed", String(c)); computeOutputSearchAndFilter(); },
    onMatchNavigated,
    setOutputActiveMatchIndex: (idx) => { outputActiveMatchIndex = idx; onMatchNavigated(); },
    setOutputSeverityFilter: (f) => { outputSeverityFilter = f; if ($("#output-severity-filter")) $("#output-severity-filter").value = f; computeOutputSearchAndFilter(); },
    getLastOutput: () => lastOutput,
    setLastOutput: (val, truncated = false) => { lastOutput = val; outputTruncated = truncated; computeOutputSearchAndFilter(); },
    getOutputTruncated: () => outputTruncated,
    setSelectedId: (id) => { selectedId = id; },
    getSelectedId: () => selectedId,
    getOverviewMode: () => overviewMode,
    setOverviewMode,
    cycleOverviewMode,
    formatPercent,
    formatBytes,
    formatBytesRate,
    renderTelemetry,
    refreshTelemetry,
    startTelemetryPolling,
    stopTelemetryPolling,
    isTelemetryInFlight: () => telemetryInFlight,
    getTelemetryTimer: () => telemetryTimer,
  };`, context);
  return { context, elements, intervals, requests, storageData, getElement: (selector) => document.querySelector(selector) };
}

function response(payload) {
  return { ok: true, status: 200, json: async () => payload };
}

function run(id, name = id) {
  return {
    id,
    name,
    command: `${id}.exe`,
    status: "running",
    connection: "connected",
    pid: 100,
    exit_code: null,
    runtime_seconds: 1,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:00Z",
    ended_at: null,
  };
}

async function testRapidSelection() {
  const { context, elements, intervals, requests } = dashboardHarness();
  const firstA = context.__dashboard.selectRun("A");
  const selectB = context.__dashboard.selectRun("B");
  const secondA = context.__dashboard.selectRun("A");
  await Promise.resolve();

  const detailRequests = requests.filter((item) => !item.url.includes("/output") && !item.url.includes("/telemetry"));
  const telemetryRequests = requests.filter((item) => item.url.includes("/telemetry"));
  const outputRequests = requests.filter((item) => item.url.includes("/output"));
  assert.equal(detailRequests.length, 3);
  assert.equal(outputRequests.length, 3);

  detailRequests[2].resolve(response(run("A", "latest A")));
  outputRequests[2].resolve(response({ state: "available", text: "latest output", cursor: "latest", reset: true, at_end: false, finished: false }));
  if (telemetryRequests[2]) telemetryRequests[2].resolve(response({ id: "A", cpu_percent: 10.0, rss_bytes: 1024 }));
  await secondA;
  detailRequests[0].resolve(response(run("A", "stale A")));
  outputRequests[0].resolve(response({ state: "available", text: "stale A output", cursor: "old", reset: true, at_end: false, finished: false }));
  if (telemetryRequests[0]) telemetryRequests[0].resolve(response({ id: "A", cpu_percent: 5.0, rss_bytes: 1024 }));
  detailRequests[1].resolve(response(run("B", "stale B")));
  outputRequests[1].resolve(response({ state: "available", text: "stale B output", cursor: "old", reset: true, at_end: false, finished: false }));
  if (telemetryRequests[1]) telemetryRequests[1].resolve(response({ id: "B", cpu_percent: 5.0, rss_bytes: 1024 }));
  await Promise.all([firstA, selectB]);

  assert.equal(elements.get("#selected-name").textContent, "latest A");
  assert.equal(elements.get("#output-text").textContent, "latest output");
  assert.equal(intervals.size, 2); // outputTimer and telemetryTimer
  const currentOutputRequests = requests.filter((item) => item.url.includes("/output"));
  assert.equal(currentOutputRequests.length, 3);
  context.__dashboard.refreshOutput();
  context.__dashboard.refreshOutput();
  await Promise.resolve();
  assert.equal(requests.filter((item) => item.url.includes("/output")).length, 4);
  const outputRequestsAfterOverlap = requests.filter((item) => item.url.includes("/output"));
  outputRequestsAfterOverlap[3].resolve(response({ state: "available", text: "tail", cursor: "next", reset: false, at_end: false, finished: false }));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(elements.get("#output-text").textContent, "latest outputtail");
  context.__dashboard.refreshOutput();
  await Promise.resolve();
  assert.match(requests.filter((item) => item.url.includes("/output"))[4].url, /cursor=next/);
}

async function testClearInvalidatesPendingSelection() {
  const { context, elements, intervals, requests } = dashboardHarness();
  const pending = context.__dashboard.selectRun("A");
  context.__dashboard.clearSelection();
  await Promise.resolve();

  for (const request of requests) {
    if (request.url.includes("/output")) {
      request.resolve(response({ state: "available", text: "stale output", cursor: "stale", reset: true, at_end: false, finished: false }));
    } else {
      request.resolve(response(run("A", "stale details")));
    }
  }
  await pending;

  assert.equal(elements.get("#selected-name")?.textContent || "", "");
  assert.equal(elements.get("#output-text")?.textContent || "", "");
  assert.equal(intervals.size, 0);

  const loggedOut = dashboardHarness();
  const pendingAfterLogout = loggedOut.context.__dashboard.selectRun("B");
  loggedOut.context.__dashboard.showLogin("locked");
  await Promise.resolve();
  for (const request of loggedOut.requests) {
    request.resolve(response(request.url.includes("/output")
      ? { state: "available", text: "stale output", cursor: "stale", reset: true, at_end: false, finished: false }
      : run("B", "stale details")));
  }
  await pendingAfterLogout;
  assert.equal(loggedOut.getElement("#selected-name").textContent, "");
  assert.equal(loggedOut.getElement("#output-text").textContent, "");
  assert.equal(loggedOut.intervals.size, 0);
}

async function testTerminalInputRequiresSupervisorLockAndCleanupClosesOnlySocket() {
  const { context } = dashboardHarness();
  const sent = [];
  const closed = [];
  const socket = {
    readyState: 1,
    send(value) { sent.push(value); },
    close(code, reason) { closed.push({ code, reason }); this.readyState = 3; },
  };

  context.__dashboard.setTerminalTestState(socket, { mode: "view", session_holds_lock: false });
  assert.equal(context.__dashboard.terminalInputAllowed(), false);
  assert.equal(context.__dashboard.sendTerminalInput("view input"), false);
  context.__dashboard.setTerminalTestState(socket, { mode: "interact", session_holds_lock: false });
  assert.equal(context.__dashboard.terminalInputAllowed(), false);
  assert.equal(context.__dashboard.sendTerminalInput("queued input"), false);
  context.__dashboard.setTerminalTestState(socket, { mode: "interact", session_holds_lock: true });
  assert.equal(context.__dashboard.terminalInputAllowed(), true);
  assert.equal(context.__dashboard.sendTerminalInput("authorized input"), true);
  assert.deepEqual(Array.from(sent[0]), Array.from(new TextEncoder().encode("authorized input")));

  context.__dashboard.setTerminalTestState(socket, { mode: "view", session_holds_lock: false, finished: true });
  context.__dashboard.updateTerminalControls();
  assert.equal(context.document.querySelector("#terminal-control-button").disabled, true);
  assert.equal(context.document.querySelector("#terminal-lock-button").disabled, true);

  context.__dashboard.closeTerminal();
  assert.deepEqual(closed, [{ code: 1000, reason: "terminal view closed" }]);
  assert.equal(socket.readyState, 3);
}

async function testStatusGroupsAndBrowserOnlyWorkspaceTabs() {
  const { context, requests, getElement } = dashboardHarness();
  context.__dashboard.setRuns([
    run("A", "active worker"),
    { ...run("B", "failed worker"), status: "failed" },
    { ...run("C", "completed worker"), status: "finished" },
  ]);
  context.__dashboard.renderRuns();
  const groups = getElement("#process-list").children;
  assert.deepEqual(groups.map((group) => group.children[0].children[0].textContent), ["Running", "Failed", "Completed"]);
  assert.deepEqual(groups.map((group) => group.children.length - 1), [1, 1, 1]);

  const first = context.__dashboard.selectRun("A");
  await Promise.resolve();
  for (const request of requests) {
    request.resolve(response(request.url.includes("/output")
      ? { state: "available", text: "A output", cursor: "A", reset: true, at_end: true, finished: true }
      : run("A", "active worker")));
  }
  await first;
  assert.equal(getElement("#workspace-tabs").children.length, 2);
  assert.equal(getElement("#workspace-tabs").children[0].children[0].children[1].textContent, "active worker");

  const second = context.__dashboard.selectRun("B");
  await Promise.resolve();
  for (const request of requests.slice(2)) {
    request.resolve(response(request.url.includes("/output")
      ? { state: "available", text: "B output", cursor: "B", reset: true, at_end: true, finished: true }
      : run("B", "failed worker")));
  }
  await second;
  assert.equal(getElement("#workspace-tabs").children.length, 3);

  const closeSelected = context.__dashboard.closeWorkspaceTab("B");
  await Promise.resolve();
  for (const request of requests.slice(4)) {
    request.resolve(response(request.url.includes("/output")
      ? { state: "available", text: "A output", cursor: "A2", reset: true, at_end: true, finished: true }
      : run("A", "active worker")));
  }
  await closeSelected;
  assert.equal(getElement("#workspace-tabs").children.length, 2);
  assert.equal(getElement("#workspace-tabs").children[0].children[0].attributes["aria-selected"], "true");
  assert.equal(getElement("#process-list").children[1].children.length, 2);
}

async function testNewProcessTabShowsOnEmptyRegistryAndLaunchSubmitsOnce() {
  const { context, requests, getElement } = dashboardHarness();
  context.__dashboard.setRuns([]);
  context.__dashboard.renderRuns();
  context.__dashboard.renderWorkspaceTabs();
  assert.equal(getElement("#new-process-empty-button").hidden, false);
  assert.equal(getElement("#workspace-tabs").children.length, 1);
  assert.equal(getElement("#workspace-tabs").children[0].textContent, "+");

  const opening = context.__dashboard.openNewProcess();
  await Promise.resolve();
  assert.equal(requests[0].url, "/api/launch-defaults");
  requests[0].resolve(response({ cwd: "C:/synthetic" }));
  await opening;
  getElement("#launch-program").value = "python.exe";
  getElement("#launch-arguments").value = "-c\nprint('two words')\nvalue with spaces";
  getElement("#launch-name").value = "synthetic job";
  getElement("#launch-cwd").value = "C:/synthetic";
  const submission = context.__dashboard.submitLaunch({ preventDefault() {} });
  await Promise.resolve();
  const launchRequest = requests[1];
  assert.equal(getElement("#launch-submit").disabled, true);
  await context.__dashboard.submitLaunch({ preventDefault() {} });
  assert.equal(requests.filter((item) => item.url === "/api/runs").length, 1);
  launchRequest.resolve(response(run("new-run", "synthetic job")));
  await Promise.resolve();
  for (const item of requests.slice(2)) {
    item.resolve(response(item.url.includes("/output")
      ? { state: "available", text: "started", cursor: "c1", reset: true, at_end: false, finished: false }
      : run("new-run", "synthetic job")));
  }
  await submission;
  assert.equal(getElement("#workspace-tabs").children.length, 2);
  assert.equal(getElement("#selected-name").textContent, "synthetic job");
  assert.equal(getElement("#output-text").textContent, "started");
  assert.equal(getElement("#launch-submit").disabled, false);
}

async function testOutputNormalizesCarriageReturnsAcrossChunks() {
  const { context, requests, getElement } = dashboardHarness();
  const selected = context.__dashboard.selectRun("A");
  await Promise.resolve();
  requests.find((item) => !item.url.includes("/output")).resolve(response(run("A")));
  requests.find((item) => item.url.includes("/output")).resolve(response({
    state: "available", text: "plain one\rplain two\r", cursor: "first", reset: true,
    at_end: false, finished: false,
  }));
  await selected;

  context.__dashboard.refreshOutput();
  await Promise.resolve();
  requests.filter((item) => item.url.includes("/output"))[1].resolve(response({
    state: "available", text: "\nprogress 1\rprogress 2\r\nwide: 界🙂\n", cursor: "last",
    reset: false, at_end: true, finished: true,
  }));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(getElement("#output-text").textContent, "plain one\nplain two\nprogress 1\nprogress 2\nwide: 界🙂\n");
}

async function testFollowOutputSuspendsOnScrollAndJumpResumesIt() {
  const { context, getElement } = dashboardHarness();
  const output = getElement("#output-text");
  const follow = getElement("#follow-output");
  output.scrollHeight = 1000;
  output.clientHeight = 100;
  output.scrollTop = 0;

  output.dispatch("scroll");
  assert.equal(follow.checked, false);

  getElement("#scroll-output").dispatch("click");
  assert.equal(output.scrollTop, output.scrollHeight);
  assert.equal(follow.checked, true);
}

async function testOutputHistoryStaysWithinConfiguredViewLimit() {
  const { context, requests, getElement } = dashboardHarness();
  const selected = context.__dashboard.selectRun("A");
  await Promise.resolve();
  requests.find((item) => !item.url.includes("/output")).resolve(response(run("A")));
  requests.find((item) => item.url.includes("/output")).resolve(response({
    state: "available", text: "x".repeat(600 * 1024), cursor: "large", reset: true,
    at_end: false, finished: false,
  }));
  await selected;

  const outputText = getElement("#output-text").textContent;
  assert.equal(outputText.length, 512 * 1024);
  assert.equal(outputText, "x".repeat(512 * 1024));
}

async function testTruncatedTerminalReplayWarnsThatScreenMayBeIncomplete() {
  const { context } = dashboardHarness();
  assert.match(context.__dashboard.terminalReplayMessage(true), /screen may be incomplete/i);
  assert.equal(context.__dashboard.terminalReplayMessage(false), "");
}

function testExplorerGroupingFilteringSortingAndEmptyMessages() {
  const { context, getElement } = dashboardHarness();
  context.__dashboard.setRuns([
    { ...run("id-a", "zulu"), status: "running", created_at: "2026-01-02T00:00:00Z", started_at: "2026-01-02T00:00:00Z", runtime_seconds: 30 },
    { ...run("id-b", "alpha"), status: "failed", created_at: "2026-01-03T00:00:00Z", started_at: "2026-01-03T00:00:00Z", runtime_seconds: 10 },
    { ...run("id-c", "beta"), status: "finished", created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z", runtime_seconds: 20 },
  ]);

  getElement("#process-grouping").value = "none";
  getElement("#process-grouping").dispatch("change");
  getElement("#process-sort").value = "name";
  getElement("#process-sort").dispatch("change");
  context.__dashboard.renderRuns();
  assert.deepEqual(getElement("#process-list").children.map((row) => row.children[1].children[0].textContent), ["alpha", "beta", "zulu"]);

  for (const [sort, names] of [
    ["recent", ["alpha", "zulu", "beta"]],
    ["started", ["alpha", "zulu", "beta"]],
    ["duration", ["zulu", "beta", "alpha"]],
    ["status", ["zulu", "alpha", "beta"]],
  ]) {
    getElement("#process-sort").value = sort;
    getElement("#process-sort").dispatch("change");
    assert.deepEqual(getElement("#process-list").children.map((row) => row.children[1].children[0].textContent), names);
  }
  getElement("#process-sort").value = "name";
  getElement("#process-sort").dispatch("change");

  getElement("#process-status-filter").value = "failed";
  getElement("#process-status-filter").dispatch("change");
  context.__dashboard.renderRuns();
  assert.equal(getElement("#process-count").textContent, "1");
  assert.equal(getElement("#process-list").children[0].title, "alpha · id-b");

  getElement("#process-search").value = "not present";
  context.__dashboard.renderRuns();
  assert.equal(getElement("#list-state").textContent, "No processes match these filters.");
  assert.equal(getElement("#new-process-empty-button").hidden, true);
}

function testExplorerPaginationKeepsDomBoundedAndSearchesAllRuns() {
  const { context, getElement } = dashboardHarness();
  getElement("#process-grouping").value = "none";
  getElement("#process-grouping").dispatch("change");
  context.__dashboard.setRuns(Array.from({ length: 450 }, (_, index) => run(`run-${index}`, `worker ${index}`)));
  context.__dashboard.renderRuns();
  assert.equal(getElement("#process-count").textContent, "450");
  assert.equal(getElement("#process-list").children.length, 100);
  assert.equal(getElement("#process-page-state").textContent, "1 / 5");

  getElement("#process-next-page").dispatch("click");
  assert.equal(getElement("#process-page-state").textContent, "2 / 5");
  assert.equal(getElement("#process-list").children.length, 100);
  getElement("#process-search").value = "worker 449";
  context.__dashboard.renderRuns();
  assert.equal(getElement("#process-count").textContent, "1");
  assert.equal(getElement("#process-list").children.length, 1);
}

async function testWorkspaceSessionStorageRestoresOnlyValidRunIdsAndSafePreferences() {
  const { context, requests, storageData, getElement } = dashboardHarness();
  context.__dashboard.setRuns([
    { ...run("run-safe", "visible name"), command: "private-command.exe", cwd: "C:/private" },
    run("run-stale", "stale"),
  ]);
  const selected = context.__dashboard.selectRun("run-safe");
  await Promise.resolve();
  for (const request of requests) {
    request.resolve(response(request.url.includes("/output")
      ? { state: "available", text: "secret output", cursor: "c1", reset: true, at_end: true, finished: true }
      : { ...run("run-safe", "visible name"), command: "private-command.exe", cwd: "C:/private" }));
  }
  await selected;
  getElement("#process-search").value = "safe query";
  getElement("#process-search").dispatch("input");
  getElement("#process-grouping").value = "none";
  getElement("#process-grouping").dispatch("change");
  getElement("#process-sort").value = "name";
  getElement("#process-sort").dispatch("change");
  context.__dashboard.persistWorkspaceState();
  const raw = storageData.get("runmux-workspace-v1");
  assert.ok(raw.includes("run-safe"));
  assert.ok(!raw.includes("private-command"));
  assert.ok(!raw.includes("C:/private"));
  assert.ok(!raw.includes("secret output"));
  const stored = JSON.parse(raw);
  stored.openRunIds.push("run-stale");
  stored.selectedId = "run-stale";
  storageData.set("runmux-workspace-v1", JSON.stringify(stored));

  const restored = dashboardHarness(storageData);
  restored.context.__dashboard.setRuns([run("run-safe", "visible name")]);
  const selectedId = restored.context.__dashboard.restoreRunViews();
  assert.equal(selectedId, "run-safe");
  assert.deepEqual(Array.from(restored.context.__dashboard.openRunIds()), ["run-safe"]);
  assert.equal(restored.getElement("#process-grouping").value, "none");
  assert.equal(restored.getElement("#process-search").value, "safe query");

  const malformedStorage = new Map([["runmux-workspace-v1", "{" ]]);
  const safeDefaults = dashboardHarness(malformedStorage);
  assert.equal(safeDefaults.getElement("#process-grouping").value, "status");
  assert.equal(safeDefaults.getElement("#process-search").value, "");
}

async function testDuplicateNameRunsKeepDistinctTabIdentityAndCloseOnlyView() {
  const { context, requests, getElement } = dashboardHarness();
  context.__dashboard.setRuns([
    run("20261024-120000-a1b2c3", "same worker"),
    run("20261024-120001-d4e5f6", "same worker"),
  ]);
  context.__dashboard.renderRuns();
  const rows = getElement("#process-list").children[0].children.slice(1);
  assert.equal(rows.length, 2);
  assert.notEqual(rows[0].title, rows[1].title);

  const first = context.__dashboard.selectRun("20261024-120000-a1b2c3");
  await Promise.resolve();
  for (const request of requests) request.resolve(response(request.url.includes("/output")
    ? { state: "available", text: "", cursor: "", reset: true, at_end: true, finished: true }
    : run("20261024-120000-a1b2c3", "same worker")));
  await first;
  const second = context.__dashboard.selectRun("20261024-120001-d4e5f6");
  await Promise.resolve();
  for (const request of requests.slice(2)) request.resolve(response(request.url.includes("/output")
    ? { state: "available", text: "", cursor: "", reset: true, at_end: true, finished: true }
    : run("20261024-120001-d4e5f6", "same worker")));
  await second;

  const tabs = getElement("#workspace-tabs").children.slice(0, 2);
  assert.equal(tabs.length, 2);
  assert.deepEqual(tabs.map((tab) => tab.children[0].children.at(-1).textContent), ["a1b2c3", "d4e5f6"]);
  context.__dashboard.closeWorkspaceTab("20261024-120001-d4e5f6");
  assert.equal(context.__dashboard.runCount(), 2);
}

async function testSelectedDetailRefreshReconcilesExplorerStatusByRunId() {
  const { context, requests, getElement } = dashboardHarness();
  context.__dashboard.setRuns([run("run-a", "active worker"), run("run-b", "other worker")]);
  const selected = context.__dashboard.selectRun("run-a");
  await Promise.resolve();
  for (const request of requests) request.resolve(response(request.url.includes("/output")
    ? { state: "available", text: "", cursor: "", reset: true, at_end: true, finished: true }
    : run("run-a", "active worker")));
  await selected;

  const detail = context.__dashboard.refreshSelected();
  await Promise.resolve();
  requests.at(-1).resolve(response({ ...run("run-a", "active worker"), status: "finished", exit_code: 0 }));
  await detail;
  assert.equal(context.__dashboard.getRun("run-a").status, "finished");
  assert.equal(context.__dashboard.getRun("run-b").status, "running");
  assert.equal(getElement("#selected-status").textContent, "Completed");
}

function testExplorerResizeAndCollapseStateCanBeChangedAccessibly() {
  const { context, getElement } = dashboardHarness();
  context.__dashboard.resizeExplorerBy(24);
  assert.equal(context.__dashboard.explorerWidth(), 324);
  context.__dashboard.toggleExplorerCollapsed();
  assert.equal(context.__dashboard.explorerCollapsed(), true);
  assert.equal(getElement("#explorer-toggle").attributes["aria-expanded"], "false");
}


function testLogClassificationAndSeverityFiltering() {
  const { context, getElement } = dashboardHarness();
  const d = context.__dashboard;

  // 1. Classification
  assert.equal(d.classifyLogLine("[ERROR] Connection refused"), "error");
  assert.equal(d.classifyLogLine("2026-10-24 10:00:00 [INFO] Listening on port 8080"), "info");
  assert.equal(d.classifyLogLine("WARNING: High CPU load detected"), "warn");
  assert.equal(d.classifyLogLine("error: failed to open config.yaml"), "error");
  assert.equal(d.classifyLogLine('{"level": "error", "message": "panic"}'), "error");
  assert.equal(d.classifyLogLine('timestamp=123 level=warn msg="retrying"'), "warn");
  assert.equal(d.classifyLogLine("2026-10-24 12:00:00 - app - DEBUG - query params"), "debug");
  assert.equal(d.classifyLogLine("Progress: 45% (120/300 files)"), "other");
  assert.equal(d.classifyLogLine("An error occurred in user input during normal run"), "other");
  assert.equal(d.classifyLogLine("Random unstructured log line 1234"), "other");

  // 2. matchesSeverityFilter
  assert.equal(d.matchesSeverityFilter("error", "all"), true);
  assert.equal(d.matchesSeverityFilter("other", "all"), true);
  assert.equal(d.matchesSeverityFilter("error", "error"), true);
  assert.equal(d.matchesSeverityFilter("warn", "error"), false);
  assert.equal(d.matchesSeverityFilter("error", "warn"), true);
  assert.equal(d.matchesSeverityFilter("warn", "warn"), true);
  assert.equal(d.matchesSeverityFilter("info", "warn"), false);
  assert.equal(d.matchesSeverityFilter("info", "info"), true);
  assert.equal(d.matchesSeverityFilter("debug", "debug"), true);
  assert.equal(d.matchesSeverityFilter("other", "other"), true);
  assert.equal(d.matchesSeverityFilter("error", "other"), false);

  // 3. Output filtering in dashboard
  const logs = [
    "[INFO] System boot",
    "[WARN] Disk threshold 80%",
    "[ERROR] Out of memory",
    "Unstructured progress trace",
  ].join("\n");

  d.setLastOutput(logs);
  assert.equal(getElement("#output-scope-note").textContent, "Loaded buffer: 4 lines · 94 B");

  // Filter to errors only
  d.setOutputSeverityFilter("error");
  assert.equal(getElement("#output-scope-note").textContent, "Showing 1 of 4 lines (loaded buffer)");
  assert.match(getElement("#output-text").textContent, /Out of memory/);
  assert.doesNotMatch(getElement("#output-text").textContent, /System boot/);

  // Filter to other (unstructured)
  d.setOutputSeverityFilter("other");
  assert.equal(getElement("#output-scope-note").textContent, "Showing 1 of 4 lines (loaded buffer)");
  assert.match(getElement("#output-text").textContent, /Unstructured progress trace/);
  assert.doesNotMatch(getElement("#output-text").textContent, /Out of memory/);

  // Reset to all
  d.setOutputSeverityFilter("all");
  assert.equal(getElement("#output-scope-note").textContent, "Loaded buffer: 4 lines · 94 B");
  assert.equal(getElement("#output-text").textContent, logs);
}

function testBoundedOutputLiteralSearchAndReDoSProtection() {
  const { context, getElement } = dashboardHarness();
  const d = context.__dashboard;

  const logs = [
    "[INFO] Worker 1 started on port 8080",
    "[WARN] Worker 1 high load",
    "[ERROR] worker 2 terminated",
    "Batch completed successfully",
  ].join("\n");

  d.setLastOutput(logs);

  // 1. Plain search (case insensitive by default)
  d.setOutputSearchQuery("worker");
  assert.equal(d.getOutputMatches().length, 3);
  assert.equal(getElement("#output-search-count").textContent, "1 of 3 (loaded buffer)");
  assert.equal(getElement("#output-search-clear").hidden, false);
  assert.equal(getElement("#output-search-prev").disabled, false);
  assert.equal(getElement("#output-search-next").disabled, false);

  // 2. Case sensitive search
  d.setOutputSearchCase(true);
  d.computeOutputSearchAndFilter();
  assert.equal(d.getOutputMatches().length, 1);
  assert.equal(getElement("#output-search-count").textContent, "1 of 1 (loaded buffer)");

  // 3. Literal search handles special regex characters literally without error
  d.setOutputSearchCase(false);
  d.setOutputSearchQuery("[INFO]");
  d.computeOutputSearchAndFilter();
  assert.equal(d.getOutputMatches().length, 1);
  assert.equal(d.getOutputMatches()[0].text, "[INFO]");
  assert.equal(getElement("#output-search-count").textContent, "1 of 1 (loaded buffer)");

  // 4. Invalid unescaped regex pattern characters are safe and match literally
  d.setOutputSearchQuery("[invalid(");
  d.computeOutputSearchAndFilter();
  assert.equal(d.getOutputMatches().length, 0);
  assert.equal(d.getOutputSearchError(), null);
  assert.equal(getElement("#output-search-count").textContent, "0 matches (loaded buffer)");
  assert.equal(getElement("#output-search-prev").disabled, true);
  assert.equal(getElement("#output-search-next").disabled, true);

  // 5. ReDoS Catastrophic Backtracking Protection:
  // Testing pattern (a+)+$ against 100 'a's + 'b' executes safely in <50ms as a literal search
  const pathologicalString = "a".repeat(100) + "b";
  d.setLastOutput(pathologicalString);
  const start = Date.now();
  d.setOutputSearchQuery("(a+)+$");
  d.computeOutputSearchAndFilter();
  const duration = Date.now() - start;
  assert.ok(duration < 50, `Literal search took too long: ${duration}ms`);
  assert.equal(d.getOutputMatches().length, 0);
  assert.equal(getElement("#output-search-count").textContent, "0 matches (loaded buffer)");

  // 6. Clear search
  d.clearOutputSearch();
  assert.equal(d.getOutputMatches().length, 0);
  assert.equal(d.getOutputSearchQuery(), "");
  assert.equal(getElement("#output-search-count").textContent, "No query");
  assert.equal(getElement("#output-search-clear").hidden, true);
}

function testPathologicalBufferDomBoundingAndAccurateLabels() {
  const { context, getElement } = dashboardHarness();
  const d = context.__dashboard;
  const container = getElement("#output-text");

  // Generate 5,000 short lines (simulating a pathological high-line-count buffer)
  const lines = [];
  for (let i = 0; i < 5000; i++) {
    lines.push(`synthetic log line ${i} event-payload`);
  }
  d.setLastOutput(lines.join("\n"));

  // 1. With search active, DOM rendering bounds span.output-line elements to MAX_RENDER_LINES = 2000
  d.setOutputSearchQuery("synthetic");
  d.computeOutputSearchAndFilter();

  const renderedLines = container.children.filter((c) => c.className === "output-line");
  assert.equal(renderedLines.length, 2000, "DOM lines must be bounded to MAX_RENDER_LINES");
  assert.equal(d.getOutputMatches().length, 5000, "Search must count all matches across loaded buffer");

  // 2. Accurate search count and scope note when partially displayed
  const countText = getElement("#output-search-count").textContent;
  assert.equal(countText, "1 of 5,000 (loaded buffer · lines 1–2,000 displayed)");

  const scopeNote = getElement("#output-scope-note").textContent;
  assert.match(scopeNote, /Loaded buffer: 5,000 lines · \d+ \w+ \(displaying lines 1–2,000\)/);

  // 3. Navigation across large buffer slides the displayed window to active match
  // Navigate directly to match 3,500 using helper
  d.setOutputActiveMatchIndex(3500);
  assert.equal(d.getOutputActiveMatchIndex(), 3500);
  const countAfterNav = getElement("#output-search-count").textContent;
  assert.equal(countAfterNav, "3,501 of 5,000 (loaded buffer · lines 2,501–4,500 displayed)");

  // Test incremental nextOutputMatch navigation
  d.nextOutputMatch();
  assert.equal(d.getOutputActiveMatchIndex(), 3501);
  assert.equal(getElement("#output-search-count").textContent, "3,502 of 5,000 (loaded buffer · lines 2,502–4,501 displayed)");

  // Active match element must be rendered in DOM
  const activeMark = container.children
    .flatMap((c) => c.children || [])
    .find((m) => m.className && m.className.includes("active-match"));
  assert.ok(activeMark, "Active match element must be rendered in DOM");

  // 4. High match density on a single line / slice bounds <mark> elements to MAX_RENDER_MATCHES = 500
  const denseLine = "word ".repeat(1000);
  d.setLastOutput(denseLine);
  d.setOutputSearchQuery("word");
  d.computeOutputSearchAndFilter();
  assert.equal(d.getOutputMatches().length, 1000);
  const markCount = container.children
    .flatMap((c) => c.children || [])
    .filter((m) => m.tagName && m.tagName.toLowerCase() === "mark").length;
  assert.equal(markCount, 500, "Rendered mark tags must be bounded to MAX_RENDER_MATCHES");

  d.clearOutputSearch();
}

function testOutputMatchNavigationAndFollowCoordination() {
  const { context, getElement } = dashboardHarness();
  const d = context.__dashboard;

  const logs = [
    "alpha line one",
    "alpha line two",
    "alpha line three",
  ].join("\n");

  d.setLastOutput(logs);
  d.setOutputSearchQuery("alpha");
  assert.equal(d.getOutputMatches().length, 3);
  assert.equal(d.getOutputActiveMatchIndex(), 0);
  assert.equal(getElement("#output-search-count").textContent, "1 of 3 (loaded buffer)");

  // Initially follow is checked
  getElement("#follow-output").checked = true;

  // Next match moves to index 1 and unchecks follow
  d.nextOutputMatch();
  assert.equal(d.getOutputActiveMatchIndex(), 1);
  assert.equal(getElement("#output-search-count").textContent, "2 of 3 (loaded buffer)");
  assert.equal(getElement("#follow-output").checked, false);

  // Next match moves to index 2
  d.nextOutputMatch();
  assert.equal(d.getOutputActiveMatchIndex(), 2);
  assert.equal(getElement("#output-search-count").textContent, "3 of 3 (loaded buffer)");

  // Wrap around to index 0
  d.nextOutputMatch();
  assert.equal(d.getOutputActiveMatchIndex(), 0);
  assert.equal(getElement("#output-search-count").textContent, "1 of 3 (loaded buffer)");

  // Prev match wraps back to index 2
  d.prevOutputMatch();
  assert.equal(d.getOutputActiveMatchIndex(), 2);
  assert.equal(getElement("#output-search-count").textContent, "3 of 3 (loaded buffer)");

  // Jump to latest re-enables follow
  getElement("#scroll-output").dispatch("click");
  assert.equal(getElement("#follow-output").checked, true);
}

function testOutputSearchAndFilterAccurateScopeLabeling() {
  const { context, getElement } = dashboardHarness();
  const d = context.__dashboard;

  const logs = "line 1\nline 2\nline 3\n[ERROR] line 4";

  // Full buffer (not truncated)
  d.setLastOutput(logs, false);
  assert.match(getElement("#output-scope-note").textContent, /Loaded buffer: 4 lines/);

  d.setOutputSearchQuery("line");
  assert.equal(getElement("#output-search-count").textContent, "1 of 4 (loaded buffer)");

  // Filtered scope
  d.setOutputSeverityFilter("error");
  assert.equal(getElement("#output-scope-note").textContent, "Showing 1 of 4 lines (loaded buffer)");
  assert.equal(getElement("#output-search-count").textContent, "1 of 1 (loaded buffer)");

  // Truncated tail (chunk.truncated === true)
  d.setOutputSeverityFilter("all");
  d.setLastOutput(logs, true);
  assert.match(getElement("#output-scope-note").textContent, /Loaded tail · earlier output omitted: 4 lines/);
  assert.equal(getElement("#output-search-count").textContent, "1 of 4 (loaded tail · earlier output omitted)");

  // 0 matches in truncated tail
  d.setOutputSearchQuery("nonexistent");
  assert.equal(getElement("#output-search-count").textContent, "0 matches (loaded tail · earlier output omitted)");
}

async function testOutputLiveStreamingUpdatesSearchAndFilter() {
  const { context, getElement, requests } = dashboardHarness();
  const d = context.__dashboard;

  const runPromise = d.selectRun("stream-run");
  await Promise.resolve();

  // Initial chunk arrives with 2 errors
  const detailReq = requests.find((r) => !r.url.includes("/output"));
  const outputReq = requests.find((r) => r.url.includes("/output"));
  detailReq.resolve(response(run("stream-run", "stream worker")));
  outputReq.resolve(response({
    state: "available",
    text: "[ERROR] first fail\n[INFO] running\n[ERROR] second fail\n",
    cursor: "cur1",
    reset: true,
    truncated: false,
    at_end: false,
    finished: false,
  }));
  await runPromise;

  // Set search query to "ERROR"
  d.setOutputSearchQuery("ERROR");
  assert.equal(d.getOutputMatches().length, 2);
  assert.equal(getElement("#output-search-count").textContent, "1 of 2 (loaded buffer)");

  // Streaming chunk arrives with a 3rd error
  d.refreshOutput();
  await Promise.resolve();
  const nextOutputReq = requests.filter((r) => r.url.includes("/output")).at(-1);
  nextOutputReq.resolve(response({
    state: "available",
    text: "[ERROR] third fail\n",
    cursor: "cur2",
    reset: false,
    truncated: false,
    at_end: false,
    finished: false,
  }));
  await new Promise((resolve) => setImmediate(resolve));

  // Search matches should automatically update to 3!
  assert.equal(d.getOutputMatches().length, 3);
  assert.equal(getElement("#output-search-count").textContent, "1 of 3 (loaded buffer)");
}

function testOutputTextSecurityAndXssImmunity() {
  const { context, getElement } = dashboardHarness();
  const d = context.__dashboard;

  const maliciousText = '<script>alert("pwned")</script><img src=x onerror=alert(1)>';
  d.setLastOutput(maliciousText);
  d.setOutputSearchQuery("alert");

  const container = getElement("#output-text");
  const spans = container.children.filter((c) => c.className === "output-line");
  assert.equal(spans.length, 1);
  const marks = spans[0].children.filter((c) => c.tagName === "mark");
  assert.equal(marks.length, 2);
  assert.equal(marks[0].textContent, "alert");
  assert.equal(marks[1].textContent, "alert");

  const tags = container.children.map((c) => c.tagName);
  assert.equal(tags.includes("script"), false);
  assert.equal(tags.includes("img"), false);
  const spanChildTags = spans[0].children.map((c) => c.tagName);
  assert.equal(spanChildTags.includes("script"), false);
  assert.equal(spanChildTags.includes("img"), false);
}


async function testOverviewModeSelectionAndCycling() {
  const localData = new Map();
  const { context, getElement } = dashboardHarness(new Map(), localData);
  const db = context.__dashboard;

  // 1. Initial default mode should be "inline" (Mode B)
  assert.equal(db.getOverviewMode(), "inline");
  assert.equal(getElement("#run-inspector").classList.contains("mode-inline"), true);
  assert.equal(getElement("#mode-btn-b").getAttribute("aria-pressed"), "true");

  // 2. Direct selection to Mode A (minimal)
  db.setOverviewMode("minimal");
  assert.equal(db.getOverviewMode(), "minimal");
  assert.equal(getElement("#run-inspector").classList.contains("mode-minimal"), true);
  assert.equal(getElement("#mode-btn-a").getAttribute("aria-pressed"), "true");
  assert.equal(getElement("#mode-btn-b").getAttribute("aria-pressed"), "false");
  assert.equal(localData.get("runmux-overview-mode-v1"), "minimal");

  // 3. Cycle: minimal -> inline -> dashboard -> expanded -> minimal
  db.cycleOverviewMode();
  assert.equal(db.getOverviewMode(), "inline");
  assert.equal(getElement("#run-inspector").classList.contains("mode-inline"), true);
  assert.equal(getElement("#mode-btn-b").getAttribute("aria-pressed"), "true");

  db.cycleOverviewMode();
  assert.equal(db.getOverviewMode(), "dashboard");
  assert.equal(getElement("#run-inspector").classList.contains("mode-dashboard"), true);
  assert.equal(getElement("#mode-btn-c").getAttribute("aria-pressed"), "true");

  db.cycleOverviewMode();
  assert.equal(db.getOverviewMode(), "expanded");
  assert.equal(getElement("#run-inspector").classList.contains("mode-expanded"), true);
  assert.equal(getElement("#mode-btn-d").getAttribute("aria-pressed"), "true");

  db.cycleOverviewMode();
  assert.equal(db.getOverviewMode(), "minimal");
  assert.equal(getElement("#run-inspector").classList.contains("mode-minimal"), true);

  // 4. Persistence across reload:
  localData.set("runmux-overview-mode-v1", "dashboard");
  const reloadHarness = dashboardHarness(new Map(), localData);
  assert.equal(reloadHarness.context.__dashboard.getOverviewMode(), "dashboard");
  assert.equal(reloadHarness.getElement("#run-inspector").classList.contains("mode-dashboard"), true);
  assert.equal(reloadHarness.getElement("#mode-btn-c").getAttribute("aria-pressed"), "true");
}


async function testLiveTelemetryRenderingAndZeroVsUnavailableDistinction() {
  const { context, getElement } = dashboardHarness();
  const db = context.__dashboard;

  // 1. Test formatters directly
  assert.equal(db.formatPercent(0.0), "0.0%");
  assert.equal(db.formatPercent(null), "—");
  assert.equal(db.formatPercent(undefined), "—");
  assert.equal(db.formatPercent(42.56), "42.6%");

  assert.equal(db.formatBytes(0), "0 B");
  assert.equal(db.formatBytes(null), "—");
  assert.equal(db.formatBytes(1024), "1.0 KiB");
  assert.equal(db.formatBytes(52428800), "50.0 MiB");
  assert.equal(db.formatBytes(1073741824), "1.00 GiB");

  assert.equal(db.formatBytesRate(0), "0 B/s");
  assert.equal(db.formatBytesRate(null), "—");
  assert.equal(db.formatBytesRate(1048576), "1.0 MiB/s");
  assert.equal(db.formatBytesRate(51200), "50.0 KiB/s");

  // 2. Test renderTelemetry with active process in Mode D
  db.setOverviewMode("expanded");

  const activeProcessStats = {
    id: "run-101",
    numeric_id: 101,
    status: "running",
    pid: 1234,
    process_count: 3,
    thread_count: 12,
    cpu_percent: 250.0,
    cpu_percent_normalized: 62.5,
    cpu_count: 4,
    cpu_time_seconds: 14.5,
    rss_bytes: 52428800, // 50 MiB
    read_bytes_per_second: 1048576, // 1 MiB/s
    write_bytes_per_second: 51200, // 50 KiB/s
    total_read_bytes: 10485760, // 10 MiB
    total_write_bytes: 2097152, // 2 MiB
    gpu_memory_bytes: 1073741824, // 1 GiB
    unavailable: null,
    sampled_at: Date.now() / 1000,
  };

  const hostStats = {
    cpu_percent: 34.2,
    cpu_count: 8,
    memory_used_bytes: 8589934592, // 8 GiB
    memory_available_bytes: 25769803776,
    memory_total_bytes: 34359738368, // 32 GiB
    memory_percent: 25.0,
    net_read_bytes_per_second: 2097152, // 2 MiB/s
    net_write_bytes_per_second: 102400, // 100 KiB/s
    gpu_devices: [{
      index: 0,
      name: "NVIDIA GeForce RTX 4090",
      load: 72,
      memory_used: 12884901888, // 12 GiB
      memory_total: 25769803776, // 24 GiB
      temperature: 58,
    }],
    sampled_at: Date.now() / 1000,
  };

  db.renderTelemetry(activeProcessStats, hostStats);

  // Assert Process Tree Metrics
  assert.equal(getElement("#val-inline-cpu").textContent, "250.0%");
  assert.equal(getElement("#val-inline-rss").textContent, "50.0 MiB");
  assert.equal(getElement("#val-inline-procs").textContent, "3p / 12t");

  assert.equal(getElement("#card-cpu-val").textContent, "250.0%");
  assert.equal(getElement("#card-cpu-sub").textContent, "62.5% norm (4 cores)");

  assert.equal(getElement("#card-rss-val").textContent, "50.0 MiB");
  assert.equal(getElement("#card-rss-sub").textContent, "Resident physical memory");

  assert.equal(getElement("#card-tree-val").textContent, "3 procs · 12 threads");
  assert.equal(getElement("#card-io-val").textContent, "↓ 1.0 MiB/s · ↑ 50.0 KiB/s");
  assert.equal(getElement("#card-io-sub").textContent, "Total: ↓ 10.0 MiB · ↑ 2.0 MiB");

  assert.equal(getElement("#card-gpu-proc-val").textContent, "1.00 GiB");
  assert.equal(getElement("#card-gpu-proc-sub").textContent, "Attributed compute VRAM");

  // Assert Host & Device Metrics
  assert.equal(getElement("#card-host-cpu-val").textContent, "34.2%");
  assert.equal(getElement("#card-host-cpu-sub").textContent, "8 logical cores total");

  assert.equal(getElement("#card-host-ram-val").textContent, "8.00 GiB / 32.00 GiB");
  assert.equal(getElement("#card-host-ram-sub").textContent, "25.0% system utilized");

  assert.equal(getElement("#card-host-net-val").textContent, "↓ 2.0 MiB/s · ↑ 100.0 KiB/s");
  assert.equal(getElement("#card-host-net-sub").textContent, "Host-wide network delta");

  assert.equal(getElement("#card-gpu-dev-val").textContent, "NVIDIA GeForce RTX 4090: 72% load");
  assert.equal(getElement("#card-gpu-dev-sub").textContent, "12.00 GiB / 24.00 GiB · 58°C");

  // 3. Test First-sample / Baseline state (rates are null, instantaneous are present)
  const baselineStats = {
    ...activeProcessStats,
    cpu_percent: null,
    cpu_percent_normalized: null,
    read_bytes_per_second: null,
    write_bytes_per_second: null,
    gpu_memory_bytes: null,
  };
  db.renderTelemetry(baselineStats, hostStats);

  assert.equal(getElement("#card-cpu-val").textContent, "—");
  assert.equal(getElement("#card-cpu-sub").textContent, "Baseline pending (first sample)");
  assert.equal(getElement("#card-io-val").textContent, "—");
  assert.equal(getElement("#card-gpu-proc-val").textContent, "None attributed");

  // 4. Test Valid Zero Utilization (active process, 0% CPU, 0 B/s IO)
  const zeroWorkStats = {
    ...activeProcessStats,
    cpu_percent: 0.0,
    cpu_percent_normalized: 0.0,
    read_bytes_per_second: 0,
    write_bytes_per_second: 0,
  };
  db.renderTelemetry(zeroWorkStats, hostStats);
  assert.equal(getElement("#card-cpu-val").textContent, "0.0%");
  assert.equal(getElement("#card-io-val").textContent, "↓ 0 B/s · ↑ 0 B/s");

  // 5. Test Unavailable / Exited Process
  const exitedStats = {
    ...activeProcessStats,
    cpu_percent: null,
    rss_bytes: null,
    process_count: 0,
    thread_count: 0,
    unavailable: "process exited",
  };
  db.renderTelemetry(exitedStats, hostStats);

  assert.equal(getElement("#card-cpu-val").textContent, "—");
  assert.equal(getElement("#card-cpu-sub").textContent, "process exited");
  assert.equal(getElement("#card-rss-val").textContent, "—");
  assert.equal(getElement("#telemetry-status-banner").hidden, false);
  assert.equal(getElement("#telemetry-status-banner").textContent, "Process inactive: process exited");
}

async function testTelemetryPollingBoundsAndLifecycle() {
  const { context, getElement, intervals } = dashboardHarness();
  const db = context.__dashboard;

  // 1. Mode A (Minimal) must NOT start polling
  db.setOverviewMode("minimal");
  db.startTelemetryPolling();
  assert.equal(db.getTelemetryTimer(), null);

  // 2. Mode B should start polling interval
  db.setOverviewMode("inline");
  // Set selectedId to run-1
  db.setRuns([run("run-1")]);
  db.setSelectedId("run-1");
  db.startTelemetryPolling();
  assert.equal(db.getTelemetryTimer() !== null, true);

  // 3. Stop polling clears timer
  db.stopTelemetryPolling();
  assert.equal(db.getTelemetryTimer(), null);

  // 4. In-flight flag prevents concurrent overlapping requests
  assert.equal(db.isTelemetryInFlight(), false);

  // 5. Run switching cancels previous and starts new request
  const h = dashboardHarness();
  h.context.__dashboard.setRuns([run("run-A"), run("run-B")]);
  h.context.__dashboard.setOverviewMode("inline");
  const pA = h.context.__dashboard.selectRun("run-A");
  await Promise.resolve();
  const telA = h.requests.filter(r => r.url.includes("/api/runs/run-A/telemetry"));
  assert.equal(telA.length, 1);

  const pB = h.context.__dashboard.selectRun("run-B");
  await Promise.resolve();
  const telB = h.requests.filter(r => r.url.includes("/api/runs/run-B/telemetry"));
  assert.equal(telB.length, 1);

  h.context.__dashboard.clearSelection();
  assert.equal(h.context.__dashboard.getTelemetryTimer(), null);
}

Promise.all([
  testOverviewModeSelectionAndCycling(),
  testLiveTelemetryRenderingAndZeroVsUnavailableDistinction(),
  testTelemetryPollingBoundsAndLifecycle(),
  testRapidSelection(),
  testClearInvalidatesPendingSelection(),
  testStatusGroupsAndBrowserOnlyWorkspaceTabs(),
  testNewProcessTabShowsOnEmptyRegistryAndLaunchSubmitsOnce(),
  testOutputNormalizesCarriageReturnsAcrossChunks(),
  testFollowOutputSuspendsOnScrollAndJumpResumesIt(),
  testOutputHistoryStaysWithinConfiguredViewLimit(),
  testTruncatedTerminalReplayWarnsThatScreenMayBeIncomplete(),
  Promise.resolve().then(testExplorerGroupingFilteringSortingAndEmptyMessages),
  Promise.resolve().then(testExplorerPaginationKeepsDomBoundedAndSearchesAllRuns),
  testWorkspaceSessionStorageRestoresOnlyValidRunIdsAndSafePreferences(),
  testDuplicateNameRunsKeepDistinctTabIdentityAndCloseOnlyView(),
  testSelectedDetailRefreshReconcilesExplorerStatusByRunId(),
  Promise.resolve().then(testExplorerResizeAndCollapseStateCanBeChangedAccessibly),
  testTerminalInputRequiresSupervisorLockAndCleanupClosesOnlySocket(),
  Promise.resolve().then(testLogClassificationAndSeverityFiltering),
  Promise.resolve().then(testBoundedOutputLiteralSearchAndReDoSProtection),
  Promise.resolve().then(testPathologicalBufferDomBoundingAndAccurateLabels),
  Promise.resolve().then(testOutputMatchNavigationAndFollowCoordination),
  Promise.resolve().then(testOutputSearchAndFilterAccurateScopeLabeling),
  testOutputLiveStreamingUpdatesSearchAndFilter(),
  Promise.resolve().then(testOutputTextSecurityAndXssImmunity),
]).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
