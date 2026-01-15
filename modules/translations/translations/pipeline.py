"""Pipeline orchestration."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from .catalog import CatalogEntry, TranslationCatalog
from .config import PipelineConfig, TranscriberConfig, TranslatorConfig
from .transcribers import Segment, TranscriptionResult, get_transcriber
from .translators import TranslationResult, TranslationUnit, get_translator
from .utils import fingerprint_text, safe_filename, write_json


@dataclass(slots=True)
class PipelineArtifact:
    source: Path
    transcription: TranscriptionResult
    translations: Dict[str, TranslationResult]
    safe_title: str


def suggest_safe_title(text: str, target_lang: str) -> str:
    return f"{target_lang}_{safe_filename(text.strip())}"[:180]


def translate_segments(
    transcription: TranscriptionResult,
    translator_cfg: TranslatorConfig,
) -> Dict[str, TranslationResult]:
    units = [TranslationUnit(text=s.text, source_language=transcription.language) for s in transcription.segments]
    results: Dict[str, TranslationResult] = {}
    for lang in translator_cfg.target_languages:
        cfg = TranslatorConfig(**{**translator_cfg.__dict__, "target_languages": [lang]})
        translator = get_translator(cfg)
        translated = translator.translate(units)
        results[lang] = translated
    return results


def export_subtitles(artifact: PipelineArtifact, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for lang, translation in artifact.translations.items():
        srt_path = out_dir / f"{artifact.safe_title}.{lang}.srt"
        lines = []
        for idx, segment in enumerate(artifact.transcription.segments, start=1):
            text = translation.lines[idx - 1] if idx - 1 < len(translation.lines) else segment.text
            lines.append(str(idx))
            lines.append(_format_ts(segment.start, segment.end))
            lines.append(text)
            lines.append("")
        srt_path.write_text("\n".join(lines), encoding="utf-8")


def _format_ts(start: float, end: float) -> str:
    return f"{_seconds_to_srt(start)} --> {_seconds_to_srt(end)}"


def _seconds_to_srt(value: float) -> str:
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    seconds = int(value % 60)
    millis = int((value - int(value)) * 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def run_pipeline(cfg: PipelineConfig) -> List[PipelineArtifact]:
    artifacts: List[PipelineArtifact] = []
    catalog = TranslationCatalog(cfg.catalog_path, None) if cfg.catalog_path else None
    transcriber = get_transcriber(cfg.transcriber)
    for source in cfg.iter_sources():
        transcription = transcriber.transcribe(source)
        translations = translate_segments(transcription, cfg.translator)
        safe_title = suggest_safe_title(transcription.segments[0].text, cfg.translator.target_languages[0]) if transcription.segments else safe_filename(source.stem)
        artifact = PipelineArtifact(
            source=source,
            transcription=transcription,
            translations=translations,
            safe_title=safe_title,
        )
        _persist_outputs(cfg, artifact, catalog)
        artifacts.append(artifact)
    return artifacts


def _persist_outputs(cfg: PipelineConfig, artifact: PipelineArtifact, catalog: TranslationCatalog | None) -> None:
    base_dir = artifact.source.parent if cfg.write_safe_titles else cfg.tmp_dir
    out_dir = base_dir / artifact.safe_title
    if cfg.export_srt:
        export_subtitles(artifact, out_dir)
    if cfg.export_json:
        payload = {
            "source": str(artifact.source),
            "language": artifact.transcription.language,
            "segments": [
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                    "language": seg.language,
                }
                for seg in artifact.transcription.segments
            ],
            "translations": {
                lang: res.lines for lang, res in artifact.translations.items()
            },
        }
        write_json(out_dir / "translation.json", payload)
    if catalog:
        for lang, res in artifact.translations.items():
            fingerprint = fingerprint_text(res.join(), catalog.cfg.hash_algorithm)
            entry = CatalogEntry(
                fingerprint=fingerprint,
                source=str(artifact.source),
                language=artifact.transcription.language,
                target_language=lang,
                text=res.join(),
                safe_title=artifact.safe_title,
                metadata={"segments": len(res.lines)},
            )
            catalog.add(entry)
