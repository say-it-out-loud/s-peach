"""Tests for automatic config scaffolding on first run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.cli.conftest import run_main


class TestAutoInit:
    """Auto-init scaffolds config when config dir doesn't exist."""

    def test_serve_auto_inits_when_no_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Commands that need config auto-scaffold on first run."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        assert not (xdg / "s-peach").exists()

        with patch("uvicorn.run"):
            code, _, err = run_main("serve")

        cfg_dir = xdg / "s-peach"
        assert cfg_dir.exists()
        assert (cfg_dir / "server.yaml").exists()
        assert (cfg_dir / "client.yaml").exists()
        assert "First run detected" in err

    def test_auto_init_skips_when_config_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No auto-init if config dir already exists."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        (xdg / "s-peach").mkdir(parents=True)

        with patch("uvicorn.run"):
            _, _, err = run_main("serve")

        assert "First run detected" not in err

    def test_init_command_does_not_trigger_auto_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 'init' command itself should not trigger auto-init."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        code, _, err = run_main("init")

        assert "First run detected" not in err
        assert code == 0

    def test_doctor_does_not_trigger_auto_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 'doctor' command should not trigger auto-init."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        _, _, err = run_main("doctor")

        assert "First run detected" not in err

    def test_auto_init_hint_on_scaffolding_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If auto-scaffolding fails, print a hint instead of crashing."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        with (
            patch("s_peach.scaffolding.init_scaffolding", side_effect=OSError("boom")),
            patch("uvicorn.run"),
        ):
            code, _, err = run_main("serve")

        assert "s-peach init" in err
        assert code == 0
