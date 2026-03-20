"""Voice discovery/audition CLI command."""

from __future__ import annotations

import argparse
import sys

import httpx

from s_peach.cli import _helpers


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register discover subcommand."""
    discover_parser = subparsers.add_parser(
        "discover", help="Audition all voices for a TTS model"
    )
    discover_parser.add_argument(
        "text",
        nargs="?",
        default=None,
        help="Text to speak (default: sample sentence)",
    )
    discover_parser.add_argument(
        "--model",
        default=None,
        help="TTS model to audition voices for (required)",
    )
    discover_parser.add_argument(
        "--voices",
        default=None,
        help="Comma-separated list of voice names to audition (default: all)",
    )
    discover_parser.add_argument(
        "--wait",
        type=float,
        default=1.0,
        help="Seconds to pause between voices (default: 1)",
    )
    discover_parser.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Playback speed multiplier",
    )
    discover_parser.add_argument(
        "--exaggeration",
        type=float,
        default=None,
        help="Chatterbox exaggeration factor",
    )
    discover_parser.add_argument(
        "--cfg-weight",
        type=float,
        default=None,
        help="Chatterbox CFG weight",
    )
    discover_parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout per /speak-sync call in seconds (default: 30)",
    )
    discover_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List voice names without playing them",
    )
    discover_parser.add_argument(
        "--url",
        default=None,
        help="Server URL (default: from config or http://localhost:7777)",
    )


def _cmd_discover(args: argparse.Namespace) -> None:
    """Audition all voices for a given TTS model."""
    import time as _time

    url = _helpers._resolve_url(args.url)
    api_key = _helpers._resolve_api_key()

    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    # Fetch voice list from server
    try:
        resp = httpx.get(
            f"{url}/voices",
            headers=headers,
            timeout=args.timeout,
        )
    except httpx.ConnectError:
        print(
            f"Error: cannot connect to server at {url}\n"
            "Hint: Start the server with: s-peach serve\n"
            "      Run 's-peach doctor' to diagnose issues.",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.TimeoutException:
        print(
            f"Error: request timed out after {args.timeout}s\n"
            "Hint: Run 's-peach doctor' to diagnose issues.",
            file=sys.stderr,
        )
        sys.exit(1)

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        print(f"Error: {detail}", file=sys.stderr)
        sys.exit(1)

    voice_data = resp.json()

    # If --model not specified, print available models and exit
    if not args.model:
        models = [entry["model"] for entry in voice_data]
        print("Error: --model is required.\n", file=sys.stderr)
        print(f"Available models: {', '.join(models)}", file=sys.stderr)
        sys.exit(1)

    # Find the model's voice group
    model_voices = None
    for entry in voice_data:
        if entry["model"] == args.model:
            model_voices = [v["name"] for v in entry["voices"]]
            break

    if model_voices is None:
        models = [entry["model"] for entry in voice_data]
        print(
            f"Error: model '{args.model}' not found on server.\n"
            f"Available models: {', '.join(models)}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Filter voices if --voices specified
    skipped = 0
    if args.voices:
        requested = [v.strip() for v in args.voices.split(",")]
        filtered = []
        for name in requested:
            if name in model_voices:
                filtered.append(name)
            else:
                print(f"Warning: voice '{name}' not found for model '{args.model}', skipping", file=sys.stderr)
                skipped += 1
        model_voices = filtered

    total = len(model_voices) + skipped
    text = args.text or "The quick brown fox jumps over the lazy dog"

    if args.dry_run:
        for i, voice in enumerate(model_voices, 1):
            print(f"  {voice} ({args.model}) [{i}/{len(model_voices)}]")
        print(f"\nListed {len(model_voices)}/{total} voices for {args.model} ({skipped} skipped)")
        return

    played = 0
    for i, voice in enumerate(model_voices, 1):
        print(f"\u25b6 {voice} ({args.model}) [{i}/{len(model_voices)}]")

        # Build request body
        body: dict = {
            "text": text,
            "model": args.model,
            "voice": voice,
        }
        if args.speed is not None:
            body["speed"] = args.speed
        if args.exaggeration is not None:
            body["exaggeration"] = args.exaggeration
        if args.cfg_weight is not None:
            body["cfg_weight"] = args.cfg_weight

        try:
            sync_resp = httpx.post(
                f"{url}/speak-sync",
                json=body,
                headers=headers,
                timeout=args.timeout,
            )
        except httpx.ConnectError:
            print(f"Error: lost connection to server at {url}", file=sys.stderr)
            sys.exit(1)
        except httpx.TimeoutException:
            print(f"Warning: timed out playing voice '{voice}'", file=sys.stderr)
            skipped += 1
            continue

        if sync_resp.status_code >= 400:
            try:
                detail = sync_resp.json().get("detail", sync_resp.text)
            except Exception:
                detail = sync_resp.text
            print(f"Warning: error playing voice '{voice}': {detail}", file=sys.stderr)
            skipped += 1
            continue

        played += 1

        # Pause between voices (skip after last)
        if i < len(model_voices) and args.wait > 0:
            _time.sleep(args.wait)

    total_with_skipped = played + skipped
    print(f"Played {played}/{total_with_skipped} voices for {args.model} ({skipped} skipped)")
