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
