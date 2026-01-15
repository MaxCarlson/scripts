# translations

Media-focused transcription + translation toolkit with CLI utilities for renaming, dedupe metadata, and localized search.

## Features

* **Audio extraction + transcription** using pluggable engines (Faster-Whisper, OpenAI Whisper, WebRTC VAD + diarization).
* **Multi-target translation** with language-aware adapters (DeepL, HuggingFace, custom glossary rules) plus Japanese-optimized presets.
* **Safe naming + dedupe metadata** – generate Windows-safe filenames, SRT/VTT files, and JSON fingerprints for vdEdUle/video dedupe flows.
* **Catalog storage**: structured NDJSON log for later reuse/search.
* **CLI-first workflow** with `translations pipeline`, `translations transcribe`, `translations translate`, and `translations catalog` commands.

## Quick start

```bash
pip install -e .[gpu,translate]
translations pipeline \
  --source D:\Pictures\Saved\videos\sample.mp4 \
  --target-lang en ja \
  --tmp-dir D:\tmp\audio \
  --translator deepl \
  --catalog catalogs/translations.ndjson
```

See `translations --help` for sub-command details.
