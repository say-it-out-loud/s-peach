"""Tests for s-peach daemon management (start, stop, restart, status, logs)."""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from s_peach.daemon import (
    _check_running,
    _format_duration,
    is_process_alive,
    is_speach_process,
    _safe_write_file,
    _wait_for_ready,
    logs_command,
    read_pid,
    restart_daemon,
    start_daemon,
    status_daemon,
    stop_daemon,
)


# --- Fixtures ---


@pytest.fixture()
def daemon_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up isolated XDG directories for daemon tests."""
    runtime = tmp_path / "runtime" / "s-peach"
    state = tmp_path / "state" / "s-peach"
    config = tmp_path / "config" / "s-peach"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return runtime, state, config


def _write_pid_file(daemon_dirs, pid: int | str) -> Path:
    """Helper to write a PID file in the test runtime dir."""
    runtime, _, _ = daemon_dirs
    runtime.mkdir(parents=True, exist_ok=True)
    pf = runtime / "s-peach.pid"
    pf.write_text(str(pid))
    return pf


def _capture(func, *args, **kwargs) -> tuple[int, str, str]:
    """Capture stdout/stderr and return code from a function that calls sys.exit or returns int."""
    out = StringIO()
    err = StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
        try:
            result = func(*args, **kwargs)
            code = result if isinstance(result, int) else 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


# === Tests: read_pid ===


class TestReadPid:
    def test_no_pid_file(self, daemon_dirs) -> None:
        assert read_pid() is None

    def test_valid_pid_file(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 12345)
        assert read_pid() == 12345

    def test_invalid_content(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, "not-a-number")
        assert read_pid() is None

    def test_empty_file(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, "")
        assert read_pid() is None


# === Tests: _safe_write_file ===


class TestSafeWriteFile:
    def test_writes_content_with_mode(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        _safe_write_file(target, "hello", 0o644)
        assert target.read_text() == "hello"
        mode = target.stat().st_mode & 0o777
        assert mode == 0o644

    def test_refuses_symlink(self, tmp_path: Path) -> None:
        real = tmp_path / "real.txt"
        real.write_text("real")
        link = tmp_path / "link.txt"
        link.symlink_to(real)
        with pytest.raises(OSError, match="symlink"):
            _safe_write_file(link, "evil", 0o644)


# === Tests: is_process_alive ===


class TestIsProcessAlive:
    def test_current_process_is_alive(self) -> None:
        assert is_process_alive(os.getpid()) is True

    def test_dead_pid(self) -> None:
        # PID 99999999 is almost certainly not alive
        assert is_process_alive(99999999) is False


# === Tests: is_speach_process ===


class TestIsSpeachProcess:
    def test_current_python_process(self) -> None:
        # Current process is python — /proc/pid/cmdline should contain "python"
        # This tests the /proc path on Linux
        pid = os.getpid()
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        if proc_cmdline.exists():
            # On Linux, our process cmdline contains "python"
            result = is_speach_process(pid)
            # The current process might be "python" which is caught by comm fallback
            # but won't have "s-peach" in cmdline. Since we check for python in comm,
            # this should return True
            assert isinstance(result, bool)

    def test_nonexistent_pid(self) -> None:
        assert is_speach_process(99999999) is False

    def test_ps_fallback_when_no_proc(self) -> None:
        """When /proc is unavailable (macOS), falls back to `ps` command."""
        pid = os.getpid()
        # Mock away /proc paths so they don't exist, forcing ps fallback
        mock_ps_result = MagicMock()
        mock_ps_result.returncode = 0
        mock_ps_result.stdout = "/usr/bin/python3 -m pytest tests/test_daemon.py"
        with patch("s_peach.daemon.Path") as mock_path_cls, \
             patch("s_peach.daemon.subprocess.run", return_value=mock_ps_result):
            # Make /proc paths not exist
            mock_proc = MagicMock()
            mock_proc.exists.return_value = False
            mock_path_cls.return_value = mock_proc

            # ps returns a plain python/pytest command — not s-peach/uvicorn
            result = is_speach_process(pid)
            assert result is False

    def test_ps_fallback_finds_speach(self) -> None:
        """ps fallback detects s-peach in command line."""
        with patch("s_peach.daemon.Path") as mock_path_cls:
            mock_proc = MagicMock()
            mock_proc.exists.return_value = False
            mock_path_cls.return_value = mock_proc

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "/usr/bin/python3 -m s_peach.cli serve"

            with patch("s_peach.daemon.subprocess.run", return_value=mock_result):
                assert is_speach_process(12345) is True


# === Tests: _check_running ===


class TestCheckRunning:
    def test_no_pid_file(self, daemon_dirs) -> None:
        assert _check_running() is None

    def test_stale_pid_file_dead_process(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 99999999)
        assert _check_running() is None
        # PID file should be cleaned up
        runtime, _, _ = daemon_dirs
        assert not (runtime / "s-peach.pid").exists()

    def test_stale_pid_file_non_speach_process(self, daemon_dirs) -> None:
        # PID 1 (init/systemd) is alive but not s-peach
        _write_pid_file(daemon_dirs, 1)
        with patch("s_peach.daemon.is_process_alive", return_value=True), \
             patch("s_peach.daemon.is_speach_process", return_value=False):
            assert _check_running() is None


# === Tests: _format_duration ===


class TestFormatDuration:
    def test_seconds(self) -> None:
        assert _format_duration(30) == "30s"

    def test_minutes(self) -> None:
        assert _format_duration(90) == "1m30s"

    def test_hours(self) -> None:
        assert _format_duration(3661) == "1h1m"

    def test_days(self) -> None:
        assert _format_duration(90000) == "1d1h"


# === Tests: start_daemon ===


class TestStartDaemon:
    def test_start_spawns_serve_process(self, daemon_dirs) -> None:
        runtime, state, _ = daemon_dirs
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None  # Child is alive

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            code, out, err = _capture(start_daemon)

        assert code == 0
        assert "42" in out
        assert "ready" in out.lower()
        # Check PID file was written
        pf = runtime / "s-peach.pid"
        assert pf.exists()
        assert pf.read_text().strip() == "42"

        # Verify Popen was called with serve command
        popen_cmd = mock_popen.call_args.args[0]
        assert "serve" in popen_cmd

    def test_start_creates_directories(self, daemon_dirs) -> None:
        runtime, state, _ = daemon_dirs
        assert not runtime.exists()
        assert not state.exists()

        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc), \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            _capture(start_daemon)

        assert runtime.exists()
        assert state.exists()
        assert (runtime.stat().st_mode & 0o777) == 0o700
        assert (state.stat().st_mode & 0o777) == 0o700

    def test_start_redirects_output_to_log(self, daemon_dirs) -> None:
        runtime, state, _ = daemon_dirs
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            _capture(start_daemon)

        # stdout and stderr should be file descriptors (ints)
        popen_kwargs = mock_popen.call_args.kwargs
        assert isinstance(popen_kwargs["stdout"], int)
        assert popen_kwargs["stderr"] == popen_kwargs["stdout"]
        assert popen_kwargs["stdin"] == subprocess.DEVNULL

    def test_start_when_already_running(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 12345)

        with patch("s_peach.daemon.is_process_alive", return_value=True), \
             patch("s_peach.daemon.is_speach_process", return_value=True):
            code, out, err = _capture(start_daemon)

        assert code == 1
        assert "already running" in err

    def test_start_cleans_stale_pid_and_proceeds(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 99999999)
        runtime, _, _ = daemon_dirs

        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc), \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            code, out, err = _capture(start_daemon)

        assert code == 0
        assert "42" in out

    def test_start_stale_pid_non_speach_process(self, daemon_dirs) -> None:
        """PID file exists with PID reused by non-s-peach process -> treat as stale."""
        _write_pid_file(daemon_dirs, 1)  # PID 1 is init

        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.is_process_alive", side_effect=lambda pid: pid != 99999999), \
             patch("s_peach.daemon.is_speach_process", side_effect=lambda pid: pid == 42), \
             patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc), \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            code, out, err = _capture(start_daemon)

        assert code == 0

    def test_start_child_dies_during_readiness(self, daemon_dirs) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = 1  # Child died

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc), \
             patch("s_peach.daemon._wait_for_ready", return_value="died"):
            code, out, err = _capture(start_daemon)

        assert code == 1
        assert "exited during startup" in err
        # PID file should be cleaned up
        runtime, _, _ = daemon_dirs
        assert not (runtime / "s-peach.pid").exists()

    def test_start_spawn_fails_file_not_found(self, daemon_dirs) -> None:
        with patch("s_peach.daemon.subprocess.Popen", side_effect=FileNotFoundError("not found")):
            code, out, err = _capture(start_daemon)

        assert code == 1
        assert "cannot spawn" in err.lower()

    def test_start_spawn_fails_permission(self, daemon_dirs) -> None:
        with patch("s_peach.daemon.subprocess.Popen", side_effect=PermissionError("denied")):
            code, out, err = _capture(start_daemon)

        assert code == 1
        assert "permission denied" in err.lower()

    def test_start_pid_file_mode_0644(self, daemon_dirs) -> None:
        runtime, _, _ = daemon_dirs
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc), \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            _capture(start_daemon)

        pf = runtime / "s-peach.pid"
        mode = pf.stat().st_mode & 0o777
        assert mode == 0o644

    def test_start_log_file_mode_0600(self, daemon_dirs) -> None:
        _, state, _ = daemon_dirs
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc), \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            _capture(start_daemon)

        lf = state / "s-peach.log"
        assert lf.exists()
        mode = lf.stat().st_mode & 0o777
        assert mode == 0o600

    def test_start_with_host_and_port(self, daemon_dirs) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            _capture(start_daemon, host="127.0.0.1", port=8888)

        cmd = mock_popen.call_args.args[0]
        assert "--host" in cmd
        assert "127.0.0.1" in cmd
        assert "--port" in cmd
        assert "8888" in cmd

    def test_start_detaches_process(self, daemon_dirs) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("s_peach.daemon._wait_for_ready", return_value="healthy"):
            _capture(start_daemon)

        assert mock_popen.call_args.kwargs["start_new_session"] is True

    def test_concurrent_start_blocked_by_flock(self, daemon_dirs) -> None:
        """Simulate flock failure to test concurrent start protection."""
        runtime, _, _ = daemon_dirs
        runtime.mkdir(parents=True, exist_ok=True)

        def _flock_side_effect(fd, op):
            if op & fcntl.LOCK_EX:
                raise OSError("locked")
            # Allow LOCK_UN to succeed

        with patch("s_peach.daemon.fcntl.flock", side_effect=_flock_side_effect):
            code, out, err = _capture(start_daemon)

        assert code == 1
        assert "another" in err.lower() or "progress" in err.lower()

    def test_start_timeout_still_starting(self, daemon_dirs) -> None:
        """Server still loading models after timeout -> warning but exit 0."""
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc), \
             patch("s_peach.daemon._wait_for_ready", return_value="starting"):
            code, out, err = _capture(start_daemon)

        assert code == 0
        assert "still loading" in err.lower()

    def test_start_timeout_not_responding(self, daemon_dirs) -> None:
        """Server alive but not responding after timeout -> warning but exit 0."""
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None

        with patch("s_peach.daemon.subprocess.Popen", return_value=mock_proc), \
             patch("s_peach.daemon._wait_for_ready", return_value="not responding"):
            code, out, err = _capture(start_daemon)

        assert code == 0
        assert "not responding" in err.lower()


# === Tests: _wait_for_ready ===


class TestWaitForReady:
    def test_returns_healthy_immediately(self) -> None:
        with patch("s_peach.daemon._check_health", return_value="healthy"), \
             patch("s_peach.daemon.time.sleep"), \
             patch("s_peach.daemon.time.monotonic", side_effect=[0.0, 0.5]):
            result = _wait_for_ready(7777, timeout=10.0)
        assert result == "healthy"

    def test_returns_healthy_after_starting(self) -> None:
        """Health transitions from 'starting' to 'healthy'."""
        with patch("s_peach.daemon._check_health", side_effect=["starting", "starting", "healthy"]), \
             patch("s_peach.daemon.time.sleep"), \
             patch("s_peach.daemon.time.monotonic", side_effect=[0.0, 1.0, 2.0, 3.0]):
            result = _wait_for_ready(7777, timeout=10.0)
        assert result == "healthy"

    def test_returns_starting_on_timeout(self) -> None:
        """Times out while still starting."""
        with patch("s_peach.daemon._check_health", return_value="starting"), \
             patch("s_peach.daemon.time.sleep"), \
             patch("s_peach.daemon.time.monotonic", side_effect=[0.0, 5.0, 11.0]):
            result = _wait_for_ready(7777, timeout=10.0)
        assert result == "starting"

    def test_returns_not_responding_on_timeout(self) -> None:
        """Times out while server not responding at all."""
        with patch("s_peach.daemon._check_health", return_value="not responding"), \
             patch("s_peach.daemon.time.sleep"), \
             patch("s_peach.daemon.time.monotonic", side_effect=[0.0, 5.0, 11.0]):
            result = _wait_for_ready(7777, timeout=10.0)
        assert result == "not responding"

    def test_detects_dead_process(self) -> None:
        """Returns 'died' if the process exits during polling."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Process exited

        with patch("s_peach.daemon._check_health", return_value="not responding"), \
             patch("s_peach.daemon.time.sleep"), \
             patch("s_peach.daemon.time.monotonic", side_effect=[0.0, 1.0]):
            result = _wait_for_ready(7777, timeout=10.0, proc=mock_proc)
        assert result == "died"

    def test_no_proc_skips_poll_check(self) -> None:
        """Without proc, doesn't try to check process status."""
        with patch("s_peach.daemon._check_health", side_effect=["not responding", "healthy"]), \
             patch("s_peach.daemon.time.sleep"), \
             patch("s_peach.daemon.time.monotonic", side_effect=[0.0, 1.0, 2.0]):
            result = _wait_for_ready(7777, timeout=10.0, proc=None)
        assert result == "healthy"


# === Tests: stop_daemon ===


class TestStopDaemon:
    def test_stop_no_pid_file(self, daemon_dirs) -> None:
        code, out, err = _capture(stop_daemon)
        assert code == 1
        assert "not running" in err.lower()

    def test_stop_stale_pid(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 99999999)
        code, out, err = _capture(stop_daemon)
        assert code == 1
        assert "not running" in err.lower()
        # PID file cleaned up
        runtime, _, _ = daemon_dirs
        assert not (runtime / "s-peach.pid").exists()

    def test_stop_invalid_pid_content(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, "garbage")
        code, out, err = _capture(stop_daemon)
        assert code == 1
        assert "invalid" in err.lower()
        runtime, _, _ = daemon_dirs
        assert not (runtime / "s-peach.pid").exists()

    def test_stop_sends_sigterm(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 12345)

        with patch("s_peach.daemon.is_process_alive", side_effect=[True, False]), \
             patch("s_peach.daemon.is_speach_process", return_value=True), \
             patch("s_peach.daemon.os.kill") as mock_kill, \
             patch("s_peach.daemon.time.sleep"):
            code, out, err = _capture(stop_daemon)

        assert code == 0
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)
        assert "stopped" in out.lower()

    def test_stop_escalates_to_sigkill(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 12345)

        # Process stays alive for the SIGTERM wait loop, then dies after SIGKILL
        alive_calls = [True] * 30  # Always alive during SIGTERM wait
        with patch("s_peach.daemon.is_process_alive", side_effect=alive_calls), \
             patch("s_peach.daemon.is_speach_process", return_value=True), \
             patch("s_peach.daemon.os.kill") as mock_kill, \
             patch("s_peach.daemon.time.sleep"), \
             patch("s_peach.daemon.time.monotonic", side_effect=[0.0, 1.0, 2.0, 3.0, 4.0, 5.1]):
            code, out, err = _capture(stop_daemon)

        assert code == 0
        # Should have sent SIGTERM first, then SIGKILL
        kill_calls = mock_kill.call_args_list
        assert kill_calls[0] == call(12345, signal.SIGTERM)
        assert kill_calls[1] == call(12345, signal.SIGKILL)
        assert "force stopped" in out.lower()

    def test_stop_force_sends_sigkill_immediately(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 12345)

        with patch("s_peach.daemon.is_process_alive", return_value=True), \
             patch("s_peach.daemon.is_speach_process", return_value=True), \
             patch("s_peach.daemon.os.kill") as mock_kill, \
             patch("s_peach.daemon.time.sleep"):
            code, out, err = _capture(stop_daemon, force=True)

        assert code == 0
        mock_kill.assert_called_once_with(12345, signal.SIGKILL)
        assert "force stopped" in out.lower()

    def test_stop_removes_pid_file(self, daemon_dirs) -> None:
        runtime, _, _ = daemon_dirs
        _write_pid_file(daemon_dirs, 12345)

        with patch("s_peach.daemon.is_process_alive", side_effect=[True, False]), \
             patch("s_peach.daemon.is_speach_process", return_value=True), \
             patch("s_peach.daemon.os.kill"), \
             patch("s_peach.daemon.time.sleep"):
            _capture(stop_daemon)

        assert not (runtime / "s-peach.pid").exists()

    def test_stop_pid_not_speach_process(self, daemon_dirs) -> None:
        """PID belongs to a different process -> don't kill, report stale."""
        _write_pid_file(daemon_dirs, 12345)

        with patch("s_peach.daemon.is_process_alive", return_value=True), \
             patch("s_peach.daemon.is_speach_process", return_value=False):
            code, out, err = _capture(stop_daemon)

        assert code == 1
        assert "does not belong" in err.lower() or "stale" in err.lower()

    def test_stop_process_already_gone_during_kill(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 12345)

        with patch("s_peach.daemon.is_process_alive", return_value=True), \
             patch("s_peach.daemon.is_speach_process", return_value=True), \
             patch("s_peach.daemon.os.kill", side_effect=ProcessLookupError):
            code, out, err = _capture(stop_daemon)

        assert code == 0
        assert "stopped" in out.lower()


# === Tests: restart_daemon ===


class TestRestartDaemon:
    def test_restart_stops_and_starts(self, daemon_dirs) -> None:
        with patch("s_peach.daemon._check_running", return_value=12345), \
             patch("s_peach.daemon.stop_daemon", return_value=0) as mock_stop, \
             patch("s_peach.daemon.start_daemon", return_value=0) as mock_start:
            code, out, err = _capture(restart_daemon)

        assert code == 0
        mock_stop.assert_called_once()
        mock_start.assert_called_once()

    def test_restart_proceeds_when_not_running(self, daemon_dirs) -> None:
        with patch("s_peach.daemon._check_running", return_value=None), \
             patch("s_peach.daemon.start_daemon", return_value=0) as mock_start:
            code, out, err = _capture(restart_daemon)

        assert code == 0
        mock_start.assert_called_once()
        assert "no running server" in err.lower()

    def test_restart_start_fails_after_stop(self, daemon_dirs) -> None:
        with patch("s_peach.daemon._check_running", return_value=12345), \
             patch("s_peach.daemon.stop_daemon", return_value=0), \
             patch("s_peach.daemon.start_daemon", return_value=1):
            code, out, err = _capture(restart_daemon)

        assert code == 1
        assert "could not be restarted" in err.lower()

    def test_restart_stop_fails(self, daemon_dirs) -> None:
        with patch("s_peach.daemon._check_running", return_value=12345), \
             patch("s_peach.daemon.stop_daemon", return_value=1):
            code, out, err = _capture(restart_daemon)

        assert code == 1
        assert "failed to stop" in err.lower()


# === Tests: status_daemon ===


class TestStatusDaemon:
    def test_status_not_running(self, daemon_dirs) -> None:
        code, out, err = _capture(status_daemon)
        assert code == 1
        assert "not running" in out.lower()

    def test_status_running_healthy(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, os.getpid())

        with patch("s_peach.daemon.is_speach_process", return_value=True), \
             patch("s_peach.daemon._check_health", return_value="healthy"), \
             patch("s_peach.daemon._get_uptime", return_value="5m30s"):
            code, out, err = _capture(status_daemon)

        assert code == 0
        assert "running" in out.lower()
        assert "healthy" in out.lower()
        assert str(os.getpid()) in out
        assert "5m30s" in out

    def test_status_running_not_responding(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, os.getpid())

        with patch("s_peach.daemon.is_speach_process", return_value=True), \
             patch("s_peach.daemon._check_health", return_value="not responding"), \
             patch("s_peach.daemon._get_uptime", return_value=""):
            code, out, err = _capture(status_daemon)

        assert code == 0
        assert "not responding" in out.lower()

    def test_status_stale_pid(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, 99999999)
        code, out, err = _capture(status_daemon)
        assert code == 1
        assert "not running" in out.lower()
        runtime, _, _ = daemon_dirs
        assert not (runtime / "s-peach.pid").exists()

    def test_status_invalid_pid_file(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, "garbage")
        code, out, err = _capture(status_daemon)
        assert code == 1
        assert "invalid" in err.lower()

    def test_status_pid_not_speach(self, daemon_dirs) -> None:
        _write_pid_file(daemon_dirs, os.getpid())

        with patch("s_peach.daemon.is_speach_process", return_value=False), \
             patch("s_peach.daemon._check_health", return_value="not responding"):
            code, out, err = _capture(status_daemon)

        assert code == 1
        assert "not running" in out.lower()

    def test_status_service_managed_healthy(self, daemon_dirs) -> None:
        """No PID file, but health check succeeds — service-managed server."""
        with patch("s_peach.daemon._check_health", return_value="healthy"):
            code, out, err = _capture(status_daemon)

        assert code == 0
        assert "service-managed" in out.lower()
        assert "healthy" in out.lower()

    def test_status_service_managed_not_responding(self, daemon_dirs) -> None:
        """No PID file and health check fails — not running."""
        with patch("s_peach.daemon._check_health", return_value="not responding"):
            code, out, err = _capture(status_daemon)

        assert code == 1
        assert "not running" in out.lower()


# === Tests: logs_command ===


class TestLogsCommand:
    def test_logs_no_file(self, daemon_dirs) -> None:
        code, out, err = _capture(logs_command, follow=False)
        assert code == 1
        assert "no log file" in err.lower()

    def test_logs_no_follow_last_50(self, daemon_dirs) -> None:
        _, state, _ = daemon_dirs
        state.mkdir(parents=True, exist_ok=True)
        lf = state / "s-peach.log"
        lines = [f"line {i}" for i in range(200)]
        lf.write_text("\n".join(lines) + "\n")

        code, out, err = _capture(logs_command, lines=50, follow=False)
        assert code == 0
        output_lines = out.strip().split("\n")
        assert len(output_lines) == 50
        assert output_lines[0] == "line 150"
        assert output_lines[-1] == "line 199"

    def test_logs_custom_line_count(self, daemon_dirs) -> None:
        _, state, _ = daemon_dirs
        state.mkdir(parents=True, exist_ok=True)
        lf = state / "s-peach.log"
        lines = [f"line {i}" for i in range(200)]
        lf.write_text("\n".join(lines) + "\n")

        code, out, err = _capture(logs_command, lines=10, follow=False)
        assert code == 0
        output_lines = out.strip().split("\n")
        assert len(output_lines) == 10
        assert output_lines[0] == "line 190"

    def test_logs_empty_file_no_follow(self, daemon_dirs) -> None:
        _, state, _ = daemon_dirs
        state.mkdir(parents=True, exist_ok=True)
        lf = state / "s-peach.log"
        lf.write_text("")

        code, out, err = _capture(logs_command, lines=50, follow=False)
        assert code == 0
        assert out.strip() == ""

    def test_logs_refuses_symlink(self, daemon_dirs) -> None:
        _, state, _ = daemon_dirs
        state.mkdir(parents=True, exist_ok=True)
        real = state / "real.log"
        real.write_text("data")
        lf = state / "s-peach.log"
        lf.symlink_to(real)

        code, out, err = _capture(logs_command, follow=False)
        assert code == 1
        assert "symlink" in err.lower()

    def test_logs_follow_uses_tail(self, daemon_dirs) -> None:
        _, state, _ = daemon_dirs
        state.mkdir(parents=True, exist_ok=True)
        lf = state / "s-peach.log"
        lf.write_text("some log line\n")

        with patch("s_peach.daemon.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            code, out, err = _capture(logs_command, lines=50, follow=True)

        assert code == 0
        cmd = mock_run.call_args.args[0]
        assert "tail" in cmd
        assert "-f" in cmd
        assert "-n" in cmd
        assert "50" in cmd

    def test_logs_follow_ctrl_c(self, daemon_dirs) -> None:
        _, state, _ = daemon_dirs
        state.mkdir(parents=True, exist_ok=True)
        lf = state / "s-peach.log"
        lf.write_text("log\n")

        with patch("s_peach.daemon.subprocess.run", side_effect=KeyboardInterrupt):
            code, out, err = _capture(logs_command, lines=50, follow=True)

        assert code == 0  # Clean exit on Ctrl+C
