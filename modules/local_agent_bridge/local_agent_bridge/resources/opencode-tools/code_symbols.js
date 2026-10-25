"use strict"

const { runLocalAgent } = require("./local_agent_bridge.js")

module.exports = {
  description: "Return a bounded Python AST outline with symbol line ranges and source hash. Read only.",
  args: {
    path: { type: "string", description: "Workspace-relative Python source path" },
  },
  execute(args, context) {
    return runLocalAgent(
      ["code", "symbols", "-C", context.directory, "-b", "8192", "-j", "--", args.path],
      context,
      16 * 1024,
    )
  },
}
