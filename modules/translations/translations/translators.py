"""Translation engines with registry."""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

from .config import TranslatorConfig
from .utils import normalize_whitespace

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TranslationUnit:
    text: str
    source_language: str


@dataclass(slots=True)
class TranslationResult:
    target_language: str
    lines: List[str]

    def join(self) -> str:
        return "\n".join(self.lines)


class BaseTranslator(abc.ABC):
    name: str

    def __init__(self, cfg: TranslatorConfig):
        self.cfg = cfg

    @abc.abstractmethod
    def translate(self, units: Sequence[TranslationUnit]) -> TranslationResult:
        raise NotImplementedError


class DeepLTranslator(BaseTranslator):
    name = "deepl"

    def __init__(self, cfg: TranslatorConfig):
        super().__init__(cfg)
        try:
            import deepl  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dep
            raise RuntimeError("deepl package missing; install deepl or set DEEPL_AUTH_KEY") from exc
        self.client = deepl.Translator.from_env()

    def translate(self, units: Sequence[TranslationUnit]) -> TranslationResult:
        text = [unit.text for unit in units]
        resp = self.client.translate_text(text, target_lang=self.cfg.target_languages[0].upper())
        translated = [normalize_whitespace(entry.text) for entry in resp]
        return TranslationResult(target_language=self.cfg.target_languages[0], lines=translated)


class HFTranslator(BaseTranslator):
    name = "hf"

    def __init__(self, cfg: TranslatorConfig):
        super().__init__(cfg)
        try:
            from transformers import pipeline  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("transformers missing; install translations[translate]") from exc
        model = "facebook/nllb-200-distilled-600M"
        self.pipe = pipeline("translation", model=model, device="cuda" if self._has_cuda() else "cpu")

    @staticmethod
    def _has_cuda() -> bool:
        try:
            import torch

            return torch.cuda.is_available()  # pragma: no cover
        except Exception:
            return False

    def translate(self, units: Sequence[TranslationUnit]) -> TranslationResult:
        outputs = self.pipe([u.text for u in units], src_lang=units[0].source_language, tgt_lang=self.cfg.target_languages[0])
        translated = [normalize_whitespace(out["translation_text"]) for out in outputs]
        return TranslationResult(target_language=self.cfg.target_languages[0], lines=translated)


class SimpleRuleTranslator(BaseTranslator):
    name = "simple"

    def translate(self, units: Sequence[TranslationUnit]) -> TranslationResult:
        logger.warning("Using fallback SimpleRuleTranslator; results may be poor")
        translated = [normalize_whitespace(u.text) for u in units]
        return TranslationResult(target_language=self.cfg.target_languages[0], lines=translated)


TRANSLATORS: Dict[str, type[BaseTranslator]] = {
    DeepLTranslator.name: DeepLTranslator,
    HFTranslator.name: HFTranslator,
    SimpleRuleTranslator.name: SimpleRuleTranslator,
}


def get_translator(cfg: TranslatorConfig) -> BaseTranslator:
    cls = TRANSLATORS.get(cfg.name)
    if not cls:
        raise KeyError(f"Unknown translator '{cfg.name}'")
    return cls(cfg)


def available_translators() -> Iterable[str]:
    return TRANSLATORS.keys()
