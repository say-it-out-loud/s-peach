"""Unified s-peach CLI entry point with subcommand routing."""

from __future__ import annotations

import argparse
import sys

from s_peach.cli._parser import _build_parser
from s_peach.cli.daemon import _cmd_logs, _cmd_restart, _cmd_start, _cmd_status, _cmd_stop
from s_peach.cli.discover import _cmd_discover
from s_peach.cli.doctor import _cmd_doctor
from s_peach.cli.hooks import _cmd_install_hook, _cmd_uninstall_hook
from s_peach.cli.init import _cmd_config, _cmd_init, _cmd_reload
from s_peach.cli.notify import _cmd_notify
from s_peach.cli.say import _cmd_say, _cmd_say_that_again
from s_peach.cli.serve import _cmd_serve
from s_peach.cli.service import _cmd_install_service, _cmd_uninstall_service
from s_peach.cli.voices import _cmd_voices

_IS_WINDOWS = sys.platform == "win32"
_POSIX_ONLY_COMMANDS = {"start", "stop", "restart", "status", "logs",
                        "install-service", "uninstall-service"}


def main(argv: list[str] | None = None) -> None:
    """Entry point for the unified s-peach CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if _IS_WINDOWS and args.command in _POSIX_ONLY_COMMANDS:
        print(
            f"Error: '{args.command}' is not available on Windows.\n"
            "Use 's-peach serve' to run the server in the foreground.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.command == "serve":
        _cmd_serve(args)
    elif args.command == "say":
        _cmd_say(args)
    elif args.command == "notify":
        _cmd_notify(args)
    elif args.command == "say-that-again":
        _cmd_say_that_again(args)
    elif args.command == "voices":
        _cmd_voices(args)
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "config":
        # Find the config subparser to pass for help printing.
        # NOTE: This uses private argparse API (_subparsers._actions) which is
        # fragile and may break across Python versions. There is no public API
        # to retrieve a subparser by name after creation.
        config_parser = None
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                config_parser = action.choices.get("config")
                break
        _cmd_config(args, config_parser)
    elif args.command == "reload":
        _cmd_reload(args)
    elif args.command == "start":
        _cmd_start(args)
    elif args.command == "stop":
        _cmd_stop(args)
    elif args.command == "restart":
        _cmd_restart(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "doctor":
        _cmd_doctor(args)
    elif args.command == "logs":
        _cmd_logs(args)
    elif args.command == "install-service":
        _cmd_install_service(args)
    elif args.command == "uninstall-service":
        _cmd_uninstall_service(args)
    elif args.command == "discover":
        _cmd_discover(args)
    elif args.command == "install-hook":
        _cmd_install_hook(args)
    elif args.command == "uninstall-hook":
        _cmd_uninstall_hook(args)
    else:
        print(f"Error: unknown command '{args.command}'", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(1)
