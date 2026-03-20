"""Tests for CLI commands."""

from __future__ import annotations

from unittest.mock import patch

from tests.cli.conftest import run_main


class TestInstallHookCLI:
    def test_install_hook_no_target_exits_1(self) -> None:
        """install-hook with no argument prints error and exits 1."""
        code, _, err = run_main("install-hook")
        assert code == 1
        assert "missing hook target" in err.lower()
        assert "claude-code" in err

    def test_install_hook_unknown_target_exits_1(self) -> None:
        """install-hook with unknown target prints error and exits 1."""
        code, _, err = run_main("install-hook", "vscode")
        assert code == 1
        assert "unknown hook target" in err.lower()
        assert "claude-code" in err

    def test_install_hook_claude_code_calls_install(self) -> None:
        """install-hook claude-code delegates to hooks.install_hook."""
        with patch("s_peach.hooks.install_hook") as mock_install:
            code, _, _ = run_main("install-hook", "claude-code")

        assert code == 0
        mock_install.assert_called_once_with(target=None)

    def test_install_hook_claude_code_with_target_flag(self) -> None:
        """install-hook claude-code --target passes through."""
        with patch("s_peach.hooks.install_hook") as mock_install:
            code, _, _ = run_main(
                "install-hook", "claude-code", "--target", "settings.json"
            )

        assert code == 0
        mock_install.assert_called_once_with(target="settings.json")

    def test_uninstall_hook_no_target_exits_1(self) -> None:
        """uninstall-hook with no argument prints error and exits 1."""
        code, _, err = run_main("uninstall-hook")
        assert code == 1
        assert "missing hook target" in err.lower()
        assert "claude-code" in err

    def test_uninstall_hook_unknown_target_exits_1(self) -> None:
        """uninstall-hook with unknown target prints error and exits 1."""
        code, _, err = run_main("uninstall-hook", "zed")
        assert code == 1
        assert "unknown hook target" in err.lower()
        assert "claude-code" in err

    def test_uninstall_hook_claude_code_calls_uninstall(self) -> None:
        """uninstall-hook claude-code delegates to hooks.uninstall_hook."""
        with patch("s_peach.hooks.uninstall_hook") as mock_uninstall:
            code, _, _ = run_main("uninstall-hook", "claude-code")

        assert code == 0
        mock_uninstall.assert_called_once()

