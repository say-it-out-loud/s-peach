"""Tests for voice registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from s_peach.config import Settings
from s_peach.models.base import VoiceInfo
from s_peach.voices import VoiceRegistry


@pytest.fixture()
def mock_model() -> MagicMock:
    model = MagicMock()
    model.name.return_value = "kitten-mini"
    model.voices.return_value = [
        VoiceInfo(name="Bella", native_id="Bella"),
        VoiceInfo(name="Jasper", native_id="Jasper"),
    ]
    return model


@pytest.fixture()
def registry(settings: Settings, mock_model: MagicMock) -> VoiceRegistry:
    return VoiceRegistry(settings=settings, models={"kitten-mini": mock_model})


class TestVoiceResolution:
    def test_resolves_known_voice(self, registry: VoiceRegistry) -> None:
        resolved = registry.resolve(voice_name="Bella", model_name="kitten-mini")
        assert resolved.model_name == "kitten-mini"
        assert resolved.native_id == "Bella"
        assert resolved.friendly_name == "Bella"

    def test_unknown_voice_raises_key_error(self, registry: VoiceRegistry) -> None:
        with pytest.raises(KeyError, match="not found"):
            registry.resolve(voice_name="NonExistent", model_name="kitten-mini")


class TestVoiceListing:
    def test_list_voices_grouped_by_model(
        self, registry: VoiceRegistry, mock_model: MagicMock
    ) -> None:
        voices = registry.list_voices()
        assert "kitten-mini" in voices
        assert len(voices["kitten-mini"]) == 2
        mock_model.voices.assert_called_once()

    def test_available_models(self, registry: VoiceRegistry) -> None:
        assert registry.available_models == ["kitten-mini"]
