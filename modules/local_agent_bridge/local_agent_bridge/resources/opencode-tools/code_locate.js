"use strict"

const { runLocalAgent } = require("./local_agent_bridge.js")

module.exports = {
  description: "Find workspace-relative source paths with bounded Git-aware discovery. Read only; default cap is 200 paths and 8 KiB JSON.",
  args: {
    query: { type: "string", description: "Optional case-insensitive path substring; use an empty string to list paths." },
  },
  execute(args, context) {
    return runLocalAgent(
      ["code", "locate", "-C", context.directory, "-l", "100", "-b", "8192", "-j", "--", args.query],
      context,
      16 * 1024,
    )
  },
}
