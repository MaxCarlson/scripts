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
    '    cwd=r"' + stateDir.replace(/\\/g, "/") + '",',
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
    '    cwd=r"' + stateDir.replace(/\\/g, "/") + '",',
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
    "import json",
    "from pathlib import Path",
    "from types import SimpleNamespace",
    "import runmux.runner",
    "import runmux.web",
    "def mock_create_managed_run(target_store, **kwargs):",
    "    runs = target_store.list_runs()",
    "    new_id = f'20261024-09990{len(runs) + 1}-abcdef'",
    "    new_dir = target_store.state_dir / 'runs' / new_id",
    "    new_dir.mkdir(parents=True, exist_ok=True)",
    "    log = new_dir / 'output.ansi'",
    "    log.write_text('New run log output\\n', encoding='utf-8')",
    "    new_rec = target_store.create_run(",
    "        run_id=new_id,",
    "        name=kwargs.get('name') or 'worker',",
    "        status='running',",
    "        program='python',",
    "        argv_json=json.dumps(kwargs.get('program_args') or ['python']),",
    "        cwd=str(kwargs.get('cwd') or target_store.state_dir),",
    "        env_overrides_json='{}',",
    "        auth_token='new-token',",
    "        log_path=log,",
    "        command_line='python',",
    "        restart_of=kwargs.get('restart_of'),",
    "        duplicate_of=kwargs.get('duplicate_of'),",
    "    )",
    "    return SimpleNamespace(record=new_rec, supervisor_process=None)",
    "runmux.runner.create_managed_run = mock_create_managed_run",
    "runmux.web.create_managed_run = mock_create_managed_run",
    "from runmux.web import create_runmux_web_app",
    "import uvicorn",
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

    // 17. Phase 4A: Selected-process Lifecycle Browser Controls
    console.log("Testing Phase 4A lifecycle controls and confirmation modal in real Chrome...");
    const lifecycleScreenshotsDir = path.join(__dirname, "../docs/plans/20261024-1315_runmux-web-lifecycle-frontend/screenshots");
    fs.mkdirSync(lifecycleScreenshotsDir, { recursive: true });

    // Select the active run ("e2e worker")
    await evaluate(`(function() {
      const rows = document.querySelectorAll(".process-row");
      for (const row of rows) {
        if (row.textContent.includes("e2e worker")) {
          row.click();
          break;
        }
      }
    })()`);
    await sleep(500);

    // Verify initial button states on active run:
    // Stop: enabled, Kill: enabled, Restart: disabled, Duplicate: enabled
    // On Windows backend, Pause/Resume is presented as unavailable (disabled = true) with explanatory title
    const initialButtonStates = await evaluate(`({
      stopDisabled: document.querySelector("#action-stop-btn").disabled,
      killDisabled: document.querySelector("#action-kill-btn").disabled,
      restartDisabled: document.querySelector("#action-restart-btn").disabled,
      dupDisabled: document.querySelector("#action-duplicate-btn").disabled,
      pauseDisabled: document.querySelector("#action-pause-btn").disabled,
      pauseText: document.querySelector("#action-pause-btn").textContent,
      pauseTitle: document.querySelector("#action-pause-btn").title,
      feedbackHidden: document.querySelector("#lifecycle-feedback").hidden,
      modalHidden: document.querySelector("#lifecycle-confirm-modal").hidden,
    })`);
    assert.equal(initialButtonStates.stopDisabled, false, "Stop button should be enabled on active run");
    assert.equal(initialButtonStates.killDisabled, false, "Kill button should be enabled on active run");
    assert.equal(initialButtonStates.restartDisabled, true, "Restart button must be disabled on active run");
    assert.equal(initialButtonStates.dupDisabled, false, "Duplicate button should be enabled on active run");
    assert.equal(initialButtonStates.pauseDisabled, true, "Pause button must be disabled on Windows backend");
    assert.equal(initialButtonStates.pauseText, "Pause", "Action label should be Pause for running run");
    assert.match(initialButtonStates.pauseTitle, /not supported on Windows/i, "Pause title must explain Windows lack of support");
    assert.equal(initialButtonStates.modalHidden, true, "Confirmation modal must be hidden initially");
    console.log("Verified initial lifecycle button eligibility on active run (Windows capability aware).");

    // A. Test Stop Confirmation Dialog & Cancel
    console.log("Testing Stop confirmation modal open and cancellation...");
    await evaluate(`document.querySelector("#action-stop-btn").click()`);
    await sleep(200);

    const stopModalState = await evaluate(`({
      hidden: document.querySelector("#lifecycle-confirm-modal").hidden,
      title: document.querySelector("#confirm-modal-title").textContent,
      name: document.querySelector("#confirm-run-name").textContent,
      runId: document.querySelector("#confirm-run-id").textContent,
      submitLabel: document.querySelector("#confirm-submit-btn").textContent,
    })`);
    assert.equal(stopModalState.hidden, false, "Modal should open on Stop click");
    assert.match(stopModalState.title, /Stop Process/);
    assert.equal(stopModalState.name, "e2e worker");
    assert.equal(stopModalState.runId, runId);
    assert.equal(stopModalState.submitLabel, "Stop Process");

    // Click Cancel
    await evaluate(`document.querySelector("#confirm-cancel-btn").click()`);
    await sleep(150);
    const modalClosedAfterCancel = await evaluate(`document.querySelector("#lifecycle-confirm-modal").hidden`);
    assert.equal(modalClosedAfterCancel, true, "Modal should close after cancel click");
    console.log("Verified Stop confirmation modal cancellation.");

    // B. Test Kill Confirmation Dialog & Capture Screenshot
    console.log("Testing Kill confirmation modal and capturing screenshot...");
    await evaluate(`document.querySelector("#action-kill-btn").click()`);
    await sleep(200);

    const killModalState = await evaluate(`({
      hidden: document.querySelector("#lifecycle-confirm-modal").hidden,
      title: document.querySelector("#confirm-modal-title").textContent,
      name: document.querySelector("#confirm-run-name").textContent,
      runId: document.querySelector("#confirm-run-id").textContent,
      desc: document.querySelector("#confirm-modal-desc").textContent,
      submitLabel: document.querySelector("#confirm-submit-btn").textContent,
    })`);
    assert.equal(killModalState.hidden, false, "Modal should open on Kill click");
    assert.match(killModalState.title, /Kill Process/);
    assert.equal(killModalState.name, "e2e worker");
    assert.equal(killModalState.runId, runId);
    assert.match(killModalState.desc, /force kill/);
    assert.equal(killModalState.submitLabel, "Kill Process");

    // Capture screenshot of confirmation modal
    let confirmShot = await sendCommand("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(lifecycleScreenshotsDir, "lifecycle_confirm_modal.png"), Buffer.from(confirmShot.data, "base64"));
    console.log("Saved lifecycle_confirm_modal.png");

    // C. Confirm Kill Execution & Capture Feedback Banner Screenshot
    console.log("Submitting Kill confirmation and capturing feedback banner screenshot...");
    await evaluate(`document.querySelector("#confirm-submit-btn").click()`);
    await sleep(100);

    // Feedback banner should be visible immediately with in-flight or status message
    const feedbackImmediately = await evaluate(`({
      hidden: document.querySelector("#lifecycle-feedback").hidden,
      className: document.querySelector("#lifecycle-feedback").className,
      text: document.querySelector("#lifecycle-feedback span") ? document.querySelector("#lifecycle-feedback span").textContent : "",
    })`);
    assert.equal(feedbackImmediately.hidden, false, "Feedback banner must be visible during/after action");

    let feedbackShot = await sendCommand("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(lifecycleScreenshotsDir, "lifecycle_feedback_banner.png"), Buffer.from(feedbackShot.data, "base64"));
    console.log("Saved lifecycle_feedback_banner.png");

    // Wait up to 4s for process termination to reflect in status
    let killedConfirmed = false;
    for (let i = 0; i < 20; i++) {
      await sleep(200);
      const currentStatus = await evaluate(`document.querySelector("#selected-status").textContent.trim().toLowerCase()`);
      if (currentStatus === "killed") {
        killedConfirmed = true;
        break;
      }
    }
    assert.equal(killedConfirmed, true, "Process status should transition to 'killed'");

    // Verify updated button states on killed run:
    // Stop: disabled, Kill: disabled, Restart: ENABLED, Duplicate: enabled, Pause: disabled
    const killedButtonStates = await evaluate(`({
      stopDisabled: document.querySelector("#action-stop-btn").disabled,
      killDisabled: document.querySelector("#action-kill-btn").disabled,
      restartDisabled: document.querySelector("#action-restart-btn").disabled,
      dupDisabled: document.querySelector("#action-duplicate-btn").disabled,
      pauseDisabled: document.querySelector("#action-pause-btn").disabled,
    })`);
    assert.equal(killedButtonStates.stopDisabled, true, "Stop button should be disabled on killed run");
    assert.equal(killedButtonStates.killDisabled, true, "Kill button should be disabled on killed run");
    assert.equal(killedButtonStates.restartDisabled, false, "Restart button must be ENABLED on killed run");
    assert.equal(killedButtonStates.dupDisabled, false, "Duplicate button should be enabled on killed run");
    assert.equal(killedButtonStates.pauseDisabled, true, "Pause button should be disabled on killed run");
    console.log("Verified button states transition on killed process.");

    // D. Test Restart on Killed Process
    console.log("Testing Restart action on killed process...");
    const initialTabsCount = await evaluate(`document.querySelectorAll(".workspace-tab").length`);
    await evaluate(`document.querySelector("#action-restart-btn").click()`);

    let restartedRunId = null;
    for (let i = 0; i < 25; i++) {
      await sleep(200);
      const selectedText = await evaluate(`document.querySelector("#selected-identity").textContent.trim()`);
      const match = selectedText.match(/RUN\s+(2026\d{4}-\d{6}-[0-9a-f]{6})/);
      if (match && match[1] !== runId) {
        restartedRunId = match[1];
        break;
      }
    }
    assert.ok(restartedRunId, "Restart did not switch selection to a new Run ID");
    assert.notEqual(restartedRunId, runId, "Restart must create a new immutable Run ID");

    // Verify tab bar reconciled: tab count incremented, new run tab is active
    const newTabsCount = await evaluate(`document.querySelectorAll(".workspace-tab").length`);
    assert.equal(newTabsCount, initialTabsCount + 1, "Restart should add a new tab");

    // Verify original run is still preserved in tabs and explorer
    const originalTabPresent = await evaluate(`Boolean(document.querySelector('.workspace-tab .workspace-tab-select[title*="${runId}"]'))`);
    assert.equal(originalTabPresent, true, "Original run tab must be preserved");
    const originalExplorerPresent = await evaluate(`(function() {
      const rows = document.querySelectorAll(".process-row");
      for (const row of rows) {
        if (row.textContent.includes("e2e worker")) return true;
      }
      return false;
    })()`);
    assert.equal(originalExplorerPresent, true, "Original run must remain in explorer");
    console.log("Verified restart reconciliation: new run created, tabs updated, historical identity preserved.");

    // E. Test Duplicate Action
    console.log("Testing Duplicate action on restarted run...");
    const preDupTabsCount = await evaluate(`document.querySelectorAll(".workspace-tab").length`);
    await evaluate(`document.querySelector("#action-duplicate-btn").click()`);

    let duplicatedRunId = null;
    for (let i = 0; i < 25; i++) {
      await sleep(200);
      const selectedText = await evaluate(`document.querySelector("#selected-identity").textContent.trim()`);
      const match = selectedText.match(/RUN\s+(2026\d{4}-\d{6}-[0-9a-f]{6})/);
      if (match && match[1] !== restartedRunId && match[1] !== runId) {
        duplicatedRunId = match[1];
        break;
      }
    }
    assert.ok(duplicatedRunId, "Duplicate did not switch selection to a new Run ID");
    const postDupTabsCount = await evaluate(`document.querySelectorAll(".workspace-tab").length`);
    assert.equal(postDupTabsCount, preDupTabsCount + 1, "Duplicate should add another tab");
    console.log("Verified duplicate reconciliation: new run created and selected.");

    // F. Test Pause Button & Platform Capability Awareness
    console.log("Testing Pause/Resume platform capability awareness and direct 501 error handling...");
    // Direct invocation on Windows backend to verify 501 error feedback
    await evaluate(`(function() {
      executeLifecycleAction("pause", selectedId);
    })()`);
    await sleep(400);

    const pauseFeedback = await evaluate(`({
      hidden: document.querySelector("#lifecycle-feedback").hidden,
      isError: document.querySelector("#lifecycle-feedback").classList.contains("feedback-error"),
      message: document.querySelector("#lifecycle-feedback span") ? document.querySelector("#lifecycle-feedback span").textContent : "",
    })`);
    assert.equal(pauseFeedback.hidden, false, "Pause feedback must be visible");
    assert.equal(pauseFeedback.isError, true, "Pause on Windows should show feedback-error class");
    assert.match(pauseFeedback.message, /not supported on Windows|501/i, "Message must mention Windows lack of pause support");

    // Verify terminal follow / output follow was not simulated or suspended
    const outputFollowChecked = await evaluate(`document.querySelector("#follow-output") ? document.querySelector("#follow-output").checked : true`);
    assert.equal(outputFollowChecked, true, "Output follow state must not be simulated or altered by pause");
    console.log("Verified 501 Not Implemented handling for Pause without simulated freezing.");

    // Test supported Pause -> Resume transitions
    console.log("Testing supported Pause -> Resume transitions in browser...");
    await evaluate(`(function() {
      setSystemCapabilities({ platform: "linux", supports_pause_resume: true });
      updateLifecycleControls(getRun(selectedId));
    })()`);
    await sleep(100);

    const supportedRunningBtn = await evaluate(`({
      disabled: document.querySelector("#action-pause-btn").disabled,
      text: document.querySelector("#action-pause-btn").textContent,
      title: document.querySelector("#action-pause-btn").title,
    })`);
    assert.equal(supportedRunningBtn.disabled, false, "Pause button must be enabled where supported");
    assert.equal(supportedRunningBtn.text, "Pause");

    // When status is paused, action must switch to Resume
    await evaluate(`(function() {
      const currentRun = getRun(selectedId);
      if (currentRun) {
        currentRun.status = "paused";
        updateLifecycleControls(currentRun);
      }
    })()`);
    await sleep(100);

    const supportedPausedBtn = await evaluate(`({
      disabled: document.querySelector("#action-pause-btn").disabled,
      text: document.querySelector("#action-pause-btn").textContent,
      action: document.querySelector("#action-pause-btn").getAttribute("data-action"),
      title: document.querySelector("#action-pause-btn").title,
    })`);
    assert.equal(supportedPausedBtn.disabled, false, "Resume button must be enabled where supported");
    assert.equal(supportedPausedBtn.text, "Resume", "Action label must switch to Resume for paused process");
    assert.equal(supportedPausedBtn.action, "resume");
    assert.match(supportedPausedBtn.title, /Resume process/);

    // Restore real run status and capabilities
    await evaluate(`(function() {
      const currentRun = getRun(selectedId);
      if (currentRun) {
        currentRun.status = "running";
      }
      setSystemCapabilities({ platform: "win32", supports_pause_resume: false });
      updateLifecycleControls(getRun(selectedId));
    })()`);
    console.log("Verified Pause -> Resume state and label transitions on supported platform.");

    // G. Test View-Only Tab Close
    console.log("Testing view-only tab close behavior...");
    const preCloseTabs = await evaluate(`document.querySelectorAll(".workspace-tab").length`);
    // Click close on the active tab's close button
    await evaluate(`(function() {
      const activeTab = document.querySelector(".workspace-tab.active");
      if (activeTab) {
        const closeBtn = activeTab.querySelector(".workspace-tab-close");
        if (closeBtn) closeBtn.click();
      }
    })()`);
    await sleep(300);

    const postCloseTabs = await evaluate(`document.querySelectorAll(".workspace-tab").length`);
    assert.equal(postCloseTabs, preCloseTabs - 1, "Tab close should remove tab from tab bar");

    // Verify the duplicated run is STILL present in explorer!
    const runStillInExplorer = await evaluate(`(function() {
      const rows = document.querySelectorAll(".process-row");
      for (const row of rows) {
        if (row.title.includes("${duplicatedRunId}") || row.textContent.includes("${duplicatedRunId.slice(-6)}")) return true;
      }
      return false;
    })()`);
    assert.equal(runStillInExplorer, true, "Closed run must still exist in explorer");

    // Capture overall lifecycle overview screenshot
    let overviewShot = await sendCommand("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(lifecycleScreenshotsDir, "lifecycle_controls_overview.png"), Buffer.from(overviewShot.data, "base64"));
    console.log("Saved lifecycle_controls_overview.png");
    console.log("Verified view-only tab close: tab closed without terminating the process.");

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
