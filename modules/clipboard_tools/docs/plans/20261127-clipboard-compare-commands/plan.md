# Clipboard Comparison Commands

## Intent

Give `cld` a concise clipboard-to-file summary, keep the old full diff available as `cldd`, and compare pairs of files with `comp` / `compd`, including paths returned by `fd`.

## Goals and constraints

- Preserve the legacy `clipboard_diff.py` behavior and `rwc --from-last-cld` snapshot flow under `cldd`.
- Reuse the current normalized comparison by default and strict mode when requested.
- Report decoded character counts, as the existing comparison model already does.
- Compare every unordered pair for any number of files; the summary is last in `compd`.
- Resolve `fd` output as a NUL-delimited path list; do not use shell interpolation or CSV parsing.
- No clipboard reads or writes in `comp` or `compd`.

## Approaches considered

1. Reuse the existing comparison model and add a small comparison CLI layer (chosen): preserves current equality semantics and centralizes pair generation.
2. Implement new independent text and diff logic: rejected because it could drift from existing normalization and decoding behavior.
3. Convert `fd` output into comma-separated command text: rejected because paths may contain commas; direct argv-list expansion is simpler and safe.

## Implementation and validation

1. Add tests first for file comparisons, concise summaries, all-pairs enumeration, `fd` expansion/errors, detailed output ordering, and legacy `cldd` dispatch.
2. Implement reusable file comparison and command functions; register `cld`, `cldd`, `comp`, and `compd` entry points.
3. Update package major version, README, module CLI descriptions, and scripts-help registry.
4. Run the focused clipboard_tools tests, inspect the task diff, and verify status before reporting.

## Delivery

Commit and push the isolated feature branch when verified. Do not merge unless this feature is explicitly authorized for merge. No local/global install or PATH changes are part of this change.
