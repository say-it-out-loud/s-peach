"""Init, config, and reload CLI commands."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys

import httpx

from s_peach.cli import _helpers
from s_peach.scaffolding import init_scaffolding


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register init, config, and reload subcommands."""
    # --- init ---
    init_parser = subparsers.add_parser(
        "init", help="Create config files with documented defaults"
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configs (backs up to *.bak first)",
    )
    init_parser.add_argument(
        "--defaults",
        action="store_true",
        help="Non-interactive mode: create configs with defaults, skip if they exist",
    )

    # --- config ---
    config_parser = subparsers.add_parser(
        "config", help="Open config file in editor"
    )
    config_subparsers = config_parser.add_subparsers(dest="config_target")
    server_config_parser = config_subparsers.add_parser(
        "server", help="Edit server config (reloads after save)"
    )
    server_config_parser.add_argument(
        "--url", default=None, help="Server URL for reload"
    )
    config_subparsers.add_parser("client", help="Edit client/notifier config")

    # --- reload ---
    reload_parser = subparsers.add_parser(
        "reload", help="Reload server configuration"
    )
    reload_parser.add_argument(
        "--url", default=None, help="Server URL"
    )


def _cmd_init(args: argparse.Namespace) -> None:
    """Create config files with documented defaults."""
    if not args.force:
        from s_peach.paths import config_file, notifier_file

        server_cfg = config_file()
        notifier_cfg = notifier_file()
        existing = [f for f in [server_cfg, notifier_cfg] if f.exists()]
        if existing:
            if args.defaults:
                print("Config files already exist, skipping.")
                return
            for f in existing:
                print(f"Error: {f} already exists", file=sys.stderr)
            print(
                "Use --force to overwrite (existing files backed up to *.bak)",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        actions = init_scaffolding(force=args.force)
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    for action in actions:
        print(action)


def _cmd_config(args: argparse.Namespace, config_parser: argparse.ArgumentParser) -> None:
    """Open config file in editor."""
    if not hasattr(args, "config_target") or args.config_target is None:
        from s_peach.paths import config_dir

        from pathlib import Path

        home = str(Path.home())
        if sys.platform == "win32":
            home_prefix = "%USERPROFILE%"
        else:
            home_prefix = "~"
        cfg = str(config_dir()).replace(home, home_prefix)
        hf_cache = str(Path(home) / ".cache" / "huggingface" / "hub")
        hf_display = hf_cache.replace(home, home_prefix)
        print(f"Config directory: {cfg}")
        print(f"Model weights:   {hf_display}")
        print()
        config_parser.print_help()
        sys.exit(0)

    from s_peach.paths import config_file, notifier_file

    if args.config_target == "server":
        target = config_file()
    elif args.config_target == "client":
        target = notifier_file()
    else:
        config_parser.print_help()
        sys.exit(0)

    if not target.exists():
        print(
            f"Error: {target} does not exist.\n"
            "Run 's-peach init' to create config files.\n"
            "Run 's-peach doctor' to diagnose issues.",
            file=sys.stderr,
        )
        sys.exit(1)

    editor = _helpers._get_editor()
    cmd = shlex.split(editor) + [str(target)]
    subprocess.run(cmd, check=False)

    # After editing server config, POST /reload
    if args.config_target == "server":
        url = _helpers._resolve_url(getattr(args, "url", None))
        api_key = _helpers._resolve_api_key()
        _do_reload(url, api_key, exit_on_connection_error=False)


def _do_reload(url: str, api_key: str | None, *, exit_on_connection_error: bool = True) -> None:
    """POST /reload to the server."""
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        response = httpx.post(
            f"{url}/reload",
            json={},
            headers=headers,
            timeout=30.0,
        )
    except httpx.ConnectError:
        msg = f"Warning: cannot connect to server at {url}"
        if exit_on_connection_error:
            print(
                f"Error: cannot connect to server at {url}\n"
                "Hint: Run 's-peach doctor' to diagnose issues.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(f"{msg} (server not running?)", file=sys.stderr)
            return
    except httpx.TimeoutException:
        print(
            "Error: reload request timed out\n"
            "Hint: Run 's-peach doctor' to diagnose issues.",
            file=sys.stderr,
        )
        sys.exit(1)

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print(f"Error: reload failed: {detail}", file=sys.stderr)
        sys.exit(1)

    print("Config reloaded.")


def _cmd_reload(args: argparse.Namespace) -> None:
    """Reload server configuration."""
    url = _helpers._resolve_url(args.url)
    api_key = _helpers._resolve_api_key()
    _do_reload(url, api_key, exit_on_connection_error=True)
