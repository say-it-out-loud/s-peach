"""Shared CLI helper functions used across command modules."""

from __future__ import annotations

import os
import subprocess
import sys


def _summary_workdir() -> str:
    """Return an isolated working directory for summary subprocesses."""
    from s_peach.paths import config_dir

    path = config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _ensure_config() -> None:
    """Auto-scaffold config if the config directory doesn't exist.

    Runs the equivalent of ``s-peach init --defaults`` so first-time users
    get a working setup without an extra manual step.
    """
    from s_peach.paths import config_dir

    if config_dir().exists():
        return

    from s_peach.scaffolding import init_scaffolding

    try:
        actions = init_scaffolding()
    except Exception:
        # Don't block the command — the user can always run init manually.
        print(
            "Hint: run 's-peach init' to create config files.",
            file=sys.stderr,
        )
        return

    print("First run detected — created default config files:", file=sys.stderr)
    for action in actions:
        print(f"  {action}", file=sys.stderr)
    print("Tip: run 's-peach config server' to customize.\n", file=sys.stderr)


def _resolve_url(args_url: str | None) -> str:
    """Resolve server URL from flag, env var, client.yaml, server.yaml, or default.

    Priority: --url flag > S_PEACH_URL env > client.yaml host/port > server.yaml > default.
    """
    url = args_url or os.environ.get("S_PEACH_URL")
    if url is None:
        # Try client.yaml first (the client knows where its server is)
        notifier = _load_notifier_config()
        host = notifier.get("host")
        port = notifier.get("port")
        if host or port:
            host = str(host) if host else "localhost"
            port = int(port) if port else 7777
            if host == "0.0.0.0":
                host = "localhost"
            url = f"http://{host}:{port}"

    if url is None:
        # Fall back to server.yaml
        try:
            from s_peach.config import load_settings

            settings = load_settings()
            host = settings.server.host
            port = settings.server.port
            if host == "0.0.0.0":
                host = "localhost"
            url = f"http://{host}:{port}"
        except Exception:
            url = "http://localhost:7777"
    if not url.startswith(("http://", "https://")):
        print(
            f"Error: URL must start with http:// or https://, got: {url}",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def _load_notifier_config() -> dict:
    """Load client.yaml defaults. Returns empty dict on any failure."""
    try:
        from s_peach.paths import notifier_file

        import yaml

        path = notifier_file()
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def _resolve_api_key() -> str | None:
    """Resolve API key: S_PEACH_API_KEY env var > client.yaml > None."""
    env_key = os.environ.get("S_PEACH_API_KEY")
    if env_key is not None:
        return env_key
    key = _load_notifier_config().get("api_key")
    return str(key) if key else None


def _get_editor() -> str:
    """Get editor command using $VISUAL > $EDITOR > platform fallback."""
    fallback = "notepad" if sys.platform == "win32" else "vi"
    return os.environ.get("VISUAL") or os.environ.get("EDITOR") or fallback


def _summarize_text_with_prompt(text: str, notifier: dict, prompt_key: str) -> str:
    """Summarize text using a specific prompt key from client.yaml summary config.

    Like _summarize_text but allows choosing between 'say_prompt' and 'notify_prompt'.
    Falls back to original text if summarization fails.
    """
    summary_cfg = notifier.get("summary", {})
    command = summary_cfg.get("command", 'claude -p --no-session-persistence "$1" --model sonnet')
    prompt = summary_cfg.get(
        prompt_key,
        "Summarize what was just accomplished or what's happening "
        "in 1-2 short sentences. Be concise as this will be read aloud "
        "as a TTS notification. No code, no markdown, no bullet points, "
        "just plain speech.",
    )
    max_length = int(summary_cfg.get("max_length", 500))
    timeout_secs = int(summary_cfg.get("timeout", 30))
    workdir = _summary_workdir()

    try:
        result = subprocess.run(
            ["bash", "-c", command, "_", prompt],
            input=text,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
            cwd=workdir,
        )
        summary = result.stdout.strip()
        if summary:
            return summary[:max_length]
    except subprocess.TimeoutExpired:
        print("Warning: summary command timed out, using original text.", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: summary failed ({exc}), using original text.", file=sys.stderr)

    return text[:max_length]


def _summarize_text(text: str, notifier: dict) -> str:
    """Summarize text using the summary command from client.yaml.

    Falls back to original text if summarization fails.
    """
    summary_cfg = notifier.get("summary", {})
    command = summary_cfg.get("command", 'claude -p --no-session-persistence "$1" --model sonnet')
    prompt = summary_cfg.get(
        "say_prompt",
        "Condense the following text into 1-2 short sentences suitable for "
        "text-to-speech. Keep the meaning and tone. No code, no markdown, "
        "no bullet points — just plain speech.",
    )
    max_length = int(summary_cfg.get("max_length", 500))
    timeout_secs = int(summary_cfg.get("timeout", 30))
    workdir = _summary_workdir()

    try:
        result = subprocess.run(
            ["bash", "-c", command, "_", prompt],
            input=text,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
            cwd=workdir,
        )
        summary = result.stdout.strip()
        if summary:
            return summary[:max_length]
    except subprocess.TimeoutExpired:
        print("Warning: summary command timed out, using original text.", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: summary failed ({exc}), using original text.", file=sys.stderr)

    return text[:max_length]
