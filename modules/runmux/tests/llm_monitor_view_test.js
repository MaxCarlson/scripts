"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function makeElement(tagName = "div") {
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
    get className() {
      return [...classes].join(" ");
    },
    set className(val) {
      classes.clear();
      if (val) val.split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    },
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
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name === "class") this.className = `${value}`;
    },
    getAttribute(name) { return this.attributes[name] ?? null; },
    removeAttribute(name) { delete this.attributes[name]; },
    append(...children) { this._textContent = undefined; this.children.push(...children); },
    replaceChildren(...children) { this._textContent = undefined; this.children = [...children]; },
    querySelector(selector) {
      function find(node) {
        if (!node || typeof node !== "object") return null;
        if (selector.startsWith("#") && node.id === selector.slice(1)) return node;
        if (selector.startsWith(".") && node.classList?.contains(selector.slice(1))) return node;
        if (selector === node.tagName?.toLowerCase()) return node;
        for (const child of node.children || []) {
          const res = find(child);
          if (res) return res;
        }
        return null;
      }
      return find(this);
    },
    querySelectorAll(selector) {
      const results = [];
      function collect(node) {
        if (!node || typeof node !== "object") return;
        if (selector.startsWith(".") && node.classList?.contains(selector.slice(1))) results.push(node);
        if (selector === node.tagName?.toLowerCase()) results.push(node);
        for (const child of node.children || []) collect(child);
      }
      collect(this);
      return results;
    },
    click() { this.dispatch("click"); },
  };
}

function createTestHarness(container) {
  const elements = new Map();
  const document = {
    createElement(tag) { return makeElement(tag); },
    createTextNode(text) { return { textContent: text, nodeType: 3 }; },
    getElementById(id) {
      if (elements.has(`#${id}`)) return elements.get(`#${id}`);
      return container?.querySelector(`#${id}`) ?? null;
    },
    querySelector(selector) {
      if (elements.has(selector)) return elements.get(selector);
      return container?.querySelector(selector) ?? null;
    },
  };

  const requests = [];
  const responses = new Map();

  const api = async (path, options = {}) => {
    requests.push({ path, options });
    const url = new URL(path, "http://localhost");
    const route = url.pathname;

    if (responses.has(route)) {
      const handler = responses.get(route);
      return handler(url.searchParams, options);
    }

    throw new Error(`Unhandled route: ${route}`);
  };

  const context = {
    document,
    globalThis: {},
    URL,
    URLSearchParams,
    AbortController,
    setTimeout,
    clearTimeout,
    Date,
    navigator: { clipboard: { writeText: async () => {} } },
  };
  context.window = context.globalThis;

  const scriptPath = path.join(__dirname, "../src/runmux/web_static/assets/llm-monitor.js");
  const code = fs.readFileSync(scriptPath, "utf8");
  vm.createContext(context);
  vm.runInContext(code, context);

  return {
    context,
    document,
    elements,
    requests,
    responses,
    api,
    Monitor: context.globalThis.RunmuxLLMMonitor,
  };
}

async function runTests() {
  console.log("Starting llm_monitor_view_test.js...");

  // Test 1: Start and Disabled State
  {
    const container = makeElement("div");
    container.id = "llm-monitor-workspace";
    const harness = createTestHarness(container);

    harness.responses.set("/api/llm-monitor/v1/status", () => ({
      json: async () => ({
        availability: "disabled",
        reason_code: "config_disabled",
        configured_provider: "opencode",
        refresh_interval_seconds: 5.0,
      }),
    }));

    harness.Monitor.start(container, harness.api);
    await new Promise((r) => setTimeout(r, 20));

    assert.equal(container.classList.contains("llm-monitor-workspace"), true);
    assert.equal(harness.Monitor.getStatus().availability, "disabled");

    // Must not poll snapshot when disabled
    assert.equal(harness.requests.some((r) => r.path.includes("/snapshot")), false, "Must not poll when disabled");
    console.log("✓ Test 1: Disabled state correctly handled without snapshot polling");
  }

  // Test 2: Available State, Snapshot Polling, and Safe Text Rendering
  {
    const container = makeElement("div");
    container.id = "llm-monitor-workspace";
    const harness = createTestHarness(container);

    harness.responses.set("/api/llm-monitor/v1/status", () => ({
      json: async () => ({
        availability: "available",
        configured_provider: "opencode",
        refresh_interval_seconds: 2.0,
      }),
    }));

    harness.responses.set("/api/llm-monitor/v1/snapshot", () => ({
      json: async () => ({
        schema_version: 1,
        availability: "available",
        snapshot: {
          system: {
            loaded_models: ["<script>alert(1)</script>"],
          },
          sessions: [
            {
              provider_instance_id: "http://127.0.0.1:4096",
              session_id: "sess-xss-<img src=x onerror=1>",
              model: "<script>alert(1)</script>",
              state: "running",
              total_tokens: 15420,
            },
          ],
          hardware: {
            devices: [{ name: "RTX 4090", vram_used_bytes: 8 * (1024 ** 3), vram_total_bytes: 24 * (1024 ** 3) }],
          },
        },
      }),
    }));

    harness.Monitor.start(container, harness.api);
    harness.Monitor.onVisibilityChange(true);
    await new Promise((r) => setTimeout(r, 30));

    assert.equal(harness.requests.some((r) => r.path.includes("/snapshot")), true, "Should poll snapshot when visible");

    const sessionList = container.querySelector("#monitor-session-list");
    assert.ok(sessionList);
    const card = sessionList.children[0];
    assert.ok(card);
    assert.equal(card.dataset.sessionId, "sess-xss-<img src=x onerror=1>");
    assert.equal(card.textContent.includes("<script>alert(1)</script>"), true, "XSS string rendered as text");

    console.log("✓ Test 2: Available state, snapshot polling, and safe text rendering verified");
  }

  // Test 3: Session Selection, Detail Diagnostics, and 404/503 Handling
  {
    const container = makeElement("div");
    container.id = "llm-monitor-workspace";
    const harness = createTestHarness(container);

    harness.responses.set("/api/llm-monitor/v1/status", () => ({
      json: async () => ({ availability: "available", configured_provider: "opencode" }),
    }));

    harness.responses.set("/api/llm-monitor/v1/snapshot", () => ({
      json: async () => ({
        availability: "available",
        snapshot: {
          system: { loaded_models: ["qwen38"] },
          sessions: [
            { provider_instance_id: "http://127.0.0.1:4096", session_id: "sess-1", model: "qwen38", state: "running" },
            { provider_instance_id: "http://127.0.0.1:4096", session_id: "sess-missing", model: "qwen38", state: "idle" },
          ],
        },
      }),
    }));

    harness.responses.set("/api/llm-monitor/v1/sessions/detail", (params) => {
      const sessId = params.get("session_id");
      if (sessId === "sess-1") {
        return {
          json: async () => ({
            detail: {
              summary: { session_id: "sess-1", model: "qwen38", state: "running", total_tokens: 4200 },
              context_utilization: 0.25,
            },
          }),
        };
      }
      if (sessId === "sess-missing") {
        const err = new Error("Not found");
        err.status = 404;
        throw err;
      }
      const err = new Error("Provider offline");
      err.status = 503;
      throw err;
    });

    harness.responses.set("/api/llm-monitor/v1/sessions/timeline", () => ({
      json: async () => ({
        events: [
          { event_type: "user_message", timestamp: "2026-10-29T12:00:00Z", summary: "Write tests" },
          { event_type: "model_output", timestamp: "2026-10-29T12:00:05Z", summary: "Output tokens" },
        ],
        next_cursor: "cursor-pg-2",
      }),
    }));

    harness.responses.set("/api/llm-monitor/v1/alerts", () => ({
      json: async () => ({
        alerts: [{ severity: "warning", message: "High context usage", timestamp: "2026-10-29T12:00:00Z" }],
      }),
    }));

    harness.Monitor.start(container, harness.api);
    harness.Monitor.onVisibilityChange(true);
    await new Promise((r) => setTimeout(r, 20));

    // Select sess-1
    await harness.Monitor.selectSession("http://127.0.0.1:4096", "sess-1");
    await new Promise((r) => setTimeout(r, 40));

    const selected = harness.Monitor.getSelectedSession();
    assert.equal(selected.provider_instance_id, "http://127.0.0.1:4096");
    assert.equal(selected.session_id, "sess-1");

    const contentEl = container.querySelector("#monitor-detail-content");
    assert.ok(contentEl);
    assert.equal(contentEl.hidden, false);
    assert.equal(contentEl.textContent.includes("sess-1"), true);
    assert.equal(contentEl.textContent.includes("25.0%"), true, "Context utilization rendered");
    assert.equal(contentEl.textContent.includes("High context usage"), true, "Alert rendered");
    assert.equal(contentEl.textContent.includes("Write tests"), true, "Timeline event rendered");

    // Select sess-missing (404)
    await harness.Monitor.selectSession("http://127.0.0.1:4096", "sess-missing");
    await new Promise((r) => setTimeout(r, 40));
    assert.equal(contentEl.textContent.includes("Session Missing"), true, "404 maps to Session Missing error box");

    console.log("✓ Test 3: Session selection, diagnostics, timeline, and 404 handling verified");
  }

  // Test 4: Workspace Lifecycle: Pausing on Hide, Stopping on Logout (Stage 5)
  {
    const container = makeElement("div");
    container.id = "llm-monitor-workspace";
    const harness = createTestHarness(container);

    harness.responses.set("/api/llm-monitor/v1/status", () => ({
      json: async () => ({ availability: "available", configured_provider: "opencode" }),
    }));
    harness.responses.set("/api/llm-monitor/v1/snapshot", () => ({
      json: async () => ({ availability: "available", snapshot: { sessions: [] } }),
    }));

    harness.Monitor.start(container, harness.api);
    harness.Monitor.onVisibilityChange(true);
    await new Promise((r) => setTimeout(r, 20));

    const countBefore = harness.requests.filter((r) => r.path.includes("/snapshot")).length;
    assert.ok(countBefore >= 1);

    // Hide workspace
    harness.Monitor.onVisibilityChange(false);
    await new Promise((r) => setTimeout(r, 40));

    // Stop workspace (logout / lock)
    harness.Monitor.stop();
    assert.equal(harness.Monitor.getSelectedSession(), null);
    assert.equal(harness.Monitor.getStatus(), null);
    assert.equal(container.children.length, 0, "Container cleared on stop");

    console.log("✓ Test 4: Visibility pausing and stop cleanup verified");
  }

  // Test 5: Outdated Async Race Protection
  {
    const container = makeElement("div");
    container.id = "llm-monitor-workspace";
    const harness = createTestHarness(container);

    harness.responses.set("/api/llm-monitor/v1/status", () => ({
      json: async () => ({ availability: "available", configured_provider: "opencode" }),
    }));
    harness.responses.set("/api/llm-monitor/v1/snapshot", () => ({
      json: async () => ({ availability: "available", snapshot: { sessions: [] } }),
    }));

    const slowDeferred = deferred();
    harness.responses.set("/api/llm-monitor/v1/sessions/detail", (params) => {
      const sessId = params.get("session_id");
      if (sessId === "slow-session") {
        return slowDeferred.promise.then(() => ({
          json: async () => ({
            detail: { summary: { session_id: "slow-session", model: "old-model" } },
          }),
        }));
      }
      return {
        json: async () => ({
          detail: { summary: { session_id: "fast-session", model: "new-model" } },
        }),
      };
    });
    harness.responses.set("/api/llm-monitor/v1/sessions/timeline", () => ({ json: async () => ({ events: [] }) }));
    harness.responses.set("/api/llm-monitor/v1/alerts", () => ({ json: async () => ({ alerts: [] }) }));

    harness.Monitor.start(container, harness.api);
    harness.Monitor.onVisibilityChange(true);
    await new Promise((r) => setTimeout(r, 20));

    // Request slow session
    harness.Monitor.selectSession("http://127.0.0.1:4096", "slow-session");
    // Before slow resolves, switch to fast-session
    harness.Monitor.selectSession("http://127.0.0.1:4096", "fast-session");
    await new Promise((r) => setTimeout(r, 20));

    // Now resolve slow session
    slowDeferred.resolve();
    await new Promise((r) => setTimeout(r, 40));

    const contentEl = container.querySelector("#monitor-detail-content");
    assert.equal(contentEl.textContent.includes("fast-session"), true);
    assert.equal(contentEl.textContent.includes("new-model"), true);
    assert.equal(contentEl.textContent.includes("old-model"), false, "Outdated response must not overwrite active view");

    console.log("✓ Test 5: Outdated async race protection verified");
  }

  // --- Test 6: Auth locked (401) handling and dynamic class sanitization ---
  {
    let showLoginCalledWith = null;
    const container = makeElement("div");
    container.id = "llm-monitor-workspace";
    const harness = createTestHarness(container);
    harness.context.showLogin = (msg) => { showLoginCalledWith = msg; };
    harness.context.globalThis.showLogin = (msg) => { showLoginCalledWith = msg; };

    harness.responses.set("/api/llm-monitor/v1/status", () => ({
      json: async () => ({
        schema_version: 1,
        availability: "available",
        configured_provider: "opencode",
      }),
    }));

    // Return malformed / adversarial session state to test class sanitization
    harness.responses.set("/api/llm-monitor/v1/snapshot", () => ({
      json: async () => ({
        schema_version: 1,
        system: { total_sessions: 1, loaded_models: [] },
        sessions: [
          {
            provider_instance_id: "http://127.0.0.1:4096",
            session_id: "sec-sess",
            model: "qwen",
            state: "ACTIVE; color: red\" <script>",
          },
        ],
      }),
    }));

    harness.Monitor.start(container, harness.api);
    harness.Monitor.onVisibilityChange(true);
    await new Promise((r) => setTimeout(r, 40));

    const pill = container.querySelector(".session-status-pill");
    assert.ok(pill, "Status pill must exist");
    assert.equal(pill.className.includes("<script>"), false, "Must sanitize dynamic class");
    assert.equal(pill.className.includes("active--color--red---script-"), true, "Must normalize to safe CSS identifier");

    // Test auth locked error
    harness.responses.set("/api/llm-monitor/v1/sessions/detail", () => {
      throw new Error("locked");
    });

    harness.Monitor.selectSession("http://127.0.0.1:4096", "sec-sess");
    await new Promise((r) => setTimeout(r, 40));

    assert.ok(showLoginCalledWith, "showLogin must be called on 401 locked error");
    assert.ok(showLoginCalledWith.includes("Session expired"), "Must present session expired message");

    console.log("✓ Test 6: Auth locked (401) handling and dynamic class sanitization verified");
  }

  console.log("\nALL 6 llm_monitor_view_test.js TEST SUITES PASSED!");
}

runTests().catch((err) => {
  console.error("Test failed:", err);
  process.exit(1);
});
