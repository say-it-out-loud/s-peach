"""KittenTTS backend — parameterized for multiple model sizes."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
import structlog

from s_peach.config import Settings
from s_peach.models.base import VoiceInfo

logger = structlog.get_logger()

_SAMPLE_RATE = 24000


class KittenTTSModel:
    """KittenTTS backend implementing the TTSModel protocol.

    Parameterized by model_id (HuggingFace repo) and model_name
    (user-facing name). Supports kitten-mini, kitten-micro, kitten-nano.
    """

    def __init__(
        self,
        settings: Settings,
        model_id: str,
        model_name: str,
    ) -> None:
        self._settings = settings
        self._model_id = model_id
        self._model_name = model_name
        self._model: Any | None = None
        self._lock = threading.Lock()
        self._voice_map: dict[str, str] = settings.voices.get("kitten", {})
        self._kitten_cfg = settings.kitten

    def speak(self, text: str, voice: str, **kwargs: Any) -> tuple[np.ndarray, int]:
        """Generate audio. Blocks until complete or timeout.

        Auto-loads the model if not loaded. Must be called from a thread
        (the server uses asyncio.to_thread).
        """
        self._ensure_loaded()

        timeout = self._settings.tts_timeout
        result: list[np.ndarray | None] = [None]
        error: list[BaseException | None] = [None]

        def _generate() -> None:
            try:
                speed = kwargs.get("speed", self._kitten_cfg.speed)
                result[0] = self._model.generate(text, voice=voice, speed=speed)
            except Exception as e:
                error[0] = e

        gen_thread = threading.Thread(target=_generate, daemon=True)
        gen_thread.start()
        gen_thread.join(timeout=timeout)

        if gen_thread.is_alive():
            logger.error("tts_generation_timeout", model=self._model_name, timeout=timeout, text_len=len(text))
            raise TimeoutError(
                f"TTS generation timed out after {timeout}s"
            )

        if error[0] is not None:
            raise error[0]

        audio = result[0]
        if audio is None:
            raise RuntimeError("TTS generation returned None")

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
        """Kitten models do not support language switching."""
        return []

    def name(self) -> str:
        return self._model_name

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load the KittenTTS model into memory."""
        with self._lock:
            if self._model is not None:
                return
            logger.debug("model_loading", model=self._model_name, model_id=self._model_id)
            try:
                from kittentts import KittenTTS

                self._model = KittenTTS(self._model_id)
                logger.debug("model_loaded", model=self._model_name)
            except Exception:
                logger.exception("model_load_failed", model=self._model_name)
                raise

    def unload(self) -> None:
        """Unload the model from memory."""
        with self._lock:
            if self._model is None:
                return
            logger.debug("model_unloading", model=self._model_name)
            self._model = None
            logger.debug("model_unloaded", model=self._model_name)

    def _ensure_loaded(self) -> None:
        """Load the model if not already loaded."""
        if self._model is None:
            self.load()
