"""Diagnostic check: daemon status, health endpoint, and port availability."""

from __future__ import annotations

import socket
import sys

from s_peach.doctor.models import CheckCategory, CheckResult

_IS_WINDOWS = sys.platform == "win32"


def check_server(settings=None) -> CheckCategory:
    """Check daemon status, health endpoint, and port availability."""
    cat = CheckCategory(name="Server")

    # Determine port
    port = 7777
    if settings is not None:
        port = settings.server.port
    else:
        try:
            from s_peach.config import load_settings
            port = load_settings().server.port
        except Exception:
            pass

    if _IS_WINDOWS:
        # Daemon management is not available on Windows — skip PID check,
        # just check port and health endpoint.
        cat.checks.append(CheckResult(
            name="Daemon process",
            status="info",
            message="Daemon management not available on Windows (use 's-peach serve')",
        ))
        _check_port(cat, port)
        _check_health(cat, port)
        return cat

    from s_peach.daemon import is_process_alive, read_pid

    # Check PID file
    pid = read_pid()

    if pid is None:
        cat.checks.append(CheckResult(
            name="Daemon process",
            status="info",
            message="No daemon PID file found (server may be stopped or running via 'serve')",
        ))

        # Check if port is in use
        _check_port(cat, port)
        return cat

    # PID file exists — check if process is alive
    alive = is_process_alive(pid)

    if not alive:
        # Stale PID file
        cat.checks.append(CheckResult(
            name="Daemon process",
            status="warn",
            message=f"Stale PID file (PID {pid} is not running)",
            fix="Run: s-peach doctor --fix (removes stale PID file)",
            fixable=True,
        ))

        # Check if port is in use by something else
        _check_port(cat, port)
        return cat

    # Process is alive
    cat.checks.append(CheckResult(
        name="Daemon process",
        status="ok",
        message=f"Daemon running (PID {pid})",
    ))

    # Health check
    _check_health(cat, port)

    return cat


def _check_health(cat: CheckCategory, port: int) -> None:
    """Check the /health endpoint."""
    try:
        import httpx

        resp = httpx.get(
            f"http://127.0.0.1:{port}/health",
            timeout=0.5,
        )
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "unknown")
            models = data.get("models", {})
            model_info = ", ".join(
                f"{k}: {v}" for k, v in models.items()
            ) if models else "no model info"
            cat.checks.append(CheckResult(
                name="Health endpoint",
                status="ok",
                message=f"Server healthy (status: {status}, {model_info})",
            ))
        else:
            cat.checks.append(CheckResult(
                name="Health endpoint",
                status="warn",
                message=f"Server returned HTTP {resp.status_code}",
            ))
    except Exception as exc:
        cat.checks.append(CheckResult(
            name="Health endpoint",
            status="warn",
            message=f"Health check failed: {exc}",
        ))


def _check_port(cat: CheckCategory, port: int) -> None:
    """Check if a port is in use via socket.connect_ex."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        result = sock.connect_ex(("127.0.0.1", port))
        if result == 0:
            cat.checks.append(CheckResult(
                name="Port availability",
                status="info",
                message=f"Port {port} is in use by another process",
            ))
        else:
            cat.checks.append(CheckResult(
                name="Port availability",
                status="info",
                message=f"Port {port} is available",
            ))
    finally:
        sock.close()
