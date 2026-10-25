"use strict"

const { spawnSync } = require("node:child_process")

function runLocalAgent(args, context, maxBuffer) {
  const directory = context && context.directory
  if (typeof directory !== "string" || !directory) {
    return JSON.stringify({ status: "error", errors: [{ code: "workspace", message: "OpenCode did not provide a project directory" }] })
  }
  const executable = process.platform === "win32" ? "local-agent.exe" : "local-agent"
  const result = spawnSync(executable, args, {
    cwd: directory,
    encoding: "utf8",
    shell: false,
    timeout: 10000,
    maxBuffer,
    windowsHide: true,
  })
  if (result.error) {
    return JSON.stringify({
      status: "error",
      errors: [{ code: "bridge_cli", message: `Could not run ${executable}: ${result.error.message}` }],
    })
  }
  return result.stdout || result.stderr || JSON.stringify({
    status: "error",
    errors: [{ code: "bridge_cli", message: `local-agent exited with status ${result.status}` }],
  })
}

module.exports = { runLocalAgent }
