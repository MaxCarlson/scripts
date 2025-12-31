# Video Dataset Tools

Generate reproducible video datasets with deterministic and randomized variants, truth manifests, and optional live terminal dashboards.

## Features
- Deterministic trims, scales, bitrate tweaks, container changes, and copies.
- Randomized overlapping variants with seed control and overlap probability.
- CPU and CUDA (NVENC) ffmpeg modes with per-process thread control.
- Safety toggles: dry-run and explicit confirm flag.
- Truth manifest (`truth.json`) plus mapping/id map helpers.
- Optional live TermDash UI (`-d/--ui`) showing keys, downloads, variants, errors, and throughput.

## Installation
From the repo root:

```bash
python -m pip install -e modules/video_dataset_tools
```

Requirements:
- Python 3.9+
- ffmpeg available on PATH (CUDA mode also requires NVIDIA drivers + NVENC)
- yt-dlp available on PATH
- For TermDash UI: `modules/termdash` is bundled; no extra install needed.

## CLI Usage
```
vdt [options]   # short alias (installed entry point)
video-dataset-tools [options]  # legacy alias
```
Key flags (short/long required per project guidelines):
- `-m/--mapping-file` Text file with one key per line.
- `-i/--id-map` JSON map of key -> YouTube ID/URL.
- `-u/--urls-file` URLs file; auto-creates mapping/id map (use with `-M/--num-masters`).
- `-Z/--auto-urls` Auto-discover N YouTube URLs via yt-dlp search (seeded, no URLs file needed).
- `-M/--num-masters` Number of masters to select in urls-file mode (default 3).
  - When using `-Z/--auto-urls`, `-M` is automatically set to the same value.
- `-o/--output-dir` Destination root (default `data`).
- `-s/--skip-download` Reuse existing originals; do not run yt-dlp.
- `-t/--truth-file` Optional explicit manifest path.
- `-r/--trim` Extra trim spec `start:duration` or `name:start:duration` (repeatable).
- `-S/--seed` Seed for random variants and URL shuffling.
- `-R/--min-random-variants` Minimum randomized variants per master (default 2).
- `-X/--max-random-variants` Maximum randomized variants per master (default 5).
- `-p/--overlap-prob` Probability of forcing overlapping manipulations (default 0.65).
- `-f/--flat-layout` Put variants directly under `variants/` instead of per-key folders.
- `-w/--mapping-out` Where to write generated mapping file (urls mode).
- `-j/--id-map-out` Where to write generated id map (urls mode).
- `-g/--mode` `cpu` or `cuda` (NVENC) ffmpeg encoding.
- `-J/--workers` Concurrent download/variant workers (default CPU count).
- `-T/--ffmpeg-threads` Threads per ffmpeg process (None = ffmpeg default).
- `-U/--max-mem-gb` Soft memory cap; reduces worker count (cap/2 heuristic).
- `-L/--log-level` Logging verbosity.
- `-n/--dry-run` Plan only; no yt-dlp or ffmpeg.
- `-y/--confirm` Required safety latch to run non-dry runs.
- `--shuffle-urls` Shuffle URLs before picking masters.
- `--no-random` Disable randomized variants.
- `-d/--ui` Show live TermDash dashboard during processing.

## Examples
- Auto-discover 100 random YouTube videos (seeded), heavier randomized variants, CUDA + dashboard:
  ```bash
  vdt -Z 100 -S 42 -R 3 -X 6 -p 0.65 -g cuda -J 4 -d -y
  ```

- Pick 20 masters deterministically from a URLs file (seeded), CUDA, 4 workers:
  ```bash
  vdt -u urls.txt -M 20 -S 123 -g cuda -J 4 -y
  ```
- Same but shuffle URLs before selecting, with more randomized variants (3–6 each, overlap 0.7):
  ```bash
  vdt -u urls.txt -M 20 -S 123 --shuffle-urls -R 3 -X 6 -p 0.7 -y
  ```
- Flat layout, capped ffmpeg threads, live dashboard:
  ```bash
  vdt -u urls.txt -M 10 -f -T 4 -d -y
  ```
- Reuse downloaded masters, add an extra trim, disable random variants:
  ```bash
  vdt -m mapping.txt -i id_map.json -s -r 10:30 --no-random -y
  ```

## Randomized Variants
- Controlled by `RandomPlan(seed, min_variants, max_variants, overlap_prob)`.
- Seeded per-key for reproducibility; overlap probability encourages multi-manipulation outputs.
- Includes possible trims, scaling, audio removal/bitrate, video bitrate/CRF. All outputs are MP4.

## Outputs
- `original/` downloaded masters (`<key>.<ext>`).
- `variants/` deterministic variants (per-key subfolders unless `-f/--flat-layout`).
- `truth.json` manifest mapping each key to original and all variant paths.
- Optional `mapping.txt` and `id_map.json` when using `--urls-file` workflow.

## TermDash UI
- Enable with `-d/--ui` in a TTY. Shows keys started/total, downloads, deterministic + random variant counts, errors, throughput, and elapsed time.
- UI shuts down cleanly when processing completes; falls back to logging if TermDash is unavailable.

## Development & Testing
- Format: `black --line-length 120 modules/video_dataset_tools`
- Lint: `ruff check modules/video_dataset_tools`
- Tests: `pytest modules/video_dataset_tools/tests -v`
- Coverage goal: ~100% across transformations and dataset logic. Tests mock yt-dlp/ffmpeg to avoid external calls.

## GPU vs CPU
- `-g cuda` enables NVENC (`h264_nvenc`) with CUDA hwaccel; ensure drivers + ffmpeg NVENC build are available.
- `-g cpu` uses libx264. `-T/--ffmpeg-threads` caps ffmpeg worker threads in either mode.

## Safety Toggles
- `-n/--dry-run` avoids any downloads or ffmpeg work.
- `-y/--confirm` is required for real runs to prevent accidental execution.
