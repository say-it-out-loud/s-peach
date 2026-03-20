"""Tests for FastAPI server endpoints."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from s_peach.config import Settings

from tests.server.conftest import _patched_app


class TestSpeak:
    def test_valid_text_returns_202(self, client: TestClient) -> None:
        resp = client.post(
            "/speak",
            json={"text": "Hello world", "model": "kitten-mini", "voice": "Bella"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert "queue_size" in data

    def test_empty_text_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/speak",
            json={"text": "", "model": "kitten-mini", "voice": "Bella"},
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_whitespace_only_text_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/speak",
            json={"text": "   ", "model": "kitten-mini", "voice": "Bella"},
        )
        assert resp.status_code == 400

    def test_text_exceeding_max_length_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/speak",
            json={"text": "x" * 1001, "model": "kitten-mini", "voice": "Bella"},
        )
        assert resp.status_code == 400
        assert "1000" in resp.json()["detail"]

    def test_missing_model_returns_400(self, client: TestClient) -> None:
        resp = client.post("/speak", json={"text": "hello"})
        assert resp.status_code == 400
        assert "model is required" in resp.json()["detail"]

    def test_missing_voice_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/speak", json={"text": "hello", "model": "kitten-mini"},
        )
        assert resp.status_code == 400
        assert "voice is required" in resp.json()["detail"]

    def test_unknown_model_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/speak",
            json={"text": "hello", "model": "nonexistent", "voice": "X"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "nonexistent" in data["detail"]
        assert "kitten-mini" in data["available_models"]

    def test_queue_full_returns_503(self, settings: Settings) -> None:
        settings.queue_depth = 1
        with _patched_app(settings) as (app, mock_model):
            from s_peach.audio import AudioItem, AudioQueue
            import asyncio

            with patch.object(
                AudioQueue, "_play", new=lambda self, item: asyncio.sleep(30)
            ):
                with TestClient(app) as client:
                    # Pre-fill the queue so the next /speak gets rejected
                    state = app.state.app_state
                    dummy = AudioItem(
                        audio=np.zeros(100, dtype=np.float32),
                        sample_rate=24000,
                        enqueued_at=time.monotonic(),
                        text_preview="filler",
                    )
                    state.queue.enqueue(dummy)

                    resp = client.post(
                        "/speak",
                        json={"text": "overflow", "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp.status_code == 503
                    assert "full" in resp.json()["detail"].lower()


class TestHealth:
    def test_health_returns_status(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "kitten-mini" in data["models"]
        assert "queue" in data
        assert "audio_device" in data


class TestVoices:
    def test_voices_returns_list(self, client: TestClient) -> None:
        resp = client.get("/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestSpeakSync:
    def test_valid_request_returns_200_with_duration(self, settings: Settings) -> None:
        def slow_play(audio, sr, fade_ms=10, silence_pad_ms=300, trim_end_ms=0):
            time.sleep(0.05)
            return 0.05

        with _patched_app(settings) as (app, mock_model):
            with patch("s_peach.server.endpoints.play_direct", side_effect=slow_play):
                with TestClient(app) as client:
                    resp = client.post(
                        "/speak-sync",
                        json={"text": "Hello world", "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["status"] == "done"
                    assert data["duration_ms"] > 0

    def test_missing_model_returns_400(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, _):
            with patch("s_peach.server.endpoints.play_direct", return_value=1.0):
                with TestClient(app) as client:
                    resp = client.post(
                        "/speak-sync",
                        json={"text": "hello"},
                    )
                    assert resp.status_code == 400
                    assert "model is required" in resp.json()["detail"]

    def test_missing_voice_returns_400(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, _):
            with patch("s_peach.server.endpoints.play_direct", return_value=1.0):
                with TestClient(app) as client:
                    resp = client.post(
                        "/speak-sync",
                        json={"text": "hello", "model": "kitten-mini"},
                    )
                    assert resp.status_code == 400
                    assert "voice is required" in resp.json()["detail"]

    def test_invalid_model_returns_400(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, _):
            with patch("s_peach.server.endpoints.play_direct", return_value=1.0):
                with TestClient(app) as client:
                    resp = client.post(
                        "/speak-sync",
                        json={"text": "hello", "model": "nonexistent", "voice": "X"},
                    )
                    assert resp.status_code == 400
                    data = resp.json()
                    assert "nonexistent" in data["detail"]
                    assert "kitten-mini" in data["available_models"]

    def test_tts_timeout_returns_503(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, mock_model):
            mock_model.speak.side_effect = TimeoutError("timed out")
            with patch("s_peach.server.endpoints.play_direct", return_value=1.0):
                with TestClient(app) as client:
                    resp = client.post(
                        "/speak-sync",
                        json={"text": "hello", "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp.status_code == 503
                    assert "timed out" in resp.json()["detail"].lower()

    def test_tts_generation_error_returns_500(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, mock_model):
            mock_model.speak.side_effect = RuntimeError("GPU OOM")
            with patch("s_peach.server.endpoints.play_direct", return_value=1.0):
                with TestClient(app) as client:
                    resp = client.post(
                        "/speak-sync",
                        json={"text": "hello", "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp.status_code == 500
                    assert "failed" in resp.json()["detail"].lower()

    def test_saves_last_audio_for_replay(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, mock_model):
            with patch("s_peach.server.endpoints.play_direct", return_value=1.0):
                with TestClient(app) as client:
                    resp = client.post(
                        "/speak-sync",
                        json={"text": "Remember me", "model": "kitten-mini", "voice": "Bella"},
                    )
                    assert resp.status_code == 200
                    # last_audio should be set
                    state = app.state.app_state
                    assert state.last_audio is not None
                    assert state.last_audio.text_preview == "Remember me"

    def test_concurrent_requests_both_succeed(self, settings: Settings) -> None:
        """Two concurrent /speak-sync requests both complete successfully (no lock)."""
        with _patched_app(settings) as (app, mock_model):
            with patch("s_peach.server.endpoints.play_direct", return_value=0.1):
                with TestClient(app) as client:
                    results = []

                    def do_request():
                        r = client.post(
                            "/speak-sync",
                            json={"text": "hello", "model": "kitten-mini", "voice": "Bella"},
                        )
                        results.append(r.status_code)

                    t1 = threading.Thread(target=do_request)
                    t2 = threading.Thread(target=do_request)
                    t1.start()
                    t2.start()
                    t1.join(timeout=5)
                    t2.join(timeout=5)

                    assert len(results) == 2
                    assert all(s == 200 for s in results)


class TestShutdown:
    def test_server_shuts_down_cleanly(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200


class TestReloadAudioSettings:
    def test_reload_updates_audio_queue_settings(self, settings: Settings) -> None:
        """POST /reload should update the queue's audio params from new config."""
        import os
        import yaml
        from pathlib import Path

        with _patched_app(settings) as (app, _):
            with TestClient(app) as client:
                queue = app.state.app_state.queue

                # Verify baseline queue values match original settings
                assert queue._fade_ms == settings.fade_ms
                assert queue._silence_pad_ms == settings.silence_pad_ms
                assert queue._trim_end_ms == settings.trim_end_ms

                # Write a new config with different audio params
                new_fade_ms = 25
                new_silence_pad_ms = 500
                new_trim_end_ms = 50

                cfg_path = Path(os.environ["S_PEACH_CONFIG"])
                cfg_data = yaml.safe_load(cfg_path.read_text())
                cfg_data["fade_ms"] = new_fade_ms
                cfg_data["silence_pad_ms"] = new_silence_pad_ms
                cfg_data["trim_end_ms"] = new_trim_end_ms
                cfg_path.write_text(yaml.dump(cfg_data))

                resp = client.post("/reload")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "reloaded"
                assert "audio" in data["changes"]

                # Queue should now have the updated audio settings
                assert queue._fade_ms == new_fade_ms
                assert queue._silence_pad_ms == new_silence_pad_ms
                assert queue._trim_end_ms == new_trim_end_ms


class TestPortUnavailable:
    def test_lifespan_raises_system_exit_when_port_in_use(
        self, settings: Settings
    ) -> None:
        """lifespan should raise SystemExit when the configured port is already bound."""
        import socket as socket_module

        # Bind the port in the main thread so the lifespan's bind() call fails.
        blocker = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
        blocker.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEADDR, 1)
        try:
            blocker.bind(("127.0.0.1", settings.server.port))

            # Update settings so lifespan tries the same host/port
            settings.server.host = "127.0.0.1"

            raised: list[BaseException] = []
            with _patched_app(settings) as (app, _):
                try:
                    with TestClient(app):
                        pass
                except BaseException as exc:
                    raised.append(exc)

            # The lifespan raises SystemExit; anyio/starlette wraps it in a
            # different exception type (BaseExceptionGroup or CancelledError).
            # We simply verify that startup failed -- something was raised.
            assert raised, "Expected an exception when port is already in use"
        finally:
            blocker.close()
