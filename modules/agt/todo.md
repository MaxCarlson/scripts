### Implemented now
- `agt gemini` subcommand with its **own help page**.
- `-p/--prompt` accepts **literal text or a path** to a prompt file.
- `@path` ingest:
  - Supports single files, **globs** (e.g., `@src/**/*.py`) and **folders** (recursive).
  - Skips large (default 512 KB) or binary-looking files.
  - Prepends a **ReadManyFiles**-style summary plus per-file blocks to the system message.
- **REPL** mode when no prompt is provided (clears screen on start).
- **Thinking spinner** while waiting for responses (and when streaming).
- **Logging** (`--log`, `-v`) including requests.
- **Save/resume sessions** (`--session`, `--new-session`) stored in `~/.config/agt/sessions/NAME.jsonl`.
- OpenAI-compatible **/v1/chat/completions** calls via `WebAIClient`.
- Minimal **streaming** support (spinner + print as chunks arrive).

### Not yet (next pass)
- Fancy TUI auto-complete UI with up/down + Tab accept (current REPL has no dropdown UI).
- Ctrl+S to expand diffs and the full **tool approval workflow** inside the TUI (scaffolded; not wired here).
- A persistent per-run **activity log pane** inside the TUI.
- Built-in tests for the new ingest/session pieces.
- A `gpt` subcommand (the parser is ready to add one).
