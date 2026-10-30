function createTelemetryPoller(options) {
  const fetchTelemetry = options.fetchTelemetry;
  const onSample = options.onSample;
  const onError = options.onError;
  const intervalMs = options.intervalMs ?? 1800;
  const schedule = options.setTimer ?? setTimeout;
  const cancel = options.clearTimer ?? clearTimeout;
  let runId = null;
  let mode = "detail";
  let visible = true;
  let locked = false;
  let closed = false;
  let terminal = false;
  let generation = 0;
  let timer = null;
  let active = null;
  let resumeImmediately = false;

  function eligible() {
    return Boolean(runId) && mode !== "minimal" && visible && !locked && !closed && !terminal;
  }
  function clearScheduled() {
    if (timer !== null) { cancel(timer); timer = null; }
  }
  function abortActive() {
    if (active) { active.controller.abort(); active = null; }
  }
  function scheduleNext() {
    if (!eligible() || active || timer !== null) return;
    timer = schedule(() => { timer = null; void refresh(); }, intervalMs);
  }
  async function refresh() {
    if (!eligible() || active) return;
    const currentGeneration = generation;
    const controller = new AbortController();
    const request = { controller, generation: currentGeneration };
    active = request;
    try {
      const sample = await fetchTelemetry(runId, { signal: controller.signal });
      if (active !== request || generation !== currentGeneration || controller.signal.aborted) return;
      onSample(sample);
      if (["finished", "failed", "killed", "lost"].includes(sample?.status)
          || ["run is finished", "process exited"].includes(sample?.unavailable)) {
        terminal = true;
        clearScheduled();
      }
    } catch (error) {
      if (active === request && generation === currentGeneration && !controller.signal.aborted && onError) {
        onError(error);
      }
    } finally {
      if (active === request) {
        active = null;
        if (eligible()) {
          if (resumeImmediately) { resumeImmediately = false; void refresh(); }
          else scheduleNext();
        }
      }
    }
  }
  function startIfEligible() {
    if (!eligible()) return;
    clearScheduled();
    if (active) resumeImmediately = true;
    else void refresh();
  }

  return {
    selectRun(nextRunId) {
      if (closed || nextRunId === runId) return;
      clearScheduled();
      abortActive();
      generation += 1;
      runId = nextRunId || null;
      terminal = false;
      resumeImmediately = false;
      startIfEligible();
    },
    setMode(nextMode) {
      if (closed || nextMode === mode) return;
      mode = nextMode;
      if (mode === "minimal") clearScheduled();
      else startIfEligible();
    },
    setVisible(nextVisible) {
      if (closed || Boolean(nextVisible) === visible) return;
      visible = Boolean(nextVisible);
      if (!visible) clearScheduled();
      else startIfEligible();
    },
    setLocked(nextLocked) {
      if (closed || Boolean(nextLocked) === locked) return;
      locked = Boolean(nextLocked);
      if (locked) { clearScheduled(); abortActive(); generation += 1; }
      else startIfEligible();
    },
    deselectRun() {
      if (closed || runId === null) return;
      runId = null;
      generation += 1;
      clearScheduled();
      abortActive();
    },
    close() {
      if (closed) return;
      closed = true;
      runId = null;
      generation += 1;
      resumeImmediately = false;
      clearScheduled();
      abortActive();
    },
  };
}

module.exports = { createTelemetryPoller };
