# Checklist

- [x] Real four-resource stale scenario is summarized as 11 current and 4 outdated, with copy/link methods visible.
- [x] Current, outdated, missing, conflict, and disabled optional-feature states are distinct in human output.
- [x] JSON keeps existing operation fields and exit codes and adds a backward-compatible summary.
- [x] File/tree byte drift, nested tree changes, missing resources, link target changes, and generated role source changes are tested.
- [x] Managed config semantic equivalence and drift are tested and reported as semantic verification.
- [x] Package version, active package path, resource source paths, and checkout association are reported without assuming CWD provenance.
- [x] Color auto mode respects non-TTY output and `NO_COLOR`; JSON contains no terminal escapes.
- [x] Status path remains read-only; no live home/state paths are used by tests.
- [x] Complete module tests, changed-file Ruff, and `git diff --check` run; full-suite run has two Git Bash/MSYS environment failures and two existing whole-module Ruff findings, documented in STATUS.md.
- [x] Rebuilt and inspected the 3.5.0 wheel after final command-formatting changes.
