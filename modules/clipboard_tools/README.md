<!-- version: 2.0.0 -->
# clipboard_tools

Clipboard command suite with multi-buffer storage, concise and detailed comparisons, terminal capture (`cb2c`/`cb2cf`), and tmux → Windows clipboard bridging.

## Install and verify

Run `python setup.py -f -v` from the scripts checkout whose commands should change. Version 2.0.0 changes console scripts, so a full reinstall regenerates both the virtual-environment commands and repository `bin/` proxies.

In PowerShell, check `Get-Command cld,cldd,comp,compd -All`. For `comp`, the scripts checkout's `bin\comp.cmd` must appear before `C:\Windows\System32\comp.exe`. Confirm the active Python imports this checkout with `python -c "import clipboard_tools; print(clipboard_tools.__file__)"`.

## Entry points
- `c2c` / `c2cd` / `c2cr` / `c2ca` – copy files to clipboard (or `-t`/`--text` for literal text)
- `gcb` / `scb` – cross-platform get/set clipboard short commands (file path, literal text, or stdin)
- `pclip` – print clipboard with stats and buffer metadata
- `rwc` / `rwcp` / `sfcb` – replace file from clipboard (or last cld snapshot); `sfcb` replaces legacy `sfc` alias without shadowing Windows `sfc.exe`
- `cld <file>` – summarize whether the clipboard matches a file and which side is larger; use `-s/--strict`, `-z/--trim-trailing-newline`, `-E/--encoding`, and `-k/--check`
- `cldd <file>` – show the previous full clipboard-vs-file diff and retain the `rwc --from-last-cld` snapshot behavior
- `comp <file> <file> [...]` – print a concise summary for every unordered file pair; use `comp fd <pattern>` to compare `fd` search results
- `compd <file> <file> [...]` – show the full diff for every pair, followed by the concise summary; also supports `compd fd <pattern>`
- `apc`, `crx`, `cb2c`, `cb2cf`, `otc`, `otcw`, `otca`, `otcwa`
- `tmuxcp` (legacy alias: `tmux2winclip`) – auto-copy tmux buffer to every detected clipboard target

Buffers persist under `CLIPBOARD_STATE_DIR` (else platform defaults) and track chars/lines/words, timestamps, and read counts.

`cld`, `comp`, and `compd` use the existing decoded text character counts for their size summaries. Comparisons normalize line endings by default; `--strict` compares exact text. `comp` and `compd` do not read or change the clipboard. `fd` results are passed internally as a path list, so filenames containing spaces or commas remain intact.

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

## Terminal capture (`cb2c` / `cb2cf`) & platform limitations
- **tmux**: `cb2c` captures `tmux capture-pane -pS -10000 -E - -J`. Note that `tmux` interprets `clear` escape sequences internally rather than storing `\x1b[H\x1b[2J` in pane text; when no clear marker is present in the captured buffer, `cb2c` warns and copies the captured buffer.
- **Session logs (`--session-log` / `CLIPBOARD_SESSION_LOG`)**: Forward-recorded logs (e.g. `script`, `Start-Transcript`, `~/.term_log.session_shlvl_<N>`) preserve ANSI clear sequences when recorded, enabling since-last-clear slicing.
- **Native Windows Terminal**: A child Python process cannot read arbitrary existing Windows Terminal / ConPTY scrollback. Outside `tmux` and without `--session-log`, `cb2c` exits `1` with guidance to use Windows Terminal's native `exportBuffer`/`copy` action, `tmux`, or `--session-log`.

## Compatibility & collisions
- `c2c`: Python `c2c` is file-first (`c2c <file>`), with `-t/--text` and `-I/--stdin` for literal text. In PowerShell (`W11-powershell/Config/Modules/ClipboardModule.psm1`), `c2c` / `scb` -> `Set-ClipboardContent` preserves single-argument literal-or-file behavior and forwards flags/multi-files to `c2c.exe`.
- `gcb` / `scb`: Available as Python console entry points on POSIX/WSL/Termux/cmd.exe; in PowerShell, native/module aliases (`Alias`) retain higher precedence than `Application`.
- `sfcb`: Dedicated cross-platform alias for `replace_with_clipboard` (same as `rwc`), replacing the legacy PowerShell `sfc` alias so `C:\WINDOWS\system32\sfc.exe` is never shadowed.
