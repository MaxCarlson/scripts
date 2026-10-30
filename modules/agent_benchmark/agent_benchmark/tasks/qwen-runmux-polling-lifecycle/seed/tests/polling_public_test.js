const assert = require("node:assert/strict");
const { createTelemetryPoller } = require("../src/telemetry_polling.js");

const pendingTimers = [];
const timers = {
  set(callback, delay) {
    const timer = { callback, delay, cancelled: false };
    pendingTimers.push(timer);
    return timer;
  },
  clear(timer) { if (timer) timer.cancelled = true; },
  runNext() {
    const timer = pendingTimers.find((item) => !item.cancelled);
    assert.ok(timer, "expected a scheduled polling timer");
    timer.cancelled = true;
    timer.callback();
  },
};

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

async function settle() { await Promise.resolve(); await Promise.resolve(); }

async function testImmediateSingleFlightAndCadence() {
  const first = deferred();
  const calls = [];
  const poller = createTelemetryPoller({
    fetchTelemetry: (runId, options) => { calls.push({ runId, options }); return first.promise; },
    onSample() {}, intervalMs: 1800,
    setTimer: timers.set, clearTimer: timers.clear,
  });
  poller.selectRun("run-a");
  poller.setMode("detail");
  assert.equal(calls.length, 1, "eligible run starts immediately");
  poller.selectRun("run-a");
  assert.equal(calls.length, 1, "visibility changes cannot overlap an in-flight request");
  first.resolve({ status: "running" });
  await settle();
  assert.equal(pendingTimers.filter((item) => !item.cancelled).length, 1);
  const timer = pendingTimers.find((item) => !item.cancelled);
  assert.equal(timer.delay, 1800);
  timers.runNext();
  assert.equal(calls.length, 2);
  poller.close();
}

async function testVisibilityAndModeSuppressRequests() {
  const calls = [];
  const poller = createTelemetryPoller({
    fetchTelemetry: async (runId) => { calls.push(runId); return { status: "running" }; },
    onSample() {}, intervalMs: 10, setTimer: timers.set, clearTimer: timers.clear,
  });
  poller.setMode("minimal");
  poller.selectRun("run-a");
  assert.equal(calls.length, 0);
  poller.setMode("detail");
  assert.equal(calls.length, 1);
  await settle();
  poller.setVisible(false);
  const live = pendingTimers.find((item) => !item.cancelled);
  assert.ok(!live, "hidden page suspends the timer");
  poller.setVisible(true);
  assert.equal(calls.length, 2, "visible page resumes immediately");
  poller.close();
}

async function testRunSwitchAbortsAndIgnoresStaleResult() {
  const old = deferred();
  const samples = [];
  const calls = [];
  const poller = createTelemetryPoller({
    fetchTelemetry: (runId, request) => {
      calls.push({ runId, request });
      return runId === "old" ? old.promise : Promise.resolve({ status: "running", runId });
    },
    onSample: (sample) => samples.push(sample),
    setTimer: timers.set, clearTimer: timers.clear,
  });
  poller.selectRun("old");
  const oldSignal = calls[0].request.signal;
  poller.selectRun("new");
  assert.equal(oldSignal.aborted, true);
  old.resolve({ status: "running", runId: "old" });
  await settle();
  assert.deepEqual(samples.map((sample) => sample.runId), ["new"]);
  poller.close();
}

async function main() {
  await testImmediateSingleFlightAndCadence();
  await testVisibilityAndModeSuppressRequests();
  await testRunSwitchAbortsAndIgnoresStaleResult();
  console.log("PASS: polling cadence, single-flight, visibility, and run replacement");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
