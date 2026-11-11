// Remote Control Mobile Dashboard Application Logic
// Enforces DOM-safe rendering, CSRF protection, and zero local caching of incident secrets.

(function () {
  "use strict";

  let currentCsrfToken = "";
  let activeTab = "summary";
  let pollTimer = null;

  // ── DOM Helper (Strictly XSS-Safe) ───────────────────────────────────────────

  function h(tag, attrs = {}, children = []) {
    const element = document.createElement(tag);
    for (const [key, val] of Object.entries(attrs)) {
      if (key === "className") {
        element.className = val;
      } else if (key === "style" && typeof val === "object") {
        Object.assign(element.style, val);
      } else if (key.startsWith("on") && typeof val === "function") {
        element.addEventListener(key.slice(2).toLowerCase(), val);
      } else {
        element.setAttribute(key, val);
      }
    }
    for (const child of Array.isArray(children) ? children : [children]) {
      if (child == null) continue;
      if (typeof child === "string" || typeof child === "number") {
        element.appendChild(document.createTextNode(String(child)));
      } else if (child instanceof Node) {
        element.appendChild(child);
      }
    }
    return element;
  }

  // ── PWA & Offline Support ────────────────────────────────────────────────────

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch((err) => {
        console.debug("ServiceWorker registration skipped:", err);
      });
    });
  }

  function updateOnlineStatus() {
    const banner = document.getElementById("offline-banner");
    if (!navigator.onLine) {
      banner.style.display = "block";
    } else {
      banner.style.display = "none";
    }
  }

  window.addEventListener("online", updateOnlineStatus);
  window.addEventListener("offline", updateOnlineStatus);

  // ── API Fetch Wrapper ────────────────────────────────────────────────────────

  async function apiFetch(url, options = {}) {
    const headers = options.headers || {};
    headers["Accept"] = "application/json";

    // Auto-inject CSRF token for state-changing calls
    if (["POST", "PUT", "DELETE", "PATCH"].includes((options.method || "GET").toUpperCase())) {
      headers["Content-Type"] = "application/json";
      if (currentCsrfToken) {
        headers["X-CSRF-Token"] = currentCsrfToken;
      }
    }

    options.headers = headers;
    options.credentials = "same-origin";

    try {
      const resp = await fetch(url, options);
      if (resp.status === 401) {
        showLoginView("Session expired. Please log in again.");
        throw new Error("unauthenticated");
      }
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.message || data.error || `HTTP ${resp.status}`);
      }
      return data;
    } catch (err) {
      if (err.message !== "unauthenticated") {
        console.warn(`API Error [${url}]:`, err);
      }
      throw err;
    }
  }

  // ── Navigation & Views ───────────────────────────────────────────────────────

  function showLoginView(errorMessage = "") {
    document.getElementById("view-login").style.display = "block";
    document.getElementById("app-container").style.display = "none";
    if (pollTimer) clearInterval(pollTimer);

    const errBox = document.getElementById("login-error");
    if (errorMessage) {
      errBox.textContent = errorMessage;
      errBox.style.display = "block";
    } else {
      errBox.style.display = "none";
    }
  }

  function showAppView() {
    document.getElementById("view-login").style.display = "none";
    document.getElementById("app-container").style.display = "flex";
    loadActiveTab();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(loadActiveTab, 30000); // 30s background refresh
  }

  function setupTabs() {
    const navButtons = document.querySelectorAll(".nav-btn");
    navButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        navButtons.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        activeTab = btn.getAttribute("data-tab");

        document.querySelectorAll(".tab-content").forEach((c) => {
          c.style.display = "none";
        });
        const activeSection = document.getElementById(`tab-${activeTab}`);
        if (activeSection) {
          activeSection.style.display = "block";
        }
        loadActiveTab();
      });
    });
  }

  function loadActiveTab() {
    if (!navigator.onLine) {
      updateOnlineStatus();
      return;
    }
    if (activeTab === "summary") loadSummary();
    else if (activeTab === "incidents") loadIncidents();
    else if (activeTab === "notifications") loadNotifications();
    else if (activeTab === "providers") loadProviders();
    else if (activeTab === "heartbeat") loadHeartbeat();
    else if (activeTab === "settings") loadSettings();
  }

  // ── Tab 1: Summary ───────────────────────────────────────────────────────────

  async function loadSummary() {
    try {
      const data = await apiFetch("/api/summary");
      const notif = data.notifications || {};
      document.getElementById("stat-active").textContent = notif.active_incidents ?? 0;
      document.getElementById("stat-ack").textContent = notif.acknowledged_incidents ?? 0;
      document.getElementById("stat-resolved").textContent = notif.resolved_incidents ?? 0;
      document.getElementById("stat-outbox").textContent = notif.pending_outbox ?? 0;

      const compContainer = document.getElementById("summary-components");
      compContainer.textContent = "";

      // 1. Broker
      const brokerBox = h("div", { className: "stat-box", style: { textAlign: "left", display: "flex", justifyContent: "space-between" } }, [
        h("div", {}, [
          h("strong", {}, "Notifications Broker"),
          h("div", { style: { fontSize: "0.75rem", color: "var(--text-muted)" } }, `Schema v${notif.schema_version ?? "?"} (${notif.status || "unknown"})`)
        ]),
        h("span", { className: `badge badge-${notif.available ? "success" : "critical"}` }, notif.available ? "Online" : "Offline")
      ]);
      compContainer.appendChild(brokerBox);

      // 2. Heartbeat
      const hb = data.heartbeat || {};
      const hbBox = h("div", { className: "stat-box", style: { textAlign: "left", display: "flex", justifyContent: "space-between" } }, [
        h("div", {}, [
          h("strong", {}, "Host Heartbeat (Off-Host)"),
          h("div", { style: { fontSize: "0.75rem", color: "var(--text-muted)" } }, `${hb.check_name || "Host Alive"} [${hb.execution_mode || "unknown"}]`)
        ]),
        h("span", { className: `badge badge-${hb.task_installed ? "success" : "warning"}` }, hb.task_installed ? hb.task_state : "Uninstalled")
      ]);
      compContainer.appendChild(hbBox);

      // 3. Coordinator Placeholder
      const rc = data.coordinator || {};
      const rcBox = h("div", { className: "stat-box", style: { textAlign: "left", display: "flex", justifyContent: "space-between" } }, [
        h("div", {}, [
          h("strong", {}, "Resource Coordinator"),
          h("div", { style: { fontSize: "0.75rem", color: "var(--text-muted)" } }, rc.message || "Phase 05")
        ]),
        h("span", { className: "badge badge-stale" }, "Placeholder")
      ]);
      compContainer.appendChild(rcBox);

    } catch (err) {
      console.warn("Failed loading summary:", err);
    }
  }

  // ── Tab 2: Incidents ─────────────────────────────────────────────────────────

  async function loadIncidents() {
    const statusVal = document.getElementById("filter-incident-status").value;
    const severityVal = document.getElementById("filter-incident-severity").value;
    const list = document.getElementById("incidents-list");
    list.textContent = "";

    let url = "/api/incidents?limit=50";
    if (statusVal) url += `&status=${encodeURIComponent(statusVal)}`;
    if (severityVal) url += `&severity=${encodeURIComponent(severityVal)}`;

    try {
      const data = await apiFetch(url);
      document.getElementById("incidents-count").textContent = data.total;

      if (!data.items || data.items.length === 0) {
        list.appendChild(h("div", { className: "empty-state" }, "No matching incidents recorded."));
        return;
      }

      data.items.forEach((inc) => {
        const item = h(
          "div",
          {
            className: "incident-item",
            onClick: () => showIncidentDetail(inc.incident_id),
          },
          [
            h("div", { className: "incident-header" }, [
              h("span", { className: `badge badge-${inc.severity}` }, inc.severity),
              h("span", { className: "incident-meta" }, new Date(inc.last_seen || inc.updated_at || Date.now()).toLocaleTimeString()),
            ]),
            h("div", { className: "incident-summary" }, inc.summary || inc.incident_key),
            h("div", { className: "incident-meta" }, [
              h("span", {}, `${inc.source} • `),
              h("span", { style: { fontWeight: "600" } }, inc.status.toUpperCase()),
              h("span", {}, ` (${inc.occurrence_count} occurrences)`),
            ]),
          ]
        );
        list.appendChild(item);
      });
    } catch (err) {
      list.appendChild(h("div", { className: "error-message" }, `Failed loading incidents: ${err.message}`));
    }
  }

  async function showIncidentDetail(incidentId) {
    const modal = document.getElementById("incident-modal");
    const body = document.getElementById("modal-body");
    body.textContent = "Loading incident evidence...";
    modal.style.display = "flex";

    try {
      const data = await apiFetch(`/api/incidents/${encodeURIComponent(incidentId)}`);
      const inc = data.incident;
      body.textContent = "";

      body.appendChild(h("div", { style: { marginBottom: "12px" } }, [
        h("div", { style: { fontSize: "1rem", fontWeight: "700" } }, inc.summary),
        h("div", { style: { color: "var(--text-muted)", fontSize: "0.75rem" } }, `Key: ${inc.incident_key} | Source: ${inc.source}`),
      ]));

      // Status info
      body.appendChild(h("div", { className: "stat-box", style: { textAlign: "left", marginBottom: "12px" } }, [
        h("div", {}, `Status: ${inc.status.toUpperCase()}`),
        h("div", {}, `Severity: ${inc.severity}`),
        h("div", {}, `First Seen: ${inc.first_seen || inc.opened_at || "N/A"}`),
        h("div", {}, `Last Seen: ${inc.last_seen || inc.updated_at || "N/A"}`),
        inc.resolved_at ? h("div", {}, `Resolved: ${inc.resolved_at}`) : null,
      ]));

      // Recent Occurrences
      body.appendChild(h("h3", { style: { fontSize: "0.875rem", fontWeight: "700", marginBottom: "8px" } }, "Recent Occurrences"));
      const occList = h("div", { style: { maxHeight: "150px", overflowY: "auto", marginBottom: "16px" } });
      (inc.occurrences || []).forEach((occ) => {
        occList.appendChild(h("div", { style: { fontSize: "0.75rem", borderBottom: "1px solid var(--border-color)", padding: "4px 0" } }, [
          h("div", { style: { fontWeight: "600" } }, `${occ.occurred_at}: ${occ.summary}`),
        ]));
      });
      body.appendChild(occList);

      // Delivery History
      body.appendChild(h("h3", { style: { fontSize: "0.875rem", fontWeight: "700", marginBottom: "8px" } }, "Provider Delivery Attempts"));
      const attList = h("div", { style: { maxHeight: "150px", overflowY: "auto" } });
      (inc.delivery_attempts || []).forEach((att) => {
        attList.appendChild(h("div", { style: { fontSize: "0.75rem", borderBottom: "1px solid var(--border-color)", padding: "4px 0" } }, [
          h("div", { style: { fontWeight: "600" } }, `${att.attempted_at} - ${att.provider}: ${att.status}`),
          att.error_message ? h("div", { style: { color: "var(--status-critical)" } }, att.error_message) : null,
        ]));
      });
      body.appendChild(attList);

    } catch (err) {
      body.textContent = `Error loading incident: ${err.message}`;
    }
  }

  // ── Tab 3: Notifications Outbox ──────────────────────────────────────────────

  async function loadNotifications() {
    const list = document.getElementById("notifications-list");
    list.textContent = "";

    try {
      const data = await apiFetch("/api/notifications?limit=50");
      if (!data.notifications || data.notifications.length === 0) {
        list.appendChild(h("div", { className: "empty-state" }, "No notifications recorded in outbox."));
        return;
      }

      data.notifications.forEach((n) => {
        const item = h("div", { className: "incident-item" }, [
          h("div", { className: "incident-header" }, [
            h("span", { className: `badge badge-${n.severity || "info"}` }, n.provider_id || n.provider || "outbox"),
            h("span", { className: "incident-meta" }, new Date(n.created_at || Date.now()).toLocaleTimeString()),
          ]),
          h("div", { className: "incident-summary" }, n.summary || n.title || "Notification"),
          h("div", { style: { fontSize: "0.8125rem", color: "var(--text-muted)" } }, n.error_message || n.body || ""),
          h("div", { className: "incident-meta" }, `Status: ${n.status} (Retries: ${n.retry_count || 0})`),
        ]);
        list.appendChild(item);
      });
    } catch (err) {
      list.appendChild(h("div", { className: "error-message" }, `Failed loading notifications: ${err.message}`));
    }
  }

  // ── Tab 4: Providers ─────────────────────────────────────────────────────────

  async function loadProviders() {
    const list = document.getElementById("providers-list");
    list.textContent = "";

    try {
      const data = await apiFetch("/api/providers");
      (data.providers || []).forEach((p) => {
        const card = h("div", { className: "stat-box", style: { textAlign: "left", marginBottom: "12px" } }, [
          h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" } }, [
            h("strong", {}, p.provider.toUpperCase()),
            h("span", { className: `badge badge-${p.status === "ready" ? "success" : "warning"}` }, p.status),
          ]),
          h("div", { style: { fontSize: "0.8125rem", color: "var(--text-muted)" } }, p.details || ""),
        ]);
        list.appendChild(card);
      });
    } catch (err) {
      list.appendChild(h("div", { className: "error-message" }, `Failed loading providers: ${err.message}`));
    }
  }

  // ── Tab 5: Heartbeat ─────────────────────────────────────────────────────────

  async function loadHeartbeat() {
    const container = document.getElementById("heartbeat-info");
    container.textContent = "";

    try {
      const data = await apiFetch("/api/heartbeat");
      const hb = data.heartbeat || {};

      const card = h("div", { className: "stat-box", style: { textAlign: "left" } }, [
        h("div", { style: { display: "flex", justifyContent: "space-between", marginBottom: "12px" } }, [
          h("strong", {}, hb.check_name || "Host Alive"),
          h("span", { className: `badge badge-${hb.task_installed ? "success" : "warning"}` }, hb.task_installed ? hb.task_state : "Uninstalled"),
        ]),
        h("div", { style: { fontSize: "0.875rem", marginBottom: "4px" } }, `Execution Mode: ${hb.execution_mode || "unknown"}`),
        h("div", { style: { fontSize: "0.875rem", marginBottom: "4px" } }, `Logged-off Capable: ${hb.logged_off_capable ? "Yes (Runs 24/7 without user login)" : "No (Interactive only)"}`),
        h("div", { style: { fontSize: "0.875rem", marginBottom: "4px" } }, `Last Run: ${hb.last_run_time || "Never"} (Result: ${hb.last_result || "N/A"})`),
        h("div", { style: { fontSize: "0.875rem", marginBottom: "4px" } }, `Next Scheduled: ${hb.next_run_time || "N/A"}`),
        h("div", { style: { fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "8px" } }, `Target Ping URL: ${hb.ping_url_redacted || "N/A"}`),
      ]);
      container.appendChild(card);
    } catch (err) {
      container.appendChild(h("div", { className: "error-message" }, `Failed loading heartbeat: ${err.message}`));
    }
  }

  // ── Tab 6: Settings & Devices ────────────────────────────────────────────────

  async function loadSettings() {
    const sessInfo = document.getElementById("session-info");
    const devList = document.getElementById("devices-list");
    sessInfo.textContent = "Loading session details...";
    devList.textContent = "";

    try {
      const sessData = await apiFetch("/api/auth/session");
      const s = sessData.session || {};
      sessInfo.textContent = "";
      sessInfo.appendChild(h("div", {}, [
        h("div", {}, `Session ID: ${s.session_id}`),
        h("div", {}, `Active Device: ${s.device_id}`),
        h("div", {}, `Expires: ${new Date(s.expires_at).toLocaleString()}`),
      ]));

      const devData = await apiFetch("/api/auth/devices");
      (devData.devices || []).forEach((d) => {
        const isCurrent = d.device_id === s.device_id;
        const devItem = h("div", { className: "stat-box", style: { textAlign: "left", marginBottom: "8px" } }, [
          h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } }, [
            h("div", {}, [
              h("strong", {}, d.device_name || d.device_id),
              isCurrent ? h("span", { className: "badge badge-info", style: { marginLeft: "8px" } }, "This Device") : null,
              h("div", { style: { fontSize: "0.75rem", color: "var(--text-muted)" } }, `Last active: ${new Date(d.last_seen_at).toLocaleString()}`),
            ]),
            !d.is_revoked && !isCurrent
              ? h(
                  "button",
                  {
                    className: "btn-secondary",
                    style: { color: "var(--status-critical)" },
                    onClick: () => revokeDevice(d.device_id),
                  },
                  "Revoke"
                )
              : null,
          ]),
        ]);
        devList.appendChild(devItem);
      });
    } catch (err) {
      sessInfo.textContent = `Failed loading settings: ${err.message}`;
    }
  }

  async function revokeDevice(deviceId) {
    if (!confirm(`Are you sure you want to permanently revoke device ${deviceId}?`)) {
      return;
    }
    try {
      await apiFetch(`/api/auth/devices/${encodeURIComponent(deviceId)}/revoke`, { method: "POST" });
      loadSettings();
    } catch (err) {
      alert(`Revocation failed: ${err.message}`);
    }
  }

  // ── Authentication & Bootstrap Handlers ─────────────────────────────────────

  async function handleLoginSubmit(event) {
    event.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    const totpCode = document.getElementById("login-totp").value.trim();
    const errBox = document.getElementById("login-error");

    errBox.style.display = "none";

    try {
      const res = await apiFetch("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username,
          password,
          totp_code: totpCode,
          device_name: navigator.userAgent.includes("Android") ? "Android Phone" : "Browser",
        }),
      });

      currentCsrfToken = res.csrf_token || "";
      document.getElementById("login-password").value = "";
      document.getElementById("login-totp").value = "";
      showAppView();
    } catch (err) {
      errBox.textContent = err.message || "Login failed.";
      errBox.style.display = "block";
    }
  }

  async function handleLogout() {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch (err) {
      console.warn("Logout error:", err);
    }
    currentCsrfToken = "";
    showLoginView("Logged out successfully.");
  }

  // ── Initialization ───────────────────────────────────────────────────────────

  window.addEventListener("DOMContentLoaded", async () => {
    setupTabs();

    document.getElementById("login-form").addEventListener("submit", handleLoginSubmit);
    document.getElementById("btn-logout").addEventListener("click", handleLogout);
    document.getElementById("filter-incident-status").addEventListener("change", loadIncidents);
    document.getElementById("filter-incident-severity").addEventListener("change", loadIncidents);
    document.getElementById("btn-modal-close").addEventListener("click", () => {
      document.getElementById("incident-modal").style.display = "none";
    });

    // Check existing session
    try {
      const data = await apiFetch("/api/auth/session");
      currentCsrfToken = data.csrf_token || "";
      showAppView();
    } catch (err) {
      showLoginView();
    }
  });
})();
