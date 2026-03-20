"""Tests for CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from tests.cli.conftest import run_main


class TestConfig:
    def test_config_bare_shows_help(self) -> None:
        code, out, _ = run_main("config")
        assert code == 0
        assert "server" in out
        assert "client" in out

    def test_config_server_opens_editor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("VISUAL", "cat")
        # Create config first
        run_main("init")

        with (
            patch("s_peach.cli.init.subprocess.run") as mock_run,
            patch("s_peach.cli.init.httpx.post", side_effect=httpx.ConnectError("no server")),
        ):
            code, _, _ = run_main("config", "server", "--url", "http://localhost:9999")

        # Editor was called with shlex.split("cat") + [path]
        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "cat"
        assert "server.yaml" in cmd[1]

    def test_config_server_uses_visual_over_editor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("VISUAL", "nano")
        monkeypatch.setenv("EDITOR", "vim")
        run_main("init")

        with (
            patch("s_peach.cli.init.subprocess.run") as mock_run,
            patch("s_peach.cli.init.httpx.post", side_effect=httpx.ConnectError("no")),
        ):
            run_main("config", "server", "--url", "http://localhost:9999")

        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "nano"

    def test_config_server_posts_reload_after_edit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("VISUAL", "true")  # no-op editor
        run_main("init")

        with (
            patch("s_peach.cli.init.subprocess.run"),
            patch("s_peach.cli.init.httpx.post") as mock_post,
        ):
            mock_post.return_value = httpx.Response(
                status_code=200,
                json={"status": "reloaded", "changes": ["voices"]},
            )
            code, out, _ = run_main("config", "server", "--url", "http://localhost:9999")

        assert code == 0
        mock_post.assert_called_once()
        assert "/reload" in mock_post.call_args.args[0]

    def test_config_server_error_if_no_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        # Pre-create dir so auto-init doesn't trigger, but leave files absent
        (tmp_path / "xdg" / "s-peach").mkdir(parents=True)
        code, _, err = run_main("config", "server")
        assert code == 1
        assert "does not exist" in err
        assert "s-peach init" in err

    def test_config_client_opens_notifier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("VISUAL", "cat")
        run_main("init")

        with patch("s_peach.cli.init.subprocess.run") as mock_run:
            code, _, _ = run_main("config", "client")

        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0]
        assert "client.yaml" in cmd[1]

    def test_config_client_error_if_no_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        # Pre-create dir so auto-init doesn't trigger, but leave files absent
        (tmp_path / "xdg" / "s-peach").mkdir(parents=True)
        code, _, err = run_main("config", "client")
        assert code == 1
        assert "does not exist" in err
        assert "s-peach init" in err

    def test_editor_command_injection_safe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Editor env var with injection attempt is handled safely via shlex.split."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("EDITOR", "echo injected;")
        run_main("init")

        with (
            patch("s_peach.cli.init.subprocess.run") as mock_run,
            patch("s_peach.cli.init.httpx.post", side_effect=httpx.ConnectError("no")),
        ):
            run_main("config", "server", "--url", "http://localhost:9999")

        # shlex.split("echo injected;") => ["echo", "injected;"]
        # subprocess.run is called without shell=True, so "injected;" is just an arg
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "echo"
        assert cmd[1] == "injected;"
        assert mock_run.call_args.kwargs.get("shell") is not True


class TestReload:
    def test_reload_posts_to_server(self) -> None:
        with patch("s_peach.cli.init.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=200,
                json={"status": "reloaded", "changes": ["voices"]},
            )
            code, out, _ = run_main("reload", "--url", "http://localhost:9999")

        assert code == 0
        assert "reloaded" in out.lower()
        assert mock_post.call_args.args[0] == "http://localhost:9999/reload"

    def test_reload_prints_confirmation(self) -> None:
        with patch("s_peach.cli.init.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=200,
                json={"status": "reloaded", "changes": ["voices", "loaded:kokoro"]},
            )
            code, out, _ = run_main("reload", "--url", "http://localhost:9999")

        assert code == 0
        assert "Config reloaded." in out

    def test_reload_connection_error(self) -> None:
        with patch(
            "s_peach.cli.init.httpx.post",
            side_effect=httpx.ConnectError("refused"),
        ):
            code, _, err = run_main("reload", "--url", "http://localhost:9999")

        assert code == 1
        assert "cannot connect" in err.lower()

    def test_reload_sends_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S_PEACH_API_KEY", "secret123")
        with patch("s_peach.cli.init.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=200,
                json={"status": "reloaded", "changes": []},
            )
            code, _, _ = run_main(
                "reload", "--url", "http://localhost:9999"
            )

        assert code == 0
        assert mock_post.call_args.kwargs["headers"]["X-API-Key"] == "secret123"

    def test_reload_env_var_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S_PEACH_API_KEY", "env-key")
        with patch("s_peach.cli.init.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=200,
                json={"status": "reloaded", "changes": []},
            )
            code, _, _ = run_main("reload", "--url", "http://localhost:9999")

        assert code == 0
        assert mock_post.call_args.kwargs["headers"]["X-API-Key"] == "env-key"

    def test_reload_server_error(self) -> None:
        with patch("s_peach.cli.init.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=500,
                json={"detail": "Config reload failed: bad YAML"},
            )
            code, _, err = run_main("reload", "--url", "http://localhost:9999")

        assert code == 1
        assert "bad YAML" in err

