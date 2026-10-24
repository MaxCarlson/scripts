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

function element() {
  const listeners = new Map();
  return {
    hidden: false,
    textContent: "",
    value: "",
    checked: true,
    className: "",
    scrollHeight: 0,
    scrollTop: 0,
    clientHeight: 0,
    lastElementChild: { textContent: "" },
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(name, handler) { listeners.set(name, handler); },
    setAttribute() {},
    append() {},
    replaceChildren() {},
    focus() {},
    blur() {},
  };
}

function dashboardHarness() {
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
    createElement() { return element(); },
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
    URLSearchParams,
    setInterval(callback, delay) {
      const id = nextInterval++;
      intervals.set(id, { callback, delay });
      return id;
    },
    clearInterval(id) { intervals.delete(id); },
    Date,
    console,
  };
  const source = fs.readFileSync(path.join(__dirname, "../src/runmux/web_static/assets/dashboard.js"), "utf8");
  vm.runInNewContext(`${source}\nglobalThis.__dashboard = { selectRun, clearSelection, refreshOutput, showLogin };`, context);
  return { context, elements, intervals, requests, getElement: (selector) => document.querySelector(selector) };
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

Promise.all([testRapidSelection(), testClearInvalidatesPendingSelection()]).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
