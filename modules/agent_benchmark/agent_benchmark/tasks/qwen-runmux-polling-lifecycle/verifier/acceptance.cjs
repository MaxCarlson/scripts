const assert = require("node:assert/strict");

function createHarness() {
  const timers = [];
  return {
    timers,
    setTimer(callback, delay) {
      const timer = { callback, delay, cancelled: false };
      timers.push(timer);
      return timer;
    },
    clearTimer(timer) { if (timer) timer.cancelled = true; },
    runNext() {
      const timer = timers.find((item) => !item.cancelled);
      assert.ok(timer, "expected exactly one future poll");
      timer.cancelled = true;
      timer.callback();
    },
    activeTimers() { return timers.filter((item) => !item.cancelled); },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

async function main() {
  const candidatePath = process.argv[2];
  const { createTelemetryPoller } = require(candidatePath);
  assert.equal(typeof createTelemetryPoller, "function");

  // Eligible selection starts immediately; an unresolved request blocks overlap.
  const harness = createHarness();
  const first = deferred();
  const calls = [];
  const samples = [];
  const poller = createTelemetryPoller({
    fetchTelemetry(runId, request) { calls.push({ runId, request }); return first.promise; },
    onSample: (sample) => samples.push(sample),
    intervalMs: 1800,
    setTimer: harness.setTimer,
    clearTimer: harness.clearTimer,
  });
  poller.selectRun("one");
  assert.equal(calls.length, 1, "selected visible run polls immediately");
  poller.setMode("minimal");
  poller.setMode("detail");
  poller.setVisible(false);
  poller.setVisible(true);
  assert.equal(calls.length, 1, "in-flight request is single-flight across state changes");
  first.resolve({ status: "running", runId: "one" });
  await flush();
  assert.equal(samples.length, 2, "visible resume runs once after the in-flight response");
  assert.equal(harness.activeTimers().length, 1);
  assert.equal(harness.activeTimers()[0].delay, 1800);
  harness.runNext();
  assert.equal(calls.length, 3, "next poll starts after cadence timer");
  poller.close();
  assert.equal(calls[2].request.signal.aborted, true, "close aborts active request");
  assert.equal(harness.activeTimers().length, 0, "close clears scheduled timer");

  // Hidden/minimal/locked/deselected/closed states suppress requests; visibility resumes once.
  const h2 = createHarness();
  const states = [];
  const p2 = createTelemetryPoller({
    fetchTelemetry: async (runId) => { states.push(runId); return { status: "running" }; },
    onSample() {}, intervalMs: 20, setTimer: h2.setTimer, clearTimer: h2.clearTimer,
  });
  p2.setMode("minimal");
  p2.selectRun("two");
  assert.equal(states.length, 0);
  p2.setMode("detail");
  assert.equal(states.length, 1);
  await flush();
  assert.equal(h2.activeTimers().length, 1);
  p2.setVisible(false);
  assert.equal(h2.activeTimers().length, 0);
  p2.setVisible(true);
  assert.equal(states.length, 2);
  await flush();
  p2.setLocked(true);
  assert.equal(h2.activeTimers().length, 0);
  p2.setLocked(false);
  assert.equal(states.length, 3);
  p2.deselectRun();
  assert.equal(h2.activeTimers().length, 0);
  p2.selectRun("three");
  assert.equal(states.length, 4);
  p2.close();
  p2.selectRun("ignored");
  assert.equal(states.length, 4);

  // A run switch cancels the old request and stale results are ignored.
  const h3 = createHarness();
  const stale = deferred();
  const calls3 = [];
  const samples3 = [];
  const p3 = createTelemetryPoller({
    fetchTelemetry(runId, request) {
      calls3.push({ runId, request });
      return runId === "old" ? stale.promise : Promise.resolve({ status: "running", runId });
    },
    onSample: (sample) => samples3.push(sample),
    setTimer: h3.setTimer,
    clearTimer: h3.clearTimer,
  });
  p3.selectRun("old");
  const oldSignal = calls3[0].request.signal;
  p3.selectRun("new");
  assert.equal(oldSignal.aborted, true);
  stale.resolve({ status: "running", runId: "old" });
  await flush();
  assert.deepEqual(samples3.map((item) => item.runId), ["new"]);
  p3.close();

  // Terminal states stop; transient failures report and retry; deselect aborts.
  const h4 = createHarness();
  const terminalPoller = createTelemetryPoller({
    fetchTelemetry: async () => ({ status: "finished" }),
    onSample() {}, setTimer: h4.setTimer, clearTimer: h4.clearTimer,
  });
  terminalPoller.selectRun("done");
  await flush();
  assert.equal(h4.activeTimers().length, 0, "terminal status stops polling");

  const h5 = createHarness();
  const errors = [];
  const failed = deferred();
  const requests = [];
  const transientPoller = createTelemetryPoller({
    fetchTelemetry(_runId, request) { requests.push(request); return failed.promise; },
    onSample() {}, onError: (error) => errors.push(error.message),
    intervalMs: 50, setTimer: h5.setTimer, clearTimer: h5.clearTimer,
  });
  transientPoller.selectRun("retry");
  failed.reject(new Error("temporary"));
  await flush();
  assert.deepEqual(errors, ["temporary"]);
  assert.equal(h5.activeTimers().length, 1, "transient failure schedules retry");
  h5.runNext();
  assert.equal(requests.length, 2);
  transientPoller.deselectRun();
  assert.equal(requests[1].signal.aborted, true, "deselect aborts active request");
  assert.equal(h5.activeTimers().length, 0);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
