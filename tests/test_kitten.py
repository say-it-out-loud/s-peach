"""Tests for KittenTTS model backend."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from s_peach.config import Settings
from s_peach.models.kitten import KittenTTSModel


@pytest.fixture()
def kitten_settings(settings: Settings) -> Settings:
    return settings


@pytest.fixture()
def kitten_model(kitten_settings: Settings) -> KittenTTSModel:
    return KittenTTSModel(
        kitten_settings,
        model_id="KittenML/kitten-tts-mini-0.8",
        model_name="kitten-mini",
    )


class TestKittenVoices:
    def test_voices_returns_config_voices(self, kitten_model: KittenTTSModel) -> None:
        voices = kitten_model.voices()
        names = [v.name for v in voices]
        assert "Bella" in names
        assert "Jasper" in names
        assert len(voices) == 8

    def test_languages_returns_empty_list(self, kitten_model: KittenTTSModel) -> None:
        """Kitten models do not support language switching — return empty list."""
        assert kitten_model.languages() == []


class TestKittenLifecycle:
    def test_not_loaded_initially(self, kitten_model: KittenTTSModel) -> None:
        assert kitten_model.is_loaded() is False

    @patch("kittentts.KittenTTS", create=True)
    def test_load_creates_model(
        self, mock_cls: MagicMock, kitten_model: KittenTTSModel
    ) -> None:
        kitten_model.load()
        assert kitten_model.is_loaded() is True
        mock_cls.assert_called_once()

    @patch("kittentts.KittenTTS", create=True)
    def test_unload_clears_model(
        self, mock_cls: MagicMock, kitten_model: KittenTTSModel
    ) -> None:
        kitten_model.load()
        kitten_model.unload()
        assert kitten_model.is_loaded() is False

    @patch("kittentts.KittenTTS", create=True)
    def test_double_load_only_creates_once(
        self, mock_cls: MagicMock, kitten_model: KittenTTSModel
    ) -> None:
        kitten_model.load()
        kitten_model.load()
        mock_cls.assert_called_once()

    @patch("kittentts.KittenTTS", create=True)
    def test_reload_after_unload(
        self, mock_cls: MagicMock, kitten_model: KittenTTSModel
    ) -> None:
        kitten_model.load()
        kitten_model.unload()
        kitten_model.load()
        assert mock_cls.call_count == 2


class TestKittenSpeak:
    @patch("kittentts.KittenTTS", create=True)
    def test_speak_returns_audio_array(
        self, mock_cls: MagicMock, kitten_model: KittenTTSModel
    ) -> None:
        fake_audio = np.zeros(24000, dtype=np.float32)
        mock_instance = mock_cls.return_value
        mock_instance.generate.return_value = fake_audio

        audio, sr = kitten_model.speak("Hello", voice="Bella")
        assert sr == 24000
        assert isinstance(audio, np.ndarray)
        assert len(audio) == 24000
        mock_instance.generate.assert_called_once_with("Hello", voice="Bella", speed=1.0)

    @patch("kittentts.KittenTTS", create=True)
    def test_speak_auto_loads_model(
        self, mock_cls: MagicMock, kitten_model: KittenTTSModel
    ) -> None:
        mock_instance = mock_cls.return_value
        mock_instance.generate.return_value = np.zeros(100, dtype=np.float32)

        kitten_model.speak("test", voice="Bella")
        assert kitten_model.is_loaded() is True

    @patch("kittentts.KittenTTS", create=True)
    def test_speak_timeout(
        self, mock_cls: MagicMock, kitten_settings: Settings
    ) -> None:
        kitten_settings.tts_timeout = 1
        model = KittenTTSModel(
            kitten_settings,
            model_id="KittenML/kitten-tts-mini-0.8",
            model_name="kitten-mini",
        )

        mock_instance = mock_cls.return_value
        mock_instance.generate.side_effect = lambda *a, **kw: time.sleep(5)

        with pytest.raises(TimeoutError, match="timed out"):
            model.speak("long text", voice="Bella")

    def test_name(self, kitten_model: KittenTTSModel) -> None:
        assert kitten_model.name() == "kitten-mini"


class TestKittenVariants:
    """Tests for parameterized KittenTTS variant construction."""

    def test_kitten80m_name(self, kitten_settings: Settings) -> None:
        model = KittenTTSModel(
            kitten_settings,
            model_id="KittenML/kitten-tts-mini-0.8",
            model_name="kitten-mini",
        )
        assert model.name() == "kitten-mini"

    def test_kitten40m_name(self, kitten_settings: Settings) -> None:
        model = KittenTTSModel(
            kitten_settings,
            model_id="KittenML/kitten-tts-micro-0.8",
            model_name="kitten-micro",
        )
        assert model.name() == "kitten-micro"

    def test_kitten15m_name(self, kitten_settings: Settings) -> None:
        model = KittenTTSModel(
            kitten_settings,
            model_id="KittenML/kitten-tts-nano-0.8-int8",
            model_name="kitten-nano",
        )
        assert model.name() == "kitten-nano"

    def test_custom_name(self, kitten_settings: Settings) -> None:
        model = KittenTTSModel(
            kitten_settings,
            model_id="X",
            model_name="Y",
        )
        assert model.name() == "Y"

    @patch("kittentts.KittenTTS", create=True)
    def test_load_uses_parameterized_model_id(
        self, mock_cls: MagicMock, kitten_settings: Settings
    ) -> None:
        model = KittenTTSModel(
            kitten_settings,
            model_id="KittenML/kitten-tts-micro-0.8",
            model_name="kitten-micro",
        )
        model.load()
        mock_cls.assert_called_once_with("KittenML/kitten-tts-micro-0.8")

    @patch("kittentts.KittenTTS", create=True)
    def test_load_kitten15m_uses_correct_model_id(
        self, mock_cls: MagicMock, kitten_settings: Settings
    ) -> None:
        model = KittenTTSModel(
            kitten_settings,
            model_id="KittenML/kitten-tts-nano-0.8-int8",
            model_name="kitten-nano",
        )
        model.load()
        mock_cls.assert_called_once_with("KittenML/kitten-tts-nano-0.8-int8")

    def test_all_variants_share_kitten_voice_map(self, kitten_settings: Settings) -> None:
        """All kitten variants use the shared 'kitten' voice map."""
        for name, mid in [
            ("kitten-mini", "KittenML/kitten-tts-mini-0.8"),
            ("kitten-micro", "KittenML/kitten-tts-micro-0.8"),
            ("kitten-nano", "KittenML/kitten-tts-nano-0.8-int8"),
        ]:
            model = KittenTTSModel(kitten_settings, model_id=mid, model_name=name)
            voices = model.voices()
            assert len(voices) == 8
            assert "Bella" in [v.name for v in voices]


class TestEspeakLoader:
    """Ensure vendored kittentts initializes espeakng-loader for phonemizer."""

    def test_phonemizer_espeak_library_env_set(self) -> None:
        """Importing onnx_model must set PHONEMIZER_ESPEAK_LIBRARY from espeakng_loader."""
        import os

        # Force re-import to trigger the env setup
        import importlib
        from s_peach._vendor.kittentts import onnx_model

        importlib.reload(onnx_model)

        lib_path = os.environ.get("PHONEMIZER_ESPEAK_LIBRARY")
        assert lib_path is not None, "PHONEMIZER_ESPEAK_LIBRARY not set after importing onnx_model"
        assert "espeakng_loader" in lib_path or "espeak" in lib_path.lower()

    def test_espeak_data_path_env_set(self) -> None:
        """Importing onnx_model must set ESPEAK_DATA_PATH from espeakng_loader."""
        import os

        import importlib
        from s_peach._vendor.kittentts import onnx_model

        importlib.reload(onnx_model)

        data_path = os.environ.get("ESPEAK_DATA_PATH")
        assert data_path is not None, "ESPEAK_DATA_PATH not set after importing onnx_model"
        assert "espeak" in data_path.lower()

    def test_phonemizer_backend_works(self) -> None:
        """phonemizer EspeakBackend must initialize without system espeak installed."""
        import importlib
        from s_peach._vendor.kittentts import onnx_model

        importlib.reload(onnx_model)

        import phonemizer

        backend = phonemizer.backend.EspeakBackend(
            language="en-us", preserve_punctuation=True, with_stress=True
        )
        assert backend is not None


class TestModelConstructors:
    """Tests for _MODEL_CONSTRUCTORS registry in server.py."""

    def test_all_variants_registered(self) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        assert "kitten-mini" in _MODEL_CONSTRUCTORS
        assert "kitten-micro" in _MODEL_CONSTRUCTORS
        assert "kitten-nano" in _MODEL_CONSTRUCTORS

    def test_old_kitten_name_not_registered(self) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        assert "kitten" not in _MODEL_CONSTRUCTORS

    def test_constructors_are_callable(self, kitten_settings: Settings) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        for name in ("kitten-mini", "kitten-micro", "kitten-nano"):
            model = _MODEL_CONSTRUCTORS[name](kitten_settings)
            assert model.name() == name
