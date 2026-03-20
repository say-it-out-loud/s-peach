"""Platform-aware path resolution for s-peach.

Uses XDG Base Directory Spec on Linux/macOS, and standard Windows locations
(%APPDATA%, %TEMP%) on Windows.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "s-peach"

_IS_WINDOWS = sys.platform == "win32"


def _home() -> Path:
    """Return the user's home directory, raising a clear error if unavailable."""
    try:
        return Path.home()
    except RuntimeError as exc:
        raise RuntimeError(
            "Cannot determine home directory. Ensure $HOME is set."
        ) from exc


def config_dir() -> Path:
    """Return the config directory.

    Windows: %APPDATA%/s-peach/
    POSIX:   $XDG_CONFIG_HOME/s-peach/ or ~/.config/s-peach/
    """
    if _IS_WINDOWS:
        base = os.environ.get("APPDATA")
        if base:
            return (Path(base) / APP_NAME).resolve()
        return (_home() / "AppData" / "Roaming" / APP_NAME).resolve()
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return (Path(base) / APP_NAME).resolve()
    return (_home() / ".config" / APP_NAME).resolve()


def runtime_dir() -> Path:
    """Return the runtime directory (PID file, sockets).

    Windows: %TEMP%/s-peach/
    POSIX:   $XDG_RUNTIME_DIR/s-peach/ or /tmp/s-peach-$UID/
    """
    if _IS_WINDOWS:
        return (Path(tempfile.gettempdir()) / APP_NAME).resolve()
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return (Path(base) / APP_NAME).resolve()
    uid = os.getuid()
    return Path(f"/tmp/s-peach-{uid}").resolve()


def state_dir() -> Path:
    """Return the state directory (logs, persistent runtime data).

    Windows: %LOCALAPPDATA%/s-peach/
    POSIX:   $XDG_STATE_HOME/s-peach/ or ~/.local/state/s-peach/
    """
    if _IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return (Path(base) / APP_NAME).resolve()
        return (_home() / "AppData" / "Local" / APP_NAME).resolve()
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return (Path(base) / APP_NAME).resolve()
    return (_home() / ".local" / "state" / APP_NAME).resolve()


def config_file() -> Path:
    """Return the server config file path: config_dir() / 'server.yaml'."""
    return config_dir() / "server.yaml"


def notifier_file() -> Path:
    """Return the client config file path: config_dir() / 'client.yaml'."""
    return config_dir() / "client.yaml"


def pid_file() -> Path:
    """Return the PID file path: runtime_dir() / 's-peach.pid'."""
    return runtime_dir() / "s-peach.pid"


def log_file() -> Path:
    """Return the log file path: state_dir() / 's-peach.log'."""
    return state_dir() / "s-peach.log"
