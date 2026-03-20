"""Tests for server helpers — validate_request() and validate_and_generate() with DI."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.responses import JSONResponse

from s_peach.config import Settings
from s_peach.server.helpers import validate_and_generate, validate_request
from s_peach.server.models import AppState, SpeakRequest
from s_peach.voices import VoiceRegistry


def _make_app_state(settings: Settings) -> AppState:
    """Build a minimal AppState with a mock model — no app startup needed."""
    state = AppState(settings)
    mock_model = MagicMock()
    mock_model.is_loaded.return_value = True
    mock_model.voices.return_value = []
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_model.speak.return_value = (fake_audio, 24000)
    state.models["kitten-mini"] = mock_model
    state.voice_registry = VoiceRegistry(settings=settings, models=state.models)
    state.ready = True
    return state


class TestValidateRequest:
    def test_valid_request_returns_validated(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="hello", model="kitten-mini", voice="Bella")
        result = validate_request(req, state)
        assert not isinstance(result, JSONResponse)
        assert result.text == "hello"
        assert result.native_id == "Bella"

    def test_empty_text_returns_400(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="", model="kitten-mini", voice="Bella")
        result = validate_request(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_missing_model_returns_400(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="hello")
        result = validate_request(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_missing_voice_returns_400(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="hello", model="kitten-mini")
        result = validate_request(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_unknown_model_returns_400(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="hello", model="nonexistent", voice="X")
        result = validate_request(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_failed_model_returns_503(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        state.failed_models["broken"] = "GPU error"
        req = SpeakRequest(text="hello", model="broken", voice="X")
        result = validate_request(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 503

    def test_speed_out_of_range_returns_400(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="hello", model="kitten-mini", voice="Bella", speed=10.0)
        result = validate_request(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_speed_passed_through_in_kwargs(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="hello", model="kitten-mini", voice="Bella", speed=1.5)
        result = validate_request(req, state)
        assert not isinstance(result, JSONResponse)
        assert result.speak_kwargs["speed"] == 1.5

    def test_unknown_voice_returns_400(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="hello", model="kitten-mini", voice="NoSuchVoice")
        result = validate_request(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400


class TestValidateAndGenerate:
    @pytest.mark.asyncio
    async def test_valid_request_returns_audio_tuple(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="hello", model="kitten-mini", voice="Bella")
        result = await validate_and_generate(req, state)
        assert not isinstance(result, JSONResponse)
        audio, sr, text = result
        assert isinstance(audio, np.ndarray)
        assert sr == 24000
        assert text == "hello"

    @pytest.mark.asyncio
    async def test_invalid_request_returns_json_response(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        req = SpeakRequest(text="", model="kitten-mini", voice="Bella")
        result = await validate_and_generate(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_tts_timeout_returns_503(self, settings: Settings) -> None:
        state = _make_app_state(settings)
        state.models["kitten-mini"].speak.side_effect = TimeoutError("boom")
        req = SpeakRequest(text="hello", model="kitten-mini", voice="Bella")
        result = await validate_and_generate(req, state)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 503
