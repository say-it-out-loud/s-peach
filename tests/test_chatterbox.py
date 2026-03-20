"""Tests for Chatterbox Turbo TTS model backend."""

from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from s_peach.config import Settings
from s_peach.models.chatterbox import ChatterboxTTSModel, ChatterboxTurboTTSModel


@pytest.fixture()
def mock_chatterbox_module():
    """Create a mock chatterbox module with ChatterboxTurboTTS class."""
    # Create module hierarchy matching real chatterbox package structure.
    # speak() patches tqdm in chatterbox.models.t3.t3 and
    # chatterbox.models.s3gen.flow_matching, so these must exist.
    mock_root = types.ModuleType("chatterbox")
    mock_tts_turbo = types.ModuleType("chatterbox.tts_turbo")
    mock_models = types.ModuleType("chatterbox.models")
    mock_s3gen = types.ModuleType("chatterbox.models.s3gen")
    mock_s3gen_fm = types.ModuleType("chatterbox.models.s3gen.flow_matching")
    mock_t3 = types.ModuleType("chatterbox.models.t3")
    mock_t3_t3 = types.ModuleType("chatterbox.models.t3.t3")

    mock_cls = MagicMock()
    mock_tts_turbo.ChatterboxTurboTTS = mock_cls
    mock_s3gen.S3GEN_SR = 24000
    # Wire submodule attributes so mock.patch can resolve dotted paths
    mock_s3gen.flow_matching = mock_s3gen_fm
    mock_t3.t3 = mock_t3_t3
    mock_models.t3 = mock_t3
    mock_models.s3gen = mock_s3gen
    # speak() patches tqdm in these modules — attributes must exist for mock.patch
    mock_t3_t3.tqdm = None
    mock_s3gen_fm.tqdm = None

    # Mock perth and torch so load()/unload() never import the real packages.
    # Real torch causes a docstring conflict on re-import across tests.
    mock_perth = types.ModuleType("perth")
    mock_perth.PerthImplicitWatermarker = MagicMock()
    mock_perth_dummy = types.ModuleType("perth.dummy_watermarker")
    mock_perth_dummy.DummyWatermarker = MagicMock()

    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = False

    with patch.dict(sys.modules, {
        "chatterbox": mock_root,
        "chatterbox.tts_turbo": mock_tts_turbo,
        "chatterbox.models": mock_models,
        "chatterbox.models.s3gen": mock_s3gen,
        "chatterbox.models.s3gen.flow_matching": mock_s3gen_fm,
        "chatterbox.models.t3": mock_t3,
        "chatterbox.models.t3.t3": mock_t3_t3,
        "perth": mock_perth,
        "perth.dummy_watermarker": mock_perth_dummy,
        "torch": mock_torch,
    }):
        yield mock_cls


def _make_mock_tensor(audio_data: np.ndarray | None = None) -> MagicMock:
    """Create a mock tensor with the squeeze().float().cpu().numpy() chain."""
    if audio_data is None:
        audio_data = np.ones(1000, dtype=np.float32)
    tensor = MagicMock()
    squeezed = MagicMock()
    floated = MagicMock()
    cpued = MagicMock()
    tensor.squeeze.return_value = squeezed
    squeezed.float.return_value = floated
    floated.cpu.return_value = cpued
    cpued.numpy.return_value = audio_data
    return tensor


@pytest.fixture()
def chatterbox_settings(settings: Settings) -> Settings:
    return settings


@pytest.fixture()
def chatterbox_model(chatterbox_settings: Settings) -> ChatterboxTurboTTSModel:
    return ChatterboxTurboTTSModel(chatterbox_settings)


class TestChatterboxName:
    def test_name_returns_chatterbox_turbo(self, chatterbox_model: ChatterboxTurboTTSModel) -> None:
        assert chatterbox_model.name() == "chatterbox-turbo"


class TestChatterboxVoices:
    def test_voices_returns_config_voices(self, chatterbox_model: ChatterboxTurboTTSModel) -> None:
        voices = chatterbox_model.voices()
        names = [v.name for v in voices]
        assert "default" in names

    def test_voices_returns_voice_info_with_native_ids(
        self, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        voices = chatterbox_model.voices()
        by_name = {v.name: v for v in voices}
        assert by_name["default"].native_id == ""


class TestChatterboxLifecycle:
    def test_not_loaded_initially(self, chatterbox_model: ChatterboxTurboTTSModel) -> None:
        assert chatterbox_model.is_loaded() is False

    def test_load_calls_from_pretrained(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        chatterbox_model.load()
        assert chatterbox_model.is_loaded() is True
        mock_chatterbox_module.from_pretrained.assert_called_once_with("cpu")

    def test_unload_clears_model(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        chatterbox_model.load()
        chatterbox_model.unload()
        assert chatterbox_model.is_loaded() is False

    def test_is_loaded_lifecycle(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        assert chatterbox_model.is_loaded() is False
        chatterbox_model.load()
        assert chatterbox_model.is_loaded() is True
        chatterbox_model.unload()
        assert chatterbox_model.is_loaded() is False

    def test_double_load_only_creates_once(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        chatterbox_model.load()
        chatterbox_model.load()
        mock_chatterbox_module.from_pretrained.assert_called_once()

    def test_double_unload_is_safe(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        chatterbox_model.load()
        chatterbox_model.unload()
        chatterbox_model.unload()  # Should not raise
        assert chatterbox_model.is_loaded() is False


class TestChatterboxSpeak:
    def test_speak_default_voice_calls_generate_without_prompt(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        mock_model = mock_chatterbox_module.from_pretrained.return_value
        mock_model.generate.return_value = _make_mock_tensor()

        audio, sr = chatterbox_model.speak("hello world", "")
        assert sr == 24000
        assert isinstance(audio, np.ndarray)
        mock_model.generate.assert_called_once_with("hello world")

    def test_speak_ref_clip_voice_calls_generate_with_prompt(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel,
        tmp_path,
    ) -> None:
        mock_model = mock_chatterbox_module.from_pretrained.return_value
        mock_model.generate.return_value = _make_mock_tensor()

        ref_clip = tmp_path / "speaker.wav"
        ref_clip.write_bytes(b"fake wav data")

        audio, sr = chatterbox_model.speak("hello world", str(ref_clip))
        assert sr == 24000
        mock_model.generate.assert_called_once_with(
            "hello world", audio_prompt_path=str(ref_clip)
        )

    def test_speak_paralinguistic_tags_passed_unmodified(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        mock_model = mock_chatterbox_module.from_pretrained.return_value
        mock_model.generate.return_value = _make_mock_tensor()

        text = "Hello [laugh] world [cough] goodbye"
        chatterbox_model.speak(text, "")
        mock_model.generate.assert_called_once_with(text)

    def test_speak_converts_tensor_to_numpy(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        expected_audio = np.random.randn(2400).astype(np.float32)
        mock_tensor = _make_mock_tensor(expected_audio)
        mock_model = mock_chatterbox_module.from_pretrained.return_value
        mock_model.generate.return_value = mock_tensor

        audio, sr = chatterbox_model.speak("test", "")
        assert sr == 24000
        np.testing.assert_array_equal(audio, expected_audio)
        # Verify the chain was called
        mock_tensor.squeeze.assert_called_once()
        mock_tensor.squeeze.return_value.float.assert_called_once()

    def test_speak_timeout_raises(
        self, mock_chatterbox_module: MagicMock, chatterbox_settings: Settings
    ) -> None:
        chatterbox_settings.tts_timeout = 1
        model = ChatterboxTurboTTSModel(chatterbox_settings)

        mock_model_instance = mock_chatterbox_module.from_pretrained.return_value

        def slow_generate(*args, **kwargs):
            time.sleep(5)
            return _make_mock_tensor()

        mock_model_instance.generate.side_effect = slow_generate

        with pytest.raises(TimeoutError, match="timed out"):
            model.speak("long text", "")

    def test_speak_auto_loads_model(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        mock_model = mock_chatterbox_module.from_pretrained.return_value
        mock_model.generate.return_value = _make_mock_tensor()

        assert chatterbox_model.is_loaded() is False
        chatterbox_model.speak("test", "")
        assert chatterbox_model.is_loaded() is True

    def test_speak_nonexistent_native_id_raises_file_not_found(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        with pytest.raises(FileNotFoundError, match="Reference audio clip not found"):
            chatterbox_model.speak("test", "/nonexistent/path/speaker.wav")

    def test_speak_propagates_generate_exception(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        mock_model = mock_chatterbox_module.from_pretrained.return_value
        mock_model.generate.side_effect = RuntimeError("model crashed")

        with pytest.raises(RuntimeError, match="model crashed"):
            chatterbox_model.speak("test", "")


class TestChatterboxLoad:
    def test_load_raises_import_error_when_not_installed(
        self, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        with patch.dict(sys.modules, {
            "chatterbox": None,
            "chatterbox.tts_turbo": None,
        }):
            with pytest.raises(ImportError, match="chatterbox-tts is not installed"):
                chatterbox_model.load()


class TestChatterboxUnload:
    def test_unload_calls_cuda_empty_cache_when_available(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        chatterbox_model.load()

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        with patch.dict(sys.modules, {"torch": mock_torch}):
            chatterbox_model.unload()

        mock_torch.cuda.empty_cache.assert_called_once()

    def test_unload_skips_cuda_when_not_available(
        self, mock_chatterbox_module: MagicMock, chatterbox_model: ChatterboxTurboTTSModel
    ) -> None:
        chatterbox_model.load()

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict(sys.modules, {"torch": mock_torch}):
            chatterbox_model.unload()

        mock_torch.cuda.empty_cache.assert_not_called()


class TestChatterboxConstructorRegistry:
    def test_chatterbox_turbo_registered_in_model_constructors(self) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        assert "chatterbox-turbo" in _MODEL_CONSTRUCTORS

    def test_chatterbox_registered_in_model_constructors(self) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        assert "chatterbox" in _MODEL_CONSTRUCTORS

    def test_chatterbox_turbo_constructor_returns_model(
        self, chatterbox_settings: Settings
    ) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        model = _MODEL_CONSTRUCTORS["chatterbox-turbo"](chatterbox_settings)
        assert model.name() == "chatterbox-turbo"

    def test_chatterbox_constructor_returns_model(
        self, chatterbox_settings: Settings
    ) -> None:
        from s_peach.server import _MODEL_CONSTRUCTORS

        model = _MODEL_CONSTRUCTORS["chatterbox"](chatterbox_settings)
        assert model.name() == "chatterbox"


class TestChatterbox500MName:
    def test_name_returns_chatterbox(self, chatterbox_settings: Settings) -> None:
        model = ChatterboxTTSModel(chatterbox_settings)
        assert model.name() == "chatterbox"
