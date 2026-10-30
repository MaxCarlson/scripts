"use strict";

(() => {
  const loginPanel = document.getElementById("login-panel");
  const loginForm = document.getElementById("login-form");
  const loginCode = document.getElementById("login-code");
  const loginError = document.getElementById("login-error");
  const dashboard = document.getElementById("dashboard");
  const logoutButton = document.getElementById("logout-button");
  let pollTimer = null;
  let requestInFlight = false;

  function setLoginError(message) {
    loginError.textContent = message;
    loginError.hidden = false;
  }

  function lockDashboard(message) {
    if (pollTimer !== null) window.clearInterval(pollTimer);
    pollTimer = null;
    dashboard.hidden = true;
    loginPanel.hidden = false;
    loginCode.value = "";
    if (message) setLoginError(message);
  }

  async function login(code) {
    loginError.hidden = true;
    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (!response.ok) throw new Error("The code was not accepted.");
      loginPanel.hidden = true;
      dashboard.hidden = false;
      await refresh();
      if (pollTimer !== null) window.clearInterval(pollTimer);
      pollTimer = window.setInterval(refresh, 2500);
    } catch {
      setLoginError("Login failed. Check the code printed by the local monitor process.");
    }
  }

  async function getJson(path) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store" });
    if (response.status === 401) throw new Error("locked");
    if (!response.ok) throw new Error("unavailable");
    return response.json();
  }

  async function refresh() {
    if (requestInFlight || dashboard.hidden) return;
    requestInFlight = true;
    try {
      const [status, servers, models, requests] = await Promise.all([
        getJson("/api/inference/v1/status"),
        getJson("/api/inference/v1/servers"),
        getJson("/api/inference/v1/models"),
        getJson("/api/inference/v1/requests"),
      ]);
      render(status, servers, models, requests);
    } catch (error) {
      if (error.message === "locked") {
        lockDashboard("Your local browser session expired. Enter the startup code again.");
      } else {
        renderUnavailable();
      }
    } finally {
      requestInFlight = false;
    }
  }

  function render(status, serversResult, modelResult, requestResult) {
    const server = Array.isArray(serversResult.servers) ? serversResult.servers[0] : null;
    const models = Array.isArray(modelResult.models) ? modelResult.models : [];
    const connected = Boolean(server && server.connection_state === "connected");
    const totalLoaded = models.reduce((sum, model) => {
      const count = model.loaded_instance_count;
      return Number.isSafeInteger(count) && count >= 0 ? sum + count : sum;
    }, 0);

    document.getElementById("metric-server").textContent = connected ? "Connected" : "Unavailable";
    document.getElementById("metric-endpoint").textContent = server && server.endpoint ? server.endpoint : "LM Studio · 127.0.0.1:1234";
    document.getElementById("metric-models").textContent = modelResult.availability === "unavailable" ? "—" : String(models.length);
    document.getElementById("metric-loaded").textContent = models.some((model) => Number.isSafeInteger(model.loaded_instance_count))
      ? String(totalLoaded) : "—";
    document.getElementById("metric-capture").textContent = requestResult.capture_state === "unavailable"
      ? "Unavailable" : "Partial";
    document.getElementById("model-count").textContent = modelResult.availability === "unavailable"
      ? "Inventory unavailable" : `${models.length} entries`;
    document.getElementById("refresh-time").textContent = status.refreshed_at
      ? `Updated ${new Date(status.refreshed_at).toLocaleTimeString()}` : "Waiting for inventory";
    document.getElementById("recording-status").textContent = status.recording && status.recording.status === "disabled"
      ? "Persistent recording: disabled" : "Persistent recording: unavailable";

    const badge = document.getElementById("server-badge");
    badge.className = `status-badge ${connected ? "status-connected" : "status-unavailable"}`;
    badge.replaceChildren(make("span", "status-dot"), document.createTextNode(connected ? "LM Studio connected" : "LM Studio unavailable"));

    const message = document.getElementById("provider-message");
    if (connected) {
      message.hidden = true;
      message.textContent = "";
    } else {
      message.hidden = false;
      message.textContent = "No model inventory was returned. The monitor uses the configured read-only endpoint and does not send inference requests.";
    }
    renderModels(models, modelResult.availability);
  }

  function renderModels(models, availability) {
    const body = document.getElementById("model-rows");
    body.replaceChildren();
    if (availability === "unavailable") {
      body.append(makeEmptyRow("LM Studio inventory is unavailable."));
      return;
    }
    if (models.length === 0) {
      body.append(makeEmptyRow("No model entries were returned by the provider."));
      return;
    }
    for (const model of models) {
      const row = document.createElement("tr");
      row.append(
        make("td", "model-name", model.name || model.provider_model_id || "Unknown model"),
        make("td", `model-state ${model.state === "loaded" ? "model-state-loaded" : ""}`, model.state || "unknown"),
        make("td", "mono", Number.isSafeInteger(model.loaded_instance_count) ? String(model.loaded_instance_count) : "—"),
        make("td", "mono", contextText(model)),
        make("td", "mono", Number.isSafeInteger(model.max_context_length) ? String(model.max_context_length) : "—"),
      );
      body.append(row);
    }
  }

  function contextText(model) {
    const contexts = Array.isArray(model.loaded_context_lengths) ? model.loaded_context_lengths : [];
    if (contexts.length > 1) return `Multiple: ${contexts.join(" / ")}`;
    if (contexts.length === 1) return String(contexts[0]);
    return Number.isSafeInteger(model.context_length) ? String(model.context_length) : "—";
  }

  function makeEmptyRow(message) {
    const row = document.createElement("tr");
    const cell = make("td", "empty-cell", message);
    cell.colSpan = 5;
    row.append(cell);
    return row;
  }

  function renderUnavailable() {
    document.getElementById("metric-server").textContent = "Unavailable";
    document.getElementById("metric-endpoint").textContent = "Inventory request failed";
    document.getElementById("metric-models").textContent = "—";
    document.getElementById("metric-loaded").textContent = "—";
    document.getElementById("metric-capture").textContent = "Unavailable";
    document.getElementById("provider-message").textContent = "The authenticated monitor API is unavailable. Check that the local server is still running.";
    document.getElementById("provider-message").hidden = false;
    const badge = document.getElementById("server-badge");
    badge.className = "status-badge status-unavailable";
    badge.replaceChildren(make("span", "status-dot"), document.createTextNode("Monitor API unavailable"));
  }

  function make(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  loginForm.addEventListener("submit", (event) => {
    event.preventDefault();
    login(loginCode.value);
  });

  logoutButton.addEventListener("click", async () => {
    try {
      await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      lockDashboard(null);
    }
  });
})();
