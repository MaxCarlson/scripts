"use strict";

(() => {
  const PAGE_ROW_LIMIT = 200;

  function formatTimestamp(value) {
    if (typeof value !== "string" || !value) return "—";
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleString() : "—";
  }

  function addCell(row, value, className = "") {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = value == null || value === "" ? "—" : String(value);
    row.append(cell);
    return cell;
  }

  function renderRunRows(body, runs, openRun) {
    body.replaceChildren();
    const boundedRuns = Array.isArray(runs) ? runs.slice(0, PAGE_ROW_LIMIT) : [];
    for (const run of boundedRuns) {
      if (!run || typeof run.id !== "string" || !run.id) continue;
      const row = document.createElement("tr");
      row.dataset.runId = run.id;
      addCell(row, typeof run.name === "string" && run.name ? run.name : "Unnamed run", "history-run-name");

      const status = typeof run.status === "string" && run.status ? run.status : "Unknown";
      const statusCell = addCell(row, status, `history-status ${status.toLowerCase().replace(/[^a-z0-9_-]/g, "-")}`);
      statusCell.setAttribute("aria-label", `Status: ${status}`);

      const idCell = document.createElement("td");
      const idButton = document.createElement("button");
      idButton.type = "button";
      idButton.className = "history-run-id-button history-run-open";
      idButton.textContent = run.id;
      idButton.setAttribute("aria-label", `Open run ${run.id}`);
      idButton.addEventListener("click", () => openRun(run.id));
      idCell.append(idButton);
      row.append(idCell);

      addCell(row, formatTimestamp(run.created_at), "history-run-created");
      addCell(row, formatTimestamp(run.ended_at), "history-run-ended");
      addCell(row, run.exit_code == null ? "—" : run.exit_code, "history-run-exit-code");
      body.append(row);
    }
  }

  globalThis.RunmuxHistoryView = Object.freeze({ renderRunRows });
})();
