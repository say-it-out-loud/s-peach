"""Notify CLI command and text extraction helpers."""

from __future__ import annotations

import argparse
import hashlib
import sys

import httpx

from s_peach.cli import _helpers

_DEDUP_TIMEOUT_SECS = 3.0


def _dedup_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _server_says_seen(
    url: str,
    api_key: str | None,
    dedup_value: str,
    timeout: float,
) -> tuple[bool | None, str | None]:
    """Ask the server if this hook/material hash was already seen.

    The server keeps an in-memory FIFO — atomic check-and-add per request.
    Returns:
      - True if the key was already seen
      - False if the key is new
      - None if the dedup endpoint could not be used, plus an error message
    """
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        response = httpx.post(
            f"{url}/dedup/check",
            json={"key": _dedup_key(dedup_value)},
            headers=headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            return None, f"notify: dedup endpoint returned {response.status_code}"
        return bool(response.json().get("seen", False)), None
    except httpx.ConnectError:
        return None, f"notify: cannot connect to server at {url}"
    except httpx.TimeoutException:
        return None, f"notify: dedup check timed out after {timeout:.1f}s"
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"notify: cannot use dedup endpoint at {url} ({exc})"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register notify subcommand."""
    notify_parser = subparsers.add_parser(
        "notify",
        help="Process hook notification from stdin and speak via server",
    )
    notify_parser.add_argument(
        "--model", default=None, help="TTS model to use (overrides client.yaml)"
    )
    notify_parser.add_argument(
        "--voice", default=None, help="Voice to use (overrides client.yaml)"
    )
    notify_parser.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Playback speed multiplier (overrides client.yaml)",
    )
    notify_parser.add_argument(
        "--exaggeration",
        type=float,
        default=None,
        help="Chatterbox exaggeration factor",
    )
    notify_parser.add_argument(
        "--cfg-weight",
        type=float,
        default=None,
        help="Chatterbox CFG weight",
    )
    notify_parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Language code for TTS generation (e.g. en, fr, zh)",
    )
    notify_parser.add_argument(
        "--url",
        default=None,
        help="Server URL (default: from config or http://localhost:7777)",
    )
    notify_parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30.0)",
    )
    notify_parser.add_argument(
        "--summary",
        action="store_true",
        default=None,
        help="Force summarization on (overrides client.yaml)",
    )
    notify_parser.add_argument(
        "--no-summary",
        action="store_true",
        default=None,
        help="Disable summarization (overrides client.yaml)",
    )
    notify_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress stdout on success",
    )


def _extract_json_field(data: dict, expression: str) -> str | None:
    """Extract a field using a dot-path expression like '.foo.bar' or '.foo[0].bar'.

    Supports dict key traversal and array indexing (e.g. '.choices[0].message.content').
    Returns None if any segment is missing or the wrong type.
    """
    if not expression.startswith("."):
        return None
    import re

    # Split on "." but keep bracket indices attached: ".choices[0].message" -> ["choices[0]", "message"]
    parts = expression[1:].split(".")
    current: object = data
    for part in parts:
        if not part:
            continue
        # Split "key[0]" into key + index, or just key
        match = re.match(r"^([^\[]*)\[(\d+)\]$", part)
        if match:
            key, idx = match.group(1), int(match.group(2))
            if key:
                if not isinstance(current, dict):
                    return None
                current = current.get(key)
            if not isinstance(current, list) or idx >= len(current):
                return None
            current = current[idx]
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        if current is None:
            return None
    if isinstance(current, str):
        return current
    return None


def _extract_claude_jsonl(transcript_path: str, tail_lines: int) -> str | None:
    """Read a JSONL transcript and extract assistant text. Returns None if nothing found."""
    from pathlib import Path

    path = Path(transcript_path)
    if not path.is_file():
        return None

    import json as _json

    texts: list[str] = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                except (ValueError, TypeError):
                    continue
                if entry.get("type") != "assistant":
                    continue
                message = entry.get("message", {})
                for content in message.get("content", []):
                    if content.get("type") == "text":
                        text = content.get("text", "")
                        if text:
                            texts.append(text)
    except (OSError, PermissionError):
        return None

    if not texts:
        return None

    # Join all texts, then take last N lines
    combined = "\n".join(texts)
    lines = combined.splitlines()
    return "\n".join(lines[-tail_lines:]) if lines else None


def _cmd_notify(args: argparse.Namespace) -> None:
    """Process hook notification from stdin and speak via server.
    Always exits 0 -- errors are printed to stderr but never cause failure.
    """
    import json as json_mod

    try:
        _cmd_notify_inner(args, json_mod)
    except Exception as exc:
        print(f"notify error: {exc}", file=sys.stderr)


def _cmd_notify_inner(args: argparse.Namespace, json_mod) -> None:
    """Inner implementation for _cmd_notify — separated for testability."""
    # Read stdin
    stdin_text = ""
    if not sys.stdin.isatty():
        stdin_text = sys.stdin.read().strip()
    dedup_value = stdin_text

    notifier = _helpers._load_notifier_config()
    summary_cfg = notifier.get("summary", {})
    source = summary_cfg.get("source", ".last_assistant_message")
    tail_lines = int(summary_cfg.get("tail_lines", 20))
    max_length = int(summary_cfg.get("max_length", 500))
    # CLI flags override config: --summary forces on, --no-summary forces off
    if getattr(args, "no_summary", False):
        summarize_enabled = False
    elif getattr(args, "summary", False):
        summarize_enabled = True
    else:
        summarize_enabled = summary_cfg.get("enabled", True)
        # Normalize string booleans from YAML
        if isinstance(summarize_enabled, str):
            summarize_enabled = summarize_enabled.lower() not in ("false", "0", "no")

    # Extract text based on source mode
    message: str | None = None
    has_content = False

    if not stdin_text:
        message = "All tasks complete."
    elif source == "raw":
        message = stdin_text
        has_content = True
    elif source == "claude_jsonl":
        # Try to read JSONL transcript file
        try:
            hook_data = json_mod.loads(stdin_text)
        except (ValueError, TypeError):
            hook_data = {}

        transcript_path = hook_data.get("transcript_path")
        if transcript_path:
            extracted = _extract_claude_jsonl(str(transcript_path), tail_lines)
            if extracted:
                message = extracted
                has_content = True

        # Fallback: try .last_assistant_message
        if not has_content:
            fallback = hook_data.get("last_assistant_message")
            if fallback and isinstance(fallback, str):
                message = fallback
                has_content = True

        if not has_content:
            message = "All tasks complete."
    else:
        # Source starts with "." — treat as dot-path expression on stdin JSON
        try:
            hook_data = json_mod.loads(stdin_text)
        except (ValueError, TypeError):
            hook_data = {}

        extracted = _extract_json_field(hook_data, source)
        if extracted:
            message = extracted
            has_content = True

        if not has_content:
            # Fallback: session_id
            session_id = hook_data.get("session_id")
            if session_id and isinstance(session_id, str):
                message = f"Session {session_id} complete."
            else:
                message = "All tasks complete."

    assert message is not None
    if has_content:
        dedup_value = message
    elif not dedup_value:
        dedup_value = message

    # Resolve server URL/auth up front so dedup can ask the server first.
    url = _helpers._resolve_url(getattr(args, "url", None))
    api_key = _helpers._resolve_api_key()
    timeout = getattr(args, "timeout", 30.0)

    # Dedup repeated notifications before any summary or /speak call. Use the
    # extracted assistant message when available so repeated Stop-hook events
    # still collapse even if session_id/transcript_path/cwd differ between
    # invocations. Fallback messages with no extracted content dedupe on their
    # final text.
    if dedup_value:
        dedup_timeout = min(timeout, _DEDUP_TIMEOUT_SECS)
        seen, dedup_error = _server_says_seen(url, api_key, dedup_value, dedup_timeout)
        if seen is None:
            print(dedup_error or f"notify: cannot use dedup endpoint at {url}", file=sys.stderr)
            return
        if seen:
            return

    # Summarize if enabled and we have real content
    if summarize_enabled and has_content:
        # Truncate to tail_lines before summarizing
        lines = message.splitlines()
        truncated = "\n".join(lines[-tail_lines:])
        summary = _helpers._summarize_text_with_prompt(truncated, notifier, "notify_prompt")
        if summary:
            message = summary[:max_length]
    else:
        message = message[:max_length]

    body: dict = {"text": message}
    model = getattr(args, "model", None) or notifier.get("model")
    if model:
        body["model"] = model
    voice = getattr(args, "voice", None) or notifier.get("voice")
    if voice:
        body["voice"] = voice
    speed = getattr(args, "speed", None)
    if speed is None:
        speed = notifier.get("speed")
    if speed is not None:
        body["speed"] = speed
    exaggeration = getattr(args, "exaggeration", None)
    if exaggeration is None:
        exaggeration = notifier.get("exaggeration")
    if exaggeration is not None:
        body["exaggeration"] = exaggeration
    cfg_weight = getattr(args, "cfg_weight", None)
    if cfg_weight is None:
        cfg_weight = notifier.get("cfg_weight")
    if cfg_weight is not None:
        body["cfg_weight"] = cfg_weight
    lang = getattr(args, "lang", None)
    if lang is None:
        lang = notifier.get("language")
    if lang is not None:
        body["language"] = lang

    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    quiet = getattr(args, "quiet", False)

    try:
        response = httpx.post(
            f"{url}/speak",
            json=body,
            headers=headers,
            timeout=timeout,
        )
        if not quiet and response.status_code < 400:
            try:
                data = response.json()
                queue_size = data.get("queue_size", "?")
                print(f"Queued. (queue size: {queue_size})")
            except Exception:
                print("Queued.")
        elif response.status_code >= 400:
            print(f"notify: server returned {response.status_code}", file=sys.stderr)
    except httpx.ConnectError:
        print(f"notify: cannot connect to server at {url}", file=sys.stderr)
    except httpx.TimeoutException:
        print("notify: request timed out", file=sys.stderr)
    except Exception as exc:
        print(f"notify: {exc}", file=sys.stderr)
