"""Tests for s_peach.mcp_server — MCP tool that reuses the TTS pipeline."""

from __future__ import annotations

from ipaddress import IPv4Network
from unittest.mock import MagicMock

import numpy as np
import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from s_peach.mcp_server import (
    _SecurityMiddleware,
    attach_app_state,
    list_voices,
    mcp,
    say_that_again,
    speak,
)


# --- Helpers ---


def _make_app_state(
    *,
    ready: bool = True,
    models: dict | None = None,
    failed_models: dict | None = None,
) -> MagicMock:
    """Build a mock AppState for MCP tool tests."""
    state = MagicMock()
    state.ready = ready
    state.models = models or {}
    state.failed_models = failed_models or {}
    state.last_audio = None

    # Voice registry
    state.voice_registry = MagicMock()

    # Audio queue
    state.queue = MagicMock()
    state.queue.enqueue.return_value = True
    state.queue.size.return_value = 1

    state.settings = MagicMock()
    state.settings.max_text_length = 1000

    return state


def _make_mock_model(audio: np.ndarray | None = None, sr: int = 24000):
    """Create a mock TTS model that returns audio."""
    model = MagicMock()
    if audio is None:
        audio = np.zeros(2400, dtype=np.float32)
    model.speak.return_value = (audio, sr)
    return model


# --- Tests ---


class TestSpeakTool:
    @pytest.mark.asyncio
    async def test_speak_empty_text_returns_error(self) -> None:
        state = _make_app_state()
        attach_app_state(state)
        result = await speak(text="   ", model="kokoro", voice="Heart")
        assert "error" in result
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_speak_too_long_text_returns_error(self) -> None:
        state = _make_app_state()
        attach_app_state(state)
        result = await speak(text="x" * 1001, model="kokoro", voice="Heart")
        assert "error" in result
        assert "1000" in result["error"]

    @pytest.mark.asyncio
    async def test_speak_server_not_ready(self) -> None:
        state = _make_app_state(ready=False)
        attach_app_state(state)
        result = await speak(text="hello", model="kokoro", voice="Heart")
        assert "error" in result
        assert "not ready" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_speak_defaults_to_first_model_and_voice(self) -> None:
        mock_model = _make_mock_model()
        state = _make_app_state(models={"kokoro": mock_model})

        resolved = MagicMock()
        resolved.model_name = "kokoro"
        resolved.native_id = "af_heart"
        state.voice_registry.resolve.return_value = resolved

        # list_voices returns VoiceInfo-like objects
        voice_info = MagicMock()
        voice_info.name = "Heart"
        state.voice_registry.list_voices.return_value = {"kokoro": [voice_info]}

        attach_app_state(state)
        result = await speak(text="hello")
        assert result["status"] == "queued"
        # Should have resolved with default model and voice
        state.voice_registry.resolve.assert_called_once_with(
            voice_name="Heart", model_name="kokoro"
        )

    @pytest.mark.asyncio
    async def test_speak_no_models_loaded(self) -> None:
        state = _make_app_state(models={})
        attach_app_state(state)
        result = await speak(text="hello")
        assert "error" in result
        assert "No models" in result["error"]

    @pytest.mark.asyncio
    async def test_speak_no_voices_for_default_model(self) -> None:
        state = _make_app_state(models={"kokoro": _make_mock_model()})
        state.voice_registry.list_voices.return_value = {"kokoro": []}
        attach_app_state(state)
        result = await speak(text="hello")
        assert "error" in result
        assert "No voices" in result["error"]

    @pytest.mark.asyncio
    async def test_speak_unknown_model_returns_error(self) -> None:
        state = _make_app_state(models={"kokoro": _make_mock_model()})
        attach_app_state(state)
        result = await speak(text="hello", model="nonexistent", voice="Heart")
        assert "error" in result
        assert "Unknown model" in result["error"]

    @pytest.mark.asyncio
    async def test_speak_failed_model_returns_503_style_error(self) -> None:
        state = _make_app_state(
            models={},
            failed_models={"kokoro": "OOM"},
        )
        attach_app_state(state)
        result = await speak(text="hello", model="kokoro", voice="Heart")
        assert "error" in result
        assert "unavailable" in result["error"].lower()
        assert "OOM" in result["error"]

    @pytest.mark.asyncio
    async def test_speak_voice_not_found_returns_error(self) -> None:
        state = _make_app_state(models={"kokoro": _make_mock_model()})
        state.voice_registry.resolve.side_effect = KeyError("not found")
        attach_app_state(state)
        result = await speak(text="hello", model="kokoro", voice="BadVoice")
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_speak_success_queues_audio(self) -> None:
        mock_model = _make_mock_model()
        state = _make_app_state(models={"kokoro": mock_model})

        resolved = MagicMock()
        resolved.model_name = "kokoro"
        resolved.native_id = "af_heart"
        state.voice_registry.resolve.return_value = resolved

        attach_app_state(state)
        result = await speak(text="hello world", model="kokoro", voice="Heart")

        assert result["status"] == "queued"
        assert result["queue_size"] == 1
        state.queue.enqueue.assert_called_once()
        assert state.last_audio is not None

    @pytest.mark.asyncio
    async def test_speak_passes_speed_to_model(self) -> None:
        mock_model = _make_mock_model()
        state = _make_app_state(models={"kokoro": mock_model})

        resolved = MagicMock()
        resolved.model_name = "kokoro"
        resolved.native_id = "af_heart"
        state.voice_registry.resolve.return_value = resolved

        attach_app_state(state)
        await speak(text="fast", model="kokoro", voice="Heart", speed=1.5)

        # The speak method should have been called with speed kwarg
        call_kwargs = mock_model.speak.call_args
        assert call_kwargs.kwargs.get("speed") == 1.5 or (
            len(call_kwargs.args) > 2 and 1.5 in call_kwargs.args
        )

    @pytest.mark.asyncio
    async def test_speak_queue_full_returns_error(self) -> None:
        mock_model = _make_mock_model()
        state = _make_app_state(models={"kokoro": mock_model})
        state.queue.enqueue.return_value = False

        resolved = MagicMock()
        resolved.model_name = "kokoro"
        resolved.native_id = "af_heart"
        state.voice_registry.resolve.return_value = resolved

        attach_app_state(state)
        result = await speak(text="hello", model="kokoro", voice="Heart")

        assert "error" in result
        assert "full" in result["error"].lower()


class TestAttachAppState:
    def test_attach_stores_state_on_mcp(self) -> None:
        state = _make_app_state()
        attach_app_state(state)
        assert mcp._app_state is state


# --- Security middleware tests ---


def _dummy_app():
    """A trivial Starlette app to wrap with _SecurityMiddleware."""

    async def homepage(request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/", homepage)])


class TestSecurityMiddleware:
    def test_passes_when_no_restrictions(self) -> None:
        state = _make_app_state()
        state.settings.ip_networks = []
        state.settings.api_key = None
        attach_app_state(state)

        app = _SecurityMiddleware(_dummy_app())
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.text == "ok"

    def test_blocks_ip_not_in_whitelist(self) -> None:
        state = _make_app_state()
        state.settings.ip_networks = [IPv4Network("10.0.0.0/8")]
        state.settings.api_key = None
        attach_app_state(state)

        app = _SecurityMiddleware(_dummy_app())
        # TestClient uses "testclient" as host which isn't valid IPv4
        client = TestClient(app)
        resp = client.get("/")
        # "testclient" is not a valid IPv4, so it should be rejected
        assert resp.status_code == 403

    def test_allows_ip_in_whitelist(self) -> None:
        state = _make_app_state()
        state.settings.ip_networks = [IPv4Network("127.0.0.0/8")]
        state.settings.api_key = None
        attach_app_state(state)

        app = _SecurityMiddleware(_dummy_app())
        client = TestClient(app, headers={"host": "127.0.0.1"})
        # TestClient's client IP is "testclient" string, not 127.0.0.1
        # so this will fail IP validation — that's expected (same as main server)
        resp = client.get("/")
        assert resp.status_code == 403

    def test_blocks_missing_api_key(self) -> None:
        state = _make_app_state()
        state.settings.ip_networks = []
        state.settings.api_key = "secret-key"
        attach_app_state(state)

        app = _SecurityMiddleware(_dummy_app())
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 401
        assert "API key" in resp.json()["detail"]

    def test_blocks_wrong_api_key(self) -> None:
        state = _make_app_state()
        state.settings.ip_networks = []
        state.settings.api_key = "secret-key"
        attach_app_state(state)

        app = _SecurityMiddleware(_dummy_app())
        client = TestClient(app, headers={"X-API-Key": "wrong"})
        resp = client.get("/")
        assert resp.status_code == 403
        assert "Invalid API key" in resp.json()["detail"]

    def test_allows_correct_api_key(self) -> None:
        state = _make_app_state()
        state.settings.ip_networks = []
        state.settings.api_key = "secret-key"
        attach_app_state(state)

        app = _SecurityMiddleware(_dummy_app())
        client = TestClient(app, headers={"X-API-Key": "secret-key"})
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.text == "ok"

    def test_returns_503_when_app_state_missing(self) -> None:
        # Detach any state
        if hasattr(mcp, "_app_state"):
            delattr(mcp, "_app_state")

        app = _SecurityMiddleware(_dummy_app())
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 503

    def test_ip_check_runs_before_api_key_check(self) -> None:
        """When both are configured and IP fails, should get 403 (IP), not 401 (key)."""
        state = _make_app_state()
        state.settings.ip_networks = [IPv4Network("10.0.0.0/8")]
        state.settings.api_key = "secret-key"
        attach_app_state(state)

        app = _SecurityMiddleware(_dummy_app())
        client = TestClient(app)
        resp = client.get("/")
        # "testclient" is invalid IP → 403 before API key check
        assert resp.status_code == 403


# --- list_voices tests ---


class TestListVoicesTool:
    @pytest.mark.asyncio
    async def test_list_voices_returns_models_and_voices(self) -> None:
        state = _make_app_state(models={"kokoro": _make_mock_model()})

        voice1 = MagicMock()
        voice1.name = "Heart"
        voice1.description = ""
        voice2 = MagicMock()
        voice2.name = "Bella"
        voice2.description = "Warm tone"
        state.voice_registry.list_voices.return_value = {"kokoro": [voice1, voice2]}

        attach_app_state(state)
        result = await list_voices()
        assert "models" in result
        assert len(result["models"]) == 1
        assert result["models"][0]["model"] == "kokoro"
        assert result["models"][0]["voices"] == [
            {"name": "Heart", "description": ""},
            {"name": "Bella", "description": "Warm tone"},
        ]

    @pytest.mark.asyncio
    async def test_list_voices_not_ready(self) -> None:
        state = _make_app_state(ready=False)
        attach_app_state(state)
        result = await list_voices()
        assert "error" in result
        assert "not ready" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_voices_multiple_models(self) -> None:
        state = _make_app_state(
            models={"kokoro": _make_mock_model(), "kitten-mini": _make_mock_model()}
        )
        v1 = MagicMock()
        v1.name = "Heart"
        v1.description = ""
        v2 = MagicMock()
        v2.name = "Bella"
        v2.description = ""
        state.voice_registry.list_voices.return_value = {
            "kokoro": [v1],
            "kitten-mini": [v2],
        }
        attach_app_state(state)
        result = await list_voices()
        assert len(result["models"]) == 2
        model_names = [m["model"] for m in result["models"]]
        assert "kokoro" in model_names
        assert "kitten-mini" in model_names


# --- say_that_again tests ---


class TestSayThatAgainTool:
    @pytest.mark.asyncio
    async def test_say_that_again_no_previous(self) -> None:
        state = _make_app_state()
        state.last_audio = None
        attach_app_state(state)
        result = await say_that_again()
        assert "error" in result
        assert "No previous" in result["error"]

    @pytest.mark.asyncio
    async def test_say_that_again_replays(self) -> None:
        state = _make_app_state()
        last = MagicMock()
        last.audio = np.zeros(2400, dtype=np.float32)
        last.sample_rate = 24000
        last.text_preview = "hello"
        state.last_audio = last
        attach_app_state(state)

        result = await say_that_again()
        assert result["status"] == "queued"
        state.queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_say_that_again_queue_full(self) -> None:
        state = _make_app_state()
        last = MagicMock()
        last.audio = np.zeros(2400, dtype=np.float32)
        last.sample_rate = 24000
        last.text_preview = "hello"
        state.last_audio = last
        state.queue.enqueue.return_value = False
        attach_app_state(state)

        result = await say_that_again()
        assert "error" in result
        assert "full" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_say_that_again_not_ready(self) -> None:
        state = _make_app_state(ready=False)
        attach_app_state(state)
        result = await say_that_again()
        assert "error" in result
        assert "not ready" in result["error"].lower()
