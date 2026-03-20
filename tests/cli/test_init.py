"""Tests for CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.conftest import run_main


class TestInit:
    def test_init_creates_both_configs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        code, out, _ = run_main("init")

        assert code == 0
        cfg_dir = tmp_path / "xdg" / "s-peach"
        server_cfg = cfg_dir / "server.yaml"
        notifier_cfg = cfg_dir / "client.yaml"
        assert server_cfg.exists()
        assert notifier_cfg.exists()

    def test_init_files_have_mode_0600(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        run_main("init")

        cfg_dir = tmp_path / "xdg" / "s-peach"
        for name in ("server.yaml", "client.yaml"):
            f = cfg_dir / name
            mode = f.stat().st_mode & 0o777
            assert mode == 0o600, f"{name} has mode {oct(mode)}, expected 0o600"

    def test_init_generates_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """init replaces placeholder with a generated random API key in both configs."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        run_main("init")

        cfg_dir = tmp_path / "xdg" / "s-peach"
        server_content = (cfg_dir / "server.yaml").read_text()
        notifier_content = (cfg_dir / "client.yaml").read_text()

        # Placeholder must not appear in either file
        assert "your-secret-key" not in server_content
        assert "your-secret-key" not in notifier_content

        # Both should contain an api_key line with the same generated key
        import yaml
        server_yaml = yaml.safe_load(server_content)
        notifier_yaml = yaml.safe_load(notifier_content)
        assert server_yaml["api_key"] is not None
        assert len(server_yaml["api_key"]) == 64  # 32 bytes hex
        assert server_yaml["api_key"] == notifier_yaml["api_key"]

    def test_init_server_config_has_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        run_main("init")

        content = (tmp_path / "xdg" / "s-peach" / "server.yaml").read_text()
        assert "enabled_models:" in content
        assert "voices:" in content
        assert "log_level:" in content
        assert "kokoro:" in content

    def test_init_notifier_config_has_documented_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        run_main("init")

        content = (tmp_path / "xdg" / "s-peach" / "client.yaml").read_text()
        assert "host" in content
        assert "port" in content
        assert "api_key" in content
        assert "summary" in content
        assert "claude" in content.lower() or "Claude" in content

    def test_init_creates_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        xdg_dir = tmp_path / "nonexistent" / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))
        code, _, _ = run_main("init")

        assert code == 0
        assert (xdg_dir / "s-peach" / "server.yaml").exists()

    def test_init_refuses_overwrite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        # Create first
        run_main("init")
        # Try again
        code, _, err = run_main("init")
        assert code == 1
        assert "already exists" in err

    def test_init_force_backs_up_and_overwrites(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        # Create first
        run_main("init")
        cfg_dir = tmp_path / "xdg" / "s-peach"
        server_cfg = cfg_dir / "server.yaml"
        # Modify original to verify backup
        server_cfg.write_text("original content")

        # Force overwrite
        code, out, _ = run_main("init", "--force")
        assert code == 0
        assert "Backed up" in out

        # Check backup exists
        bak = cfg_dir / "server.yaml.bak"
        assert bak.exists()
        assert bak.read_text() == "original content"

        # Check new file has template content
        assert "s-peach Server Configuration" in server_cfg.read_text()

