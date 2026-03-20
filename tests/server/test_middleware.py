"""Tests for API key authentication and IP whitelist middleware."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from s_peach.config import Settings
from s_peach.server import create_app

from tests.server.conftest import _make_mock_model, _patched_app


# --- IP Whitelist ---


class TestIPWhitelist:
    def test_non_whitelisted_ip_returns_403(self, settings: Settings) -> None:
        """TestClient uses 'testclient' as host -- invalid IP gets 403."""
        settings.ip_whitelist = ["10.0.0.0/8"]
        mock_model = _make_mock_model()

        import s_peach.server as srv
        original = srv._MODEL_CONSTRUCTORS.copy()
        srv._MODEL_CONSTRUCTORS["kitten-mini"] = lambda s: mock_model
        try:
            app = create_app(settings)
            with TestClient(app) as client:
                resp = client.get("/health")
                assert resp.status_code == 403
        finally:
            srv._MODEL_CONSTRUCTORS.update(original)

    def test_speak_from_non_whitelisted_ip_returns_403(
        self, settings: Settings
    ) -> None:
        settings.ip_whitelist = ["10.0.0.0/8"]
        mock_model = _make_mock_model()

        import s_peach.server as srv
        original = srv._MODEL_CONSTRUCTORS.copy()
        srv._MODEL_CONSTRUCTORS["kitten-mini"] = lambda s: mock_model
        try:
            app = create_app(settings)
            with TestClient(app) as client:
                resp = client.post("/speak", json={"text": "hello"})
                assert resp.status_code == 403
        finally:
            srv._MODEL_CONSTRUCTORS.update(original)


# --- API Key ---


@pytest.fixture()
def api_key_settings(settings: Settings) -> Settings:
    """Settings with API key configured."""
    settings.api_key = "test-secret-key"
    return settings


class TestApiKeyDisabled:
    """When api_key is None (default), all requests pass through."""

    def test_speak_allowed_without_key(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "hello", "model": "kitten-mini", "voice": "Bella"},
                )
                assert resp.status_code == 202

    def test_voices_allowed_without_key(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get("/voices")
                assert resp.status_code == 200

    def test_health_allowed_without_key(self, settings: Settings) -> None:
        with _patched_app(settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get("/health")
                assert resp.status_code == 200


class TestApiKeyEnabled:
    """When api_key is set, endpoints require X-API-Key header."""

    def test_speak_with_valid_key_returns_202(
        self, api_key_settings: Settings
    ) -> None:
        with _patched_app(api_key_settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "hello", "model": "kitten-mini", "voice": "Bella"},
                    headers={"X-API-Key": "test-secret-key"},
                )
                assert resp.status_code == 202

    def test_speak_without_key_returns_401(
        self, api_key_settings: Settings
    ) -> None:
        with _patched_app(api_key_settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post("/speak", json={"text": "hello"})
                assert resp.status_code == 401
                assert "Missing API key" in resp.json()["detail"]

    def test_speak_with_wrong_key_returns_403(
        self, api_key_settings: Settings
    ) -> None:
        with _patched_app(api_key_settings) as (app, _):
            with TestClient(app) as client:
                resp = client.post(
                    "/speak",
                    json={"text": "hello"},
                    headers={"X-API-Key": "wrong-key"},
                )
                assert resp.status_code == 403
                assert "Invalid API key" in resp.json()["detail"]

    def test_voices_with_valid_key_returns_200(
        self, api_key_settings: Settings
    ) -> None:
        with _patched_app(api_key_settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get(
                    "/voices",
                    headers={"X-API-Key": "test-secret-key"},
                )
                assert resp.status_code == 200

    def test_voices_without_key_returns_401(
        self, api_key_settings: Settings
    ) -> None:
        with _patched_app(api_key_settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get("/voices")
                assert resp.status_code == 401

    def test_health_exempt_from_api_key(
        self, api_key_settings: Settings
    ) -> None:
        with _patched_app(api_key_settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get("/health")
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"

    def test_health_exempt_even_with_wrong_key(
        self, api_key_settings: Settings
    ) -> None:
        with _patched_app(api_key_settings) as (app, _):
            with TestClient(app) as client:
                resp = client.get(
                    "/health",
                    headers={"X-API-Key": "wrong-key"},
                )
                assert resp.status_code == 200


class TestApiKeyConfig:
    """Config loading for api_key field."""

    def test_api_key_default_is_none(self) -> None:
        s = Settings()
        assert s.api_key is None

    def test_api_key_set_via_constructor(self) -> None:
        s = Settings(api_key="my-key")
        assert s.api_key == "my-key"

    def test_api_key_from_env_var(
        self, config_file, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from s_peach.config import load_settings

        monkeypatch.setenv("S_PEACH_API_KEY", "env-key")
        s = load_settings()
        assert s.api_key == "env-key"
