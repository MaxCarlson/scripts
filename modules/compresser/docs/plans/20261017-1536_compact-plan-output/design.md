# Compact compression plan output

Approved direction: the in-chat mock followed by the user's request for an
implementation plan. Applies to standalone compresser and MangaDL plan output.

## Outcome

Make the default plan report easy to scan: target, saved population, recipes,
limits, actual pilot, relevant warnings and one report path. Existing detailed
report data remains accessible through verbose output, Markdown and JSON.

## Default presentation

```text
Compression plan saved · hent1imageperpage

66,233 images · 12 recipes · 11 groups covered
Inventory: headers · saved 2h 6m ago

Limits   200 images · 750 new encodes · 15 min active time
Pilot    62 shared images across 12 recipes

Format   Lossless   Lossy qualities
AUTO     Yes        85, 70
WebP     Yes        85, 70
JPEG     Yes*       85, 70
AVIF     —          85, 70
PNG      Yes        —

* JPEG lossless requires jpegtran and JPEG source images.

WARNING: Encode budget is tight: the pilot schedules 744 image/recipe
measurements. AUTO may need multiple encodes per measurement;
cached results may reduce new encodes.

Plan     plan-60b15df8fb2aa29c2c22
Report   B:\Hent\.mangadl\hent1imageperpage\reports\latest.md

Planning only; no images encoded.
```

Use the existing bordered TermDash table style for the five format rows. No
full hashes, strata, quota panels, repeated context table or trailing COMPLETED
banner in default output. Only one Report path is printed, after publication.

## Facts and non-default requests

- Derive counts from the saved plan: shared pilot is len(pilot_member_ids), pilot
  measurements are sum(quota.total), covered groups exclude coverage_gaps. Never
  show the configured pilot ceiling as an actual allocation.
- Group formats in registered order, case-normalized display names; deduplicate
  qualities in registered order. A dash means no requested recipe in that cell,
  not that the codec universally lacks that capability. Use Yes* only for a
  requested JPEG lossless recipe, with the conditional requirement footnote.
- Add a Perceptual target column only when requested; show actual targets such as
  SSIM ≥ 0.990. Do not label perceptual recipes as lossless because quality is null.
- Show nonempty selection filters, requested accuracy target (as a goal, not an
  achieved/certified result), allow-larger policy, non-default encoder/effort, and
  distinct per-recipe encoder/effort variants. Never collapse different settings
  into an apparently identical recipe. Default auto encoder/effort6 is omitted.
- File-depth inventory is labelled unverified. Coverage gaps are explicit warnings;
  never print all groups covered if a gap exists. A future timestamp clamps age to0.
- Emit the tight-budget warning when nominal pilot measurements reach at least
  80% of max_new_encodes. This is a planning heuristic, not a runtime forecast:
  describe cache reuse and AUTO child encodes, without promising the pilot will fit.
  Omit the AUTO sentence if no AUTO recipe is registered.
- Keep snapshot loading's existing status line; this work changes the final report.

## Presentation and compatibility

Reuse TermDash wrapping, visible-width measurement and cyan/yellow conventions.
At widths40/80/120/160, preserve values and paths through wrapping, without overflow
or ellipses. Respect NO_COLOR, non-TTY output and redirected stdout; no ANSI leakage.

The full structured report and Markdown retain identities, strata, per-group quotas,
context and settings. Correct their pilot label to distinguish ceiling from actual
allocation. JSON retains its existing keys and full plan; no saved-plan schema,
recipe identity, quota, numerical, budget-admission or estimation execution changes.

Default plan rendering prints the compact view. `-v` keeps detailed console output.
`-J` remains pure JSON stdout with existing artifact metadata. Publication errors
remain visible and produce failure status; never print a nonexistent Report path.
Other operation renderers and their preservation fixtures are unchanged.

Implementation is confined to report presentation/lifecycle, tests and release docs.
Compresser/MangaDL3.2.0 is the planned feature version (current baseline3.1.1);
MangaDL requires compresser>=3.2.0. No dependencies or CLI flags are added.
Production Hent inventory/plans/images are not execution fixtures. Windows visual
review at80/120/160 columns remains a manual acceptance gate.
