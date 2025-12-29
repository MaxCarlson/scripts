# clipboard_tools

Clipboard command suite with multi-buffer storage, stats, and tmux → Windows clipboard bridging.

## Entry points
- `c2c` / `c2cd` / `c2cr` / `c2ca` – copy files to clipboard (wrap/raw/recursive/append)
- `pclip` – print clipboard with stats and buffer metadata
- `rwc` / `rwcp` – replace file from clipboard (or last cld snapshot)
- `cld`, `apc`, `crx`, `cb2c`, `cb2cf`, `otc`, `otcw`, `otca`, `otcwa`
- `tmux2winclip` / `tmuxcp` – send tmux buffer to remote Windows clipboard via SSH + PowerShell

Buffers persist under `CLIPBOARD_STATE_DIR` (else platform defaults) and track chars/lines/words, timestamps, and read counts.

## tmux2winclip behavior
- When run **inside WSL2 or Windows**, it first tries local `pwsh.exe`/`powershell.exe`, then falls back to `clip.exe`.
- On other hosts it uses `CLIPBOARD_WIN_SSH` (or `--target`) to reach your Windows desktop over SSH and call `pwsh Set-Clipboard`.
- Every run also emits an OSC52 sequence so terminals that support it get the text immediately as well.
