<!-- version: 2.0.1 -->
# scripts-help

Interactive help browser, command registry, `ag` discovery, and shell integration for the scripts repository.

## Usage

```
scripts-help                        # interactive browser (default)
scripts-help browse                 # interactive browser (explicit)
scripts-help drift                  # print drift report
scripts-help sync                   # launch AI to fix drift
scripts-help registry list [--json] # list/search/resolve/collisions/validate
scripts-help integrate [-a|-c|-r]   # dry-run-first shell adapter installer
ag [pattern]                        # search registered tools and configured shell shortcuts
ag -A [pattern]                     # include the full shell inventory and PATH executables
ag -D [pattern]                     # show and search raw command definitions
```

## Command Registry, `ag`, and Shell Integration
- **Canonical registry** (`scripts_help/command_registry.py`): Aggregates `scripts_manifest.json`, `scripts_help.registry.REGISTRY`, and `modules/*/pyproject.toml` `[project.scripts]` without duplicating metadata, using `script_logging`'s `program_id` / `invoked_name` contract.
- **`ag`** (`scripts_help/ag.py`): Case-insensitive regex search over command names and help descriptions (`Name`/`Help` table by default), with `-A/--all` for the broad shell/PATH inventory, `-D/--definitions` for raw targets, `--type`, `--source`, `--executables`, `--shell-inventory`, and JSON output. Interactive tables use kind colors unless `NO_COLOR` is set.
- Console-script help comes from explicit command descriptions when available and falls back to the module's `pyproject.toml` project description. Modules may define per-command summaries in `[tool.scripts_help.descriptions]`.
- **Installer & Rollback** (`scripts-help integrate`):
  - Dry-run by default: `scripts-help integrate`
  - Apply managed snippets (`ag_integration.ps1` / `ag_integration.sh` in `dotfiles/dynamic/`): `scripts-help integrate --apply`
  - Verify installation: `scripts-help integrate --check`
  - Rollback (preserves any user-authored lines outside managed markers): `scripts-help integrate --apply --rollback`

## Interactive browser

The default browser is structure-first rather than topic-first. The home page
lists the repository's main program groups (Modules, Python Scripts, the legacy
Python directory, Shell Scripts, PowerShell Scripts, Repository Tools, and Python Projects) and
discovers their current contents at runtime.

Navigation:

- Up/Down selects an entry; Enter opens the selected entry.
- Typing an entry number opens it. Multi-digit numbers are supported.
- In menus below the home page, / enters live search. Each typed character
  immediately filters non-matching rows while preserving the rows' original
  numbers.
- Esc while typing a search keeps the filter but returns to selection mode.
  The next Esc clears that filter; another Esc moves up one menu level.
- Esc on the home page asks for confirmation before exiting.
- The final terminal line is reserved for the currently available hotkeys.

An item's detail page combines a longer description with its path, version, and
invocation metadata when available. It can expose:

- Arguments: execute the current source-tree/registered help command at view
  time, parse its top-level options, and recursively browse subcommand help.
- README: open through glow by default, with the built-in scroll viewer as a
  fallback.
- Commit history: use tig when installed; otherwise show a path-scoped,
  scrollable git log.
- View files: launch file-util ls at the item's directory.

The browser reuses the existing registry for public command names, short
descriptions, help commands, and recorded versions. Longer descriptions are
resolved in this order: an explicit override in
scripts_help/catalog.py, the item's README, the source docstring/comment
header, then the short registry description. This keeps hand-written metadata
centralized without duplicating README content.

From a checkout, the root launcher works without installing the package first:

    python help.py

The installed entry point remains:

    scripts-help

## Subcommands

### `browse` (default)

Runs the interactive help browser. The home screen summarizes actionable
registry/README drift without interrupting navigation. Browse structural
categories to inspect programs, live arguments, READMEs, Git history, and files.

If [`glow`](https://github.com/charmbracelet/glow) is on PATH, READMEs are
rendered with markdown formatting.

### `drift`

Prints a combined drift report:
- Registry drift (new programs, stale versions, deleted paths)
- README drift (missing files, missing version tags, version mismatches)

Exits `0` if clean, `1` if any drift found — scriptable from CI or
post-install hooks.

```
scripts-help drift                  # all drift
scripts-help drift -g               # registry only
scripts-help drift -r               # README only
scripts-help drift -v               # verbose: list items missing READMEs
scripts-help drift -q               # quiet: exit code only
```

| Flag | Description |
|------|-------------|
| `-g/--registry-only` | Registry drift only |
| `-r/--readme-only` | README drift only |
| `-v/--verbose` | List all items missing READMEs (default: count only) |
| `-q/--quiet` | No output; use exit code only |

### `sync`

Offers to launch Claude Code or Codex with a prompt describing all detected
drift. The AI reads affected files and makes targeted edits.

```
scripts-help sync                   # sync everything
scripts-help sync -g                # registry only
scripts-help sync -r                # README only
scripts-help sync -n                # dry-run: print prompt without launching
scripts-help sync -C                # copy prompt to clipboard
```

| Flag | Description |
|------|-------------|
| `-g/--registry-only` | Registry sync only |
| `-r/--readme-only` | README sync only |
| `-n/--dry-run` | Print the AI prompt without launching |
| `-C/--copy` | Copy prompt to clipboard |

## Registry format

Entries live in `scripts_help/registry/registry.py`. Each item:

```python
{
    "name": "my-tool",
    "path": "pyscripts/my_tool.py",           # or "modules/my_tool"
    "desc": "One-line description.",
    "help_cmd": ["python", "pyscripts/my_tool.py", "--help"],
    "version": "1.0.0",
}
```

## README versioning

Every README must include a version tag within its first 15 lines:

```markdown
<!-- version: X.Y.Z -->
```

The version records the documented major/minor feature level. `scripts-help
drift -r` flags a version mismatch only when a program has advanced to a new
major or minor version; patch-only source changes do not request README work.
`scripts-help sync -r` offers AI-assisted fixes for actionable drift.

**Canonical README locations:**

| Program type | README location |
|-------------|-----------------|
| `modules/<name>` | `modules/<name>/README.md` |
| `pyscripts/<name>.py` | `pyscripts/readme/<name>.md` |

## Post-install drift check

`setup.py` and bootstrap scripts run a drift check after installation.
Pass `-U`/`--no-update-help` to skip:

```bash
./bootstrap.sh --no-update-help
python setup.py --no-update-help
```

```powershell
.\bootstrap.ps1 -NoUpdateHelp
```
