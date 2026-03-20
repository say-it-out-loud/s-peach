"""Shared server test fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from s_peach.config import Settings
from s_peach.server import create_app


def _make_mock_model(name: str = "kitten-mini") -> MagicMock:
    """Create a mock TTS model."""
    mock = MagicMock()
    mock.name.return_value = name
    mock.is_loaded.return_value = False
    mock.voices.return_value = []
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock.speak.return_value = (fake_audio, 24000)
    return mock


@contextmanager
def _patched_app(settings: Settings):
    """Create app with mocked KittenTTS and permissive IP whitelist."""
    settings.ip_whitelist = []  # Bypass whitelist for tests
    mock_model = _make_mock_model()

    import s_peach.server as srv
    original = srv._MODEL_CONSTRUCTORS.copy()
    srv._MODEL_CONSTRUCTORS["kitten-mini"] = lambda s: mock_model
    try:
        app = create_app(settings)
        yield app, mock_model
    finally:
        srv._MODEL_CONSTRUCTORS.update(original)


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    with _patched_app(settings) as (app, _):
        with TestClient(app) as c:
            yield c
