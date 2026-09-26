<!-- version: 1.0.0 -->
# url-file-tools

`url-files` is a dry-run-first CLI for cleaning and combining files that contain
one URL per line. It removes numbered-list prefixes, optionally deduplicates a
file in place, merges selected files, and can split a merge into one file per
registered base domain.

Registered-domain detection uses the bundled Public Suffix List data from
`tldextract`, so domains such as `example.co.uk` are grouped correctly without a
network lookup. During a merge, an exact leading `m.` hostname label is removed;
for example, `https://m.example.com/a` becomes `https://example.com/a`.

## Install

```powershell
python -m pip install -e modules/url_file_tools
```

## Examples

All commands below are previews unless `-a/--apply` is supplied.

```powershell
# Preview numbering cleanup for one file.
url-files normalize -p .\links.txt

# Rewrite a file, deduplicate normalized rows, and create a backup.
url-files normalize -p .\links.txt -u -b -a

# Preview a folder merge into merged_urls.txt.
url-files merge -p .\url-files

# Merge only explicitly named files under the target folder.
url-files merge -p .\url-files -f first.txt second.txt -o combined.txt -a

# Read selected relative paths from a manifest (blank lines and # comments are ignored).
url-files merge -p .\url-files -L .\merge-files.txt

# Preview one output file per registered base domain.
url-files merge -p .\url-files -s -o .\by-domain

# Non-interactive duplicate handling for automation.
url-files merge -p .\url-files -D remove -a

# Compare a folder of URL files with a ytaedl archive directory.
url-files archive match -p .\url-files -a .\archive

# Compare selected files with mangadl's URL-level manager state.
url-files archive match -p .\url-files -f manga.txt -a .\downloads\.mangadl\state.sqlite3 -t mangadl
```

For a merge with duplicates, dry-run output marks every later occurrence and
shows its first source location. On apply, the default `ask` policy prompts
whether later occurrences should be removed. `-D/--duplicates` can select
`remove` or `keep` explicitly. A duplicate report is written beside applied
merge output unless `--no-duplicate-report` is used.

Use `url-files <subcommand> --help` for all options.

## Library API

The CLI is backed by importable planning and matching APIs:

```python
from pathlib import Path
from url_file_tools import build_merge_plan, match_archive_urls

result = match_archive_urls(
    ["https://example.com/item/1"],
    Path("archive"),
    archive_type="ytaedl",
)
```

`match_archive_urls` never modifies downloader archives. A ytaedl text archive
contains source URLs and can be matched directly. Mangadl's normal gallery-dl
SQLite archive contains per-media keys and cannot reliably prove that a whole
source URL completed; use mangadl's `.mangadl/state.sqlite3`, whose jobs table
stores canonical source URLs and terminal status evidence.
