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
    `store.update_run("${runId}", pid=1234)`,
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

    // 7. Test Regex Search
    console.log("Testing regex search...");
    await evaluate(`(function() {
      document.querySelector("#output-search-regex").click();
      const input = document.querySelector("#output-search-query");
      input.value = "database:\\\\d+";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(100);

    const regexMatchCount = await evaluate(`document.querySelector("#output-search-count").textContent`);
    assert.equal(regexMatchCount, "1 of 1 (loaded buffer)");
    const regexMarkText = await evaluate(`document.querySelector("#output-text mark.output-match").textContent`);
    assert.equal(regexMarkText, "database:5432");
    console.log("Verified regex search match.");

    // 8. Test Invalid Regex Handling
    console.log("Testing invalid regex error handling...");
    await evaluate(`(function() {
      const input = document.querySelector("#output-search-query");
      input.value = "[invalid(";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(100);

    const invalidRegexText = await evaluate(`document.querySelector("#output-search-count").textContent`);
    assert.equal(invalidRegexText, "Invalid regex");
    const hasErrorClass = await evaluate(`document.querySelector("#output-search-count").classList.contains("has-error")`);
    assert.equal(hasErrorClass, true);
    console.log("Verified invalid regex error state.");

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

    console.log("\n==========================================");
    console.log("ALL REAL HEADLESS BROWSER E2E TESTS PASSED!");
    console.log("==========================================\n");
  } finally {
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
