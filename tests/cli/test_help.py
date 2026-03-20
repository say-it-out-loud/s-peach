"""Tests for CLI commands."""

from __future__ import annotations

from importlib.metadata import version
import subprocess
import sys

from tests.cli.conftest import run_main


class TestHelpAndVersion:
    def test_no_args_prints_help_exits_0(self) -> None:
        code, out, _ = run_main()
        assert code == 0
        assert "serve" in out
        assert "say" in out

    def test_version_flag(self) -> None:
        code, out, _ = run_main("--version")
        assert code == 0
        assert "s-peach" in out
        assert version("s-peach-tts") in out

    def test_help_lists_all_subcommands(self) -> None:
        """Help output lists all implemented subcommands."""
        code, out, _ = run_main()
        assert code == 0
        for cmd in ("serve", "say", "init", "config", "reload"):
            assert cmd in out, f"'{cmd}' not found in help output"


class TestUnknownCommand:
    def test_unknown_subcommand_exits_with_error(self) -> None:
        """Unknown subcommands should print help and exit with code != 0."""
        # argparse will raise SystemExit(2) for unrecognized arguments
        code, _, err = run_main("foobarbaz")
        # argparse treats unknown subcommands as positional args — this results
        # in an error since no positional is expected at the top level
        assert code != 0


class TestEntryPoint:
    def test_subprocess_main_module(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "s_peach.cli", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "s-peach" in result.stdout

