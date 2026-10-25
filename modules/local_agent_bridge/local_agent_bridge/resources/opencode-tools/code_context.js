"use strict"

const { runLocalAgent } = require("./local_agent_bridge.js")

module.exports = {
  description: "Read an exact workspace-relative source line range. Read only; core limits ranges to 200 lines and JSON output to 16 KiB.",
  args: {
    path: { type: "string", description: "Relative file path inside the OpenCode project directory." },
    start_line: { type: "number", description: "Inclusive one-based first line." },
    end_line: { type: "number", description: "Inclusive one-based last line." },
  },
  execute(args, context) {
    return runLocalAgent(
      ["code", "context", "-C", context.directory, "-m", "4096", "-b", "16384", "-j", "--",
        args.path, String(args.start_line), String(args.end_line)],
      context,
      32 * 1024,
    )
  },
}
