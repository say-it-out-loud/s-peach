"""Serve CLI command."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register serve subcommand."""
    serve_parser = subparsers.add_parser(
        "serve", help="Run the TTS server in the foreground"
    )
    serve_parser.add_argument(
        "--host", default=None, help="Host to bind to (default: from config)"
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: from config)",
    )


def _cmd_serve(args: argparse.Namespace) -> None:
    """Run the TTS server in the foreground."""
    from s_peach.config import load_settings

    settings = load_settings()

    host = args.host if args.host is not None else settings.server.host
    port = args.port if args.port is not None else settings.server.port

    import uvicorn

    uvicorn.run("s_peach.server:create_app", factory=True, host=host, port=port)
