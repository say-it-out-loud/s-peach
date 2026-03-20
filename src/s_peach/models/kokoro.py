"""Kokoro-82M TTS backend — lightweight, multi-language, generator-based."""

from __future__ import annotations

import threading
import warnings
from typing import Any

import numpy as np
import structlog

from s_peach.config import Settings
from s_peach.models.base import VoiceInfo

logger = structlog.get_logger()

_SAMPLE_RATE = 24000

# Maps ISO 639-1 language codes to Kokoro internal lang_code characters.
KOKORO_LANG_MAP: dict[str, str] = {
    "en": "a",  # American English
    "gb": "b",  # British English
    "ja": "j",  # Japanese
    "zh": "z",  # Mandarin Chinese
    "es": "e",  # Spanish
    "fr": "f",  # French
    "hi": "h",  # Hindi
    "it": "i",  # Italian
    "pt": "p",  # Portuguese (Brazilian)
}


class KokoroTTSModel:
    """Kokoro-82M backend implementing the TTSModel protocol.

    Uses kokoro.KPipeline with a generator-based API — iterates to get
    audio chunks, concatenates into a single ndarray.

    Supports per-language pipeline caching: pipelines are created on first
    use for each language and reused thereafter.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pipelines: dict[str, Any] = {}  # lang_code -> KPipeline
        self._lock = threading.Lock()
        self._voice_map: dict[str, str] = settings.voices.get("kokoro", {})
        self._kokoro_cfg = settings.kokoro

    def speak(self, text: str, voice: str, **kwargs: Any) -> tuple[np.ndarray, int]:
        """Generate audio. Blocks until complete or timeout.

        Auto-loads the model if not already loaded. Must be called from a thread
        (the server uses asyncio.to_thread).

        KPipeline is not thread-safe — the daemon thread pattern ensures
        only one generation runs at a time per call, and the server's
        asyncio.to_thread serializes calls through the worker queue.

        Args:
            text: Text to synthesize.
            voice: Native voice ID for this model.
            language: Optional ISO 639-1 language code (e.g. "en", "fr").
                      Overrides the configured default language.
            **kwargs: Additional model-specific params (speed).
        """
        lang_override = kwargs.get("language")
        if lang_override is not None:
            lang_code = KOKORO_LANG_MAP.get(lang_override)
            if lang_code is None:
                logger.warning(
                    "kokoro_unknown_language",
                    language=lang_override,
                    fallback=self._settings.language,
                )
                lang_code = KOKORO_LANG_MAP.get(self._settings.language, "a")
        else:
            lang_code = KOKORO_LANG_MAP.get(self._settings.language, "a")

        self._ensure_pipeline_loaded(lang_code)
        pipeline = self._pipelines[lang_code]

        timeout = self._settings.tts_timeout
        result: list[np.ndarray | None] = [None]
        error: list[BaseException | None] = [None]

        def _generate() -> None:
            try:
                chunks: list[np.ndarray] = []
                speed = kwargs.get("speed", self._kokoro_cfg.speed)
                generator = pipeline(text, voice=voice, speed=speed)
                for _graphemes, _phonemes, audio in generator:
                    if audio is not None:
                        chunks.append(audio)
                if not chunks:
                    raise RuntimeError(
                        "Kokoro generator yielded no audio chunks"
                    )
                result[0] = np.concatenate(chunks)
            except Exception as e:
                error[0] = e

        gen_thread = threading.Thread(target=_generate, daemon=True)
        gen_thread.start()
        gen_thread.join(timeout=timeout)

        if gen_thread.is_alive():
            logger.error(
                "tts_generation_timeout",
                model="kokoro",
                timeout=timeout,
                text_len=len(text),
            )
            raise TimeoutError(
                f"TTS generation timed out after {timeout}s"
            )

        if error[0] is not None:
            raise error[0]

        audio = result[0]
        if audio is None:
            raise RuntimeError("Kokoro TTS generation returned None")

        if not isinstance(audio, np.ndarray):
            audio = np.array(audio, dtype=np.float32)

        return audio, _SAMPLE_RATE

    def voices(self) -> list[VoiceInfo]:
        """Return voices from the config voice map."""
        return [
            VoiceInfo(name=friendly_name, native_id=native_id)
            for friendly_name, native_id in self._voice_map.items()
        ]

    def languages(self) -> list[str]:
        """Return supported ISO 639-1 language codes."""
        return list(KOKORO_LANG_MAP.keys())

    def name(self) -> str:
        return "kokoro"

    def is_loaded(self) -> bool:
        return bool(self._pipelines)

    def load(self) -> None:
        """Load the default Kokoro KPipeline into memory."""
        default_lang = self._settings.language
        lang_code = KOKORO_LANG_MAP.get(default_lang, "a")
        self._ensure_pipeline_loaded(lang_code)

    def unload(self) -> None:
        """Unload all cached pipelines from memory."""
        with self._lock:
            if not self._pipelines:
                return
            logger.debug("model_unloading", model="kokoro")
            self._pipelines.clear()
            logger.debug("model_unloaded", model="kokoro")

    def _ensure_loaded(self) -> None:
        """Load the model if not already loaded."""
        if not self._pipelines:
            self.load()

    def _ensure_pipeline_loaded(self, lang_code: str) -> None:
        """Load a KPipeline for the given lang_code if not already cached."""
        if lang_code in self._pipelines:
            return
        with self._lock:
            if lang_code in self._pipelines:
                return
            logger.debug("model_loading", model="kokoro", lang_code=lang_code)
            from s_peach._vendor import patch_spacy
            patch_spacy()
            try:
                from kokoro import KPipeline
            except ImportError:
                raise ImportError(
                    "kokoro is not installed. Run: uv sync"
                ) from None
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning)
                    warnings.filterwarnings("ignore", category=FutureWarning)
                    pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
                self._pipelines[lang_code] = pipeline
                logger.debug("model_loaded", model="kokoro", lang_code=lang_code)
            except SystemExit:
                # kokoro's misaki phonemizer calls spacy.cli.download() which
                # invokes pip. uv venvs don't include pip by default, causing
                # SystemExit(1). Pre-install the spaCy model first.
                raise RuntimeError(
                    "Kokoro failed to load — likely missing spaCy model. "
                    "Run: uv sync"
                ) from None
            except Exception:
                logger.exception("model_load_failed", model="kokoro")
                raise
