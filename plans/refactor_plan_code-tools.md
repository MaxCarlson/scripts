<!--
This plan outlines the consolidation of various code-related scripts into a single project.

**Source Files:**
- modules/code_tools/func_replacer.py
- modules/code_tools/rgcodeblock_cli.py
- modules/code_tools/rgcodeblock_lib/__init__.py
- modules/code_tools/rgcodeblock_lib/extractors.py
- modules/code_tools/rgcodeblock_lib/language_defs.py
- pyscripts/rgcode.py
- pyscripts/unpaired_finder.py

**Test Files:**
- modules/code_tools/tests/test_func_replacer.py
- modules/code_tools/tests/test_rgcodeblock_cli.py
- modules/code_tools/tests/test_rgcodeblock_lib_extractors.py
-->

# Refactoring Plan: Code Tools

**Goal:** Stabilize the `code_tools` module by fixing its tests, promote it to a full project in `pyprjs`, and consolidate related developer scripts into it.

### Source Files to Merge:

- `modules/code_tools/` (entire module)
- `pyscripts/rgcode.py`
- `pyscripts/unpaired_finder.py`

### Execution Plan:

1.  **Fix Tests (CRITICAL):** The first and most important step is to fix the 12 failing tests in `modules/code_tools/tests/` as reported in `tmp.pytest1`. The test suite must pass before proceeding with any other changes. This ensures the core logic (`rgcodeblock_lib`, `func_replacer`) is sound.
2.  **Promote to Project:** Move the entire `modules/code_tools` directory to `pyprjs/code_tools`.
3.  **Consolidate Functionality:**
    -   Review the logic in `pyscripts/clipboard_replace.py` and merge any unique features or improvements into `pyprjs/code_tools/func_replacer.py`. The goal is to have one canonical tool for this task.
    -   Review `pyscripts/rgcode.py` and merge its functionality into `pyprjs/code_tools/rgcodeblock_cli.py`. It is likely an older version and can be fully replaced.
4.  **Update Project Configuration:** Adjust the `pyproject.toml` within the new `pyprjs/code_tools` directory to reflect its new status as a standalone project, ensuring its entry points (`func_replacer`, `rgcodeblock`) are correctly defined.

### Files to Delete Post-Refactoring:

- The original `modules/code_tools/` directory.
- `pyscripts/clipboard_replace.py`
- `pyscripts/rgcode.py`
