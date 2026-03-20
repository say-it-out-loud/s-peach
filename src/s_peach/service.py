"""OS service installation for s-peach.

Supports macOS LaunchAgent (via plistlib + launchctl) and
Linux systemd user units (via systemctl --user).
"""

from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import structlog

from s_peach.daemon import _check_running
from s_peach.paths import log_file, state_dir

log = structlog.get_logger(__name__)


# --- Constants ---

MACOS_PLIST_LABEL = "com.s-peach.server"
MACOS_PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
MACOS_PLIST_PATH = MACOS_PLIST_DIR / f"{MACOS_PLIST_LABEL}.plist"

LINUX_UNIT_NAME = "s-peach.service"
LINUX_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
LINUX_UNIT_PATH = LINUX_UNIT_DIR / LINUX_UNIT_NAME


def _resolve_binary() -> str:
    """Resolve absolute path to the s-peach binary, or exit 1 if not found."""
    binary = shutil.which("s-peach")
    if binary is None:
        log.error(
            "s-peach not found on PATH",
            hint="Ensure s-peach is installed and available in your PATH.",
        )
        sys.exit(1)
    return binary


def _warn_if_daemon_running() -> None:
    """Warn if a Phase 3 daemon is running (PID file + process alive)."""
    running_pid = _check_running()
    if running_pid is not None:
        log.warning(
            "s-peach daemon is already running",
            pid=running_pid,
            hint="Run 's-peach stop' first to avoid conflicts with the system service.",
        )


def _detect_platform() -> str:
    """Detect the current platform. Returns 'macos', 'linux', or exits 1."""
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform.startswith("linux"):
        return "linux"
    else:
        log.error(
            "unsupported platform",
            platform=sys.platform,
            hint="Only macOS and Linux are supported.",
        )
        sys.exit(1)


def _wait_and_report_readiness() -> None:
    """Wait for the server to become ready after service start, with user feedback."""
    from s_peach.daemon import _wait_for_ready

    try:
        from s_peach.config import load_settings
        port = load_settings().server.port
    except Exception:
        port = 7777

    log.info("waiting for server to be ready", port=port)
    readiness = _wait_for_ready(port, timeout=120.0)

    if readiness == "healthy":
        log.info("server is ready", port=port)
    elif readiness == "starting":
        log.warning(
            "server is still loading models after 120s",
            hint="It may become ready shortly. Check with: s-peach status",
        )
    else:
        log.warning(
            "server not responding after 120s",
            port=port,
            hint="Check logs: s-peach logs --no-follow",
        )


# --- macOS LaunchAgent ---


def _macos_build_plist(binary_path: str) -> dict:
    """Build a LaunchAgent plist dictionary."""
    lf = log_file()
    # Ensure state dir exists so the log path is valid
    sd = state_dir()
    sd.mkdir(parents=True, exist_ok=True)

    return {
        "Label": MACOS_PLIST_LABEL,
        "ProgramArguments": [binary_path, "serve"],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(lf),
        "StandardErrorPath": str(lf),
    }


def _macos_unload_existing() -> None:
    """Unload the existing LaunchAgent, ignoring errors if not loaded."""
    uid = os.getuid()
    try:
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(MACOS_PLIST_PATH)],
            capture_output=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _macos_install_service() -> None:
    """Install a macOS LaunchAgent for s-peach."""
    binary_path = _resolve_binary()
    _warn_if_daemon_running()

    plist_data = _macos_build_plist(binary_path)

    # Unload existing service if plist already exists
    if MACOS_PLIST_PATH.exists():
        log.info("existing service found, replacing")
        _macos_unload_existing()

    # Ensure LaunchAgents directory exists
    MACOS_PLIST_DIR.mkdir(parents=True, exist_ok=True)

    # Write plist using plistlib (safe from XML injection)
    with open(MACOS_PLIST_PATH, "wb") as f:
        plistlib.dump(plist_data, f)

    # Set permissions to 0644
    MACOS_PLIST_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    # Load the service
    uid = os.getuid()
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(MACOS_PLIST_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        error_output = result.stderr or result.stdout or "unknown error"
        log.error("launchctl bootstrap failed", detail=error_output)
        sys.exit(1)

    # Wait for server to become ready
    _wait_and_report_readiness()

    log.info(
        "service installed and loaded",
        plist=str(MACOS_PLIST_PATH),
        logs=str(log_file()),
    )


def _macos_uninstall_service() -> None:
    """Uninstall the macOS LaunchAgent for s-peach."""
    if not MACOS_PLIST_PATH.exists():
        log.info("no service installed (plist not found)")
        return

    # Unload the service
    uid = os.getuid()
    result = subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(MACOS_PLIST_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        # Warn but proceed with removal
        error_output = result.stderr or result.stdout or ""
        if error_output:
            log.warning("launchctl bootout issue", detail=error_output)

    # Remove plist
    MACOS_PLIST_PATH.unlink()

    log.info("service uninstalled", removed=str(MACOS_PLIST_PATH))


# --- Linux systemd ---


def _linux_build_unit(binary_path: str) -> str:
    """Build a systemd user unit file content."""
    lf = log_file()
    # Ensure state dir exists so the log path is valid
    sd = state_dir()
    sd.mkdir(parents=True, exist_ok=True)

    return (
        "[Unit]\n"
        "Description=s-peach TTS notification server\n"
        "After=default.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={binary_path} serve\n"
        "Type=exec\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        f"StandardOutput=file:{lf}\n"
        f"StandardError=file:{lf}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _linux_run_systemctl(*args: str) -> subprocess.CompletedProcess:
    """Run systemctl --user with the given args. Returns the CompletedProcess."""
    cmd = ["systemctl", "--user", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _linux_check_bus_error(result: subprocess.CompletedProcess) -> bool:
    """Check if a systemctl failure is a D-Bus/session error and print guidance."""
    combined = (result.stderr or "") + (result.stdout or "")
    bus_keywords = ["Failed to connect to bus", "No such file or directory", "DBUS_SESSION_BUS_ADDRESS"]
    if any(kw in combined for kw in bus_keywords):
        user = os.environ.get("USER", "$USER")
        log.error(
            "cannot connect to the user session bus",
            hint=(
                "This usually means you're in an SSH session without a D-Bus session. "
                f"Fix with: loginctl enable-linger {user} — "
                "then log out and back in, or run: export XDG_RUNTIME_DIR=/run/user/$(id -u)"
            ),
        )
        return True
    return False


def _linux_install_service() -> None:
    """Install a systemd user service for s-peach."""
    binary_path = _resolve_binary()
    _warn_if_daemon_running()

    unit_content = _linux_build_unit(binary_path)

    # Create systemd user directory with mode 0700
    LINUX_UNIT_DIR.mkdir(parents=True, exist_ok=True)
    LINUX_UNIT_DIR.chmod(stat.S_IRWXU)

    # Write unit file
    LINUX_UNIT_PATH.write_text(unit_content)
    LINUX_UNIT_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    # daemon-reload
    result = _linux_run_systemctl("daemon-reload")
    if result.returncode != 0:
        if _linux_check_bus_error(result):
            sys.exit(1)
        error_output = result.stderr or result.stdout or "unknown error"
        log.error("systemctl --user daemon-reload failed", detail=error_output)
        sys.exit(1)

    # enable --now
    result = _linux_run_systemctl("enable", "--now", "s-peach")
    if result.returncode != 0:
        if _linux_check_bus_error(result):
            sys.exit(1)
        error_output = result.stderr or result.stdout or "unknown error"
        log.error("systemctl --user enable --now s-peach failed", detail=error_output)
        sys.exit(1)

    # Wait for server to become ready
    _wait_and_report_readiness()

    log.info(
        "service installed and enabled",
        unit=str(LINUX_UNIT_PATH),
        logs=str(log_file()),
    )


def _linux_uninstall_service() -> None:
    """Uninstall the systemd user service for s-peach."""
    if not LINUX_UNIT_PATH.exists():
        log.info("no service installed (unit file not found)")
        return

    # 1. Stop
    result = _linux_run_systemctl("stop", "s-peach")
    if result.returncode != 0:
        error_output = result.stderr or result.stdout or ""
        if error_output:
            log.warning("stop failed", detail=error_output.strip())

    # 2. Disable
    result = _linux_run_systemctl("disable", "s-peach")
    if result.returncode != 0:
        error_output = result.stderr or result.stdout or ""
        if error_output:
            log.warning("disable failed", detail=error_output.strip())

    # 3. Remove unit file
    LINUX_UNIT_PATH.unlink()

    # 4. daemon-reload
    result = _linux_run_systemctl("daemon-reload")
    if result.returncode != 0:
        error_output = result.stderr or result.stdout or ""
        if error_output:
            log.warning("daemon-reload failed", detail=error_output.strip())

    log.info("service uninstalled", removed=str(LINUX_UNIT_PATH))


# --- Public API ---


def install_service() -> None:
    """Install the appropriate OS service for s-peach."""
    platform = _detect_platform()
    if platform == "macos":
        _macos_install_service()
    elif platform == "linux":
        _linux_install_service()


def uninstall_service() -> None:
    """Uninstall the OS service for s-peach."""
    platform = _detect_platform()
    if platform == "macos":
        _macos_uninstall_service()
    elif platform == "linux":
        _linux_uninstall_service()
