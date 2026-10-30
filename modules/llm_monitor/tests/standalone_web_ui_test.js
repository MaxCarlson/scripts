"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const root = path.join(__dirname, "../llm_monitor/web_static");
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  const css = fs.readFileSync(path.join(root, "assets/app.css"), "utf8");
  const jsRoot = path.join(root, "assets/js");
  const app = fs.readFileSync(path.join(jsRoot, "app.mjs"), "utf8");
  const transcript = fs.readFileSync(path.join(jsRoot, "transcript.mjs"), "utf8");
  const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/ui_scenario_v1.json"), "utf8"));
  const stateModule = await import(pathToFileURL(path.join(jsRoot, "state.mjs")));
  const formatters = await import(pathToFileURL(path.join(jsRoot, "formatters.mjs")));

  assert.match(html, /<script type="module" src="\/assets\/js\/app\.mjs"><\/script>/);
  assert.doesNotMatch(html, /<script[^>]*>\s*[^<]/i);
  assert.doesNotMatch(html, /<style\b/i);
  assert.match(html, /id="kpi-grid"/);
  assert.match(html, /class="explorer-grid"/);
  assert.match(html, /id="panel-transcript"/);
  assert.match(html, /id="panel-telemetry"/);
  assert.match(html, /id="panel-timeline"/);
  assert.match(css, /--lm-bg:\s*#0d1119/i);
  assert.match(css, /grid-template-columns:\s*minmax\(290px, \.9fr\) minmax\(0, 1\.75fr\)/);
  assert.match(css, /max-width:\s*740px/);
  assert.match(css, /prefers-reduced-motion/);
  assert.doesNotMatch(app, /\.innerHTML\s*=/);
  assert.doesNotMatch(transcript, /\.innerHTML\s*=/);
  assert.match(app, /llm-monitor-ui-v1/);
  assert.match(fixture._notice, /SYNTHETIC UI TEST FIXTURE ONLY/);
  assert.doesNotMatch(app, /ui_scenario_v1|synthetic-req-42/);

  let state = stateModule.createState();
  state = stateModule.mergeSnapshot(state, fixture);
  assert.equal(state.selectedRequestKey, stateModule.requestKey(fixture.requestResult.requests[0]));
  assert.equal(state.captureState, "available");
  assert.equal(state.requests.length, 4);
  assert.equal(formatters.tokenMetric(state.requests[0], "input_tokens").value, "—");
  assert.equal(formatters.tokenMetric(state.requests.find((item) => item.request_id === "synthetic-req-418"), "input_tokens").value, "~80");

  const older = state.requests.find((item) => item.request_id === "synthetic-req-420");
  state = stateModule.selectRequest(state, stateModule.requestKey(older));
  assert.equal(state.autoFollow, false);
  const incoming = JSON.parse(JSON.stringify(fixture));
  incoming.requestResult.requests.unshift({
    request_id: "synthetic-req-422", server_instance_id: "synthetic-server-a", model_instance_id: "fixture/qwen-coder#1",
    provider_model_id: "fixture/qwen-coder", source: "synthetic_fixture", state: "active", started_at: "2026-10-29T12:00:06Z", content: [], coverage: {},
  });
  state = stateModule.mergeSnapshot(state, incoming);
  assert.equal(state.selectedRequestKey, stateModule.requestKey(older), "new requests must not steal a manually selected request");

  const active = state.requests.find((item) => item.request_id === "synthetic-req-421");
  const activeIdentity = { request_id: active.request_id, server_instance_id: active.server_instance_id, model_instance_id: active.model_instance_id, provider_model_id: active.provider_model_id };
  state = stateModule.applyRequestEvent(state, { type: "output.delta", request: activeIdentity, sequence: 4, delta: " Additional text." });
  assert.ok(state.requests.find((item) => item.request_id === active.request_id).content.at(-1).text.endsWith("Additional text."));

  const latest = state.requests.find((item) => item.request_id === "synthetic-req-422");
  const identity = { request_id: latest.request_id, server_instance_id: latest.server_instance_id, model_instance_id: latest.model_instance_id, provider_model_id: latest.provider_model_id };
  state = stateModule.applyRequestEvent(state, { type: "reasoning.delta", request: identity, sequence: 1, delta: "Thinking" });
  state = stateModule.applyRequestEvent(state, { type: "output.delta", request: identity, sequence: 2, delta: "Answer" });
  const updated = state.requests.find((item) => item.request_id === "synthetic-req-422");
  assert.deepEqual(updated.content.map((part) => part.kind), ["reasoning", "assistant"]);
  assert.equal(updated.content[0].text, "Thinking");
  assert.equal(updated.content[1].text, "Answer");
  assert.equal(state.selectedRequestKey, stateModule.requestKey(older));
  const stale = stateModule.applyRequestEvent(state, { type: "output.delta", request: identity, sequence: 2, delta: "must not append" });
  assert.equal(stale, state, "out-of-order duplicate sequences are ignored");
  const gap = stateModule.applyRequestEvent(state, { type: "request.updated", request: identity, sequence: 5, payload: { output_tokens: null } });
  assert.equal(gap.requests.find((item) => item.request_id === latest.request_id).stream_gap, true);
  assert.equal(formatters.tokenMetric(gap.requests.find((item) => item.request_id === latest.request_id), "output_tokens").value, "—");
  const interrupted = stateModule.applyRequestEvent(gap, { type: "stream.interrupted", request: identity, sequence: 6 });
  assert.equal(interrupted.requests.find((item) => item.request_id === latest.request_id).state, "unknown");
  state = stateModule.mergeSnapshot(state, fixture);
  assert.ok(state.requests.find((item) => item.request_id === active.request_id).content.at(-1).text.endsWith("Additional text."), "snapshot reconciliation must retain a local appended delta until the server snapshot catches up");
  assert.equal(stateModule.visibleRequests({ ...state, search: "review the fixture" }).length, 1);

  console.log("Standalone UI structure, fixture isolation, safe rendering, selection, streaming reducer, and missing-metric checks passed.");
}

function pathToFileURL(value) {
  return require("node:url").pathToFileURL(value).href;
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
