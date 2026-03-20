"""TTSModel protocol — all TTS backends implement this."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class VoiceInfo:
    """Metadata for a single voice."""

    name: str
    native_id: str
    description: str = ""


@runtime_checkable
class TTSModel(Protocol):
    """Protocol for TTS model backends."""

    def speak(self, text: str, voice: str, **kwargs: Any) -> tuple[np.ndarray, int]:
        """Generate audio for the given text and voice.

        Args:
            text: Text to synthesize.
            voice: Native voice ID for this model.
            **kwargs: Optional model-specific params (exaggeration, cfg_weight).
                      Backends that don't support them silently ignore.

        Returns:
            Tuple of (audio_array, sample_rate).

        Raises:
            TimeoutError: If generation exceeds the configured timeout.
        """
        ...

    def voices(self) -> list[VoiceInfo]:
        """Return available voices for this model."""
        ...

    def name(self) -> str:
        """Return the model's identifier (e.g. 'kitten')."""
        ...

    def is_loaded(self) -> bool:
        """Return True if the model is currently loaded in memory."""
        ...

    def load(self) -> None:
        """Load the model into memory."""
        ...

    def unload(self) -> None:
        """Unload the model from memory."""
        ...

    def languages(self) -> list[str]:
        """Return supported ISO 639-1 language codes.

        Returns an empty list for models that do not support language selection
        (e.g. kitten variants).
        """
        return []
