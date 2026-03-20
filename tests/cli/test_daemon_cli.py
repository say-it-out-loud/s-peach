"""Tests for daemon CLI command routing."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest

from s_peach.cli import main


class TestCLIRouting:
    """Test that cli dispatch correctly routes to daemon commands."""

    def test_start_routed(self) -> None:
        with patch("s_peach.daemon.start_daemon", return_value=0) as mock:
            with pytest.raises(SystemExit) as exc_info:
                main(["start"])
            assert exc_info.value.code == 0
            mock.assert_called_once()

    def test_stop_routed(self) -> None:
        with patch("s_peach.daemon.stop_daemon", return_value=0) as mock:
            with pytest.raises(SystemExit) as exc_info:
                main(["stop"])
            assert exc_info.value.code == 0
            mock.assert_called_once()

    def test_stop_force_flag(self) -> None:
        with patch("s_peach.daemon.stop_daemon", return_value=0) as mock:
            with pytest.raises(SystemExit) as exc_info:
                main(["stop", "--force"])
            assert exc_info.value.code == 0
            mock.assert_called_once_with(force=True)

    def test_restart_routed(self) -> None:
        with patch("s_peach.daemon.restart_daemon", return_value=0) as mock:
            with pytest.raises(SystemExit) as exc_info:
                main(["restart"])
            assert exc_info.value.code == 0
            mock.assert_called_once()

    def test_status_routed(self) -> None:
        with patch("s_peach.daemon.status_daemon", return_value=0) as mock:
            with pytest.raises(SystemExit) as exc_info:
                main(["status"])
            assert exc_info.value.code == 0
            mock.assert_called_once()

    def test_logs_routed(self) -> None:
        with patch("s_peach.daemon.logs_command", return_value=0) as mock:
            with pytest.raises(SystemExit) as exc_info:
                main(["logs", "--no-follow"])
            assert exc_info.value.code == 0
            mock.assert_called_once_with(lines=50, follow=False)

    def test_logs_custom_lines(self) -> None:
        with patch("s_peach.daemon.logs_command", return_value=0) as mock:
            with pytest.raises(SystemExit) as exc_info:
                main(["logs", "-n", "100", "--no-follow"])
            assert exc_info.value.code == 0
            mock.assert_called_once_with(lines=100, follow=False)

    def test_logs_negative_n_rejected(self) -> None:
        out = StringIO()
        err = StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            with pytest.raises(SystemExit) as exc_info:
                main(["logs", "-n", "-5", "--no-follow"])
            assert exc_info.value.code == 1
        assert "positive" in err.getvalue().lower()

    def test_help_includes_new_commands(self) -> None:
        out = StringIO()
        with patch("sys.stdout", out):
            with pytest.raises(SystemExit):
                main(["--help"])
        help_text = out.getvalue()
        for cmd in ("start", "stop", "restart", "status", "logs"):
            assert cmd in help_text, f"'{cmd}' not in help output"
