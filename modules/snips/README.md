# snips

`snips` manages Windows text templates and keyboard actions from one versioned JSON configuration. AutoHotkey v2 runs the registered shortcuts as a per-user background process; Python is used only by the management CLI.

## Architecture choice

The CLI is a small custom Python module backed by AutoHotkey v2. FlitKey offers global hotkeys, cursor markers, clipboard text, and a JSON config, but its documented management surface is a desktop application and import flow. Lintalist offers editable snippets and hotkeys, but its current source is AutoHotkey v1 based. Espanso offers a CLI and file-based configuration, but its current documentation says shortcut-triggered matches are not supported yet. Those interfaces do not provide a simpler reusable CLI for this repository's exact hotkey actions.

- [FlitKey features and Windows support](https://github.com/swarajnandedkar/FlitKey#key-features)
- [Lintalist features and AutoHotkey runtime](https://github.com/lintalist/lintalist#introduction)
- [Espanso trigger and shortcut status](https://espanso.org/docs/get-started/#understanding-matches)

Canonical config lives at `%APPDATA%\snips\config.json`. Runtime files live separately at `%LOCALAPPDATA%\snips\runtime`. Template bodies are written as UTF-8 text data files. The generated `.ahk` file contains only validated hotkey strings and paths, so snippet content is never compiled into executable source.

## Install and use

Install the `snips` module with the repository's normal setup, or from the repository root run `python -m pip install -e .\modules\snips` to create the `snips` command in the active Python environment.

Mutating commands preview by default. Add `--apply` to persist. `snips install --apply` reuses an installed AutoHotkey v2, or installs in this order: WinGet `AutoHotkey.AutoHotkey`, Scoop Extras `autohotkey`, then the official v2 installer. It creates starter actions for Markdown code blocks (`Ctrl+Alt+B`) and fenced clipboard text (`Ctrl+Alt+V`), starts the runtime, and registers it under the current user's Windows Run key. No Python process stays running.

```powershell
snips install --apply
snips list
snips show --id markdown-code-block
```

Add templates from files to preserve multiline Unicode content:

```powershell
snips add --id meeting-note --name "Meeting note" --hotkey Ctrl+Alt+M --file .\meeting.md --apply
snips bind --id meeting-note --hotkey Ctrl+Shift+M --apply
snips edit --id meeting-note --file .\meeting.md --apply
```

Actions can also be registered without template content:

```powershell
snips add --id fence-selection --name "Fence selected text" --kind selection-fence --hotkey Ctrl+Alt+S --apply
```

`selection-fence` copies the current selection with Ctrl+C, wraps it in a Markdown fence, pastes it in place, then restores the full prior clipboard. Some applications prevent synthetic copy/paste; `snips doctor` cannot determine another application's selection behavior.

Back up and restore configuration:

```powershell
snips export --output .\snips-backup.json --apply
snips import --input-file .\snips-backup.json
snips import --input-file .\snips-backup.json --replace --apply
```

The import default merges by binding ID. `--replace` replaces all managed bindings only when paired with `--apply`. All mutating commands accept `--json` for structured output and `--config` to select a nondefault config path. `--help` is available at the root and each subcommand.

## Diagnostics and behavior

```powershell
snips status --json
snips doctor
snips reload --apply
```

Exit codes are `0` for success or preview, `2` for invalid input/configuration, `3` for filesystem errors, and `4` for backend, runtime, or diagnostics failures. Argument-parser usage errors also return `2`.

Clipboard-fence chooses a run of backticks one character longer than the longest backtick run in the copied text. It adds only the surrounding fence and separator line breaks; it does not trim or normalize the clipboard text. Clipboard formats are saved with AutoHotkey `ClipboardAll()` and restored after paste. Clipboard contents are never logged. These shortcuts only copy/paste text and do not submit forms or messages.

Hotkey collisions inside the managed config are rejected. Windows does not expose a dependable list of registrations owned by PowerToys and unrelated AutoHotkey scripts, so conflicts with those tools may only be found when the runtime registers shortcuts. `snips doctor` reports this limit. If a registration fails, the active update is rolled back where possible and the status file records an error without snippet content.

## Limitations

- The runtime and global shortcuts are Windows-only and require AutoHotkey v2.
- Caret repositioning counts characters after `{{cursor}}`; applications with unusual text controls may interpret keyboard navigation differently.
- Interactive validation depends on the target application's copy/paste behavior. No GUI validation is claimed unless it is performed explicitly.
