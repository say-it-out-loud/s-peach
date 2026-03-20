"""Hook install/uninstall CLI commands.

Note: This module shadows s_peach.hooks — it contains the CLI wrappers
that delegate to the hooks module for actual functionality.
"""

from __future__ import annotations

import argparse
import sys


_SUPPORTED_HOOK_TARGETS = {"claude-code"}


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register install-hook and uninstall-hook subcommands."""
    # --- install-hook ---
    install_hook_parser = subparsers.add_parser(
        "install-hook",
        help="Install a TTS notification hook (e.g. s-peach install-hook claude-code)",
    )
    install_hook_parser.add_argument(
        "hook_target",
        nargs="?",
        default=None,
        help="Hook target to install (currently only 'claude-code' is supported)",
    )
    install_hook_parser.add_argument(
        "--target",
        default=None,
        help="Settings file to modify: settings.json (user-level) or settings.local.json (project-level)",
    )

    # --- uninstall-hook ---
    uninstall_hook_parser = subparsers.add_parser(
        "uninstall-hook",
        help="Remove a TTS notification hook (e.g. s-peach uninstall-hook claude-code)",
    )
    uninstall_hook_parser.add_argument(
        "hook_target",
        nargs="?",
        default=None,
        help="Hook target to uninstall (currently only 'claude-code' is supported)",
    )


def _cmd_install_hook(args: argparse.Namespace) -> None:
    """Install a TTS notification hook for the given target."""
    hook_target = args.hook_target
    if hook_target is None:
        print(
            "Error: missing hook target.\n"
            "Usage: s-peach install-hook claude-code\n\n"
            f"Supported targets: {', '.join(sorted(_SUPPORTED_HOOK_TARGETS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    if hook_target not in _SUPPORTED_HOOK_TARGETS:
        print(
            f"Error: unknown hook target '{hook_target}'.\n"
            f"Supported targets: {', '.join(sorted(_SUPPORTED_HOOK_TARGETS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    from s_peach.hooks import install_hook

    install_hook(target=args.target)


def _cmd_uninstall_hook(args: argparse.Namespace) -> None:
    """Remove a TTS notification hook for the given target."""
    hook_target = args.hook_target
    if hook_target is None:
        print(
            "Error: missing hook target.\n"
            "Usage: s-peach uninstall-hook claude-code\n\n"
            f"Supported targets: {', '.join(sorted(_SUPPORTED_HOOK_TARGETS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    if hook_target not in _SUPPORTED_HOOK_TARGETS:
        print(
            f"Error: unknown hook target '{hook_target}'.\n"
            f"Supported targets: {', '.join(sorted(_SUPPORTED_HOOK_TARGETS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    from s_peach.hooks import uninstall_hook

    uninstall_hook()
