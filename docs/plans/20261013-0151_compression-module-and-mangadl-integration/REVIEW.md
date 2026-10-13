# Complete current-tree review — 2026-10-13

Read all predecessor plan files, compresser source/tests/docs, MangaDL compression
adapter/parser/registration/versions, termdash table/bar source/tests and renderer,
relevant audit/index/progress code, and historical validation evidence. Root
`C:\Users\mcarls\src\scripts`, HEAD `9a8e95b`. Existing changes preserved.
Git status excludes inaccessible pscripts submodule metadata; no work there.

## Findings

| Priority | Source evidence | Required correction |
| --- | --- | --- |
| Critical | engine.compress_batch recovers even in analysis; recovery unlinks record paths based on decodability | Read-only analysis; contained owned fingerprinted explicit recovery; retain unresolved journals |
| Critical | workers overwrite/delete one shared journal; journal write errors ignored | Exclusive writer ownership, durable atomic journal, unique temps and fault tests |
| Critical | engine deletes existing target; same-extension uses shutil.move | Collision refusal, atomic replace, source-change checks |
| High | jpegtran receives Pillow-resaved JPEG and two positional paths | Original JPEG input, portable -outfile, lossless-only dispatch |
| High | PNG/unavailable formats fall back to JPEG, including .png suffix | Real PNG or unavailable, never mislabeled output |
| High | AVIF q100 called lossless; WebP converts LA/P to RGB; exact absent | Truthful lossless/alpha/sample/metadata/frame guards |
| High | codecs still call binary_search_quality; threshold failure returns bytes | Smallest passing measured candidate or retain original |
| High | max-pixel constant unused; SSIM windows*kernel expands ~121 samples/pixel | Enforced bounds, memory-aware concurrency, separable metric |
| High | direct-gallery selector ignores filters; full URLs matched as folder substrings | Exact source-index resolution and explicit folder selectors |
| Medium | output-dir ignored; standalone failures return0; ranges unchecked | Implement/reject options, nonzero failures, parser validation |
| Medium | JSON without -N gets progress stdout | stderr/plain progress, clean JSON with defaults, finally cleanup |
| Medium | auto fixed WebP/tall JPEG; cache session-only and no inventory cache | Measured candidates, persistent settings/version-aware cache |
| Medium | UI uses handwritten ANSI, five rows, lifetime ETA and unused file bar | Actual termdash, gallery/overall progress, rolling ETA and terminal tests |
| Medium | table max_width unused, codepoint widths; bar tiny widths exceed bound | Width/Unicode/ANSI tests and renderer corrections |
| Medium | MangaDL shim1.28 vs package1.29; invented doc API classes; broken plan link | Sync source/API/docs/version/evidence |

## Documentation freshness (0 healthy, 100 stale/misleading)

- Compresser **85/100**: guarantees/API invented or unproven; 18 historical tests
  cover happy paths, not safety/fidelity contracts.
- Termdash **65/100**: new API undocumented and width promise unimplemented;
  old handoff retains historical49-test loading state.
- MangaDL **65/100**: compression default/filter/recovery promises inaccurate;
  primary README omits command; exposed shim stale.
- Plans **85/100**: completion claims contradicted by source. Reopened S5–S8;
  docs correction is an explicit implementation gate, not cosmetic cleanup.

Historical dispatcher evidence does show compresser18 tests and MangaDL PASS.
It cannot validate untested guarantees. No new test results claimed in this review.

## User folder report, inspected read-only

`B:\Hent\hent1imageperpage\mangadl-folder-audit-report.json`: 1,098 folders,
3 complete,17 incomplete,1,078 unknown;157 ambiguous identities. All17 incomplete
have no source URL/expected count, numbering gaps, no corrupt files or duplicates;
14 also ambiguous. Formatter returns early for ambiguous and hides gap findings.
These are inferred sequence gaps, NOT source-confirmed missing pages.

AMBIGUOUS currently means multiple canonical candidates extracted from recursive
JSON strings (possibly unrelated links). UNKNOWN means insufficient source/count
evidence. Identity and completeness are independent and counts overlap.
Batch repair currently supports URL-file reports and proven exact page identities.

## Primary sources checked

- [Pillow formats](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html):
  WebP exact preserves transparent RGB; AVIF quality isn't losslessness; metadata
  needs explicit save options.
- [libjpeg-turbo usage](https://raw.githubusercontent.com/libjpeg-turbo/libjpeg-turbo/main/doc/usage.txt):
  original coefficients, portable -outfile, -copy all.
- [cwebp](https://developers.google.com/speed/webp/docs/cwebp): metadata default none.

No bulk/live library mutation, compression or binary installs performed.
