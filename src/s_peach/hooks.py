"""Claude Code hook install/uninstall logic for s-peach TTS notifications."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

# Valid targets for --target flag
VALID_TARGETS = {"settings.json", "settings.local.json"}

# Script filename — also used as marker to detect our hook in settings
_IS_WINDOWS = sys.platform == "win32"
HOOK_SCRIPT = "s-peach-notifier.bat" if _IS_WINDOWS else "s-peach-notifier.sh"
HOOK_MARKER = "s-peach-notifier"  # matches both .sh and .bat in settings detection


def claude_dir() -> Path:
    """Return the Claude Code config directory (~/.claude/)."""
    return Path.home() / ".claude"


def _base_dir(target: str) -> Path:
    """Return the base .claude directory for a given target.

    User-level (settings.json): ~/.claude/
    Project-level (settings.local.json): .claude/ (relative to cwd)
    """
    if target == "settings.local.json":
        return Path.cwd() / ".claude"
    return claude_dir()


def _scripts_dir(target: str = "settings.json") -> Path:
    """Return the scripts directory for a given target."""
    return _base_dir(target) / "scripts"


def notifier_script_dest(target: str = "settings.json") -> Path:
    """Return the destination path for the notifier script."""
    return _scripts_dir(target) / HOOK_SCRIPT


def _hook_entry(target: str) -> dict:
    """Build the hook entry with the correct script path for the target."""
    if _IS_WINDOWS:
        if target == "settings.local.json":
            command = f".claude\\scripts\\{HOOK_SCRIPT}"
        else:
            command = f"%USERPROFILE%\\.claude\\scripts\\{HOOK_SCRIPT}"
    else:
        if target == "settings.local.json":
            command = f"bash .claude/scripts/{HOOK_SCRIPT}"
        else:
            command = f"bash ~/.claude/scripts/{HOOK_SCRIPT}"
    return {
        "type": "command",
        "command": command,
        "async": True,
    }


def settings_path(target: str) -> Path:
    """Return the full path for a Claude settings target.

    For 'settings.json': ~/.claude/settings.json (user-level)
    For 'settings.local.json': .claude/settings.local.json (project-level)
    """
    if target == "settings.json":
        return claude_dir() / "settings.json"
    elif target == "settings.local.json":
        return Path.cwd() / ".claude" / "settings.local.json"
    else:
        raise ValueError(f"Invalid target: {target}")


def _bundled_notifier_script() -> str:
    """Read the bundled notifier script from package data."""
    from importlib.resources import files

    return files("s_peach").joinpath("data", HOOK_SCRIPT).read_text()


def hook_exists_in_settings(settings: dict) -> bool:
    """Check if the s-peach hook is already installed in settings."""
    hooks = settings.get("hooks", {})
    stop_hooks = hooks.get("Stop", [])
    for stop_entry in stop_hooks:
        inner_hooks = stop_entry.get("hooks", [])
        for hook in inner_hooks:
            cmd = hook.get("command", "")
            if HOOK_MARKER in cmd:
                return True
    return False


def _deep_merge_hook(settings: dict, target: str) -> dict:
    """Deep merge the s-peach Stop hook into existing settings."""
    # Ensure hooks.Stop exists
    if "hooks" not in settings:
        settings["hooks"] = {}
    if "Stop" not in settings["hooks"]:
        settings["hooks"]["Stop"] = []

    # Append our hook entry
    settings["hooks"]["Stop"].append({
        "hooks": [_hook_entry(target)],
    })

    return settings


def _remove_hook_from_settings(settings: dict) -> tuple[dict, bool]:
    """Remove s-peach hook entries from settings. Returns (modified_settings, was_modified)."""
    hooks = settings.get("hooks", {})
    stop_hooks = hooks.get("Stop", [])
    if not stop_hooks:
        return settings, False

    new_stop = []
    modified = False
    for stop_entry in stop_hooks:
        inner_hooks = stop_entry.get("hooks", [])
        # Keep entries that don't contain our marker
        filtered = [h for h in inner_hooks if HOOK_MARKER not in h.get("command", "")]
        if len(filtered) < len(inner_hooks):
            modified = True
        if filtered:
            new_stop.append({"hooks": filtered, **{k: v for k, v in stop_entry.items() if k != "hooks"}})
        else:
            modified = True  # entire stop_entry removed

    if modified:
        if new_stop:
            settings["hooks"]["Stop"] = new_stop
        else:
            del settings["hooks"]["Stop"]
            # Remove empty hooks dict
            if not settings["hooks"]:
                del settings["hooks"]

    return settings, modified


def _backup_settings(path: Path) -> Path | None:
    """Copy existing settings file to .bak before modifying. Returns backup path or None."""
    if not path.exists():
        return None
    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(str(path), str(bak))
    return bak


def _atomic_write_json(path: Path, data: dict, original_mode: int | None = None) -> None:
    """Write JSON atomically: write to temp file in same dir, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".s-peach-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        # Preserve original permissions if known
        if original_mode is not None:
            os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, str(path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_settings(path: Path) -> dict:
    """Read a Claude settings JSON file. Creates with {} if missing.

    Raises ValueError if file exists but contains invalid JSON.
    """
    if not path.exists():
        return {}

    text = path.read_text().strip()
    if not text:
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {path}: {exc}"
        ) from exc


def _prompt_target() -> str:
    """Prompt user to choose settings target. Exits if stdin is not a TTY."""
    if not sys.stdin.isatty():
        print(
            "Error: stdin is not a TTY. Use --target to specify the settings file.\n"
            "  s-peach install-hook --target settings.json        # user-level (synced)\n"
            "  s-peach install-hook --target settings.local.json  # project-level (local only)",
            file=sys.stderr,
        )
        sys.exit(1)

    home_prefix = "%USERPROFILE%" if _IS_WINDOWS else "~"
    print("Where should the hook be installed?\n")
    print(f"  1) {home_prefix}/.claude/settings.json         (user-level, synced across machines)")
    print( "  2) .claude/settings.local.json     (project-level, local only)\n")

    while True:
        try:
            choice = input("Choose [1/2]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)

        if choice == "1":
            return "settings.json"
        elif choice == "2":
            return "settings.local.json"
        else:
            print("Please enter 1 or 2.")


def install_hook(target: str | None = None) -> None:
    """Install the s-peach Claude Code hook.

    Args:
        target: Settings file to modify. If None, prompts the user.
    """
    # Validate target if provided
    if target is not None and target not in VALID_TARGETS:
        print(
            f"Error: invalid target '{target}'. "
            f"Must be one of: {', '.join(sorted(VALID_TARGETS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Prompt if no target
    if target is None:
        target = _prompt_target()

    # Resolve settings path and check if hook already exists
    target_path = settings_path(target)
    try:
        settings = _read_settings(target_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if hook_exists_in_settings(settings):
        print(f"Hook already installed in {target_path}")
        sys.exit(0)

    # Step 1: Install notifier script
    script_installed = False
    try:
        scripts_dir = _scripts_dir(target)
        scripts_dir.mkdir(parents=True, exist_ok=True)

        script_dest = notifier_script_dest(target)
        script_content = _bundled_notifier_script()
        script_dest.write_text(script_content)
        if not _IS_WINDOWS:
            script_dest.chmod(
                stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH  # 0755
            )
        script_installed = True
        print(f"Installed notifier script: {script_dest}")
    except Exception as exc:
        print(f"Error installing notifier script: {exc}", file=sys.stderr)
        sys.exit(1)

    # Step 2: Scaffold client.yaml if missing
    yaml_scaffolded = False
    try:
        from s_peach.paths import notifier_file, config_dir

        notifier_cfg = notifier_file()
        if notifier_cfg.exists():
            print(f"Notifier config already exists: {notifier_cfg}")
        else:
            from s_peach.scaffolding import _bundled_notifier_config, _generate_api_key, _API_KEY_PLACEHOLDER

            config_dir().mkdir(parents=True, exist_ok=True)
            content = _bundled_notifier_config().replace(
                _API_KEY_PLACEHOLDER, _generate_api_key()
            )
            notifier_cfg.write_text(content)
            notifier_cfg.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
            yaml_scaffolded = True
            print(f"Created notifier config: {notifier_cfg}")
    except Exception as exc:
        print(f"Warning: failed to scaffold notifier config: {exc}", file=sys.stderr)

    # Step 3: Merge hook into Claude settings
    try:
        # Back up existing settings before modifying
        bak = _backup_settings(target_path)
        if bak:
            print(f"Backed up settings to: {bak}")

        # Capture original permissions if file exists
        original_mode = None
        if target_path.exists():
            original_mode = stat.S_IMODE(target_path.stat().st_mode)

        settings = _deep_merge_hook(settings, target)
        _atomic_write_json(target_path, settings, original_mode)
        print(f"Added hook to: {target_path}")
    except Exception as exc:
        # Report what succeeded before the failure
        succeeded = []
        if script_installed:
            succeeded.append(f"  - Notifier script: {notifier_script_dest(target)}")
        if yaml_scaffolded:
            from s_peach.paths import notifier_file as _nf
            succeeded.append(f"  - Notifier config: {_nf()}")
        if succeeded:
            print("The following steps succeeded:", file=sys.stderr)
            for s in succeeded:
                print(s, file=sys.stderr)
        print(f"Error: failed to merge hook into settings: {exc}", file=sys.stderr)
        sys.exit(1)

    # Summary
    print("\nHook installation complete.")
    print(f"  Script:   {notifier_script_dest(target)}")
    if yaml_scaffolded:
        from s_peach.paths import notifier_file as _nf2
        print(f"  Config:   {_nf2()}")
    print(f"  Settings: {target_path}")


def uninstall_hook() -> None:
    """Uninstall the s-peach Claude Code hook from all settings files."""
    # Step 1: Check both settings files for hook entries
    settings_files = {
        "settings.json": claude_dir() / "settings.json",
        "settings.local.json": Path.cwd() / ".claude" / "settings.local.json",
    }

    found_any = False
    modified_files: list[str] = []
    errors: list[str] = []

    for path in settings_files.values():
        if not path.exists():
            continue

        try:
            settings = _read_settings(path)
        except ValueError:
            print(f"Warning: {path} contains invalid JSON, skipping.", file=sys.stderr)
            continue

        if not hook_exists_in_settings(settings):
            continue

        found_any = True

        # Remove hook entries
        settings, was_modified = _remove_hook_from_settings(settings)
        if not was_modified:
            continue

        # Write back atomically
        try:
            bak = _backup_settings(path)
            if bak:
                print(f"Backed up settings to: {bak}")
            original_mode = stat.S_IMODE(path.stat().st_mode)
            _atomic_write_json(path, settings, original_mode)
            modified_files.append(str(path))
            print(f"Removed hook from: {path}")
        except PermissionError:
            errors.append(str(path))
            print(f"Error: permission denied writing to {path}", file=sys.stderr)
        except Exception as exc:
            errors.append(str(path))
            print(f"Error: failed to update {path}: {exc}", file=sys.stderr)

    if errors:
        print(
            "\nError: could not update settings files. "
            "Script not removed to avoid orphaned hook references.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not found_any:
        print("No hook installed.")
        sys.exit(0)

    # Step 2: Remove notifier script from both locations (only after settings updated successfully)
    for t in VALID_TARGETS:
        # Remove both .sh and .bat variants (cross-platform cleanup)
        for script_name in ("s-peach-notifier.sh", "s-peach-notifier.bat"):
            script_path = _scripts_dir(t) / script_name
            if script_path.exists():
                script_path.unlink()
                print(f"Removed: {script_path}")

        # Clean up empty scripts directory
        sd = _scripts_dir(t)
        if sd.exists() and not any(sd.iterdir()):
            sd.rmdir()
            print(f"Removed empty directory: {sd}")

    # Note: client.yaml is intentionally preserved
    print("\nHook uninstallation complete.")
    if modified_files:
        print("Modified files:")
        for f in modified_files:
            print(f"  - {f}")
