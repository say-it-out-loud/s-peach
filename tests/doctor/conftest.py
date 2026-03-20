"""Shared fixtures for doctor tests."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml


@pytest.fixture
def home_dir(tmp_path: Path) -> Path:
    """Create a fake home directory."""
    d = tmp_path / "home"
    d.mkdir()
    return d


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Create a fake XDG config directory for s-peach."""
    d = tmp_path / "xdg" / "s-peach"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def runtime_dir(tmp_path: Path) -> Path:
    """Create a fake runtime directory."""
    d = tmp_path / "run" / "s-peach"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def valid_config(config_dir: Path) -> Path:
    """Write a valid server.yaml."""
    cfg = config_dir / "server.yaml"
    cfg.write_text(yaml.dump({
        "server": {"host": "0.0.0.0", "port": 7777},
        "enabled_models": ["kokoro"],
        "api_key": "test-key-123",
        "voices": {
            "kokoro": {"Heart": "af_heart"},
            "kitten": {"Bella": "Bella"},
        },
    }))
    cfg.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return cfg


@pytest.fixture
def valid_notifier(config_dir: Path) -> Path:
    """Write a valid client.yaml with matching API key."""
    nf = config_dir / "client.yaml"
    nf.write_text(yaml.dump({"api_key": "test-key-123"}))
    nf.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return nf


@pytest.fixture
def _patch_paths(config_dir: Path, runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch s_peach.paths to use tmp dirs."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir.parent))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir.parent))


def _make_settings(**overrides):
    """Create a mock Settings object with defaults."""
    settings = MagicMock()
    settings.server.port = overrides.get("port", 7777)
    settings.server.host = overrides.get("host", "0.0.0.0")
    settings.enabled_models = overrides.get("enabled_models", ["kokoro"])
    settings.api_key = overrides.get("api_key", "test-key-123")
    settings.voices = overrides.get("voices", {
        "kokoro": {"Heart": "af_heart"},
        "kitten": {"Bella": "Bella"},
    })
    return settings
