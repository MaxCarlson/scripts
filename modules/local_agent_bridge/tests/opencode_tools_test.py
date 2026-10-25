"""Offline contract checks for the optional OpenCode tool adapters."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_opencode_tools_call_bounded_cli_with_argv_and_session_directory():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable for OpenCode adapter contract test")
    tools = Path(__file__).resolve().parents[1] / "local_agent_bridge/resources/opencode-tools"
    script = r"""
const assert = require("node:assert/strict")
const childProcess = require("node:child_process")
const { pathToFileURL } = require("node:url")
const calls = []
childProcess.spawnSync = (executable, args, options) => {
  calls.push({ executable, args, options })
  return { status: 0, stdout: '{"status":"ok"}', stderr: "", error: null }
}
const locate = require(process.argv[1])
const contextTool = require(process.argv[2])
;(async () => {
  assert.equal(await locate.execute({ query: "-pattern" }, { directory: "C:/sample project" }), '{"status":"ok"}')
  assert.equal(await contextTool.execute({ path: "src/file.py", start_line: 4, end_line: 8 },
    { directory: "C:/sample project" }), '{"status":"ok"}')
  assert.equal(calls.length, 2)
  assert.equal(calls[0].options.shell, false)
  assert.equal(calls[0].options.cwd, "C:/sample project")
  assert.deepEqual(calls[0].args.slice(-2), ["--", "-pattern"])
  assert.deepEqual(calls[1].args.slice(-4), ["--", "src/file.py", "4", "8"])
  assert.ok(calls[0].args.includes("-b"))
  assert.ok(calls[1].args.includes("-b"))
})().catch(error => { console.error(error); process.exitCode = 1 })
"""
    result = subprocess.run(
        [node, "-e", script, str(tools / "code_locate.js"), str(tools / "code_context.js")],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_checkpoint_compaction_plugin_uses_pinned_hook_and_bounded_cli_packet():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable for OpenCode plugin contract test")
    plugin = Path(__file__).resolve().parents[1] / "local_agent_bridge/resources/opencode-plugins/local_agent_checkpoint.js"
    script = r"""
const assert = require("node:assert/strict")
const childProcess = require("node:child_process")
const { pathToFileURL } = require("node:url")
const calls = []
let response
childProcess.execFile = (executable, args, options, callback) => {
  calls.push({ executable, args, options })
  callback(null, JSON.stringify(response), "")
}
;(async () => {
  const plugin = (await import(pathToFileURL(process.argv[1]).href)).default
  const hooks = await plugin.server({ directory: "C:/sample project" })
  const output = { context: [] }
  response = { status: "stale", task_id: "task-8", identities: { session_id: "ses-8", job_id: "job-8" },
    objective: "Continue the task", next_action: "Inspect stale evidence", automatic_resubmission: false }
  await hooks["experimental.session.compacting"]({ sessionID: "ses-8" }, output)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].executable, "local-agent")
  assert.deepEqual(calls[0].args, ["checkpoint", "recover-session", "ses-8", "-C", "C:/sample project", "-j"])
  assert.equal(calls[0].options.cwd, "C:/sample project")
  assert.equal(calls[0].options.shell, false)
  assert.equal(calls[0].options.timeout, 5000)
  assert.equal(output.context.length, 1)
  assert.match(output.context[0], /task-8/)
  assert.match(output.context[0], /never resubmit/)
  response = { status: "current", task_id: "task-large", identities: { session_id: "ses-8", job_id: "j".repeat(1000) },
    objective: "o".repeat(16000), next_action: "n".repeat(16000),
    decisions: Array(200).fill("d".repeat(1000)), pending_checks: Array(200).fill("p".repeat(1000)),
    recovery_rules: Array(200).fill("r".repeat(1000)), automatic_resubmission: false }
  await hooks["experimental.session.compacting"]({ sessionID: "ses-8" }, output)
  assert.equal(output.context.length, 2)
  assert.ok(Buffer.byteLength(output.context[1], "utf8") < 4000)
  response = { status: "missing" }
  await hooks["experimental.session.compacting"]({ sessionID: "ses-unknown" }, output)
  assert.equal(output.context.length, 2)
})().catch(error => { console.error(error); process.exitCode = 1 })
"""
    result = subprocess.run([node, "-e", script, str(plugin)], capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


def test_structural_tools_use_bounded_cli_argv_without_shell():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable for OpenCode adapter contract test")
    tools = Path(__file__).resolve().parents[1] / "local_agent_bridge/resources/opencode-tools"
    script = r"""
const assert = require("node:assert/strict")
const childProcess = require("node:child_process")
const calls = []
childProcess.spawnSync = (executable, args, options) => {
  calls.push({ executable, args, options })
  return { status: 0, stdout: '{"status":"ok"}', stderr: "", error: null }
}
const symbols = require(process.argv[1])
const map = require(process.argv[2])
;(async () => {
  const context = { directory: "C:/project" }
  await symbols.execute({ path: "src/a.py" }, context)
  await map.execute({ task_query: "reconcile checkpoints" }, context)
  assert.equal(calls.length, 2)
  assert.equal(calls[0].options.shell, false)
  assert.deepEqual(calls[0].args, ["code", "symbols", "-C", "C:/project", "-b", "8192", "-j", "--", "src/a.py"])
  assert.deepEqual(calls[1].args, ["code", "map", "-C", "C:/project", "-f", "80", "-l", "40",
    "-t", "1800", "-b", "8192", "-j", "--", "reconcile checkpoints"])
  assert.ok(calls.every(call => call.options.cwd === context.directory))
})().catch(error => { console.error(error); process.exitCode = 1 })
"""
    result = subprocess.run([node, "-e", script, str(tools / "code_symbols.js"), str(tools / "code_map.js")],
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
