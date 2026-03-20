"""Service install/uninstall CLI commands."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register install-service and uninstall-service subcommands."""
    subparsers.add_parser(
        "install-service",
        help="Install OS service for auto-start on login (launchd on macOS, systemd on Linux)",
    )
    subparsers.add_parser(
        "uninstall-service",
        help="Remove the OS service",
    )


def _cmd_install_service(args: argparse.Namespace) -> None:
    """Install OS service for auto-start on login."""
    from s_peach.service import install_service

    install_service()


def _cmd_uninstall_service(args: argparse.Namespace) -> None:
    """Remove the OS service."""
    from s_peach.service import uninstall_service

    uninstall_service()
