"""Integration tests — real app with mocked audio output.

These tests use the real TTS model (KittenTTS) when available.
Audio playback is mocked at the sounddevice layer.
Mark with @pytest.mark.model for tests requiring the model.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from s_peach.config import Settings
from s_peach.server import create_app


def _make_mock_model(name: str, voices: list | None = None) -> MagicMock:
    """Create a mock TTS model with standard behavior."""
    mock = MagicMock()
    mock.name.return_value = name
    mock.is_loaded.return_value = False
    mock.voices.return_value = voices or []
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock.speak.return_value = (fake_audio, 24000)

    def mock_load():
        mock.is_loaded.return_value = True

    def mock_unload():
        mock.is_loaded.return_value = False

    mock.load.side_effect = mock_load
    mock.unload.side_effect = mock_unload
    return mock


@contextmanager
def _integration_app(settings: Settings, mock_tts: bool = True):
    """Create app with mocked audio output but optionally real TTS model."""
    settings.ip_whitelist = []  # Bypass for TestClient

    if mock_tts:
        mock_kitten = _make_mock_model("kitten-mini")

        import s_peach.server as srv
        original = srv._MODEL_CONSTRUCTORS.copy()
        srv._MODEL_CONSTRUCTORS["kitten-mini"] = lambda s: mock_kitten
        try:
            with patch("s_peach.audio.AudioQueue._play", new=_fake_play):
                app = create_app(settings)
                yield app, mock_kitten
        finally:
            srv._MODEL_CONSTRUCTORS.update(original)
    else:
        with patch("s_peach.audio.AudioQueue._play", new=_fake_play):
            app = create_app(settings)
            yield app, None


@contextmanager
def _multi_model_app(settings: Settings):
    """Create app with kitten and kokoro mocked."""
    settings.ip_whitelist = []
    settings.enabled_models = ["kitten-mini", "kokoro"]

    mock_kitten = _make_mock_model("kitten-mini")
    mock_kokoro = _make_mock_model("kokoro")

    import s_peach.server as srv
    original = srv._MODEL_CONSTRUCTORS.copy()
    srv._MODEL_CONSTRUCTORS["kitten-mini"] = lambda s: mock_kitten
    srv._MODEL_CONSTRUCTORS["kokoro"] = lambda s: mock_kokoro
    try:
        with patch("s_peach.audio.AudioQueue._play", new=_fake_play):
            app = create_app(settings)
            yield app, mock_kitten, mock_kokoro
    finally:
        srv._MODEL_CONSTRUCTORS.update(original)


_played_items: list[str] = []


async def _fake_play(self, item):
    """Fake play that records what was played."""
    _played_items.append(item.text_preview)


@pytest.fixture(autouse=True)
def _clear_played():
    _played_items.clear()
    yield
    _played_items.clear()


class TestHappyPath:
    def test_speak_queues_and_plays(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, mock_model):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "Hello world", "model": "kitten-mini", "voice": "Bella"},
                )
                assert resp.status_code == 202
                assert resp.json()["status"] == "queued"

    def test_health_reflects_model_state(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, mock_model):
            with TestClient(app) as client:
                health = client.get("/health").json()
                assert health["status"] == "ok"
                assert "kitten-mini" in health["models"]

    def test_voices_endpoint(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get("/voices")
                assert resp.status_code == 200
                assert isinstance(resp.json(), list)


class TestFIFOOrdering:
    def test_multiple_requests_play_in_order(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                for text in ["first", "second", "third"]:
                    resp = client.post(
                        "/speak",
                        json={"text": text, "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp.status_code == 202

                import time
                time.sleep(1.5)

            assert _played_items == ["first", "second", "third"]


class TestQueueCapacity:
    def test_queue_full_then_accepts(self, settings: Settings) -> None:
        settings.queue_depth = 2

        async def slow_play(self, item):
            await asyncio.sleep(30)

        with patch("s_peach.audio.AudioQueue._play", new=slow_play):
            settings.ip_whitelist = []
            mock_model = _make_mock_model("kitten-mini")

            import s_peach.server as srv
            original = srv._MODEL_CONSTRUCTORS.copy()
            srv._MODEL_CONSTRUCTORS["kitten-mini"] = lambda s: mock_model
            try:
                app = create_app(settings)
                with TestClient(app) as client:
                    resp1 = client.post(
                        "/speak",
                        json={"text": "a", "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp1.status_code == 202
                    resp2 = client.post(
                        "/speak",
                        json={"text": "b", "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp2.status_code == 202

                    resp3 = client.post(
                        "/speak",
                        json={"text": "c", "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp3.status_code == 503
            finally:
                srv._MODEL_CONSTRUCTORS.update(original)


class TestInputValidation:
    def test_empty_text_rejected(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "", "model": "kitten-mini", "voice": "Bella"},
                )
                assert resp.status_code == 400

    def test_long_text_rejected(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "x" * 1001, "model": "kitten-mini", "voice": "Bella"},
                )
                assert resp.status_code == 400

    def test_missing_model_returns_400(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post("/speak", json={"text": "hello"})
                assert resp.status_code == 400
                assert "model is required" in resp.json()["detail"]
                assert "available_models" in resp.json()

    def test_missing_voice_returns_400(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak", json={"text": "hello", "model": "kitten-mini"},
                )
                assert resp.status_code == 400
                assert "voice is required" in resp.json()["detail"]

    def test_unknown_voice_returns_400(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "hello", "model": "kitten-mini", "voice": "NonExistent"},
                )
                assert resp.status_code == 400
                assert "not found" in resp.json()["detail"]


class TestIPWhitelist:
    def test_whitelisted_ip_allowed(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get("/health")
                assert resp.status_code == 200

    def test_non_whitelisted_returns_403(self, settings: Settings) -> None:
        settings.ip_whitelist = ["10.0.0.0/8"]

        import s_peach.server as srv
        original = srv._MODEL_CONSTRUCTORS.copy()
        mock_model = _make_mock_model("kitten-mini")
        srv._MODEL_CONSTRUCTORS["kitten-mini"] = lambda s: mock_model
        try:
            app = create_app(settings)
            with TestClient(app) as client:
                resp = client.get("/health")
                assert resp.status_code == 403
        finally:
            srv._MODEL_CONSTRUCTORS.update(original)


class TestMultiModelSpeak:
    """Integration tests for multi-model /speak routing."""

    def test_speak_with_kitten_model(self, settings: Settings) -> None:
        with _multi_model_app(settings) as (app, mock_kitten, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "hello", "model": "kitten-mini", "voice": "Bella"},
                )
                assert resp.status_code == 202
                # /speak generates audio in a background task — wait for it
                import time
                time.sleep(0.5)
                mock_kitten.speak.assert_called_once()

    def test_speak_with_kokoro_model(self, settings: Settings) -> None:
        with _multi_model_app(settings) as (app, _, mock_kokoro):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "hello", "model": "kokoro", "voice": "Heart"},
                )
                assert resp.status_code == 202
                # /speak generates audio in a background task — wait for it
                import time
                time.sleep(0.5)
                mock_kokoro.speak.assert_called_once()

    def test_speak_disabled_model_returns_400(self, settings: Settings) -> None:
        """Request for model not in enabled_models gets 400."""
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "hello", "model": "nonexistent", "voice": "X"},
                )
                assert resp.status_code == 400
                data = resp.json()
                assert "available_models" in data


class TestMultiModelVoices:
    """Integration tests for multi-model /voices endpoint."""

    def test_voices_returns_both_models(self, settings: Settings) -> None:
        from s_peach.models.base import VoiceInfo

        with _multi_model_app(settings) as (app, mock_kitten, mock_kokoro):
            mock_kitten.voices.return_value = [
                VoiceInfo(name="Bella", native_id="Bella")
            ]
            mock_kokoro.voices.return_value = [
                VoiceInfo(name="Heart", native_id="af_heart")
            ]
            with TestClient(app) as client:
                resp = client.get("/voices")
                assert resp.status_code == 200
                data = resp.json()
                model_names = [entry["model"] for entry in data]
                assert "kitten-mini" in model_names
                assert "kokoro" in model_names

    def test_voices_single_model(self, settings: Settings) -> None:
        """Only enabled model appears in /voices."""
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get("/voices")
                data = resp.json()
                model_names = [entry["model"] for entry in data]
                assert "kitten-mini" in model_names


class TestMultiModelHealth:
    """Integration tests for multi-model /health endpoint."""

    def test_health_both_models(self, settings: Settings) -> None:
        with _multi_model_app(settings) as (app, _, __):
            with TestClient(app) as client:
                resp = client.get("/health")
                data = resp.json()
                assert data["status"] == "ok"
                assert "kitten-mini" in data["models"]
                assert "kokoro" in data["models"]

    def test_health_single_model(self, settings: Settings) -> None:
        with _integration_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get("/health")
                data = resp.json()
                assert "kitten-mini" in data["models"]
                assert data["models"]["kitten-mini"]["enabled"] is True
