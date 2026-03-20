"""Argument parser builder for the s-peach CLI."""

from __future__ import annotations

import argparse

from importlib.metadata import version

from s_peach.cli import (
    daemon,
    discover,
    doctor,
    hooks,
    init,
    notify,
    say,
    serve,
    service,
    voices,
)

# All command modules that register subcommands.
_COMMAND_MODULES = [
    serve,
    say,
    notify,
    voices,
    init,
    daemon,
    doctor,
    discover,
    hooks,
    service,
]


def _build_parser() -> argparse.ArgumentParser:
    """Build the unified s-peach CLI parser."""
    pkg_version = version("s-peach-tts")

    parser = argparse.ArgumentParser(
        prog="s-peach",
        description="TTS notification server — speak status updates aloud.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"s-peach {pkg_version}",
    )

    subparsers = parser.add_subparsers(dest="command")

    for module in _COMMAND_MODULES:
        module.register(subparsers)

    return parser
