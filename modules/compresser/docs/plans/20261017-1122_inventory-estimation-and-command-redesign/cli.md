# Proposed canonical compression CLI

Target syntax, not yet installed. Native execution authorized; see
[execution-review.md](execution-review.md) for capability/default/provenance decisions
and model escalation gates. No backwards compatibility layer.

## Operation tree

```text
mangadl compress inventory   # enumerate and save population; no encodes
mangadl compress plan        # create/view estimation plan; no encodes
mangadl compress estimate    # execute/resume bounded statistical estimation
mangadl compress analyze     # exact measurements, one recipe, all or explicit sample
mangadl compress compare     # explicit benchmark, selected recipes, all or explicit sample
mangadl compress preview     # external full-resolution image copies
mangadl compress apply       # guarded source mutation, exact recipe, requires --write
mangadl compress recover     # recovery preview, --write plus exact token applies
```

Standalone: `compresser <operation>`, same options except `-i/--input` replaces
MangaDL `-d/--destination`; MangaDL alone retains repeatable exact `-u/--url` filters.
Bare command prints operation help, does not scan. Target/options follow the operation;
do not implement options-before-operation parsing. Top help lists operations/common
concepts; each operation help shows only applicable groups. `compare` is explicit
benchmarking; `estimate` is the normal library savings workflow.

## Option ownership

Every option has a short and long spelling. Shared options are defined once in
`arguments.py`; effective defaults are operation-specific and explicit in help.

| Operations | Options |
| --- | --- |
| All | MangaDL `-d/--destination`, standalone `-i/--input`; `-J/--json`; `-N/--no-ui`; `-v/--verbose` |
| All except recover | `-I/--workspace` (parent directory) |
| Inventory/plan/estimate/analyze/compare/preview/apply | MangaDL `-u/--url` (repeatable exact selection); recovery rejects filters |
| Inventory only | `-D/--depth files\|headers` (default headers), `-t/--threads` |
| Plan/estimate | `-f/--format FORMAT [FORMAT ...]`, `-m/--mode lossless\|lossy\|perceptual`, `-q/--quality Q [Q ...]`, `-p/--perceptual-target`, `-A/--encoder`, `-e/--effort`, `-z/--seed`, `-s/--max-images`, `-T/--max-trials`, `-M/--max-time`, `-a/--accuracy-pp` |
| Plan only | `-r/--plan ID` optionally views existing matching plan; otherwise create and print ID |
| Estimate only | `-r/--plan ID` executes/resumes compatible plan; explicit conflicting recipe/scope/seed fails; resource flags provide additional run allowances |
| Estimate/analyze/compare/preview/apply | `-t/--threads`, `-B/--memory-budget`, `-k/--cache use\|refresh\|off`, `-K/--cache-file` advanced override |
| Estimate/analyze/compare | `-X/--scratch-dir` advanced read-only staging |
| Analyze/compare | `-s/--sample N\|p%\|all` (default all), `-z/--seed`; library-wide format/size random design |
| Analyze/apply | Single `-f/--format`, `-m/--mode`, single `-q/--quality`, `-p/--perceptual-target`, `-A/--encoder`, `-e/--effort` |
| Compare | `-f/--format FORMAT [FORMAT ...]` required, `-m/--mode lossless\|lossy\|perceptual\|both`, `-q/--quality Q [Q ...]`, `-p/--perceptual-target`, `-A/--encoder`, `-e/--effort` |
| Analyze/compare/preview/apply | `-U/--inventory-policy refresh\|snapshot` (default refresh); snapshot read-only only, forbidden for apply/preview |
| Preview | `-n/--count` default 3, `-q/--quality Q [Q ...]` default 90 80, `-f/--format FORMAT [FORMAT ...]` default webp, `-A/--encoder`, `-e/--effort`, `-O/--output` optional external override; lossless baseline included |
| Apply | `-w/--write` required, `-L/--allow-lossy` required for lossy/perceptual, `-F/--allow-larger` |
| Analyze/compare | `-F/--allow-larger` estimates signed replacement outcomes |
| Plan/estimate | `-F/--allow-larger` permits fixed-mode signed estimates; incompatible with certified accuracy target |
| Recover | `-w/--write`, `-C/--confirm TOKEN` required together to apply; omitted write previews; no sampling/encoder/resource flags |
| Standalone root | `-V/--version`; MangaDL keeps its existing global version handling |

Q accepts integer 1..100 or exact decimal fractions (0.85 -> 85), deduplicated in
input order. Do not accept arbitrary fractional percentages that the backend rounds
silently. Explicit quality is rejected with lossless-only mode; lossless recipe identity
uses codec compression effort rather than pretending quality is comparable across codecs.
Combined comparison applies q only to its lossy recipes. `plan/estimate` defaults one
WebP lossless recipe; lossy omitted q defaults 80. For multiple formats, validate every
requested combination; do not silently introduce/remove formats or reinterpret PNG lossy.
Perceptual mode keeps current SSIM target contract and budgets every internal encode.

Inventory refresh is its own explicit operation for plan/estimate. Existing completed
inventory required; snapshot staleness is disclosed and selected fingerprints checked.
Plan-only does not open trial DB or image files. No `--plan-only`, `--resume` or
`--sample-pool` flag: the operation and `--plan ID` supply those functions. No rounds
flag initially; bounded rounds are a controller detail. Preserve richer internal APIs.

## Old surface audit and replacement

| Existing option(s) | Decision |
| --- | --- |
| `-l/--inventory-only`, `-D/--inventory-depth` | Replace with `inventory -D/--depth`; remove operation flag |
| `-c/--compare`, `-b/--compare-both` | Replace with `compare -m both`; no flat comparison flags |
| `-O/--preview-dir`, `-n/--preview-count` | Replace with `preview`, optional `-O/--output`, `-n/--count` |
| `-R/--recover`, `-C/--confirm-recovery` | Replace with `recover`, `-C/--confirm`; retain write/token safeguards |
| `-q`, `-Q/--qualities/--preview-qualities` | One `-q/--quality` list parser, cardinality depends on operation |
| `-s`, `-P/--sample-percent` | One explicit `--sample N\|p%\|all` in exact operations; estimate has `--max-images`, not a percentage or misleading auto heuristic |
| `-A/--algorithm` | Rename long form to `--encoder`; format and encoder remain distinct |
| `-B/--memory-budget-mib` | Rename long form to `--memory-budget`; retain current units/percentage/auto parser and limits |
| `-k/--cache-policy` | Rename long form to `--cache`; keep actual policies and diagnostics |
| `-I/--workspace`, hidden `--inventory-file` | Keep workspace parent only; remove file-path detection/legacy warning/alias |
| Standalone `-o/--output-dir` | Remove rejected placeholder; do not repurpose lowercase `-o` |
| `-U/--inventory-policy trust` | Name explicit saved snapshot policy `snapshot`; no compatibility alias |
| `-w/-L/-F` | Keep only where meaningful; independent destructive policies are not redundant |
| `-f/-m/-p/-e/-t/-K/-X/-N/-J/-v`, MangaDL `-d/-u`, standalone `-i` | Preserve capabilities in applicable operation help; reject ignored options |

Do not add convenience aliases for removed spellings. Reserve short letters per
operation; `-s` may mean sample vs maximum images because each operation owns its help.
No safety decision inferred from an operation name alone: `apply` still requires `-w`.
No implicit new broad all-formats comparison. Invalid syntax fails before any artifacts.

## Proposed examples (not current commands)

```powershell
mangadl compress inventory -d 'B:\Hent\hent1imageperpage' -I 'B:\Hent' -D files
mangadl compress plan -d 'B:\Hent\hent1imageperpage' -I 'B:\Hent' -m lossy -f webp avif -q 75 85 -s 512 -T 2000 -M 5m
mangadl compress estimate -d 'B:\Hent\hent1imageperpage' -I 'B:\Hent' -r PLAN_ID -M 10m
mangadl compress estimate -d 'B:\Hent\hent1imageperpage' -I 'B:\Hent' -m lossy -f webp -q 85 -a 1 -M 10m
mangadl compress preview -d 'B:\Hent\hent1imageperpage' -I 'B:\Hent' -f webp -q 85 90 -n 3
mangadl compress recover -d 'B:\Hent\hent1imageperpage'
```

The user's old `compress -d ... -I ... -l` is replaced by the first inventory form
(omit `-D files` for its former header default), producing the requested hidden-container
workspace. No command shown here should be run on B: during implementation validation.
