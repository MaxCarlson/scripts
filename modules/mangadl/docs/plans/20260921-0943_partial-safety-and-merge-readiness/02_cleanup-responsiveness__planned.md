# Stage S2 - Cleanup and Responsiveness

## Scope

- Add a `partials clean` command with destination-derived defaults, repeatable
  targets, JSON output, dry-run default, and explicit apply mode.
- Validate containment, metadata, archive identity, worker activity, and
  manifest coverage before any mutation.
- Remove exact manifest keys in one archive transaction before deleting files.
- Replace dashboard whole-log reads with bounded reverse tail reads.

## Verification

- Tests cover directory and file targets, overlapping targets, missing and
  malformed metadata, path traversal, active markers, SQLite rollback, partial
  filesystem failure safety, UTF-8/replacement decoding, and large log tails.
