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
    textContent: "",
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
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = [...children]; },
    focus() {},
    blur() {},
    scrollIntoView() {},
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
]).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
