<!-- version: 0.3.0 -->
# scripts-help

Interactive help browser and registry/README sync for the scripts repository.

## Usage

```
scripts-help              # interactive browser (default)
scripts-help browse       # interactive browser (explicit)
scripts-help drift        # print drift report
scripts-help sync         # launch AI to fix drift
```

## Subcommands

### `browse` (default)

Runs the interactive help browser. Displays startup warnings for any detected
registry or README drift. Navigate categories and subcategories to find
programs, view `--help` output, and open READMEs.

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

The version must match the program's current version. `scripts-help drift -r`
detects mismatches; `scripts-help sync -r` offers AI-assisted fixes.

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
