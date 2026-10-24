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
    className: "",
    scrollHeight: 0,
    scrollTop: 0,
    clientHeight: 0,
    style: {},
    lastElementChild: { textContent: "" },
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(name, handler) { listeners.set(name, handler); },
    dispatch(name, ...args) { listeners.get(name)?.(...args); },
    setAttribute(name, value) { this.attributes[name] = value; },
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

function dashboardHarness(storageData = new Map()) {
  const elements = new Map();
  const intervals = new Map();
  const requests = [];
  let nextInterval = 1;
  const document = {
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
    navigator: { clipboard: { writeText: async () => {} } },
    sessionStorage: {
      getItem(key) { return storageData.get(key) ?? null; },
      setItem(key, value) { storageData.set(key, `${value}`); },
      removeItem(key) { storageData.delete(key); },
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
    setOutputSearchRegex: (r) => { outputSearchRegex = r; if ($("#output-search-regex")) $("#output-search-regex").setAttribute("aria-pressed", String(r)); computeOutputSearchAndFilter(); },
    setOutputSeverityFilter: (f) => { outputSeverityFilter = f; if ($("#output-severity-filter")) $("#output-severity-filter").value = f; computeOutputSearchAndFilter(); },
    getLastOutput: () => lastOutput,
    setLastOutput: (val, truncated = false) => { lastOutput = val; outputTruncated = truncated; computeOutputSearchAndFilter(); },
    getOutputTruncated: () => outputTruncated,
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

  const detailRequests = requests.filter((item) => !item.url.includes("/output"));
  const outputRequests = requests.filter((item) => item.url.includes("/output"));
  assert.equal(detailRequests.length, 3);
  assert.equal(outputRequests.length, 3);

  detailRequests[2].resolve(response(run("A", "latest A")));
  outputRequests[2].resolve(response({ state: "available", text: "latest output", cursor: "latest", reset: true, at_end: false, finished: false }));
  await secondA;
  detailRequests[0].resolve(response(run("A", "stale A")));
  outputRequests[0].resolve(response({ state: "available", text: "stale A output", cursor: "old", reset: true, at_end: false, finished: false }));
  detailRequests[1].resolve(response(run("B", "stale B")));
  outputRequests[1].resolve(response({ state: "available", text: "stale B output", cursor: "old", reset: true, at_end: false, finished: false }));
  await Promise.all([firstA, selectB]);

  assert.equal(elements.get("#selected-name").textContent, "latest A");
  assert.equal(elements.get("#output-text").textContent, "latest output");
  assert.equal(intervals.size, 1);
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

function testBoundedOutputSearchPlainAndRegex() {
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

  // 3. Regex search
  d.setOutputSearchCase(false);
  d.setOutputSearchRegex(true);
  d.setOutputSearchQuery("port \\d+");
  d.computeOutputSearchAndFilter();
  assert.equal(d.getOutputMatches().length, 1);
  assert.equal(d.getOutputMatches()[0].text, "port 8080");
  assert.equal(getElement("#output-search-count").textContent, "1 of 1 (loaded buffer)");

  // 4. Invalid regex handling
  d.setOutputSearchQuery("[invalid(");
  d.computeOutputSearchAndFilter();
  assert.equal(d.getOutputMatches().length, 0);
  assert.equal(d.getOutputSearchError(), "Invalid regex");
  assert.equal(getElement("#output-search-count").textContent, "Invalid regex");
  assert.equal(getElement("#output-search-count").className.includes("has-error"), true);
  assert.equal(getElement("#output-search-prev").disabled, true);
  assert.equal(getElement("#output-search-next").disabled, true);

  // 5. Clear search
  d.clearOutputSearch();
  assert.equal(d.getOutputMatches().length, 0);
  assert.equal(d.getOutputSearchQuery(), "");
  assert.equal(getElement("#output-search-count").textContent, "No query");
  assert.equal(getElement("#output-search-clear").hidden, true);
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

Promise.all([
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
  Promise.resolve().then(testBoundedOutputSearchPlainAndRegex),
  Promise.resolve().then(testOutputMatchNavigationAndFollowCoordination),
  Promise.resolve().then(testOutputSearchAndFilterAccurateScopeLabeling),
  testOutputLiveStreamingUpdatesSearchAndFilter(),
  Promise.resolve().then(testOutputTextSecurityAndXssImmunity),
]).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
