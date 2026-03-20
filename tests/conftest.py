"""Shared test fixtures."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

import pytest
import yaml

from s_peach.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove S_PEACH_ env vars to isolate tests."""
    for key in list(os.environ):
        if key.startswith("S_PEACH_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def default_config_yaml() -> dict:
    """Return default config as a dict."""
    return {
        "server": {"host": "0.0.0.0", "port": 7777},
        "enabled_models": ["kitten-mini"],
        "queue_depth": 10,
        "queue_max_depth": 50,
        "queue_ttl": 60,
        "tts_timeout": 120,
        "ip_whitelist": [
            "127.0.0.1/32",
            "172.17.0.0/24",
            "10.0.0.0/8",
            "192.168.0.0/16",
        ],
        "log_level": "info",
        "kokoro": {
            "speed": 1.0,
        },
        "chatterbox": {
            "device": "cpu",
        },
        "voices": {
            "kitten": {
                "Bella": "Bella",
                "Jasper": "Jasper",
                "Luna": "Luna",
                "Bruno": "Bruno",
                "Rosie": "Rosie",
                "Hugo": "Hugo",
                "Kiki": "Kiki",
                "Leo": "Leo",
            },
            "kokoro": {
                "Heart": "af_heart",
                "Emma": "bf_emma",
                "Alpha_JP": "jf_alpha",
                "Xiaobei": "zf_xiaobei",
            },
            "chatterbox": {
                "default": "",
            },
        },
    }


@pytest.fixture()
def config_file(
    default_config_yaml: dict, tmp_path: Path
) -> Generator[Path, None, None]:
    """Write a config YAML to a temp file and set S_PEACH_CONFIG."""
    cfg_path = tmp_path / "server.yaml"
    cfg_path.write_text(yaml.dump(default_config_yaml))
    os.environ["S_PEACH_CONFIG"] = str(cfg_path)
    yield cfg_path
    os.environ.pop("S_PEACH_CONFIG", None)


@pytest.fixture()
def settings(config_file: Path) -> Settings:
    """Load settings from the temp config file."""
    from s_peach.config import load_settings

    return load_settings()
