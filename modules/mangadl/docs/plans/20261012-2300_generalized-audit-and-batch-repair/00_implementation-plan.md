# MangaDL generalized audit and batch repair

## Goal

Turn the existing URL/folder audit and guarded nhentai page repair into a
batch, report-driven workflow without weakening MangaDL's identity or apply
safety rules.

## Scope

1. Accept repeatable URL files, globs, and directories containing top-level
   `url*.txt` files. Canonicalize and deduplicate across the entire input set
   while retaining duplicate and invalid-line provenance.
2. Write a versioned audit report with useful console and JSON summaries.
   Reports default to the first destination, include the URL-file stem, and
   use numbered suffixes to preserve earlier reports. Loading progress splits
   duplicate and rejected/invalid counts. Console findings identify each
   incomplete/missing/unknown gallery with image totals and page ranges.
3. Add `mangadl repair -r REPORT`. It builds and prints its plan on every run;
   `-p/--plan-output` only saves an optional copy. Apply requires an exact plan
   token.
4. Batch the already-proven repair capabilities: exact-page nhentai repair and
   normal MangaDL downloads for entirely missing galleries. Unsupported or
   ambiguous items remain report-only.
5. After a successful repair/download, re-resolve the URL and backfill its
   source manifest only when the folder match is unique and populated.

## Deferred capability expansion

Exact-path inventories and selective repair for nested gallery-dl extractors,
Manga18FX, and HDPornComics remain later adapters. This stage establishes the
report and batch-execution contract they will consume; it does not claim broad
repair support before exact identities are proven.

## Safety

- Audit and repair preview do not download or modify archives/images.
- Existing audit index-backfill behavior remains compatible and can be disabled
  with `--no-index-backfill`.
- Batch apply re-plans from the report and current library state and requires a
  token bound to that exact plan.
- Missing downloads require one selected destination. Ambiguous identity,
  unsupported repair, and incomplete page/archive mappings fail closed.
- No production-library acceptance is performed without separate approval.
