"use strict"

const { execFile } = require("node:child_process")

const CONTEXT_MAX_BYTES = 3500

function strings(values) {
  return (Array.isArray(values) ? values : []).slice(0, 4).map((value) => String(value).slice(0, 180))
}

function compact(packet) {
  const identity = packet.identities || {}
  const value = {
    schema_version: packet.schema_version,
    status: packet.status,
    task_id: packet.task_id,
    objective: String(packet.objective || "").slice(0, 500),
    authorized_scope: strings(packet.authorized_scope),
    identities: Object.fromEntries(
      ["session_id", "job_id", "message_id", "provider_id", "model_id", "worker_agent"]
        .filter((key) => typeof identity[key] === "string")
        .map((key) => [key, identity[key].slice(0, 200)]),
    ),
    source_evidence: (Array.isArray(packet.source_evidence) ? packet.source_evidence : [])
      .slice(0, 4)
      .map((item) => ({ path: String(item.path || "").slice(0, 240), status: item.status })),
    stale_reasons: strings(packet.stale_reasons),
    decisions: strings(packet.decisions),
    modified_paths: strings(packet.modified_paths),
    completed_verification: strings(packet.completed_verification),
    pending_checks: strings(packet.pending_checks),
    blockers: strings(packet.blockers),
    next_action: String(packet.next_action || "").slice(0, 600),
    automatic_resubmission: false,
    recovery_rules: strings(packet.recovery_rules),
  }
  let text = JSON.stringify(value)
  if (Buffer.byteLength(text, "utf8") > CONTEXT_MAX_BYTES) {
    for (const key of ["authorized_scope", "stale_reasons", "decisions", "modified_paths",
      "completed_verification", "pending_checks", "blockers", "recovery_rules"]) {
      value[key] = value[key].slice(0, 2).map((item) => item.slice(0, 100))
    }
    value.identities = Object.fromEntries(Object.entries(value.identities).map(([key, item]) => [key, item.slice(0, 100)]))
    value.source_evidence = value.source_evidence.slice(0, 2)
    value.objective = value.objective.slice(0, 240)
    value.next_action = value.next_action.slice(0, 300)
    text = JSON.stringify(value)
  }
  if (Buffer.byteLength(text, "utf8") > CONTEXT_MAX_BYTES) {
    text = JSON.stringify({
      status: packet.status,
      task_id: String(packet.task_id || "").slice(0, 100),
      session_id: String(identity.session_id || "").slice(0, 100),
      stale_reasons: strings(packet.stale_reasons).slice(0, 2),
      next_action: String(packet.next_action || "").slice(0, 160),
      automatic_resubmission: false,
    })
  }
  return text
}

async function recover(directory, sessionID) {
  const stdout = await new Promise((resolve, reject) => {
    execFile(
      "local-agent",
      ["checkpoint", "recover-session", sessionID, "-C", directory, "-j"],
      { cwd: directory, shell: false, windowsHide: true, timeout: 5000, maxBuffer: 32 * 1024 },
      (error, output) => error ? reject(error) : resolve(output),
    )
  })
  return JSON.parse(stdout)
}

const server = async ({ directory }) => ({
  "experimental.session.compacting": async ({ sessionID }, output) => {
    try {
      const packet = await recover(directory, sessionID)
      if (!["current", "stale"].includes(packet.status)) return
      if (!packet.identities || packet.identities.session_id !== sessionID) return
      output.context.push(
        "Validated local-agent task checkpoint. Reconcile the existing session/job/message identity; never resubmit based on this packet. Review stale evidence before relying on prior conclusions.\n" + compact(packet),
      )
    } catch {
      // Compaction proceeds normally when local-agent or its checkpoint store is unavailable.
    }
  },
})

module.exports = { id: "local-agent-checkpoint", server }
