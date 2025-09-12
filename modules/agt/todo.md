### Implemented now
- **True TUI (default)**: `agt gemini` launches a full-screen UI (keep the REPL with `--ui repl`).
- **Tab completion**:
  - `/commands` with descriptions.
  - `@paths` for files, folders, and globs (`**/*.py`), with tab cycling and arrow selection.
- **Attachment ingestion**:
  - `@file`, `@folder/`, and globs inline; contents injected into the prompt (Gemini “ReadManyFiles”-style).
- **Background streaming**:
  - You can keep typing while the model thinks.
  - **ESC cancels** the current generation without exiting.
- **Tool permission flow**:
  - Always prompts for `write_file`, `edit_file`, and `run`.
  - `a` (always) remembers **per resource**:
    - `run` remembers **per binary** (e.g., `/usr/bin/python`), not all commands.
    - `write/edit` remember per file path.
  - Diff preview auto-shows **30 lines** and supports **show all** (`s`) inline.
- **Sessions**: `/save` and `/load` (JSONL), plus tokens/stats and clipboard copy `/cp`.
- **Logging**: `--log` path and `-v` for debug; logs request starts and errors.

### Still to do / limitations
- The permission dialog’s “expand” uses `s` (show-all) instead of Ctrl+S inside the mini-prompt (prompt_toolkit limitation for nested prompts). The main screen still shows the full history like Gemini.
- We don’t yet persist the “always allow” set across app runs (session-scoped only).
- Full “corgi mode” 😉 and rich, multi-pane tool diff viewers would require a heavier framework (e.g., Textual).
