# clipboard_tools

Clipboard command suite with multi-buffer storage, stats, and tmux → Windows clipboard bridging.

## Entry points
- `c2c` / `c2cd` / `c2cr` / `c2ca` – copy files to clipboard (wrap/raw/recursive/append)
- `pclip` – print clipboard with stats and buffer metadata
- `rwc` / `rwcp` – replace file from clipboard (or last cld snapshot)
- `cld`, `apc`, `crx`, `cb2c`, `cb2cf`, `otc`, `otcw`, `otca`, `otcwa`
- `tmuxcp` (legacy alias: `tmux2winclip`) – auto-copy tmux buffer to every detected clipboard target

Buffers persist under `CLIPBOARD_STATE_DIR` (else platform defaults) and track chars/lines/words, timestamps, and read counts.

## `tmuxcp` behavior
- Reads the active tmux buffer and emits OSC52 so upstream terminals (Termux, kitty, iTerm) receive the data even across SSH hops.
- Uses `cross_platform.clipboard_utils` to write the buffer to your local environment clipboard:
  - Termux → `termux-clipboard-set`
  - WSL → `win32yank` / `clip.exe` pass-through to Windows
  - Windows → PowerShell `Set-Clipboard` (UTF-8 safe)
  - macOS/Linux → native clipboard binaries (`pbcopy`, `wl-copy`, `xclip`, etc.)
- Optional `-t/--target` (or `CLIPBOARD_WIN_SSH`) mirrors the buffer to a remote Windows desktop via SSH + PowerShell.
- `-n/--dry-run` outputs the detected actions without touching any clipboards.
- `-l/--local-only` keeps the copy local even if a remote target/env var is configured.
