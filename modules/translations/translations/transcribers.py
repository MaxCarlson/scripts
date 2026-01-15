"""Transcriber registry abstraction."""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import TranscriberConfig, JAPANESE_PRIORITY_MODELS
from .utils import run_ffmpeg_extract_audio

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str
    language: str


@dataclass(slots=True)
class TranscriptionResult:
    source: Path
    language: str
    confidence: float
    text: str
    segments: List[Segment]


class BaseTranscriber(abc.ABC):
    name: str

    def __init__(self, cfg: TranscriberConfig):
        self.cfg = cfg

    @abc.abstractmethod
    def transcribe(self, media_path: Path) -> TranscriptionResult:
        raise NotImplementedError


class FasterWhisperTranscriber(BaseTranscriber):
    name = "faster-whisper"

    def __init__(self, cfg: TranscriberConfig):
        super().__init__(cfg)
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "faster-whisper is not installed. Install translations[gpu]"
            ) from exc
        device = "cuda" if self._has_cuda() else "cpu"
        compute_type = "float16" if device == "cuda" else "float32"
        self.model = WhisperModel(cfg.model_size, device=device, compute_type=compute_type)

    @staticmethod
    def _has_cuda() -> bool:
        try:
            import torch  # type: ignore

            return torch.cuda.is_available()  # pragma: no cover
        except Exception:  # pragma: no cover
            return False

    def transcribe(self, media_path: Path) -> TranscriptionResult:
        audio = run_ffmpeg_extract_audio(media_path, media_path.parent)
        segments_iter, info = self.model.transcribe(
            str(audio),
            language=self.cfg.language,
            vad_filter=self.cfg.use_vad,
            best_of=self.cfg.best_of,
            initial_prompt=self.cfg.initial_prompt,
            temperature=self.cfg.temperature,
            word_timestamps=False,
        )
        segments: List[Segment] = []
        text_parts: List[str] = []
        for seg in segments_iter:
            text_parts.append(seg.text.strip())
            segments.append(
                Segment(
                    start=float(seg.start),
                    end=float(seg.end),
                    text=seg.text.strip(),
                    language=info.language,
                )
            )
        return TranscriptionResult(
            source=media_path,
            language=info.language,
            confidence=info.language_probability,
            text="\n".join(text_parts).strip(),
            segments=segments,
        )


class OpenAIWhisperTranscriber(BaseTranscriber):
    name = "openai-whisper"

    def __init__(self, cfg: TranscriberConfig):
        super().__init__(cfg)
        try:
            import openai  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("openai package missing; install translations[openai]") from exc
        self.openai = openai

    def transcribe(self, media_path: Path) -> TranscriptionResult:
        audio = run_ffmpeg_extract_audio(media_path, media_path.parent)
        with open(audio, "rb") as handle:
            resp = self.openai.audio.transcriptions.create(
                model=self.cfg.model_size,
                file=handle,
                response_format="verbose_json",
            )
        segments = [
            Segment(start=s["start"], end=s["end"], text=s["text"], language=resp.language)
            for s in resp.segments
        ]
        return TranscriptionResult(
            source=media_path,
            language=resp.language,
            confidence=resp.language_probability,
            text="\n".join(seg.text for seg in segments),
            segments=segments,
        )


class DummyTranscriber(BaseTranscriber):
    name = "dummy"

    def transcribe(self, media_path: Path) -> TranscriptionResult:
        logger.warning("DummyTranscriber used; returning placeholder text")
        dummy_segment = Segment(0.0, 1.0, "Transcription unavailable", "und")
        return TranscriptionResult(
            source=media_path,
            language=self.cfg.language or "und",
            confidence=0.0,
            text=dummy_segment.text,
            segments=[dummy_segment],
        )


TRANSCIBERS: Dict[str, type[BaseTranscriber]] = {
    FasterWhisperTranscriber.name: FasterWhisperTranscriber,
    OpenAIWhisperTranscriber.name: OpenAIWhisperTranscriber,
    DummyTranscriber.name: DummyTranscriber,
}


def get_transcriber(cfg: TranscriberConfig) -> BaseTranscriber:
    # Prioritize JP-specific model if requested and unspecified
    if cfg.language in {"ja", "jp"} and cfg.model_size == "large-v3":
        cfg = TranscriberConfig(**{**cfg.__dict__, "model_size": JAPANESE_PRIORITY_MODELS[0]})
    cls = TRANSCIBERS.get(cfg.name)
    if not cls:
        raise KeyError(f"Unknown transcriber '{cfg.name}'")
    return cls(cfg)


def available_transcribers() -> Iterable[str]:
    return TRANSCIBERS.keys()
