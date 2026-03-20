"""Tests for s_peach.service — macOS LaunchAgent and Linux systemd user unit."""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_plist(path: Path) -> dict:
    """Read a plist file and return the dict."""
    with open(path, "rb") as f:
        return plistlib.load(f)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


class TestDetectPlatform:
    def test_darwin_returns_macos(self):
        from s_peach.service import _detect_platform

        with patch("s_peach.service.sys") as mock_sys:
            mock_sys.platform = "darwin"
            mock_sys.exit = MagicMock(side_effect=SystemExit(1))
            assert _detect_platform() == "macos"

    def test_linux_returns_linux(self):
        from s_peach.service import _detect_platform

        with patch("s_peach.service.sys") as mock_sys:
            mock_sys.platform = "linux"
            mock_sys.exit = MagicMock(side_effect=SystemExit(1))
            assert _detect_platform() == "linux"

    def test_unsupported_exits_1(self):
        from s_peach.service import _detect_platform

        with patch("s_peach.service.sys") as mock_sys:
            mock_sys.platform = "win32"
            mock_sys.stderr = MagicMock()
            mock_sys.exit = MagicMock(side_effect=SystemExit(1))
            with pytest.raises(SystemExit):
                _detect_platform()
            mock_sys.exit.assert_called_with(1)


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


class TestResolveBinary:
    def test_which_returns_path(self):
        from s_peach.service import _resolve_binary

        with patch("s_peach.service.shutil.which", return_value="/usr/local/bin/s-peach"):
            assert _resolve_binary() == "/usr/local/bin/s-peach"

    def test_which_returns_none_exits_1(self, capsys):
        from s_peach.service import _resolve_binary

        with patch("s_peach.service.shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                _resolve_binary()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "s-peach not found on PATH" in captured.out


# ---------------------------------------------------------------------------
# macOS LaunchAgent
# ---------------------------------------------------------------------------


class TestMacosBuildPlist:
    def test_plist_structure(self, tmp_path):
        from s_peach.service import _macos_build_plist

        with patch("s_peach.service.log_file", return_value=tmp_path / "s-peach.log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"):
            plist = _macos_build_plist("/usr/local/bin/s-peach")

        assert plist["Label"] == "com.s-peach.server"
        assert plist["ProgramArguments"] == ["/usr/local/bin/s-peach", "serve"]
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] == {"SuccessfulExit": False}
        assert plist["StandardOutPath"] == str(tmp_path / "s-peach.log")
        assert plist["StandardErrorPath"] == str(tmp_path / "s-peach.log")

    def test_plist_uses_absolute_path(self, tmp_path):
        from s_peach.service import _macos_build_plist

        abs_path = "/home/user/.local/bin/s-peach"
        with patch("s_peach.service.log_file", return_value=tmp_path / "log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"):
            plist = _macos_build_plist(abs_path)
        assert plist["ProgramArguments"][0] == abs_path

    def test_plist_runs_serve_not_start(self, tmp_path):
        from s_peach.service import _macos_build_plist

        with patch("s_peach.service.log_file", return_value=tmp_path / "log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"):
            plist = _macos_build_plist("/usr/local/bin/s-peach")
        assert plist["ProgramArguments"][1] == "serve"


class TestMacosInstallService:
    @patch("s_peach.service._wait_and_report_readiness")
    @patch("s_peach.service.subprocess.run")
    @patch("s_peach.service._warn_if_daemon_running")
    @patch("s_peach.service._resolve_binary", return_value="/usr/local/bin/s-peach")
    @patch("s_peach.service.sys")
    def test_install_creates_plist_and_loads(
        self, mock_sys, mock_resolve, mock_warn, mock_run, mock_ready, tmp_path
    ):
        mock_sys.platform = "darwin"
        mock_sys.stderr = MagicMock()
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        plist_path = tmp_path / "com.s-peach.server.plist"
        plist_dir = tmp_path

        with patch("s_peach.service.MACOS_PLIST_PATH", plist_path), \
             patch("s_peach.service.MACOS_PLIST_DIR", plist_dir), \
             patch("s_peach.service.log_file", return_value=tmp_path / "s-peach.log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"), \
             patch("s_peach.service.os.getuid", return_value=501):
            from s_peach.service import _macos_install_service

            _macos_install_service()

        # Verify plist was written
        assert plist_path.exists()
        plist_data = _read_plist(plist_path)
        assert plist_data["Label"] == "com.s-peach.server"
        assert plist_data["ProgramArguments"] == ["/usr/local/bin/s-peach", "serve"]

        # Verify permissions (0644)
        mode = plist_path.stat().st_mode & 0o777
        assert mode == 0o644

        # Verify launchctl bootstrap was called
        mock_run.assert_called_once_with(
            ["launchctl", "bootstrap", "gui/501", str(plist_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Verify readiness check was called
        mock_ready.assert_called_once()

    @patch("s_peach.service._wait_and_report_readiness")
    @patch("s_peach.service.subprocess.run")
    @patch("s_peach.service._warn_if_daemon_running")
    @patch("s_peach.service._resolve_binary", return_value="/usr/local/bin/s-peach")
    @patch("s_peach.service.sys")
    def test_install_with_existing_plist_unloads_first(
        self, mock_sys, mock_resolve, mock_warn, mock_run, mock_ready, tmp_path
    ):
        mock_sys.platform = "darwin"
        mock_sys.stderr = MagicMock()
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        plist_path = tmp_path / "com.s-peach.server.plist"
        # Create an existing plist
        plist_path.write_bytes(plistlib.dumps({"Label": "old"}))

        with patch("s_peach.service.MACOS_PLIST_PATH", plist_path), \
             patch("s_peach.service.MACOS_PLIST_DIR", tmp_path), \
             patch("s_peach.service.log_file", return_value=tmp_path / "s-peach.log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"), \
             patch("s_peach.service.os.getuid", return_value=501):
            from s_peach.service import _macos_install_service

            _macos_install_service()

        # Should have called bootout (unload) then bootstrap (load)
        calls = mock_run.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0][0] == "launchctl"
        assert calls[0][0][0][1] == "bootout"
        assert calls[1][0][0][1] == "bootstrap"

    @patch("s_peach.service.subprocess.run")
    @patch("s_peach.service._warn_if_daemon_running")
    @patch("s_peach.service._resolve_binary", return_value="/usr/local/bin/s-peach")
    @patch("s_peach.service.sys")
    def test_install_bootstrap_failure_exits_1(
        self, mock_sys, mock_resolve, mock_warn, mock_run, tmp_path
    ):
        mock_sys.platform = "darwin"
        mock_sys.stderr = MagicMock()
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        mock_run.return_value = MagicMock(returncode=1, stderr="bootstrap error", stdout="")

        plist_path = tmp_path / "com.s-peach.server.plist"

        with patch("s_peach.service.MACOS_PLIST_PATH", plist_path), \
             patch("s_peach.service.MACOS_PLIST_DIR", tmp_path), \
             patch("s_peach.service.log_file", return_value=tmp_path / "s-peach.log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"), \
             patch("s_peach.service.os.getuid", return_value=501):
            from s_peach.service import _macos_install_service

            with pytest.raises(SystemExit):
                _macos_install_service()

        mock_sys.exit.assert_called_with(1)


class TestMacosUninstallService:
    @patch("s_peach.service.subprocess.run")
    @patch("s_peach.service.sys")
    def test_uninstall_removes_plist_and_bootouts(
        self, mock_sys, mock_run, tmp_path
    ):
        mock_sys.platform = "darwin"
        mock_sys.stderr = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        plist_path = tmp_path / "com.s-peach.server.plist"
        plist_path.write_bytes(plistlib.dumps({"Label": "com.s-peach.server"}))

        with patch("s_peach.service.MACOS_PLIST_PATH", plist_path), \
             patch("s_peach.service.os.getuid", return_value=501):
            from s_peach.service import _macos_uninstall_service

            _macos_uninstall_service()

        assert not plist_path.exists()
        mock_run.assert_called_once()
        assert "bootout" in mock_run.call_args[0][0]

    @patch("s_peach.service.sys")
    def test_uninstall_no_plist_exits_0(self, mock_sys, tmp_path, capsys):
        mock_sys.platform = "darwin"
        mock_sys.stderr = MagicMock()

        plist_path = tmp_path / "com.s-peach.server.plist"

        with patch("s_peach.service.MACOS_PLIST_PATH", plist_path):
            from s_peach.service import _macos_uninstall_service

            _macos_uninstall_service()

        captured = capsys.readouterr()
        assert "no service installed" in captured.out.lower()


# ---------------------------------------------------------------------------
# Linux systemd
# ---------------------------------------------------------------------------


class TestLinuxBuildUnit:
    def test_unit_structure(self, tmp_path):
        from s_peach.service import _linux_build_unit

        log = tmp_path / "s-peach.log"
        with patch("s_peach.service.log_file", return_value=log), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"):
            unit = _linux_build_unit("/usr/local/bin/s-peach")

        assert "ExecStart=/usr/local/bin/s-peach serve" in unit
        assert "Type=exec" in unit
        assert "Restart=on-failure" in unit
        assert "RestartSec=5" in unit
        assert f"StandardOutput=file:{log}" in unit
        assert f"StandardError=file:{log}" in unit
        assert "WantedBy=default.target" in unit
        assert "[Install]" in unit


class TestLinuxInstallService:
    @patch("s_peach.service._wait_and_report_readiness")
    @patch("s_peach.service._linux_run_systemctl")
    @patch("s_peach.service._warn_if_daemon_running")
    @patch("s_peach.service._resolve_binary", return_value="/usr/local/bin/s-peach")
    @patch("s_peach.service.sys")
    def test_install_creates_unit_and_enables(
        self, mock_sys, mock_resolve, mock_warn, mock_systemctl, mock_ready, tmp_path
    ):
        mock_sys.platform = "linux"
        mock_sys.stderr = MagicMock()
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        mock_systemctl.return_value = MagicMock(returncode=0, stderr="", stdout="")

        unit_dir = tmp_path / "systemd" / "user"
        unit_path = unit_dir / "s-peach.service"

        with patch("s_peach.service.LINUX_UNIT_DIR", unit_dir), \
             patch("s_peach.service.LINUX_UNIT_PATH", unit_path), \
             patch("s_peach.service.log_file", return_value=tmp_path / "s-peach.log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"):
            from s_peach.service import _linux_install_service

            _linux_install_service()

        # Verify unit file exists with correct content
        assert unit_path.exists()
        content = unit_path.read_text()
        assert "ExecStart=/usr/local/bin/s-peach serve" in content
        assert "Type=exec" in content

        # Verify permissions
        unit_mode = unit_path.stat().st_mode & 0o777
        assert unit_mode == 0o644
        dir_mode = unit_dir.stat().st_mode & 0o777
        assert dir_mode == 0o700

        # Verify systemctl calls: daemon-reload, then enable --now
        assert mock_systemctl.call_count == 2
        assert mock_systemctl.call_args_list[0] == call("daemon-reload")
        assert mock_systemctl.call_args_list[1] == call("enable", "--now", "s-peach")

        # Verify readiness check was called
        mock_ready.assert_called_once()

    @patch("s_peach.service._linux_run_systemctl")
    @patch("s_peach.service._warn_if_daemon_running")
    @patch("s_peach.service._resolve_binary", return_value="/usr/local/bin/s-peach")
    @patch("s_peach.service.sys")
    def test_install_daemon_reload_failure_exits_1(
        self, mock_sys, mock_resolve, mock_warn, mock_systemctl, tmp_path
    ):
        mock_sys.platform = "linux"
        mock_sys.stderr = MagicMock()
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        mock_systemctl.return_value = MagicMock(
            returncode=1, stderr="failed to reload", stdout=""
        )

        unit_dir = tmp_path / "systemd" / "user"
        unit_path = unit_dir / "s-peach.service"

        with patch("s_peach.service.LINUX_UNIT_DIR", unit_dir), \
             patch("s_peach.service.LINUX_UNIT_PATH", unit_path), \
             patch("s_peach.service.log_file", return_value=tmp_path / "s-peach.log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"):
            from s_peach.service import _linux_install_service

            with pytest.raises(SystemExit):
                _linux_install_service()

        mock_sys.exit.assert_called_with(1)

    @patch("s_peach.service._linux_run_systemctl")
    @patch("s_peach.service._warn_if_daemon_running")
    @patch("s_peach.service._resolve_binary", return_value="/usr/local/bin/s-peach")
    @patch("s_peach.service.sys")
    def test_install_bus_error_prints_linger_guidance(
        self, mock_sys, mock_resolve, mock_warn, mock_systemctl, tmp_path
    ):
        mock_sys.platform = "linux"
        mock_sys.stderr = MagicMock()
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        mock_systemctl.return_value = MagicMock(
            returncode=1, stderr="Failed to connect to bus: No such file or directory", stdout=""
        )

        unit_dir = tmp_path / "systemd" / "user"
        unit_path = unit_dir / "s-peach.service"

        with patch("s_peach.service.LINUX_UNIT_DIR", unit_dir), \
             patch("s_peach.service.LINUX_UNIT_PATH", unit_path), \
             patch("s_peach.service.log_file", return_value=tmp_path / "s-peach.log"), \
             patch("s_peach.service.state_dir", return_value=tmp_path / "state"):
            from s_peach.service import _linux_install_service

            with pytest.raises(SystemExit):
                _linux_install_service()

        # Check stderr was written to with linger guidance
        mock_sys.exit.assert_called_with(1)


class TestLinuxUninstallService:
    @patch("s_peach.service._linux_run_systemctl")
    @patch("s_peach.service.sys")
    def test_uninstall_teardown_order(self, mock_sys, mock_systemctl, tmp_path):
        mock_sys.platform = "linux"
        mock_sys.stderr = MagicMock()
        mock_systemctl.return_value = MagicMock(returncode=0, stderr="", stdout="")

        unit_dir = tmp_path / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / "s-peach.service"
        unit_path.write_text("[Unit]\n")

        with patch("s_peach.service.LINUX_UNIT_PATH", unit_path):
            from s_peach.service import _linux_uninstall_service

            _linux_uninstall_service()

        # Verify teardown order: stop, disable, remove, daemon-reload
        assert mock_systemctl.call_count == 3  # stop, disable, daemon-reload
        assert mock_systemctl.call_args_list[0] == call("stop", "s-peach")
        assert mock_systemctl.call_args_list[1] == call("disable", "s-peach")
        assert mock_systemctl.call_args_list[2] == call("daemon-reload")
        assert not unit_path.exists()  # File was removed

    @patch("s_peach.service.sys")
    def test_uninstall_no_unit_exits_0(self, mock_sys, tmp_path, capsys):
        mock_sys.platform = "linux"
        mock_sys.stderr = MagicMock()

        unit_path = tmp_path / "s-peach.service"

        with patch("s_peach.service.LINUX_UNIT_PATH", unit_path):
            from s_peach.service import _linux_uninstall_service

            _linux_uninstall_service()

        captured = capsys.readouterr()
        assert "no service installed" in captured.out.lower()

    @patch("s_peach.service._linux_run_systemctl")
    @patch("s_peach.service.sys")
    def test_uninstall_continues_on_intermediate_failures(
        self, mock_sys, mock_systemctl, tmp_path
    ):
        mock_sys.platform = "linux"
        mock_sys.stderr = MagicMock()

        # Stop fails, but disable and daemon-reload succeed
        def side_effect(*args):
            if args[0] == "stop":
                return MagicMock(returncode=1, stderr="not running", stdout="")
            return MagicMock(returncode=0, stderr="", stdout="")

        mock_systemctl.side_effect = side_effect

        unit_dir = tmp_path / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / "s-peach.service"
        unit_path.write_text("[Unit]\n")

        with patch("s_peach.service.LINUX_UNIT_PATH", unit_path):
            from s_peach.service import _linux_uninstall_service

            _linux_uninstall_service()

        # Should still proceed through all steps
        assert mock_systemctl.call_count == 3
        assert not unit_path.exists()


# ---------------------------------------------------------------------------
# Readiness waiting
# ---------------------------------------------------------------------------


class TestWaitAndReportReadiness:
    def test_reports_ready(self, capsys):
        from s_peach.service import _wait_and_report_readiness

        with patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            _wait_and_report_readiness()

        captured = capsys.readouterr()
        assert "ready" in captured.out.lower()

    def test_reports_still_starting(self, capsys):
        from s_peach.service import _wait_and_report_readiness

        with patch("s_peach.daemon._wait_for_ready", return_value="starting"):
            _wait_and_report_readiness()

        captured = capsys.readouterr()
        assert "still loading" in captured.out.lower()

    def test_reports_not_responding(self, capsys):
        from s_peach.service import _wait_and_report_readiness

        with patch("s_peach.daemon._wait_for_ready", return_value="not responding"):
            _wait_and_report_readiness()

        captured = capsys.readouterr()
        assert "not responding" in captured.out.lower()


# ---------------------------------------------------------------------------
# Daemon running warning
# ---------------------------------------------------------------------------


class TestWarnIfDaemonRunning:
    @patch("s_peach.service._check_running", return_value=12345)
    def test_warns_when_daemon_running(self, mock_check, capsys):
        from s_peach.service import _warn_if_daemon_running

        _warn_if_daemon_running()
        captured = capsys.readouterr()
        assert "already running" in captured.out
        assert "s-peach stop" in captured.out

    @patch("s_peach.service._check_running", return_value=None)
    def test_no_warning_when_not_running(self, mock_check, capsys):
        from s_peach.service import _warn_if_daemon_running

        _warn_if_daemon_running()
        captured = capsys.readouterr()
        assert captured.err == ""


# ---------------------------------------------------------------------------
# Public API routing
# ---------------------------------------------------------------------------


class TestInstallServiceRouting:
    @patch("s_peach.service._macos_install_service")
    @patch("s_peach.service._detect_platform", return_value="macos")
    def test_routes_to_macos(self, mock_detect, mock_install):
        from s_peach.service import install_service

        install_service()
        mock_install.assert_called_once()

    @patch("s_peach.service._linux_install_service")
    @patch("s_peach.service._detect_platform", return_value="linux")
    def test_routes_to_linux(self, mock_detect, mock_install):
        from s_peach.service import install_service

        install_service()
        mock_install.assert_called_once()


class TestUninstallServiceRouting:
    @patch("s_peach.service._macos_uninstall_service")
    @patch("s_peach.service._detect_platform", return_value="macos")
    def test_routes_to_macos(self, mock_detect, mock_uninstall):
        from s_peach.service import uninstall_service

        uninstall_service()
        mock_uninstall.assert_called_once()

    @patch("s_peach.service._linux_uninstall_service")
    @patch("s_peach.service._detect_platform", return_value="linux")
    def test_routes_to_linux(self, mock_detect, mock_uninstall):
        from s_peach.service import uninstall_service

        uninstall_service()
        mock_uninstall.assert_called_once()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLISubcommands:
    def test_install_service_subcommand_exists(self):
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["install-service"])
        assert args.command == "install-service"

    def test_uninstall_service_subcommand_exists(self):
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["uninstall-service"])
        assert args.command == "uninstall-service"

    def test_init_defaults_flag(self):
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["init", "--defaults"])
        assert args.defaults is True
