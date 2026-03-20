"""Say and say-that-again CLI commands."""

from __future__ import annotations

import argparse
import sys

import httpx

from s_peach.cli import _helpers


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register say and say-that-again subcommands."""
    # --- say ---
    say_parser = subparsers.add_parser(
        "say", help="Send a TTS notification to the server"
    )
    say_parser.add_argument(
        "text", nargs="?", default=None, help="Text to speak (reads from stdin if omitted)"
    )
    say_parser.add_argument(
        "--model", default=None, help="TTS model to use (default: server's default)"
    )
    say_parser.add_argument(
        "--voice", default=None, help="Voice to use (default: server's default)"
    )
    say_parser.add_argument(
        "--url",
        default=None,
        help="Server URL (default: from config or http://localhost:7777)",
    )
    say_parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30.0)",
    )
    say_parser.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Playback speed multiplier (default: from config, typically 1.0)",
    )
    say_parser.add_argument(
        "--exaggeration",
        type=float,
        default=None,
        help="Chatterbox exaggeration factor (e.g. 1.5)",
    )
    say_parser.add_argument(
        "--cfg-weight",
        type=float,
        default=None,
        help="Chatterbox CFG weight (e.g. 1.0)",
    )
    say_parser.add_argument(
        "--summary",
        action="store_true",
        help="Summarize text before speaking (uses summary settings from client.yaml)",
    )
    say_parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON response from server",
    )
    say_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress stdout on success",
    )
    say_parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Language code for TTS generation (e.g. en, fr, zh). Overrides server default.",
    )
    say_parser.add_argument(
        "--save",
        action="store_true",
        help="Save generated audio as WAV to ~/.config/s-peach/output/",
    )

    # --- say-that-again ---
    say_again_parser = subparsers.add_parser(
        "say-that-again", help="Replay the last 'say' command with the same parameters"
    )
    say_again_parser.add_argument(
        "--save",
        action="store_true",
        help="Save replayed audio as WAV to ~/.config/s-peach/output/",
    )


def _cmd_say(args: argparse.Namespace) -> None:
    """Send a TTS notification to the server."""
    # Read text from positional arg or stdin
    text = args.text
    if text is None:
        if sys.stdin.isatty():
            print(
                'Error: no text provided. Usage: s-peach say "message" '
                "or echo \"message\" | s-peach say",
                file=sys.stderr,
            )
            sys.exit(1)
        text = sys.stdin.read().strip()
        if not text:
            print("Error: no text provided via stdin.", file=sys.stderr)
            sys.exit(1)

    url = _helpers._resolve_url(args.url)
    api_key = _helpers._resolve_api_key()
    notifier = _helpers._load_notifier_config()

    # Summarize if requested
    if args.summary:
        text = _helpers._summarize_text(text, notifier)

    # Build request body — CLI flags override client.yaml defaults
    body: dict = {"text": text}

    model = args.model or notifier.get("model")
    if model:
        body["model"] = model

    voice = args.voice or notifier.get("voice")
    if voice:
        body["voice"] = voice

    speed = args.speed if args.speed is not None else notifier.get("speed")
    if speed is not None:
        body["speed"] = speed

    exaggeration = args.exaggeration if args.exaggeration is not None else notifier.get("exaggeration")
    if exaggeration is not None:
        body["exaggeration"] = exaggeration

    cfg_weight = args.cfg_weight if args.cfg_weight is not None else notifier.get("cfg_weight")
    if cfg_weight is not None:
        body["cfg_weight"] = cfg_weight

    lang = args.lang if args.lang is not None else notifier.get("language")
    if lang is not None:
        body["language"] = lang

    if args.save:
        body["return_audio"] = True

    # Build request headers
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    # Send request
    try:
        response = httpx.post(
            f"{url}/speak",
            json=body,
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

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print(f"Error: {detail}", file=sys.stderr)
        sys.exit(1)

    if args.save and response.headers.get("content-type", "").startswith("audio/"):
        from datetime import datetime
        from s_peach.paths import config_dir

        output_dir = config_dir() / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        out_path = output_dir / f"{timestamp}.wav"
        out_path.write_bytes(response.content)
        if not args.quiet:
            print(f"Saved: {out_path}")
    elif args.json:
        import json

        try:
            print(json.dumps(response.json()))
        except Exception:
            print(response.text)
    elif not args.quiet:
        try:
            data = response.json()
            queue_size = data.get("queue_size", "?")
            print(f"Queued. (queue size: {queue_size})")
        except Exception:
            print("Queued.")


def _cmd_say_that_again(args: argparse.Namespace) -> None:
    """Replay the last notification from server memory (cached audio, no re-generation)."""
    url = _helpers._resolve_url(None)
    api_key = _helpers._resolve_api_key()

    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    params = {}
    if args.save:
        params["return_audio"] = "true"

    try:
        response = httpx.post(
            f"{url}/say-that-again",
            json={},
            headers=headers,
            params=params,
            timeout=30.0,
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
            "Error: request timed out\n"
            "Hint: Run 's-peach doctor' to diagnose issues.",
            file=sys.stderr,
        )
        sys.exit(1)

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print(f"Error: {detail}", file=sys.stderr)
        sys.exit(1)

    if args.save and response.headers.get("content-type", "").startswith("audio/"):
        from datetime import datetime
        from s_peach.paths import config_dir

        output_dir = config_dir() / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        out_path = output_dir / f"{timestamp}.wav"
        out_path.write_bytes(response.content)
        print(f"Saved: {out_path}")
    else:
        try:
            data = response.json()
            queue_size = data.get("queue_size", "?")
            print(f"Replayed. (queue size: {queue_size})")
        except Exception:
            print("Replayed.")
