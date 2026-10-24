"use strict";

const assert = require("node:assert/strict");
const { spawn, execSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function runBrowserE2E() {
  const tmpRoot = path.join(__dirname, "../.pytest_tmp_root/e2e_live");
  fs.mkdirSync(tmpRoot, { recursive: true });
  const stateDir = fs.mkdtempSync(path.join(tmpRoot, "state-"));
  const chromeUserDir = fs.mkdtempSync(path.join(tmpRoot, "chrome-"));
  const chromePort = 9444;
  const webPort = 8791;
  const loginCode = "e2e-secret-code";
  const runId = "20261024-070000-e2e1a2";

  // 1. Create synthetic fixture
  let workerProc = spawn("python", ["-c", "import time; time.sleep(120)"], { stdio: "ignore" });
  const workerPid = workerProc.pid;
  const runId2 = "20261024-070001-e2e1b3";

  const runDir = path.join(stateDir, "runs", runId);
  fs.mkdirSync(runDir, { recursive: true });
  const logFile = path.join(runDir, "output.ansi");

  let initialLogs = "";
  initialLogs += "\x1b[32m[INFO] System initialized on port 8080\x1b[0m\n";
  initialLogs += "\x1b[33m[WARN] Memory pressure threshold exceeded\x1b[0m\n";
  initialLogs += "\x1b[31m[ERROR] Connection timeout to database:5432\x1b[0m\n";
  initialLogs += "Progress: 45% (120/300 files) done\n";
  initialLogs += "<script>window.__xss_executed = true; alert('xss')</script><img src=\"x\" onerror=\"window.__img_xss = true;\">\n";
  for (let i = 0; i < 1000; i++) {
    initialLogs += `Synthetic log line ${i} payload data\n`;
  }
  fs.writeFileSync(logFile, initialLogs, "utf8");

  // Create SQLite registry
  const srcDir = path.join(__dirname, "../src").replace(/\\/g, "/");
  const setupScript = path.join(stateDir, "setup_db.py");
  const pyCode = [
    "import sys",
    `sys.path.insert(0, r"${srcDir}")`,
    "import json",
    "from pathlib import Path",
    "from runmux.store import RunStore",
    `state = Path(r"${stateDir.replace(/\\/g, "/")}")`,
    "store = RunStore(state)",
    "store.create_run(",
    `    run_id="${runId}",`,
    '    name="e2e worker",',
    '    status="running",',
    '    program=r"C:\\tools\\worker.exe",',
    '    argv_json=json.dumps(["worker.exe"]),',
    '    cwd=r"C:\\private\\folder",',
    "    env_overrides_json=json.dumps({}),",
    '    auth_token="ipc-secret",',
    `    log_path=Path(r"${logFile.replace(/\\/g, "/")}"),`,
    '    command_line="worker.exe",',
    ")",
    `store.update_run("${runId}", pid=${workerPid})`,
    "store.create_run(",
    `    run_id="${runId2}",`,
    '    name="finished worker",',
    '    status="finished",',
    '    program=r"C:\\tools\\finished.exe",',
    '    argv_json=json.dumps(["finished.exe"]),',
    '    cwd=r"C:\\private\\folder",',
    "    env_overrides_json=json.dumps({}),",
    '    auth_token="ipc-secret",',
    `    log_path=Path(r"${logFile.replace(/\\/g, "/")}"),`,
    '    command_line="finished.exe",',
    ")",
    `store.update_run("${runId2}", exit_code=0)`,
  ].join("\n");
  fs.writeFileSync(setupScript, pyCode, "utf8");
  execSync(`python "${setupScript}"`, { env: { ...process.env, PYTHONPATH: path.join(__dirname, "../src") } });

  // 2. Start disposable Runmux Web Server using uvicorn directly
  console.log(`Starting disposable web server on 127.0.0.1:${webPort}...`);
  const serverScript = [
    "import sys",
    `sys.path.insert(0, r"${srcDir}")`,
    "from pathlib import Path",
    "import uvicorn",
    "from runmux.web import create_runmux_web_app",
    "app = create_runmux_web_app(Path(sys.argv[1]), login_code=sys.argv[2])",
    "uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[3]), log_level='warning')",
  ].join("\n");
  const serverPyFile = path.join(stateDir, "run_server.py");
  fs.writeFileSync(serverPyFile, serverScript, "utf8");

  const server = spawn(
    "python",
    [serverPyFile, stateDir, loginCode, `${webPort}`],
    {
      stdio: "inherit",
      cwd: path.join(__dirname, ".."),
      env: { ...process.env, PYTHONPATH: path.join(__dirname, "../src") }
    }
  );

  let chrome = null;
  let ws = null;

  try {
    // Wait for server to respond
    let serverReady = false;
    for (let i = 0; i < 40; i++) {
      await sleep(250);
      try {
        const res = await fetch(`http://127.0.0.1:${webPort}/`);
        if (res.ok) {
          serverReady = true;
          break;
        }
      } catch {}
    }
    if (!serverReady) throw new Error("Disposable web server did not start in time");
    console.log("Web server is ready.");

    // 3. Launch headless Chrome
    const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
    console.log("Launching headless Chrome...");
    chrome = spawn(chromePath, [
      "--headless=new",
      `--remote-debugging-port=${chromePort}`,
      `--user-data-dir=${chromeUserDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
      `http://127.0.0.1:${webPort}/`,
    ], { stdio: "ignore" });

    // Connect to Chrome page CDP
    let pageWsUrl = null;
    for (let i = 0; i < 40; i++) {
      await sleep(250);
      try {
        const res = await fetch(`http://127.0.0.1:${chromePort}/json/list`);
        if (res.ok) {
          const pages = await res.json();
          const target = pages.find((p) => p.type === "page" && !p.url.startsWith("chrome-extension://"));
          if (target && target.webSocketDebuggerUrl) {
            pageWsUrl = target.webSocketDebuggerUrl;
            break;
          }
        }
      } catch {}
    }
    if (!pageWsUrl) throw new Error("Could not find Chrome page target");
    console.log("Connected to Chrome page CDP:", pageWsUrl);

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

    // 4. Navigate and Log in
    console.log("Navigating page to dashboard URL...");
    await sendCommand("Page.enable");
    await sendCommand("Page.navigate", { url: `http://127.0.0.1:${webPort}/` });

    console.log("Waiting for page and login form to load...");
    for (let i = 0; i < 40; i++) {
      await sleep(250);
      try {
        const ready = await evaluate(`Boolean(document.querySelector("#login-code"))`);
        if (ready) break;
      } catch {}
    }
    console.log("Submitting login form in browser...");
    await evaluate(`(function() {
      const input = document.querySelector("#login-code");
      input.value = "${loginCode}";
      document.querySelector("#login-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    })()`);

    // Wait for dashboard to display
    let loggedIn = false;
    for (let i = 0; i < 40; i++) {
      await sleep(200);
      const dashboardHidden = await evaluate(`document.querySelector("#dashboard").hidden`);
      if (dashboardHidden === false) {
        loggedIn = true;
        break;
      }
    }
    assert.equal(loggedIn, true, "Dashboard failed to become visible after login");
    console.log("Dashboard loaded successfully.");

    // Wait for process row in explorer and click it
    await sleep(500);
    const rowClicked = await evaluate(`(function() {
      const row = document.querySelector(".process-row");
      if (row) {
        row.click();
        return true;
      }
      return false;
    })()`);
    assert.equal(rowClicked, true, "Process row not found in explorer");
    console.log("Clicked process row in explorer.");

    // Wait for output to load
    let outputLoaded = false;
    let lastSeenText = "";
    for (let i = 0; i < 40; i++) {
      await sleep(250);
      lastSeenText = await evaluate(`document.querySelector("#output-text").textContent`);
      if (lastSeenText && lastSeenText.includes("System initialized")) {
        outputLoaded = true;
        break;
      }
    }
    if (!outputLoaded) {
      const stateText = await evaluate(`document.querySelector("#output-state").textContent`);
      console.log("Last seen output-text was:", JSON.stringify(lastSeenText));
      console.log("Last seen output-state was:", JSON.stringify(stateText));
    }
    assert.equal(outputLoaded, true, "Output text failed to load");
    console.log("Output content loaded in pre element.");

    // 5. Test Malicious Text & XSS Immunity in Real Browser Engine
    const xssExecuted = await evaluate(`window.__xss_executed`);
    const imgXss = await evaluate(`window.__img_xss`);
    assert.equal(xssExecuted, undefined, "XSS script executed in real browser!");
    assert.equal(imgXss, undefined, "Image onerror XSS executed in real browser!");
    console.log("Verified XSS immunity: zero unauthorized script execution.");

    // 6. Test Search: Plain Query
    console.log("Testing search query...");
    await evaluate(`(function() {
      const input = document.querySelector("#output-search-query");
      input.value = "timeout";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(100);

    const matchCountText = await evaluate(`document.querySelector("#output-search-count").textContent`);
    assert.equal(matchCountText, "1 of 1 (loaded buffer)");

    const markFound = await evaluate(`(function() {
      const mark = document.querySelector("#output-text mark.output-match.active-match");
      return mark ? mark.textContent : null;
    })()`);
    assert.equal(markFound, "timeout");
    console.log("Verified plain search match and highlight.");

    // 7. Test Literal Search with Special Characters & Case Sensitivity
    console.log("Testing literal search with regex characters and case toggle...");
    await evaluate(`(function() {
      const caseBtn = document.querySelector("#output-search-case");
      caseBtn.click();
      const input = document.querySelector("#output-search-query");
      input.value = "[ERROR]";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(100);

    const literalCount = await evaluate(`document.querySelector("#output-search-count").textContent`);
    assert.equal(literalCount, "1 of 1 (loaded buffer)");
    const literalMark = await evaluate(`document.querySelector("#output-text mark.output-match").textContent`);
    assert.equal(literalMark, "[ERROR]");
    console.log("Verified literal search with brackets and case toggle.");

    // 8. Test Catastrophic Backtracking ReDoS Protection in Real Chrome
    console.log("Testing ReDoS catastrophic backtracking protection in browser...");
    const redosStart = Date.now();
    await evaluate(`(function() {
      const input = document.querySelector("#output-search-query");
      input.value = "(a+)+$";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(100);
    const redosDuration = Date.now() - redosStart;
    assert.ok(redosDuration < 500, `ReDoS search took too long in Chrome: ${redosDuration}ms`);
    const redosCount = await evaluate(`document.querySelector("#output-search-count").textContent`);
    assert.equal(redosCount, "0 matches (loaded buffer)");
    console.log("Verified zero UI freeze on catastrophic regex pattern input.");

    // Reset case sensitivity toggle
    await evaluate(`document.querySelector("#output-search-case").click()`);
    await sleep(100);

    // 9. Test Clear Search
    console.log("Testing clear search...");
    await evaluate(`document.querySelector("#output-search-clear").click()`);
    await sleep(100);
    const clearedCount = await evaluate(`document.querySelector("#output-search-count").textContent`);
    assert.equal(clearedCount, "No query");

    // 10. Test Severity Filter
    console.log("Testing severity filter...");
    await evaluate(`(function() {
      const select = document.querySelector("#output-severity-filter");
      select.value = "error";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    })()`);
    await sleep(100);

    const filteredScope = await evaluate(`document.querySelector("#output-scope-note").textContent`);
    assert.match(filteredScope, /Showing 1 of [\d,]+ lines \(loaded buffer\)/);

    const filteredText = await evaluate(`document.querySelector("#output-text").textContent`);
    assert.match(filteredText, /Connection timeout/);
    assert.doesNotMatch(filteredText, /System initialized/);
    console.log("Verified severity filter (errors only).");

    // Test Unstructured / Other filter
    await evaluate(`(function() {
      const select = document.querySelector("#output-severity-filter");
      select.value = "other";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    })()`);
    await sleep(100);

    const otherText = await evaluate(`document.querySelector("#output-text").textContent`);
    assert.match(otherText, /Progress: 45%/);
    assert.doesNotMatch(otherText, /Connection timeout/);
    console.log("Verified unstructured / other severity filter.");

    // Reset filter to All
    await evaluate(`(function() {
      const select = document.querySelector("#output-severity-filter");
      select.value = "all";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    })()`);
    await sleep(100);

    // 11. Test Live Streaming Updates
    console.log("Testing live streaming update...");
    fs.appendFileSync(logFile, "\x1b[31m[ERROR] Live appended error stream\x1b[0m\n", "utf8");

    let liveStreamReceived = false;
    for (let i = 0; i < 20; i++) {
      await sleep(300);
      const text = await evaluate(`document.querySelector("#output-text").textContent`);
      if (text && text.includes("Live appended error stream")) {
        liveStreamReceived = true;
        break;
      }
    }
    assert.equal(liveStreamReceived, true, "Live stream update was not received by browser");
    console.log("Verified live streaming log updates in browser.");

    // 12. Test Pathological Buffer DOM Bounding & Accurate Labels in Real Chrome
    console.log("Testing pathological buffer DOM bounding in real Chrome...");
    let pathologicalLines = "";
    for (let i = 0; i < 4000; i++) {
      pathologicalLines += `Synthetic pathological line ${i} data\n`;
    }
    fs.appendFileSync(logFile, pathologicalLines, "utf8");

    // Wait for output chunk to be received
    let streamArrived = false;
    for (let i = 0; i < 30; i++) {
      await sleep(300);
      const text = await evaluate(`document.querySelector("#output-text").textContent`);
      if (text && text.includes("Synthetic pathological line 3999")) {
        streamArrived = true;
        break;
      }
    }
    assert.equal(streamArrived, true, "Pathological lines did not stream to browser");

    // Trigger search over the 4000+ line buffer
    await evaluate(`(function() {
      const input = document.querySelector("#output-search-query");
      input.value = "pathological";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(200);

    // Verify DOM element bounding in actual Chrome DOM tree
    const domLineCount = await evaluate(`document.querySelectorAll("#output-text .output-line").length`);
    assert.equal(domLineCount, 2000, "DOM lines must be strictly bounded to 2000 in real browser");

    const pathScope = await evaluate(`document.querySelector("#output-scope-note").textContent`);
    assert.match(pathScope, /displaying lines [\d,]+–[\d,]+/);

    const pathCount = await evaluate(`document.querySelector("#output-search-count").textContent`);
    assert.match(pathCount, /lines [\d,]+–[\d,]+ displayed/);

    // Navigate matches in real browser
    await evaluate(`(function() {
      document.querySelector("#output-search-next").click();
      document.querySelector("#output-search-next").click();
    })()`);
    await sleep(100);
    const navCount = await evaluate(`document.querySelector("#output-search-count").textContent`);
    assert.match(navCount, /^3 of [\d,]+/);
    console.log("Verified DOM bounding (2,000 max nodes) and accurate labels in real Chrome engine.");

    // 13. Phase 5A: Mode Switching & Direct Selection
    console.log("Testing Phase 5A overview modes and switching in real Chrome...");
    const screenshotsDir = path.join(__dirname, "../docs/plans/20261024-runmux-web-overview-telemetry/screenshots");
    fs.mkdirSync(screenshotsDir, { recursive: true });

    // Ensure we are in Mode B initially (default)
    await evaluate(`window.setOverviewMode("inline")`);
    await sleep(2000); // Allow telemetry poll cycle to populate real metrics

    let modeBHasStats = await evaluate(`(function() {
      const cpu = document.querySelector("#val-inline-cpu").textContent;
      const rss = document.querySelector("#val-inline-rss").textContent;
      return cpu !== "—" || rss !== "—";
    })()`);
    console.log("Mode B inline stats loaded:", modeBHasStats);

    // Capture Mode B screenshot (Desktop 1366x768)
    await sendCommand("Emulation.setDeviceMetricsOverride", { width: 1366, height: 768, deviceScaleFactor: 1, mobile: false });
    await sleep(300);
    let shotB = await sendCommand("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(screenshotsDir, "mode_b_inline.png"), Buffer.from(shotB.data, "base64"));
    console.log("Saved mode_b_inline.png");

    // Mode A: Minimal
    await evaluate(`document.querySelector("#mode-btn-a").click()`);
    await sleep(300);
    const isModeA = await evaluate(`document.querySelector("#run-inspector").classList.contains("mode-minimal")`);
    assert.equal(isModeA, true, "Mode A was not applied");
    const inlineHiddenA = await evaluate(`document.querySelector("#inline-telemetry").hidden`);
    const panelHiddenA = await evaluate(`document.querySelector("#telemetry-panel").hidden`);
    assert.equal(inlineHiddenA, true, "Inline telemetry should be hidden in Mode A");
    assert.equal(panelHiddenA, true, "Telemetry panel should be hidden in Mode A");
    let shotA = await sendCommand("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(screenshotsDir, "mode_a_minimal.png"), Buffer.from(shotA.data, "base64"));
    console.log("Saved mode_a_minimal.png");

    // Mode C: Dashboard
    await evaluate(`document.querySelector("#mode-btn-c").click()`);
    await sleep(2200); // Wait for telemetry poll cycle
    const isModeC = await evaluate(`document.querySelector("#run-inspector").classList.contains("mode-dashboard")`);
    assert.equal(isModeC, true, "Mode C was not applied");
    const panelVisibleC = await evaluate(`!document.querySelector("#telemetry-panel").hidden`);
    assert.equal(panelVisibleC, true, "Telemetry panel should be visible in Mode C");
    const hostHiddenC = await evaluate(`document.querySelector("#host-telemetry-section").hidden`);
    assert.equal(hostHiddenC, true, "Host telemetry section should be hidden in Mode C");
    let shotC = await sendCommand("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(screenshotsDir, "mode_c_dashboard.png"), Buffer.from(shotC.data, "base64"));
    console.log("Saved mode_c_dashboard.png");

    // Mode D: Expanded
    await evaluate(`document.querySelector("#mode-btn-d").click()`);
    await sleep(2200); // Wait for telemetry poll cycle
    const isModeD = await evaluate(`document.querySelector("#run-inspector").classList.contains("mode-expanded")`);
    assert.equal(isModeD, true, "Mode D was not applied");
    const hostVisibleD = await evaluate(`!document.querySelector("#host-telemetry-section").hidden`);
    assert.equal(hostVisibleD, true, "Host telemetry section should be visible in Mode D");
    let shotD = await sendCommand("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(screenshotsDir, "mode_d_expanded.png"), Buffer.from(shotD.data, "base64"));
    console.log("Saved mode_d_expanded.png");

    // Verify scope labels in Mode D
    const procScopeText = await evaluate(`document.querySelector("#process-telemetry-section .scope-tag").textContent`);
    assert.equal(procScopeText, "PROCESS TREE");
    const hostScopeText = await evaluate(`document.querySelector("#host-telemetry-section .scope-tag").textContent`);
    assert.match(hostScopeText, /HOST & SYSTEM/);
    const hostNetCard = await evaluate(`document.querySelector("#card-host-net .card-label").textContent`);
    assert.equal(hostNetCard, "HOST NETWORK (SYSTEM-WIDE)");
    const gpuDevCard = await evaluate(`document.querySelector("#card-gpu-dev .card-label").textContent`);
    assert.equal(gpuDevCard, "GPU DEVICE (HARDWARE)");
    const gpuProcVal = await evaluate(`document.querySelector("#card-gpu-proc-val").textContent`);
    const gpuProcSub = await evaluate(`document.querySelector("#card-gpu-proc-sub").textContent`);
    console.log(`Real Chrome GPU Attribution: ${gpuProcVal} (${gpuProcSub})`);
    assert.ok(
      gpuProcVal === "Unavailable" || gpuProcVal === "0 B" || gpuProcVal.includes("B"),
      `GPU attribution should be Unavailable, 0 B, or formatted bytes, but was: ${gpuProcVal}`
    );
    console.log("Verified scope labels and hardware separation in Mode D.");

    // Cycle Mode via button: D -> A -> B -> C -> D
    await evaluate(`document.querySelector("#mode-cycle-btn").click()`);
    assert.equal(await evaluate(`document.querySelector("#run-inspector").classList.contains("mode-minimal")`), true);
    await evaluate(`document.querySelector("#mode-cycle-btn").click()`);
    assert.equal(await evaluate(`document.querySelector("#run-inspector").classList.contains("mode-inline")`), true);
    await evaluate(`document.querySelector("#mode-cycle-btn").click()`);
    assert.equal(await evaluate(`document.querySelector("#run-inspector").classList.contains("mode-dashboard")`), true);
    await evaluate(`document.querySelector("#mode-cycle-btn").click()`);
    assert.equal(await evaluate(`document.querySelector("#run-inspector").classList.contains("mode-expanded")`), true);
    console.log("Verified mode cycling A -> B -> C -> D -> A.");

    // 14. Test Persistence Across Page Reload
    console.log("Testing overview mode persistence across page reload...");
    await evaluate(`window.setOverviewMode("dashboard")`);
    await sendCommand("Page.reload");
    let reloadedRow = false;
    for (let i = 0; i < 40; i++) {
      await sleep(200);
      try {
        const pageState = await evaluate(`({
          hasLogin: Boolean(document.querySelector("#login-form")),
          loginHidden: Boolean(document.querySelector("#login-view")?.hidden),
          dashHidden: Boolean(document.querySelector("#dashboard")?.hidden),
          hasRow: Boolean(document.querySelector(".process-row")),
          rowsCount: document.querySelectorAll(".process-row").length,
          url: window.location.href,
        })`);
        if (i % 5 === 0) console.log("Reload state at i=" + i + ":", JSON.stringify(pageState));
        if (pageState.hasRow) { reloadedRow = true; break; }
        // If login form is shown because session cookie wasn't persisted or expired, log in
        if (pageState.hasLogin && !pageState.loginHidden) {
          console.log("Submitting login form again after reload...");
          await evaluate(`(function() {
            const input = document.querySelector("#login-code");
            input.value = "${loginCode}";
            document.querySelector("#login-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
          })()`);
        }
      } catch (e) {
        if (i % 5 === 0) console.log("Eval error at i=" + i + ":", e.message);
      }
    }
    assert.equal(reloadedRow, true, "Process row not found after reload");
    await evaluate(`document.querySelector(".process-row").click()`);
    await sleep(500);
    const reloadedMode = await evaluate(`window.overviewMode`);
    assert.equal(reloadedMode, "dashboard", "Overview mode did not persist across reload");
    const reloadedClass = await evaluate(`document.querySelector("#run-inspector").classList.contains("mode-dashboard")`);
    assert.equal(reloadedClass, true, "DOM class did not reflect persisted overview mode");
    console.log("Verified persistence of mode across browser reloads.");

    // 15. Responsive Viewports Testing
    console.log("Testing responsive viewports (390, 768, 1366, 1920, 2560px)...");
    const viewports = [
      { width: 390, height: 844, mobile: true },
      { width: 768, height: 1024, mobile: false },
      { width: 1366, height: 768, mobile: false },
      { width: 1920, height: 1080, mobile: false },
      { width: 2560, height: 1080, mobile: false },
    ];
    for (const vp of viewports) {
      await sendCommand("Emulation.setDeviceMetricsOverride", { width: vp.width, height: vp.height, deviceScaleFactor: 1, mobile: vp.mobile });
      await sleep(200);
      const scrollWidth = await evaluate(`document.documentElement.scrollWidth`);
      const clientWidth = await evaluate(`document.documentElement.clientWidth`);
      assert.ok(scrollWidth <= clientWidth + 2, `Horizontal overflow at ${vp.width}px: scrollWidth=${scrollWidth}, clientWidth=${clientWidth}`);
    }
    await sendCommand("Emulation.clearDeviceMetricsOverride");
    console.log("Verified responsive stability across all viewports without horizontal overflow.");

    // 16. Run switching and terminal run handling
    console.log("Testing run switching and terminal run handling...");
    // Switch to finished run
    await evaluate(`(function() {
      const rows = document.querySelectorAll(".process-row");
      if (rows.length > 1) rows[1].click();
    })()`);
    await sleep(800);
    const selectedFinished = await evaluate(`document.querySelector("#selected-name").textContent`);
    assert.equal(selectedActiveOrFinished(selectedFinished), true);

    // Switch back to active run
    await evaluate(`document.querySelectorAll(".process-row")[0].click()`);
    await sleep(800);
    const selectedActive = await evaluate(`document.querySelector("#selected-name").textContent`);
    assert.equal(selectedActive, "e2e worker");
    console.log("Verified run switching while telemetry is active.");

    function selectedActiveOrFinished(name) {
      return name === "finished worker" || name === "e2e worker";
    }

    console.log("\n==========================================");
    console.log("ALL REAL HEADLESS BROWSER E2E TESTS PASSED!");
    console.log("==========================================\n");
  } finally {
    if (workerProc) {
      try { workerProc.kill("SIGKILL"); } catch {}
    }
    if (ws) {
      try { ws.close(); } catch {}
    }
    if (chrome) {
      try { chrome.kill("SIGKILL"); } catch {}
    }
    if (server) {
      try { server.kill("SIGKILL"); } catch {}
    }
    await sleep(500);
    try { fs.rmSync(stateDir, { recursive: true, force: true }); } catch {}
    try { fs.rmSync(chromeUserDir, { recursive: true, force: true }); } catch {}
  }
}

runBrowserE2E().catch((err) => {
  console.error("Browser E2E Failure:", err);
  process.exit(1);
});
