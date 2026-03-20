"""Tests for Kokoro-82M TTS model backend."""

from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from s_peach.config import Settings
from s_peach.models.kokoro import KokoroTTSModel


@pytest.fixture()
def mock_kokoro_module():
    """Create a mock kokoro module with KPipeline class."""
    mock_module = types.ModuleType("kokoro")
    mock_pipeline_cls = MagicMock()
    mock_module.KPipeline = mock_pipeline_cls
    with patch.dict(sys.modules, {"kokoro": mock_module}):
        yield mock_pipeline_cls


@pytest.fixture()
def kokoro_settings(settings: Settings) -> Settings:
    return settings


@pytest.fixture()
def kokoro_model(kokoro_settings: Settings) -> KokoroTTSModel:
    return KokoroTTSModel(kokoro_settings)


class TestKokoroName:
    def test_name_returns_kokoro(self, kokoro_model: KokoroTTSModel) -> None:
        assert kokoro_model.name() == "kokoro"


class TestKokoroVoices:
    def test_voices_returns_config_voices(self, kokoro_model: KokoroTTSModel) -> None:
        voices = kokoro_model.voices()
        names = [v.name for v in voices]
        assert "Heart" in names
        assert "Emma" in names
        assert len(voices) == 4  # conftest fixture has 4 kokoro voices

    def test_voices_returns_voice_info_with_native_ids(
        self, kokoro_model: KokoroTTSModel
    ) -> None:
        voices = kokoro_model.voices()
        by_name = {v.name: v for v in voices}
        assert by_name["Heart"].native_id == "af_heart"
        assert by_name["Alpha_JP"].native_id == "jf_alpha"


class TestKokoroLifecycle:
    def test_not_loaded_initially(self, kokoro_model: KokoroTTSModel) -> None:
        assert kokoro_model.is_loaded() is False

    def test_load_creates_pipeline(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        kokoro_model.load()
        assert kokoro_model.is_loaded() is True
        # Default language "en" maps to internal code "a"
        mock_kokoro_module.assert_called_once_with(lang_code="a", repo_id="hexgrad/Kokoro-82M")

    def test_load_uses_configured_language(
        self, mock_kokoro_module: MagicMock, kokoro_settings: Settings
    ) -> None:
        kokoro_settings.language = "gb"
        model = KokoroTTSModel(kokoro_settings)
        model.load()
        # ISO "gb" maps to internal code "b"
        mock_kokoro_module.assert_called_once_with(lang_code="b", repo_id="hexgrad/Kokoro-82M")

    def test_unload_clears_pipeline(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        kokoro_model.load()
        kokoro_model.unload()
        assert kokoro_model.is_loaded() is False

    def test_is_loaded_lifecycle(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        assert kokoro_model.is_loaded() is False
        kokoro_model.load()
        assert kokoro_model.is_loaded() is True
        kokoro_model.unload()
        assert kokoro_model.is_loaded() is False

    def test_double_load_only_creates_once(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        kokoro_model.load()
        kokoro_model.load()
        mock_kokoro_module.assert_called_once()

    def test_load_without_kokoro_raises_import_error(
        self, kokoro_model: KokoroTTSModel
    ) -> None:
        with patch.dict(sys.modules, {"kokoro": None}):
            with pytest.raises(ImportError, match="kokoro is not installed"):
                kokoro_model.load()


class TestKokoroSpeak:
    def test_speak_concatenates_generator_chunks(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        chunk1 = np.ones(1000, dtype=np.float32)
        chunk2 = np.ones(2000, dtype=np.float32) * 2
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([
            ("g1", "p1", chunk1),
            ("g2", "p2", chunk2),
        ])

        audio, sr = kokoro_model.speak("hello", "af_heart")
        assert sr == 24000
        assert isinstance(audio, np.ndarray)
        assert len(audio) == 3000

    def test_speak_skips_none_audio_chunks(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        chunk = np.ones(1000, dtype=np.float32)
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([
            ("g1", "p1", None),
            ("g2", "p2", chunk),
            ("g3", "p3", None),
        ])

        audio, sr = kokoro_model.speak("hello", "af_heart")
        assert len(audio) == 1000

    def test_speak_empty_generator_raises_runtime_error(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([])

        with pytest.raises(RuntimeError, match="no audio chunks"):
            kokoro_model.speak("hello", "af_heart")

    def test_speak_all_none_chunks_raises_runtime_error(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([
            ("g1", "p1", None),
            ("g2", "p2", None),
        ])

        with pytest.raises(RuntimeError, match="no audio chunks"):
            kokoro_model.speak("hello", "af_heart")

    def test_speak_passes_configured_speed(
        self, mock_kokoro_module: MagicMock, kokoro_settings: Settings
    ) -> None:
        kokoro_settings.kokoro.speed = 1.5
        model = KokoroTTSModel(kokoro_settings)

        chunk = np.ones(100, dtype=np.float32)
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([
            ("g1", "p1", chunk),
        ])

        model.speak("hello", "af_heart")
        mock_pipeline.assert_called_once_with(
            "hello", voice="af_heart", speed=1.5,
        )

    def test_speak_auto_loads_model(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        chunk = np.ones(100, dtype=np.float32)
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([
            ("g1", "p1", chunk),
        ])

        assert kokoro_model.is_loaded() is False
        kokoro_model.speak("test", "af_heart")
        assert kokoro_model.is_loaded() is True

    def test_speak_timeout(
        self, mock_kokoro_module: MagicMock, kokoro_settings: Settings
    ) -> None:
        kokoro_settings.tts_timeout = 1
        model = KokoroTTSModel(kokoro_settings)

        def slow_generator(*args, **kwargs):
            time.sleep(5)
            yield ("g1", "p1", np.ones(100, dtype=np.float32))

        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = slow_generator()

        with pytest.raises(TimeoutError, match="timed out"):
            model.speak("long text", "af_heart")


class TestKokoroLanguages:
    def test_languages_returns_all_supported_codes(self, kokoro_model: KokoroTTSModel) -> None:
        langs = kokoro_model.languages()
        assert isinstance(langs, list)
        assert "en" in langs
        assert "fr" in langs
        assert "ja" in langs
        assert "zh" in langs
        assert len(langs) == 9  # en, gb, ja, zh, es, fr, hi, it, pt

    def test_speak_with_language_kwarg_uses_correct_pipeline(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        """language kwarg in speak() selects the appropriate KPipeline."""
        chunk = np.ones(100, dtype=np.float32)
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([("g1", "p1", chunk)])

        kokoro_model.speak("bonjour", "ff_siwis", language="fr")
        # "fr" maps to internal code "f"
        mock_kokoro_module.assert_called_once_with(lang_code="f", repo_id="hexgrad/Kokoro-82M")

    def test_speak_without_language_kwarg_uses_default(
        self, mock_kokoro_module: MagicMock, kokoro_settings: Settings
    ) -> None:
        """speak() without language kwarg uses configured default language."""
        kokoro_settings.language = "ja"
        model = KokoroTTSModel(kokoro_settings)

        chunk = np.ones(100, dtype=np.float32)
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([("g1", "p1", chunk)])

        model.speak("konnichiwa", "jf_alpha")
        # "ja" maps to internal code "j"
        mock_kokoro_module.assert_called_once_with(lang_code="j", repo_id="hexgrad/Kokoro-82M")

    def test_speak_caches_pipeline_per_language(
        self, mock_kokoro_module: MagicMock, kokoro_model: KokoroTTSModel
    ) -> None:
        """Each unique language gets its own pipeline; same language reuses cached pipeline."""
        chunk = np.ones(100, dtype=np.float32)
        mock_pipeline = mock_kokoro_module.return_value
        mock_pipeline.return_value = iter([("g1", "p1", chunk)])

        # Speak in English (first call — creates pipeline for "a")
        mock_pipeline.return_value = iter([("g1", "p1", chunk)])
        kokoro_model.speak("hello", "af_heart", language="en")
        assert mock_kokoro_module.call_count == 1

        # Speak in English again — should reuse cached pipeline
        mock_pipeline.return_value = iter([("g1", "p1", chunk)])
        kokoro_model.speak("world", "af_heart", language="en")
        assert mock_kokoro_module.call_count == 1  # still 1 — no new pipeline created

        # Speak in French — creates a second pipeline
        mock_pipeline.return_value = iter([("g1", "p1", chunk)])
        kokoro_model.speak("bonjour", "ff_siwis", language="fr")
        assert mock_kokoro_module.call_count == 2  # new pipeline for "f"


class TestKokoroConstructorRegistry:
    def test_kokoro_registered_in_model_constructors(self) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        assert "kokoro" in _MODEL_CONSTRUCTORS

    def test_kokoro_constructor_returns_kokoro_model(
        self, kokoro_settings: Settings
    ) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        model = _MODEL_CONSTRUCTORS["kokoro"](kokoro_settings)
        assert model.name() == "kokoro"
