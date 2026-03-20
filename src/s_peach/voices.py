"""Voice registry — resolves voice names to (model, native_voice_id)."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from s_peach.config import Settings
from s_peach.models.base import TTSModel, VoiceInfo

logger = structlog.get_logger()


@dataclass(frozen=True)
class ResolvedVoice:
    """A voice resolved to its model and native ID."""

    model_name: str
    native_id: str
    friendly_name: str


class VoiceRegistry:
    """Resolves voice names to model backends and native IDs."""

    def __init__(self, settings: Settings, models: dict[str, TTSModel]) -> None:
        self._settings = settings
        self._models = models

    def resolve(self, voice_name: str, model_name: str) -> ResolvedVoice:
        """Resolve a voice name to a model and native ID.

        Args:
            voice_name: Friendly voice name (e.g. 'Heart').
            model_name: Model name (e.g. 'kokoro').

        Returns:
            ResolvedVoice with model_name, native_id, and friendly_name.

        Raises:
            KeyError: If voice_name is not found in the model's voice map.
        """
        # Kitten variants share a "kitten" voice map;
        # Chatterbox variants share a "chatterbox" voice map
        if model_name.startswith("kitten"):
            voice_key = "kitten"
        elif model_name.startswith("chatterbox"):
            voice_key = "chatterbox"
        else:
            voice_key = model_name
        voice_map = self._settings.voices.get(voice_key, {})

        if voice_name in voice_map:
            return ResolvedVoice(
                model_name=model_name,
                native_id=voice_map[voice_name],
                friendly_name=voice_name,
            )

        logger.warning(
            "voice_not_found",
            requested=voice_name,
            model=model_name,
            available=list(voice_map.keys())[:5],
        )
        raise KeyError(
            f"Voice '{voice_name}' not found for model '{model_name}'"
        )

    def list_voices(self) -> dict[str, list[VoiceInfo]]:
        """Return all voices grouped by model name."""
        result: dict[str, list[VoiceInfo]] = {}
        for model_name, model in self._models.items():
            result[model_name] = model.voices()
        return result

    @property
    def available_models(self) -> list[str]:
        return list(self._models.keys())
