"""Tests for configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from s_peach.config import Settings, load_settings


class TestConfigLoading:
    def test_loads_from_yaml_with_defaults(self, config_file: Path, settings: Settings) -> None:
        assert settings.server.host == "0.0.0.0"
        assert settings.server.port == 7777
        assert settings.queue_depth == 10
        assert settings.queue_max_depth == 50
        assert settings.queue_ttl == 60
        assert settings.tts_timeout == 120
        assert settings.log_level == "info"
        assert len(settings.ip_whitelist) == 4

    def test_loads_partial_yaml_uses_defaults(self, tmp_path: Path) -> None:
        cfg = tmp_path / "partial.yaml"
        cfg.write_text(yaml.dump({"log_level": "debug"}))
        os.environ["S_PEACH_CONFIG"] = str(cfg)
        s = load_settings()
        assert s.log_level == "debug"
        assert s.server.port == 7777
        assert s.queue_depth == 10

    def test_missing_config_file_with_env_var_raises(self, tmp_path: Path) -> None:
        os.environ["S_PEACH_CONFIG"] = str(tmp_path / "nonexistent.yaml")
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_settings()

    def test_missing_config_file_without_env_var_uses_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        s = load_settings()
        assert s.server.port == 7777


class TestEnvVarOverrides:
    def test_log_level_override(self, config_file: Path) -> None:
        os.environ["S_PEACH_LOG_LEVEL"] = "debug"
        s = load_settings()
        assert s.log_level == "debug"

    def test_host_override(self, config_file: Path) -> None:
        os.environ["S_PEACH_SERVER__HOST"] = "127.0.0.1"
        s = load_settings()
        assert s.server.host == "127.0.0.1"

    def test_config_path_override(self, tmp_path: Path) -> None:
        alt_cfg = tmp_path / "alt.yaml"
        alt_cfg.write_text(yaml.dump({"log_level": "error"}))
        os.environ["S_PEACH_CONFIG"] = str(alt_cfg)
        s = load_settings()
        assert s.log_level == "error"


class TestValidation:
    def test_rejects_negative_queue_depth(self) -> None:
        with pytest.raises(ValueError, match="queue_depth must be >= 1"):
            Settings(queue_depth=-1)

    def test_rejects_queue_depth_over_max(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed"):
            Settings(queue_depth=100, queue_max_depth=50)

    def test_rejects_invalid_cidr(self) -> None:
        with pytest.raises(ValueError, match="Invalid CIDR"):
            Settings(ip_whitelist=["not-a-cidr"])

    def test_rejects_invalid_log_level(self) -> None:
        with pytest.raises(ValueError, match="Invalid log_level"):
            Settings(log_level="verbose")

    def test_accepts_valid_queue_depth_at_max(self) -> None:
        s = Settings(queue_depth=50, queue_max_depth=50)
        assert s.queue_depth == 50


class TestEnabledModels:
    def test_rejects_empty_enabled_models(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            Settings(enabled_models=[])

    def test_rejects_unknown_model_in_enabled(self) -> None:
        with pytest.raises(ValueError, match="Unknown model"):
            Settings(enabled_models=["kitten-mini", "bogus"])

    def test_accepts_kitten80m(self) -> None:
        s = Settings(enabled_models=["kitten-mini"])
        assert s.enabled_models == ["kitten-mini"]

    def test_accepts_kitten40m(self) -> None:
        s = Settings(enabled_models=["kitten-micro"])
        assert s.enabled_models == ["kitten-micro"]

    def test_accepts_kitten15m(self) -> None:
        s = Settings(enabled_models=["kitten-nano"])
        assert s.enabled_models == ["kitten-nano"]

    def test_accepts_kokoro(self) -> None:
        s = Settings(enabled_models=["kokoro"])
        assert s.enabled_models == ["kokoro"]

    def test_accepts_chatterbox_turbo(self) -> None:
        s = Settings(enabled_models=["chatterbox-turbo"])
        assert s.enabled_models == ["chatterbox-turbo"]

    def test_accepts_chatterbox(self) -> None:
        s = Settings(enabled_models=["chatterbox"])
        assert s.enabled_models == ["chatterbox"]

    def test_accepts_all_models(self) -> None:
        s = Settings(enabled_models=["kitten-mini", "kitten-micro", "kitten-nano", "kokoro", "chatterbox-turbo", "chatterbox", "chatterbox-multi"])
        assert len(s.enabled_models) == 7

    def test_accepts_chatterbox_multi(self) -> None:
        s = Settings(enabled_models=["chatterbox-multi"])
        assert s.enabled_models == ["chatterbox-multi"]

    def test_rejects_old_bare_kitten_name(self) -> None:
        with pytest.raises(ValueError, match="Unknown model"):
            Settings(enabled_models=["kitten"])

    def test_rejects_unknown_model(self) -> None:
        with pytest.raises(ValueError, match="Unknown model"):
            Settings(enabled_models=["qwen3"])

    def test_kokoro_config_defaults(self, settings: Settings) -> None:
        assert settings.kokoro.speed == 1.0

    def test_kokoro_speed_validation_too_low(self) -> None:
        from s_peach.config import KokoroConfig

        with pytest.raises(ValueError, match="between 0.1 and 5.0"):
            KokoroConfig(speed=0.0)

    def test_kokoro_speed_validation_too_high(self) -> None:
        from s_peach.config import KokoroConfig

        with pytest.raises(ValueError, match="between 0.1 and 5.0"):
            KokoroConfig(speed=6.0)

    def test_kokoro_speed_validation_accepts_valid(self) -> None:
        from s_peach.config import KokoroConfig

        cfg = KokoroConfig(speed=1.5)
        assert cfg.speed == 1.5

    def test_global_language_default(self, settings: Settings) -> None:
        assert settings.language == "en"

    def test_global_language_override(self) -> None:
        s = Settings(enabled_models=["kokoro"], language="fr")
        assert s.language == "fr"

class TestVoiceMap:
    def test_voice_map_loaded(self, settings: Settings) -> None:
        assert "kitten" in settings.voices
        assert settings.voices["kitten"]["Bella"] == "Bella"
        assert len(settings.voices["kitten"]) == 8

    def test_voice_map_kokoro_model(self, settings: Settings) -> None:
        assert "kokoro" in settings.voices
        assert "Heart" in settings.voices["kokoro"]
        assert settings.voices["kokoro"]["Heart"] == "af_heart"
        assert len(settings.voices["kokoro"]) == 4  # conftest subset


class TestConfigResolutionOrder:
    """Tests for the config file resolution chain: env > local > XDG > defaults."""

    def test_env_override_loads_that_file(self, tmp_path: Path) -> None:
        """$S_PEACH_CONFIG is used regardless of other files."""
        cfg = tmp_path / "custom.yaml"
        cfg.write_text(yaml.dump({"log_level": "error"}))
        os.environ["S_PEACH_CONFIG"] = str(cfg)
        s = load_settings()
        assert s.log_level == "error"

    def test_env_override_nonexistent_raises(self, tmp_path: Path) -> None:
        """$S_PEACH_CONFIG pointing to missing file raises FileNotFoundError."""
        os.environ["S_PEACH_CONFIG"] = str(tmp_path / "nonexistent.yaml")
        with pytest.raises(FileNotFoundError, match="S_PEACH_CONFIG"):
            load_settings()

    def test_local_config_preferred_over_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """./server.yaml is preferred over ~/.config/s-peach/server.yaml."""
        # Create local config
        monkeypatch.chdir(tmp_path)
        local_cfg = tmp_path / "server.yaml"
        local_cfg.write_text(yaml.dump({"log_level": "debug"}))

        # Create XDG config with different setting
        xdg_dir = tmp_path / "xdg_config" / "s-peach"
        xdg_dir.mkdir(parents=True)
        xdg_cfg = xdg_dir / "server.yaml"
        xdg_cfg.write_text(yaml.dump({"log_level": "error"}))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

        s = load_settings()
        assert s.log_level == "debug"  # local wins

    def test_xdg_config_used_when_no_local(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """~/.config/s-peach/server.yaml is used when no local config exists."""
        # chdir to a dir without server.yaml
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.chdir(empty_dir)

        # Create XDG config
        xdg_dir = tmp_path / "xdg_config" / "s-peach"
        xdg_dir.mkdir(parents=True)
        xdg_cfg = xdg_dir / "server.yaml"
        xdg_cfg.write_text(yaml.dump({"log_level": "error"}))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

        s = load_settings()
        assert s.log_level == "error"

    def test_defaults_when_no_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Built-in defaults used when no config file exists anywhere."""
        monkeypatch.chdir(tmp_path)
        # Point XDG to empty dir
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_empty"))
        s = load_settings()
        assert s.server.port == 7777
        assert s.log_level == "info"

    def test_load_settings_logs_config_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_settings() logs which config file was loaded."""
        cfg = tmp_path / "test.yaml"
        cfg.write_text(yaml.dump({"log_level": "debug"}))
        os.environ["S_PEACH_CONFIG"] = str(cfg)

        with patch("s_peach.config.logger") as mock_logger:
            load_settings()
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "config_loaded"
            assert str(cfg) in str(call_args)

    def test_load_settings_logs_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_settings() logs 'using defaults' when no config found."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_empty"))

        with patch("s_peach.config.logger") as mock_logger:
            load_settings()
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "config_using_defaults"

