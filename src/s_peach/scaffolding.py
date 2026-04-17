"""Shared init/voice helpers extracted from main.py.

These utilities are used by both the CLI (main.py) and the diagnostic
system (doctor.py). Keeping them in a dedicated module breaks the
circular dependency between those two files.
"""

from __future__ import annotations

import secrets
import shutil
import stat

# --- Default config templates ---

_API_KEY_PLACEHOLDER = "your-secret-key"


def _generate_api_key() -> str:
    """Generate a cryptographically random API key (32 hex bytes = 64 chars)."""
    return secrets.token_hex(32)


def _bundled_server_config() -> str:
    """Read the bundled default server.yaml shipped with the package."""
    from importlib.resources import files

    return files("s_peach").joinpath("defaults", "server.yaml").read_text()


def _bundled_notifier_config() -> str:
    """Read the bundled default client.yaml shipped with the package."""
    from importlib.resources import files

    return files("s_peach").joinpath("defaults", "client.yaml").read_text()


def _bundled_claude_settings() -> str:
    """Read the bundled isolated Claude settings shipped with the package."""
    from importlib.resources import files

    return files("s_peach").joinpath("data", "settings.json").read_text()


def _bundled_voices_dir():
    """Return the importlib.resources Traversable for defaults/voices/."""
    from importlib.resources import files

    return files("s_peach").joinpath("defaults", "voices")


def init_scaffolding(*, force: bool = False) -> list[str]:
    """Create config files with documented defaults.

    This is the reusable library function for init scaffolding.
    Does not call sys.exit() or print to stdout.

    Args:
        force: If True, overwrite existing configs (backs up to *.bak first).

    Returns:
        List of descriptions of actions taken.

    Raises:
        FileExistsError: If configs exist and force is False.
        OSError: If file operations fail.
    """
    from s_peach.paths import claude_settings_file, config_dir, config_file, notifier_file

    cfg_dir = config_dir()
    server_cfg = config_file()
    notifier_cfg = notifier_file()
    claude_settings = claude_settings_file()

    files_to_create = [
        (server_cfg, _bundled_server_config()),
        (notifier_cfg, _bundled_notifier_config()),
        (claude_settings, _bundled_claude_settings()),
    ]

    # Check for existing files (unless --force)
    if not force:
        existing = [f for f, _ in files_to_create if f.exists()]
        if existing:
            raise FileExistsError(
                f"Config files already exist: {', '.join(str(f) for f in existing)}"
            )

    actions: list[str] = []

    # Create directory
    cfg_dir.mkdir(parents=True, exist_ok=True)

    # Generate a shared API key for both configs
    api_key = _generate_api_key()

    # Write files
    for filepath, template in files_to_create:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        if force and filepath.exists():
            bak = filepath.with_suffix(filepath.suffix + ".bak")
            shutil.copy2(filepath, bak)
            actions.append(f"Backed up {filepath} -> {bak}")

        content = template.replace(_API_KEY_PLACEHOLDER, api_key)
        filepath.write_text(content)
        filepath.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        actions.append(f"Created {filepath}")

    # Copy bundled default voices to config_dir/voices/
    voice_actions = _copy_bundled_voices_lib(cfg_dir)
    actions.extend(voice_actions)

    return actions


def ensure_isolated_claude_settings() -> list[str]:
    """Create isolated Claude settings in config_dir()/.claude/ if missing."""
    from s_peach.paths import claude_config_dir, claude_settings_file

    settings_path = claude_settings_file()
    if settings_path.exists():
        return []

    claude_config_dir().mkdir(parents=True, exist_ok=True)
    settings_path.write_text(_bundled_claude_settings())
    settings_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return [f"Created {settings_path}"]


def _copy_bundled_voices_lib(cfg_dir) -> list[str]:
    """Copy bundled default voice files to cfg_dir/voices/ if missing.

    Returns list of action descriptions. Backs up existing files before skipping.
    """
    from pathlib import Path

    actions: list[str] = []
    voices_dir = Path(cfg_dir) / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)

    bundled = _bundled_voices_dir()
    for item in bundled.iterdir():
        name = item.name
        if not name.endswith((".wav", ".mp3", ".flac", ".ogg")):
            continue
        dest = voices_dir / name
        if dest.exists():
            # Back up existing file before skipping
            bak = dest.with_suffix(dest.suffix + ".bak")
            if not bak.exists():
                shutil.copy2(dest, bak)
                actions.append(f"Backed up voice: {dest} -> {bak}")
            continue
        dest.write_bytes(item.read_bytes())
        actions.append(f"Copied voice: {dest}")

    return actions
