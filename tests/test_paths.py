"""Tests for XDG path resolution."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from s_peach import paths


@pytest.fixture(autouse=True)
def _clean_xdg_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove XDG env vars to isolate tests."""
    for key in (
        "XDG_CONFIG_HOME",
        "XDG_RUNTIME_DIR",
        "XDG_STATE_HOME",
    ):
        monkeypatch.delenv(key, raising=False)


class TestConfigDir:
    def test_default_returns_home_config(self) -> None:
        result = paths.config_dir()
        expected = Path.home() / ".config" / "s-peach"
        assert result == expected.resolve()
        assert isinstance(result, Path)

    def test_xdg_config_home_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
        result = paths.config_dir()
        assert result == Path("/tmp/xdg/s-peach").resolve()

    def test_returns_path_object(self) -> None:
        assert isinstance(paths.config_dir(), Path)


class TestRuntimeDir:
    def test_xdg_runtime_dir_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        result = paths.runtime_dir()
        assert result == Path("/run/user/1000/s-peach").resolve()

    def test_fallback_to_tmp_with_uid(self) -> None:
        # XDG_RUNTIME_DIR is cleared by autouse fixture
        result = paths.runtime_dir()
        uid = os.getuid()
        assert result == Path(f"/tmp/s-peach-{uid}").resolve()


class TestStateDir:
    def test_default_returns_home_state(self) -> None:
        result = paths.state_dir()
        expected = Path.home() / ".local" / "state" / "s-peach"
        assert result == expected.resolve()

    def test_xdg_state_home_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", "/tmp/state")
        result = paths.state_dir()
        assert result == Path("/tmp/state/s-peach").resolve()


class TestFilePaths:
    def test_config_file(self) -> None:
        assert paths.config_file() == paths.config_dir() / "server.yaml"

    def test_notifier_file(self) -> None:
        assert paths.notifier_file() == paths.config_dir() / "client.yaml"

    def test_claude_config_dir(self) -> None:
        assert paths.claude_config_dir() == paths.config_dir() / ".claude"

    def test_claude_settings_file(self) -> None:
        assert paths.claude_settings_file() == paths.claude_config_dir() / "settings.json"

    def test_pid_file(self) -> None:
        assert paths.pid_file() == paths.runtime_dir() / "s-peach.pid"

    def test_log_file(self) -> None:
        assert paths.log_file() == paths.state_dir() / "s-peach.log"


class TestPathNormalization:
    def test_paths_are_resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All paths should be resolved (no '..' components)."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/../tmp/xdg")
        result = paths.config_dir()
        assert ".." not in str(result)
        assert result == Path("/tmp/xdg/s-peach").resolve()


class TestHomeNotSet:
    def test_config_dir_raises_on_missing_home(self) -> None:
        with patch.object(Path, "home", side_effect=RuntimeError("no home")):
            with pytest.raises(RuntimeError, match="Cannot determine home directory"):
                paths.config_dir()

    def test_state_dir_raises_on_missing_home(self) -> None:
        with patch.object(Path, "home", side_effect=RuntimeError("no home")):
            with pytest.raises(RuntimeError, match="Cannot determine home directory"):
                paths.state_dir()

    def test_runtime_dir_works_without_home(self) -> None:
        """runtime_dir() uses /tmp fallback, doesn't need $HOME."""
        # Just verify it doesn't raise
        result = paths.runtime_dir()
        assert isinstance(result, Path)
