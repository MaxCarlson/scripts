"use strict"

const { runLocalAgent } = require("./local_agent_bridge.js")

module.exports = {
  description: "Build a task-ranked, bounded Python symbol map with source hashes. Read only.",
  args: {
    task_query: { type: "string", description: "Task description used to rank symbols and source paths" },
  },
  execute(args, context) {
    return runLocalAgent(
      ["code", "map", "-C", context.directory, "-f", "80", "-l", "40", "-t", "1800", "-b", "8192", "-j", "--", args.task_query],
      context,
      16 * 1024,
    )
  },
}
