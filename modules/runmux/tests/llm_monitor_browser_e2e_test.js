"use strict";

const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function runLLMMonitorBrowserE2E() {
  const rootDir = path.resolve(__dirname, "..");
  const tmpRoot = path.join(rootDir, ".pytest_tmp_root/llm_monitor_browser_e2e");
  fs.mkdirSync(tmpRoot, { recursive: true });
  const stateDir = fs.mkdtempSync(path.join(tmpRoot, "state-"));
  const chromeUserDir = fs.mkdtempSync(path.join(tmpRoot, "chrome-"));
  const chromePort = 9460;
  const webPort = 8798;
  const loginCode = "llm-monitor-e2e-secret";

  const screenshotsDir = path.join(
    rootDir,
    "docs/plans/20261029-0135_runmux-llm-monitor-host-integration/screenshots"
  );
  fs.mkdirSync(screenshotsDir, { recursive: true });

  // 1. Setup server script with FakeMonitoringAdapter
  const srcDir = path.join(rootDir, "src").replace(/\\/g, "/");
  const serverPy = path.join(stateDir, "run_server.py");
  const pyCode = [
    "import sys",
    `sys.path.insert(0, r"${srcDir}")`,
    "import json",
    "import time",
    "from pathlib import Path",
    "from runmux.store import RunStore",
    "from runmux.web import create_runmux_web_app",
    "from runmux.llm_monitor_integration import LLMMonitorIntegration, LLMMonitorConfig",
    "",
    "class FakeAdapter:",
    "    def __init__(self):",
    "        self.snapshot_calls = 0",
    "        self.detail_calls = 0",
    "        self.timeline_calls = 0",
    "        self.alerts_calls = 0",
    "",
    "    def snapshot(self, *, force_refresh: bool = False):",
    "        self.snapshot_calls += 1",
    "        return {",
    "            'schema_version': 1,",
    "            'refreshed_at': '2026-10-29T08:30:00Z',",
    "            'provider': {",
    "                'type': 'opencode',",
    "                'instance_id': 'http://127.0.0.1:4096',",
    "                'status': 'connected',",
    "                'error': None,",
    "            },",
    "            'system': {'total_sessions': 2, 'loaded_models': [{'name': 'qwen2.5-coder-32b', 'status': 'loaded'}]},",
    "            'sessions': [",
    "                {",
    "                    'provider_instance_id': 'http://127.0.0.1:4096',",
    "                    'session_id': 'sess-alpha-1234',",
    "                    'model': 'qwen2.5-coder-32b',",
    "                    'state': 'running',",
    "                    'tokens': {'prompt': 12450, 'completion': 6000, 'total': 18450},",
    "                },",
    "                {",
    "                    'provider_instance_id': 'http://127.0.0.1:4096',",
    "                    'session_id': 'sess-beta-5678',",
    "                    'model': 'claude-3-5-sonnet',",
    "                    'state': 'idle',",
    "                    'tokens': {'prompt': 4200, 'completion': 1100, 'total': 5300},",
    "                },",
    "            ],",
    "            'hardware': {",
    "                'scope': 'point_in_time',",
    "                'devices': [",
    "                    {",
    "                        'name': 'NVIDIA GeForce RTX 4090',",
    "                        'gpu_utilization_percent': 78,",
    "                        'vram_used_bytes': 19327352832,",
    "                        'vram_total_bytes': 25769803776,",
    "                        'temperature_celsius': 64,",
    "                    }",
    "                ],",
    "            },",
    "        }",
    "",
    "    def session_detail(self, provider_instance_id: str, session_id: str):",
    "        self.detail_calls += 1",
    "        return {",
    "            'schema_version': 1,",
    "            'summary': {",
    "                'session_id': session_id,",
    "                'provider_instance_id': provider_instance_id,",
    "                'state': 'running' if session_id == 'sess-alpha-1234' else 'idle',",
    "                'model': 'qwen2.5-coder-32b' if session_id == 'sess-alpha-1234' else 'claude-3-5-sonnet',",
    "            },",
    "            'recent_events': [",
    "                {'timestamp': '2026-10-29T08:29:10Z', 'type': 'tool_call', 'summary': \"read_file('modules/runmux/web.py')\"},",
    "                {'timestamp': '2026-10-29T08:28:45Z', 'type': 'inference', 'summary': 'Prompt evaluated (512 tokens at 38 tok/s)'},",
    "            ],",
    "            'context_utilization': {'used_tokens': 18450, 'total_tokens': 32768, 'utilization_ratio': 0.563},",
    "            'diagnostics': [",
    "                {'category': 'context', 'severity': 'info', 'message': 'Context window utilization within healthy bounds.'}",
    "            ],",
    "            'compactions': 2,",
    "        }",
    "",
    "    def timeline(self, provider_instance_id: str, session_id: str, *, cursor=None, limit=50):",
    "        self.timeline_calls += 1",
    "        return {",
    "            'schema_version': 1,",
    "            'events': [",
    "                {'timestamp': '2026-10-29T08:29:10Z', 'type': 'tool_call', 'summary': \"read_file('modules/runmux/web.py')\"},",
    "                {'timestamp': '2026-10-29T08:28:45Z', 'type': 'inference', 'summary': 'Prompt evaluated (512 tokens at 38 tok/s)'},",
    "            ],",
    "            'next_cursor': None,",
    "        }",
    "",
    "    def alerts(self, *, status=None, limit=100):",
    "        self.alerts_calls += 1",
    "        return {",
    "            'schema_version': 1,",
    "            'alerts': [",
    "                {",
    "                    'id': 'alt-1',",
    "                    'severity': 'warning',",
    "                    'timestamp': '2026-10-29T08:25:00Z',",
    "                    'message': 'Context window 56.3% utilized. Monitor memory compaction if conversation continues.',",
    "                }",
    "            ],",
    "        }",
    "",
    `state = Path(r"${stateDir.replace(/\\/g, "/")}")`,
    "store = RunStore(state)",
    "store.create_run(run_id='20261029-demo', name='demo-worker', status='running', program='python', argv_json='[]', cwd='.', env_overrides_json='{}', auth_token='tok', log_path=state/'demo.log', command_line='python demo.py')",
    "(state / 'demo.log').write_text('Log output demo\\n', encoding='utf-8')",
    "",
    "cfg = LLMMonitorConfig(enabled=True, opencode_url='http://127.0.0.1:4096', refresh_interval_seconds=5.0)",
    "integration = LLMMonitorIntegration(cfg)",
    "integration._adapter = FakeAdapter()",
    "app = create_runmux_web_app(state, login_code=sys.argv[1], llm_monitor_integration=integration)",
    "import uvicorn",
    `uvicorn.run(app, host='127.0.0.1', port=${webPort}, log_level='warning')`,
  ].join("\n");
  fs.writeFileSync(serverPy, pyCode, "utf8");

  const server = spawn("python", [serverPy, loginCode], {
    stdio: ["ignore", "pipe", "pipe"],
    cwd: rootDir,
    env: { ...process.env, PYTHONPATH: path.join(rootDir, "src") },
  });

  let serverExit = null;
  let serverOutput = "";
  server.on("exit", (code, signal) => { serverExit = { code, signal }; });
  for (const stream of [server.stdout, server.stderr]) {
    stream?.on("data", (chunk) => { serverOutput = `${serverOutput}${chunk}`.slice(-6000); });
  }

  let chrome = null;
  let ws = null;

  try {
    // Wait for server
    let serverReady = false;
    for (let i = 0; i < 40; i++) {
      await sleep(200);
      try {
        const res = await fetch(`http://127.0.0.1:${webPort}/`);
        if (res.ok) {
          serverReady = true;
          break;
        }
      } catch {}
      if (serverExit) break;
    }
    if (!serverReady) throw new Error(`Disposable server did not start in time: exit=${JSON.stringify(serverExit)}, output=${serverOutput}`);
    console.log("Server ready on port", webPort);

    // Launch Chrome
    const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
    chrome = spawn(chromePath, [
      "--headless=new",
      `--remote-debugging-port=${chromePort}`,
      `--user-data-dir=${chromeUserDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
      `http://127.0.0.1:${webPort}/`,
    ], { stdio: "ignore" });

    let pageWsUrl = null;
    for (let i = 0; i < 40; i++) {
      await sleep(200);
      try {
        const res = await fetch(`http://127.0.0.1:${chromePort}/json/list`);
        if (res.ok) {
          const pages = await res.json();
          const target = pages.find((p) => p.type === "page" && !p.url.startsWith("chrome-extension://"));
          if (target?.webSocketDebuggerUrl) {
            pageWsUrl = target.webSocketDebuggerUrl;
            break;
          }
        }
      } catch {}
    }
    if (!pageWsUrl) throw new Error("Could not find Chrome page CDP target");

    ws = new WebSocket(pageWsUrl);
    await new Promise((r) => (ws.onopen = r));

    let msgId = 1;
    function sendCommand(method, params = {}) {
      return new Promise((resolve, reject) => {
        const id = msgId++;
        function onMessage(event) {
          const data = JSON.parse(event.data);
          if (data.id === id) {
            ws.removeEventListener("message", onMessage);
            if (data.error) reject(data.error);
            else resolve(data.result);
          }
        }
        ws.addEventListener("message", onMessage);
        ws.send(JSON.stringify({ id, method, params }));
      });
    }

    async function evaluate(expression) {
      const res = await sendCommand("Runtime.evaluate", {
        expression,
        returnByValue: true,
        awaitPromise: true,
      });
      if (res.exceptionDetails) {
        throw new Error(`Browser eval error: ${JSON.stringify(res.exceptionDetails)}`);
      }
      return res.result.value;
    }

    // 2. Navigate and log in
    await sendCommand("Page.enable");
    await sendCommand("Page.navigate", { url: `http://127.0.0.1:${webPort}/` });
    await sleep(600);

    // Wait for login form
    for (let i = 0; i < 30; i++) {
      const ready = await evaluate(`Boolean(document.querySelector("#login-code"))`);
      if (ready) break;
      await sleep(150);
    }

    await evaluate(`(function() {
      const input = document.querySelector("#login-code");
      input.value = "${loginCode}";
      document.querySelector("#login-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    })()`);
    await sleep(800);

    // 3. Verify top navigation presence
    const navState = await evaluate(`({
      procTab: document.querySelector("#view-tab-processes")?.textContent.trim(),
      monitorTab: document.querySelector("#view-tab-llm-monitor")?.textContent.trim(),
      procActive: document.querySelector("#view-tab-processes")?.classList.contains("active"),
      workspaceVisible: !document.querySelector("#workspace")?.hidden,
      monitorHidden: document.querySelector("#llm-monitor-workspace")?.hidden
    })`);
    assert.equal(navState.procTab, "Processes");
    assert.equal(navState.monitorTab, "LLM Monitor");
    assert.equal(navState.procActive, true);
    assert.equal(navState.workspaceVisible, true);
    assert.equal(navState.monitorHidden, true);
    console.log("Verified initial Processes workspace is active.");

    // 4. Switch to LLM Monitor workspace
    console.log("Switching to LLM Monitor workspace...");
    await evaluate(`document.querySelector("#view-tab-llm-monitor").click()`);
    await sleep(700);

    const monitorState = await evaluate(`({
      procActive: document.querySelector("#view-tab-processes")?.classList.contains("active"),
      monitorActive: document.querySelector("#view-tab-llm-monitor")?.classList.contains("active"),
      workspaceHidden: document.querySelector("#workspace")?.hidden,
      monitorVisible: !document.querySelector("#llm-monitor-workspace")?.hidden,
      statusBadge: document.querySelector("#monitor-status-pill")?.textContent.trim(),
      statusClass: document.querySelector("#monitor-status-pill")?.classList.contains("available"),
      cardsCount: document.querySelectorAll(".monitor-session-card").length,
    })`);
    assert.equal(monitorState.procActive, false);
    assert.equal(monitorState.monitorActive, true);
    assert.equal(monitorState.workspaceHidden, true);
    assert.equal(monitorState.monitorVisible, true);
    assert.ok(monitorState.statusBadge.includes("Connected"));
    assert.equal(monitorState.statusClass, true);
    assert.equal(monitorState.cardsCount, 2);
    console.log("Verified LLM Monitor workspace active with 2 sessions rendered.");

    // 5. Select active session (sess-alpha-1234)
    console.log("Selecting session sess-alpha-1234...");
    await evaluate(`(function() {
      const cards = document.querySelectorAll(".monitor-session-card");
      cards[0].click();
    })()`);
    await sleep(600);

    const detailState = await evaluate(`(function() {
      const items = Array.from(document.querySelectorAll(".detail-item"));
      const map = {};
      for (const item of items) {
        const label = item.querySelector(".detail-label")?.textContent.trim();
        const code = item.querySelector("code, span.status-badge")?.textContent.trim();
        if (label) map[label] = code;
      }
      return {
        selectedId: document.querySelector(".monitor-session-card.selected .session-id-text")?.textContent.trim(),
        modelText: map["MODEL"],
        statusText: map["STATUS"],
        utilText: map["CONTEXT UTILIZATION"],
        hardwareCard: document.querySelector(".hardware-device-box")?.textContent,
        alertsCount: document.querySelectorAll(".alert-item").length,
        eventsCount: document.querySelectorAll(".timeline-event-item").length,
      };
    })()`);

    assert.equal(detailState.selectedId, "sess-alpha-1234");
    assert.equal(detailState.modelText, "qwen2.5-coder-32b");
    assert.equal(detailState.statusText, "running");
    assert.equal(detailState.utilText, "56.3%");
    assert.ok(detailState.hardwareCard.includes("RTX 4090"), "Hardware box must mention RTX 4090");
    assert.equal(detailState.alertsCount, 1);
    assert.equal(detailState.eventsCount, 2);
    console.log("Verified session detail diagnostics, hardware metrics, alerts, and timeline.");

    // 5b. Select second session (sess-beta-5678)
    console.log("Selecting second session sess-beta-5678...");
    await evaluate(`(function() {
      const cards = document.querySelectorAll(".monitor-session-card");
      cards[1].click();
    })()`);
    await sleep(600);

    const secondSessionState = await evaluate(`(function() {
      const items = Array.from(document.querySelectorAll(".detail-item"));
      const map = {};
      for (const item of items) {
        const label = item.querySelector(".detail-label")?.textContent.trim();
        const code = item.querySelector("code, span.status-badge")?.textContent.trim();
        if (label) map[label] = code;
      }
      return {
        selectedId: document.querySelector(".monitor-session-card.selected .session-id-text")?.textContent.trim(),
        modelText: map["MODEL"],
        statusText: map["STATUS"],
      };
    })()`);

    assert.equal(secondSessionState.selectedId, "sess-beta-5678");
    assert.equal(secondSessionState.modelText, "claude-3-5-sonnet");
    assert.equal(secondSessionState.statusText, "idle");
    console.log("Verified switching to second session updates diagnostics and status.");

    // 6. Responsive viewports and screenshots
    const viewports = [
      { name: "desktop_1920", width: 1920, height: 1080, mobile: false },
      { name: "laptop_1366", width: 1366, height: 768, mobile: false },
      { name: "tablet_768", width: 768, height: 1024, mobile: false },
      { name: "mobile_390", width: 390, height: 844, mobile: true },
    ];

    for (const vp of viewports) {
      console.log(`Testing viewport ${vp.name} (${vp.width}x${vp.height})...`);
      await sendCommand("Emulation.setDeviceMetricsOverride", {
        width: vp.width,
        height: vp.height,
        deviceScaleFactor: 1,
        mobile: vp.mobile,
      });
      await sleep(300);

      // Verify no horizontal overflow
      const pageDims = await evaluate(`({
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
      })`);
      assert.ok(
        pageDims.scrollW <= pageDims.clientW + 2,
        `Page overflow at ${vp.width}px: scrollWidth=${pageDims.scrollW}, clientWidth=${pageDims.clientW}`
      );

      // Capture screenshot
      const shot = await sendCommand("Page.captureScreenshot", { format: "png" });
      const filename = path.join(screenshotsDir, `llm_monitor_${vp.name}.png`);
      fs.writeFileSync(filename, Buffer.from(shot.data, "base64"));
      console.log(`Saved screenshot: llm_monitor_${vp.name}.png`);
    }

    // 7. Switch back to Processes workspace
    console.log("Switching back to Processes workspace...");
    await evaluate(`document.querySelector("#view-tab-processes").click()`);
    await sleep(400);

    const backState = await evaluate(`({
      procActive: document.querySelector("#view-tab-processes")?.classList.contains("active"),
      monitorActive: document.querySelector("#view-tab-llm-monitor")?.classList.contains("active"),
      procVisible: !document.querySelector("#workspace")?.hidden,
      monitorHidden: document.querySelector("#llm-monitor-workspace")?.hidden,
    })`);
    assert.equal(backState.procActive, true);
    assert.equal(backState.monitorActive, false);
    assert.equal(backState.procVisible, true);
    assert.equal(backState.monitorHidden, true);
    console.log("Verified switching back to Processes workspace restores view.");

    // 8. Test Logout / Lock cleanup
    console.log("Testing lock / logout cleanup...");
    await evaluate(`document.querySelector("#logout-button").click()`);
    await sleep(400);

    const logoutState = await evaluate(`({
      loginVisible: !document.querySelector("#login-view")?.hidden,
      dashboardHidden: Boolean(document.querySelector("#dashboard")?.hidden),
      monitorStatus: window.RunmuxLLMMonitor?.getStatus(),
    })`);
    assert.equal(logoutState.loginVisible, true);
    assert.equal(logoutState.dashboardHidden, true);
    assert.equal(logoutState.monitorStatus, null);
    console.log("Verified logout clears authentication, stops monitor polling, and resets state.");

    // 9. Test Reauthentication
    console.log("Testing reauthentication after logout...");
    await evaluate(`(function() {
      const input = document.querySelector("#login-code");
      input.value = "${loginCode}";
      document.querySelector("#login-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    })()`);
    await sleep(800);

    const reloginState = await evaluate(`({
      loginHidden: Boolean(document.querySelector("#login-view")?.hidden),
      dashboardVisible: !document.querySelector("#dashboard")?.hidden,
      monitorAvail: window.RunmuxLLMMonitor?.getStatus()?.availability,
    })`);
    assert.equal(reloginState.loginHidden, true);
    assert.equal(reloginState.dashboardVisible, true);
    assert.equal(reloginState.monitorAvail, "available");
    console.log("Verified reauthentication restores dashboard and re-initializes monitor availability.");

    console.log("\n================================================");
    console.log("ALL REAL BROWSER LLM MONITOR E2E TESTS PASSED!");
    console.log("================================================");
  } finally {
    if (ws) ws.close();
    if (chrome) chrome.kill();
    if (server) server.kill();
  }
}

runLLMMonitorBrowserE2E().catch((err) => {
  console.error("Browser E2E Failure:", err);
  process.exit(1);
});
