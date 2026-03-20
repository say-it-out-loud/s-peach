"""Daemon lifecycle management for s-peach server.

Handles start (daemonize via subprocess.Popen), stop (SIGTERM/SIGKILL),
restart, status, and log tailing.
"""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from s_peach.paths import log_file, pid_file, runtime_dir, state_dir


# --- Directory and file safety helpers ---


def _ensure_dir(path: Path, mode: int = 0o700) -> None:
    """Create directory with specified mode if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)
    # Ensure correct permissions even if it already existed
    path.chmod(mode)


def _safe_write_file(path: Path, content: str, mode: int) -> None:
    """Write content to a file safely, refusing to follow symlinks.

    Uses O_CREAT|O_WRONLY|O_TRUNC|O_NOFOLLOW to avoid symlink attacks.
    """
    if path.is_symlink():
        raise OSError(f"Refusing to write to symlink: {path}")
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW
    fd = os.open(str(path), flags, mode)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)


def _safe_open_log(path: Path, mode: int = 0o600) -> int:
    """Open log file for appending, refusing to follow symlinks.

    Returns a file descriptor suitable for subprocess stdout/stderr.
    """
    if path.is_symlink():
        raise OSError(f"Refusing to write to symlink: {path}")
    flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
    return os.open(str(path), flags, mode)


# --- PID file helpers ---


def read_pid() -> int | None:
    """Read and return PID from the PID file, or None if not found/invalid."""
    pf = pid_file()
    if not pf.exists():
        return None
    try:
        content = pf.read_text().strip()
        if not content:
            return None
        return int(content)
    except (ValueError, OSError):
        return None


def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it
        return True


def is_speach_process(pid: int) -> bool:
    """Check if the given PID belongs to an s-peach/uvicorn process.

    Checks /proc/<pid>/cmdline on Linux, falls back to os.kill(pid, 0).
    """
    # Try /proc/<pid>/cmdline (Linux)
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    try:
        if proc_cmdline.exists():
            cmdline = proc_cmdline.read_bytes().decode(errors="replace")
            # cmdline fields are NUL-separated
            return "s-peach" in cmdline or "s_peach" in cmdline or "uvicorn" in cmdline
    except (OSError, PermissionError):
        pass

    # Fallback: try psutil-style check via /proc/<pid>/comm
    proc_comm = Path(f"/proc/{pid}/comm")
    try:
        if proc_comm.exists():
            comm = proc_comm.read_text().strip()
            return "s-peach" in comm or "s_peach" in comm or "python" in comm or "uvicorn" in comm
    except (OSError, PermissionError):
        pass

    # macOS / other platforms: use `ps` to check command line
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            cmdline = result.stdout
            return "s-peach" in cmdline or "s_peach" in cmdline or "uvicorn" in cmdline
    except (OSError, subprocess.TimeoutExpired):
        pass

    # Last resort: process is alive but we can't verify ownership
    # Return False to be safe (don't kill unknown processes)
    return False


def _check_running() -> int | None:
    """Check if an s-peach daemon is already running.

    Returns the PID if running, None otherwise.
    Cleans up stale PID files as a side effect.
    """
    pid = read_pid()
    if pid is None:
        return None

    if not is_process_alive(pid):
        # Stale PID file — process is dead
        _cleanup_pid_file()
        return None

    if not is_speach_process(pid):
        # PID reused by a different process
        _cleanup_pid_file()
        return None

    return pid


def _cleanup_pid_file() -> None:
    """Remove the PID file if it exists."""
    pf = pid_file()
    try:
        pf.unlink(missing_ok=True)
    except OSError:
        pass


# --- Start ---


def start_daemon(host: str | None = None, port: int | None = None) -> int:
    """Start the s-peach server as a background daemon.

    Returns 0 on success, 1 on failure.
    """
    pf = pid_file()
    rd = runtime_dir()
    sd = state_dir()
    lf = log_file()

    # Ensure directories exist
    _ensure_dir(rd, 0o700)
    _ensure_dir(sd, 0o700)

    # Lock the PID file to prevent concurrent start races
    _ensure_dir(rd, 0o700)
    lock_path = rd / "s-peach.lock"

    # Open lock file
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError as e:
        print(f"Error: cannot create lock file: {e}", file=sys.stderr)
        return 1

    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(
                "Error: another s-peach start is in progress.",
                file=sys.stderr,
            )
            return 1

        # Check if already running
        running_pid = _check_running()
        if running_pid is not None:
            print(
                f"Error: s-peach is already running (PID {running_pid}).",
                file=sys.stderr,
            )
            return 1

        # Build command
        cmd = [sys.executable, "-m", "s_peach.cli", "serve"]
        if host is not None:
            cmd.extend(["--host", host])
        if port is not None:
            cmd.extend(["--port", str(port)])

        # Open log file for output redirection
        try:
            log_fd = _safe_open_log(lf, 0o600)
        except OSError as e:
            print(f"Error: cannot open log file {lf}: {e}", file=sys.stderr)
            return 1

        # Spawn detached process
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=log_fd,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as e:
            print(f"Error: cannot spawn server: {e}", file=sys.stderr)
            return 1
        except PermissionError as e:
            print(f"Error: permission denied spawning server: {e}", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"Error: cannot spawn server: {e}", file=sys.stderr)
            return 1
        finally:
            # Close log fd in the parent — child has inherited its own copy
            try:
                os.close(log_fd)
            except OSError:
                pass

        child_pid = proc.pid

        # Write PID file
        try:
            _safe_write_file(pf, str(child_pid), 0o644)
        except OSError as e:
            # Kill the child if we can't write the PID file
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass
            print(f"Error: cannot write PID file {pf}: {e}", file=sys.stderr)
            return 1

        # Resolve display values
        if port is None:
            try:
                from s_peach.config import load_settings
                display_port = load_settings().server.port
            except Exception:
                display_port = 7777
        else:
            display_port = port

        # Wait for server to finish loading models and become ready
        print(f"Starting s-peach (PID {child_pid}, port {display_port})...", end="", flush=True)
        readiness = _wait_for_ready(display_port, timeout=120.0, proc=proc)

        if readiness == "died":
            _cleanup_pid_file()
            poll_result = proc.poll()
            print()  # newline after dots
            print(
                f"Error: server exited during startup (code {poll_result}).\n"
                f"Check logs: s-peach logs --no-follow",
                file=sys.stderr,
            )
            return 1

        if readiness == "healthy":
            print(" ready.")
            return 0

        # Still starting or not responding after timeout
        print()  # newline after dots
        if readiness == "starting":
            print(
                "Warning: server is still loading models after 120s.\n"
                "It may become ready shortly. Check with: s-peach status",
                file=sys.stderr,
            )
        else:
            print(
                f"Warning: server process is alive but not responding on port {display_port}.\n"
                f"Check logs: s-peach logs --no-follow",
                file=sys.stderr,
            )
        return 0

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


# --- Stop ---


def stop_daemon(force: bool = False) -> int:
    """Stop the running s-peach daemon.

    Returns 0 on success, 1 on failure.
    """
    pf = pid_file()

    if not pf.exists():
        print("Error: s-peach is not running (no PID file).", file=sys.stderr)
        return 1

    pid = read_pid()
    if pid is None:
        # Invalid PID file content
        print(
            "Error: PID file contains invalid content. Cleaning up.",
            file=sys.stderr,
        )
        _cleanup_pid_file()
        return 1

    if not is_process_alive(pid):
        print("Error: s-peach is not running (stale PID file). Cleaning up.", file=sys.stderr)
        _cleanup_pid_file()
        return 1

    if not is_speach_process(pid):
        print(
            f"Error: PID {pid} does not belong to s-peach (stale PID file). Cleaning up.",
            file=sys.stderr,
        )
        _cleanup_pid_file()
        return 1

    # Send signal
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        # Already dead
        _cleanup_pid_file()
        print("s-peach stopped.")
        return 0
    except PermissionError:
        print(f"Error: permission denied stopping PID {pid}.", file=sys.stderr)
        return 1

    if force:
        # SIGKILL — process should be gone immediately, give it a moment
        time.sleep(0.5)
        _cleanup_pid_file()
        print("s-peach force stopped.")
        return 0

    # Wait for graceful shutdown (up to 5 seconds)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not is_process_alive(pid):
            _cleanup_pid_file()
            print("s-peach stopped.")
            return 0
        time.sleep(0.2)

    # Escalate to SIGKILL
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        _cleanup_pid_file()
        print("s-peach stopped.")
        return 0

    time.sleep(0.5)
    _cleanup_pid_file()
    print("s-peach force stopped (SIGTERM timed out after 5s).")
    return 0


# --- Restart ---


def restart_daemon(host: str | None = None, port: int | None = None) -> int:
    """Stop then start the s-peach daemon.

    Returns 0 on success, 1 on failure.
    """
    running_pid = _check_running()
    if running_pid is not None:
        stop_result = stop_daemon()
        if stop_result != 0:
            print("Error: failed to stop server for restart.", file=sys.stderr)
            return 1
    else:
        print("No running server found, proceeding to start.", file=sys.stderr)

    start_result = start_daemon(host=host, port=port)
    if start_result != 0:
        print(
            "Error: server was stopped but could not be restarted.\n"
            "Try starting manually: s-peach start",
            file=sys.stderr,
        )
        return 1

    return 0


# --- Status ---


def status_daemon() -> int:
    """Show the status of the s-peach daemon.

    Returns 0 if running, 1 if not running.
    """
    pid = read_pid()

    # Try to get port from config
    try:
        from s_peach.config import load_settings
        port = load_settings().server.port
    except Exception:
        port = 7777

    # --- PID file path (daemon started via `s-peach start`) ---
    found_pid = False
    if pid is not None:
        if is_process_alive(pid) and is_speach_process(pid):
            found_pid = True
        else:
            # Stale or invalid PID — clean up
            if pid is not None and not is_process_alive(pid):
                _cleanup_pid_file()
            elif pid is not None and not is_speach_process(pid):
                _cleanup_pid_file()
    else:
        pf = pid_file()
        if pf.exists():
            # Invalid PID file content
            print(
                "Error: PID file contains invalid content. Cleaning up.",
                file=sys.stderr,
            )
            _cleanup_pid_file()

    if found_pid:
        uptime_str = _get_uptime(pid)  # type: ignore[arg-type]
        health_status = _check_health(port)
        status_line = f"s-peach is running (PID {pid}, port {port}"
        if uptime_str:
            status_line += f", uptime {uptime_str}"
        status_line += f") — {health_status}"
        print(status_line)
        return 0

    # --- No PID file: check if a service-managed server is responding ---
    health_status = _check_health(port)
    if health_status in ("healthy", "starting"):
        print(f"s-peach is running (port {port}, service-managed) — {health_status}")
        return 0

    print("s-peach is not running.")
    return 1


def _get_uptime(pid: int) -> str:
    """Get process uptime as a human-readable string, or empty string."""
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.exists():
            return ""
        # Get system boot time and process start time
        stat_content = stat_path.read_text()
        # Format: pid (comm) state ... field 22 is starttime in clock ticks
        # Find the closing ) to skip the comm field (can contain spaces)
        close_paren = stat_content.rfind(")")
        if close_paren == -1:
            return ""
        fields_after_comm = stat_content[close_paren + 2 :].split()
        # starttime is field index 19 after the comm (0-indexed from after state)
        if len(fields_after_comm) < 20:
            return ""
        starttime_ticks = int(fields_after_comm[19])

        # Get clock ticks per second
        clk_tck = os.sysconf("SC_CLK_TCK")

        # Get system uptime
        with open("/proc/uptime") as f:
            system_uptime = float(f.read().split()[0])

        # Calculate process uptime
        process_start_seconds = starttime_ticks / clk_tck
        process_uptime = system_uptime - process_start_seconds

        if process_uptime < 0:
            return ""

        return _format_duration(int(process_uptime))
    except (OSError, ValueError, IndexError):
        return ""


def _format_duration(seconds: int) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m{secs}s"
    hours = minutes // 60
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h{mins}m"
    days = hours // 24
    hrs = hours % 24
    return f"{days}d{hrs}h"


def _check_health(port: int) -> str:
    """Check server health via GET /health."""
    import httpx

    try:
        resp = httpx.get(f"http://localhost:{port}/health", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "ok")
            if status == "starting":
                return "starting"
            return "healthy"
        return "not responding"
    except Exception:
        return "not responding"


def _wait_for_ready(
    port: int,
    timeout: float = 120.0,
    proc: subprocess.Popen | None = None,
) -> str:
    """Poll /health until status is 'ok' or timeout expires.

    Args:
        port: Server port to poll.
        timeout: Maximum seconds to wait.
        proc: If provided, check that the process is still alive each iteration.

    Returns:
        "healthy", "starting" (timed out while still starting), "died", or "not responding".
    """
    deadline = time.monotonic() + timeout
    last_status = "not responding"

    while time.monotonic() < deadline:
        # If we have a handle on the process, check it's still alive
        if proc is not None and proc.poll() is not None:
            return "died"

        last_status = _check_health(port)
        if last_status == "healthy":
            return "healthy"

        time.sleep(1)

    return last_status


# --- Logs ---


def logs_command(lines: int = 50, follow: bool = True) -> int:
    """Tail the daemon log file.

    Returns 0 on success, 1 on failure.
    """
    lf = log_file()

    if not lf.exists():
        print(
            f"Error: no log file found at {lf}\n"
            "Hint: Start the server with: s-peach start",
            file=sys.stderr,
        )
        return 1

    # Security check: must be a regular file
    if lf.is_symlink():
        print(f"Error: log file is a symlink: {lf}", file=sys.stderr)
        return 1
    if not lf.is_file():
        print(f"Error: log path is not a regular file: {lf}", file=sys.stderr)
        return 1

    if not follow:
        # Just read and print the last N lines
        try:
            all_lines = lf.read_text().splitlines()
        except OSError as e:
            print(f"Error: cannot read log file: {e}", file=sys.stderr)
            return 1
        for line in all_lines[-lines:]:
            print(line)
        return 0

    # Follow mode: use tail -f
    cmd = ["tail", "-f", "-n", str(lines), str(lf)]
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode
    except KeyboardInterrupt:
        return 0
