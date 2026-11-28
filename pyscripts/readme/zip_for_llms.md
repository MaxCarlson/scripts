<!-- version: 0.4.0 -->
# zip_for_llms.py

Preview and package the selected files in a repository for LLM analysis. The
preview does not create package outputs or run Gemini.

## Usage

```bash
python pyscripts/zip_for_llms.py --help
```

## Preview a selection

```bash
# Show the filtered tree, counts, byte totals, token estimate, filters and outputs
python pyscripts/zip_for_llms.py . --preview

# Inspect selected files and exclusions
python pyscripts/zip_for_llms.py . --dry-run --list-files --list-excluded

# Save a deterministic machine-readable report to stdout
python pyscripts/zip_for_llms.py . --preview --json --preset python --exclude-dir tests

# Review flattened names and Windows case-insensitive collisions
python pyscripts/zip_for_llms.py . --preview --flatten --name-by-path --list-files

# Preview the existing size-tree options
python pyscripts/zip_for_llms.py . --preview --auto-size-tree 15
```

`--json` emits one JSON object on stdout and accepts the same filters, presets,
output mode, flattening, and size limit options as packaging. A size limit
reports both the selected files and the files left after the existing
best-effort pre-compression size trimming rule; this does not predict final
compressed ZIP membership or archive size. The human report also lists the ten
largest selected files. Text token counts are rough
estimates based on readable UTF-8 source bytes; they do not model the tokenizer
of a particular LLM. Binary and non-UTF-8 files remain selected for ZIP output
but are excluded from the consolidated-text token estimate. Excluded directory
contents are not enumerated for preview counts.

## Interactive packaging

```powershell
python pyscripts/zip_for_llms.py -i
python pyscripts/zip_for_llms.py . -i -f -P python
python pyscripts/zip_for_llms.py . -i -z -x tests
python pyscripts/zip_for_llms.py . -i -d
```

The interactive workflow starts with source/output and mode settings, then lets
you inspect the selected tree, edit filters, discover repeated patterns, and
review destinations before generation. Press `Y` in review to generate; an
existing destination requires a second `Y`. `--dry-run` disables generation.
Filtering uses a cached metadata inventory and does not read file contents
until a writer is explicitly run. If the terminal UI cannot initialize, the
command exits with an error and does not fall through to packaging.
