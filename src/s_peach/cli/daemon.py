"""Daemon management CLI commands (start/stop/restart/status/logs).

Note: This module shadows s_peach.daemon — it contains thin CLI wrappers
that delegate to the daemon module for actual functionality.
"""

from __future__ import annotations

import argparse
import sys


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register daemon management subcommands."""
    # --- start ---
    start_parser = subparsers.add_parser(
        "start", help="Start the server as a background daemon"
    )
    start_parser.add_argument(
        "--host", default=None, help="Host to bind to (default: from config)"
    )
    start_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: from config)",
    )

    # --- stop ---
    stop_parser = subparsers.add_parser(
        "stop", help="Stop the running daemon"
    )
    stop_parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL immediately instead of SIGTERM",
    )

    # --- restart ---
    restart_parser = subparsers.add_parser(
        "restart", help="Restart the daemon (stop + start)"
    )
    restart_parser.add_argument(
        "--host", default=None, help="Host to bind to (default: from config)"
    )
    restart_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: from config)",
    )

    # --- status ---
    subparsers.add_parser(
        "status", help="Show whether the server is running"
    )

    # --- logs ---
    logs_parser = subparsers.add_parser(
        "logs", help="Tail the daemon log file"
    )
    logs_parser.add_argument(
        "-n",
        type=int,
        default=50,
        help="Number of lines to show (default: 50)",
    )
    logs_parser.add_argument(
        "--no-follow",
        action="store_true",
        help="Print log lines and exit (don't follow)",
    )


def _cmd_start(args: argparse.Namespace) -> None:
    """Start the server as a background daemon."""
    from s_peach.daemon import start_daemon

    result = start_daemon(host=args.host, port=args.port)
    sys.exit(result)


def _cmd_stop(args: argparse.Namespace) -> None:
    """Stop the running daemon."""
    from s_peach.daemon import stop_daemon

    result = stop_daemon(force=args.force)
    sys.exit(result)


def _cmd_restart(args: argparse.Namespace) -> None:
    """Restart the daemon."""
    from s_peach.daemon import restart_daemon

    result = restart_daemon(host=args.host, port=args.port)
    sys.exit(result)


def _cmd_status(args: argparse.Namespace) -> None:
    """Show daemon status."""
    from s_peach.daemon import status_daemon

    result = status_daemon()
    sys.exit(result)


def _cmd_logs(args: argparse.Namespace) -> None:
    """Tail the daemon log file."""
    if args.n <= 0:
        print("Error: -n must be a positive integer.", file=sys.stderr)
        sys.exit(1)

    from s_peach.daemon import logs_command

    result = logs_command(lines=args.n, follow=not args.no_follow)
    sys.exit(result)
