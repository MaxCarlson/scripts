# Programs with significant functional overlap — candidates for future consolidation.
# Each entry documents the overlap so it can be evaluated when refactoring.

OVERLAP_NOTES: list[dict] = [
    {
        "group": "HuggingFace dataset downloaders (2 programs)",
        "programs": [
            "pyscripts/dl-hf-dataset.py",
            "pyscripts/download_dataset.py",
        ],
        "note": (
            "Near-duplicate scripts: both download HuggingFace datasets via the "
            "'datasets' library. dl-hf-dataset.py has slightly more options. "
            "One should be removed or they should merge into a single script."
        ),
    },
    {
        "group": "Disk monitoring (2 programs)",
        "programs": [
            "pyscripts/check_disks.py",
            "pyscripts/monitor-disks.py",
        ],
        "note": (
            "Both report disk usage. check_disks is a one-shot snapshot; "
            "monitor-disks is real-time and interactive. Could merge as "
            "--watch / --once modes of a single disk tool."
        ),
    },
    {
        "group": "Duplicate file detection (2 programs)",
        "programs": [
            "pyscripts/deduplicator.py",
            "pyscripts/file_kit.py (duplicates subcommand)",
        ],
        "note": (
            "deduplicator.py is a standalone dedup tool; file_kit.py also has a "
            "'duplicates' subcommand. The logic overlaps. Consider absorbing "
            "deduplicator.py into file_kit as a richer subcommand."
        ),
    },
    {
        "group": "Folder comparison (2 programs)",
        "programs": [
            "pyscripts/folder_similarity.py",
            "pyscripts/folder_matcher.py",
        ],
        "note": (
            "Both compare folder contents. folder_similarity uses hashes for "
            "similarity scoring; folder_matcher matches files by extension+size. "
            "Could unify as subcommands of a single 'folder-compare' tool."
        ),
    },
    {
        "group": "Find-and-replace / file filtering (2 programs)",
        "programs": [
            "pyscripts/replacer.py",
            "pyscripts/filter-prune.py",
        ],
        "note": (
            "replacer.py does find-and-replace using ripgrep; filter-prune.py "
            "does fd/ripgrep-based deletion. Overlapping in how they search "
            "files — could share a common search backend."
        ),
    },
    {
        "group": "PDF from repo/docs (3 programs)",
        "programs": [
            "pyscripts/convert_repo_to_pdf.py",
            "pyscripts/convert_repo_to_pdf_v2.py",
            "pyscripts/gh_to_pdf.py",
            "pyscripts/web_to_pdf.py",
        ],
        "note": (
            "Four PDF-generation scripts. v1 and v2 are explicit iterations of "
            "the same local-repo script. gh_to_pdf targets GitHub Markdown. "
            "web_to_pdf uses Playwright for JS-rendered pages. Could unify as "
            "one 'to-pdf' tool with --source (local/github/url) and --engine flags."
        ),
    },
    {
        "group": "Repo packaging for LLMs (2 programs)",
        "programs": [
            "pyscripts/zip_for_llms.py",
            "pyscripts/repo_processor.py",
        ],
        "note": (
            "Both package a repo for LLM consumption. zip_for_llms has Gemini "
            "analysis and preset support; repo_processor outputs zip + text. "
            "Significant feature overlap — consolidation candidate."
        ),
    },
    {
        "group": "Clipboard copy-to scripts (2 programs)",
        "programs": [
            "pyscripts/copy_to_clipboard.py",
            "pyscripts/set_clipboard_text.py",
        ],
        "note": (
            "copy_to_clipboard reads from a file; set_clipboard_text reads from "
            "a string/stdin. Very similar. clip_tools module already unifies "
            "clipboard ops — these standalones may be redundant."
        ),
    },
    {
        "group": "Clipboard replace scripts (2 programs)",
        "programs": [
            "pyscripts/clipboard_replace.py",
            "pyscripts/replace_with_clipboard.py",
        ],
        "note": (
            "clipboard_replace targets Python function/class blocks; "
            "replace_with_clipboard is more generic. Near-duplicate — "
            "the generic one should handle both use cases."
        ),
    },
    {
        "group": "Shell history runners (2 programs)",
        "programs": [
            "pyscripts/run_history_process.py",
            "pyscripts/run_with_history.py",
        ],
        "note": (
            "Both pull file/dir paths from Atuin history and run commands. "
            "run_with_history is simpler (pick path by index); "
            "run_history_process is richer (filter, extract, batch). "
            "Could be one tool with a --simple / --batch mode."
        ),
    },
    {
        "group": "Clipboard module vs. standalone scripts (broad overlap)",
        "programs": [
            "modules/clip_tools",
            "pyscripts/append_clipboard.py",
            "pyscripts/clipboard_diff.py",
            "pyscripts/clipboard_replace.py",
            "pyscripts/copy_to_clipboard.py",
            "pyscripts/output_to_clipboard.py",
            "pyscripts/print_clipboard.py",
            "pyscripts/replace_with_clipboard.py",
            "pyscripts/set_clipboard_text.py",
            "pyscripts/copy_buffer_to_clipboard.py",
        ],
        "note": (
            "clip_tools module is a unified CLI that wraps clipboard operations. "
            "The standalone pyscripts predate it and overlap heavily. "
            "Long-term: route everything through clip_tools and deprecate "
            "the standalone scripts."
        ),
    },
    {
        "group": "File analysis module vs. script (2 programs)",
        "programs": [
            "modules/file_utils",
            "pyscripts/file_kit.py",
        ],
        "note": (
            "file_utils module and file_kit.py both provide file listing, disk "
            "space analysis, and path utilities. Consider whether file_kit "
            "should be a thin wrapper over file_utils."
        ),
    },
]
