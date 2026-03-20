"""Voices listing CLI command."""

from __future__ import annotations

import argparse
import sys

import httpx

from s_peach.cli import _helpers


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register voices subcommand."""
    voices_parser = subparsers.add_parser(
        "voices", help="List available voices from the running server"
    )
    voices_parser.add_argument(
        "--url",
        default=None,
        help="Server URL (default: from config or http://localhost:7777)",
    )
    voices_parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw JSON instead of formatted table",
    )


def _cmd_voices(args: argparse.Namespace) -> None:
    """List available voices from the running server."""
    url = _helpers._resolve_url(args.url)
    api_key = _helpers._resolve_api_key()

    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        response = httpx.get(
            f"{url}/voices",
            headers=headers,
            timeout=10.0,
        )
    except httpx.ConnectError:
        print(
            f"Error: cannot connect to server at {url}\n"
            "Hint: Run 's-peach doctor' to diagnose issues.",
            file=sys.stderr,
        )
        sys.exit(1)

    if response.status_code != 200:
        print(f"Error: server returned {response.status_code}", file=sys.stderr)
        sys.exit(1)

    data = response.json()

    if args.output_json:
        import json
        print(json.dumps(data, indent=2))
        return

    if not data:
        print("No models loaded.")
        return

    for group in data:
        model = group["model"]
        voices = group["voices"]
        languages = group.get("languages", [])
        lang_suffix = f" — languages: {', '.join(languages)}" if languages else ""
        print(f"\n  {model} ({len(voices)} voices){lang_suffix}")
        print(f"  {'─' * 40}")
        for v in voices:
            desc = f"  {v['description']}" if v.get("description") else ""
            print(f"    {v['name']}{desc}")
    print()
