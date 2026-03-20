"""Tests for s_peach.hooks — Claude Code hook install/uninstall."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def home_dir(tmp_path: Path) -> Path:
    """Create a fake home directory."""
    return tmp_path / "home"


@pytest.fixture
def claude_dir(home_dir: Path) -> Path:
    """Create a fake ~/.claude/ directory."""
    d = home_dir / ".claude"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def config_dir(home_dir: Path) -> Path:
    """Create a fake ~/.config/s-peach/ directory."""
    d = home_dir / ".config" / "s-peach"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def _patch_home(home_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch Path.home() and XDG vars to use tmp dirs."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home_dir / ".config"))
    # Ensure we don't accidentally read the real user's files
    monkeypatch.delenv("HOME", raising=False)


# ---------------------------------------------------------------------------
# Bundled script accessibility
# ---------------------------------------------------------------------------


class TestBundledScript:
    def test_bundled_script_accessible_via_importlib(self):
        """Notifier script is accessible via importlib.resources."""
        from importlib.resources import files

        script = files("s_peach").joinpath("data", "s-peach-notifier.sh")
        content = script.read_text()
        assert "#!/usr/bin/env bash" in content
        assert "s-peach-notifier.sh" in content

    def test_bundled_script_function(self):
        from s_peach.hooks import _bundled_notifier_script

        content = _bundled_notifier_script()
        assert "#!/usr/bin/env bash" in content
        assert "s-peach notify" in content


# ---------------------------------------------------------------------------
# Target validation
# ---------------------------------------------------------------------------


class TestTargetValidation:
    @pytest.mark.usefixtures("_patch_home")
    def test_valid_target_settings_json(self, claude_dir: Path):
        from s_peach.hooks import settings_path

        path = settings_path("settings.json")
        assert path == claude_dir / "settings.json"

    def test_invalid_target_raises(self):
        from s_peach.hooks import VALID_TARGETS

        assert "invalid.json" not in VALID_TARGETS

    @pytest.mark.usefixtures("_patch_home")
    def test_install_hook_invalid_target_exits_1(self, capsys):
        from s_peach.hooks import install_hook

        with pytest.raises(SystemExit) as exc_info:
            install_hook(target="invalid.json")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "invalid target" in captured.err


# ---------------------------------------------------------------------------
# Hook existence detection
# ---------------------------------------------------------------------------


class TestHookDetection:
    def test_detects_existing_hook(self):
        from s_peach.hooks import hook_exists_in_settings

        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                                "timeout": 60,
                            }
                        ]
                    }
                ]
            }
        }
        assert hook_exists_in_settings(settings) is True

    def test_no_hook_returns_false(self):
        from s_peach.hooks import hook_exists_in_settings

        assert hook_exists_in_settings({}) is False
        assert hook_exists_in_settings({"hooks": {}}) is False
        assert hook_exists_in_settings({"hooks": {"Stop": []}}) is False

    def test_other_hooks_not_detected(self):
        from s_peach.hooks import hook_exists_in_settings

        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {"type": "command", "command": "echo done", "timeout": 10}
                        ]
                    }
                ]
            }
        }
        assert hook_exists_in_settings(settings) is False


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_merge_into_empty_user_level(self):
        from s_peach.hooks import _deep_merge_hook

        result = _deep_merge_hook({}, "settings.json")
        assert "hooks" in result
        assert "Stop" in result["hooks"]
        assert len(result["hooks"]["Stop"]) == 1
        hook = result["hooks"]["Stop"][0]["hooks"][0]
        assert hook["command"] == "bash ~/.claude/scripts/s-peach-notifier.sh"
        assert hook["type"] == "command"

    def test_merge_into_empty_project_level(self):
        from s_peach.hooks import _deep_merge_hook

        result = _deep_merge_hook({}, "settings.local.json")
        hook = result["hooks"]["Stop"][0]["hooks"][0]
        assert hook["command"] == "bash .claude/scripts/s-peach-notifier.sh"
        assert hook["type"] == "command"

    def test_merge_preserves_existing_hooks(self):
        from s_peach.hooks import _deep_merge_hook

        existing = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "echo done"}]}
                ],
                "Start": [
                    {"hooks": [{"type": "command", "command": "echo start"}]}
                ],
            },
            "other_setting": True,
        }
        result = _deep_merge_hook(existing, "settings.json")
        # Original Stop hook preserved
        assert len(result["hooks"]["Stop"]) == 2
        assert result["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo done"
        # Start hook preserved
        assert "Start" in result["hooks"]
        # Other settings preserved
        assert result["other_setting"] is True

    def test_merge_preserves_existing_settings(self):
        from s_peach.hooks import _deep_merge_hook

        existing = {"permissions": {"allow": ["read"]}, "model": "claude-sonnet"}
        result = _deep_merge_hook(existing, "settings.json")
        assert result["permissions"] == {"allow": ["read"]}
        assert result["model"] == "claude-sonnet"


# ---------------------------------------------------------------------------
# Remove hook
# ---------------------------------------------------------------------------


class TestRemoveHook:
    def test_remove_from_settings(self):
        from s_peach.hooks import _remove_hook_from_settings

        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                                "timeout": 60,
                            }
                        ]
                    }
                ]
            }
        }
        result, modified = _remove_hook_from_settings(settings)
        assert modified is True
        assert "hooks" not in result  # hooks dict removed since empty

    def test_remove_preserves_other_hooks(self):
        from s_peach.hooks import _remove_hook_from_settings

        settings = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "echo done"}]},
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                            }
                        ]
                    },
                ]
            }
        }
        result, modified = _remove_hook_from_settings(settings)
        assert modified is True
        assert len(result["hooks"]["Stop"]) == 1
        assert result["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo done"

    def test_remove_no_hook_returns_unmodified(self):
        from s_peach.hooks import _remove_hook_from_settings

        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}]}}
        result, modified = _remove_hook_from_settings(settings)
        assert modified is False

    def test_remove_from_empty(self):
        from s_peach.hooks import _remove_hook_from_settings

        settings = {}
        result, modified = _remove_hook_from_settings(settings)
        assert modified is False


# ---------------------------------------------------------------------------
# Install hook (full flow)
# ---------------------------------------------------------------------------


class TestInstallHook:
    @pytest.mark.usefixtures("_patch_home")
    def test_fresh_install_creates_all_files(self, home_dir: Path, capsys):
        """Given no existing files, install-hook creates script, client.yaml, and settings."""
        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        # Script created
        script = home_dir / ".claude" / "scripts" / "s-peach-notifier.sh"
        assert script.exists()
        assert script.stat().st_mode & 0o755 == 0o755

        # Notifier config created
        notifier_cfg = home_dir / ".config" / "s-peach" / "client.yaml"
        assert notifier_cfg.exists()
        assert stat.S_IMODE(notifier_cfg.stat().st_mode) == 0o600

        # Settings file created with hook
        settings_path = home_dir / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]

        captured = capsys.readouterr()
        assert "Hook installation complete" in captured.out

    @pytest.mark.usefixtures("_patch_home")
    def test_preserves_existing_settings(self, home_dir: Path, claude_dir: Path):
        """Given existing Claude settings with other hooks, appends s-peach hook."""
        settings_path = claude_dir / "settings.json"
        existing = {
            "permissions": {"allow": ["read"]},
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "echo other"}]}
                ]
            },
        }
        settings_path.write_text(json.dumps(existing))

        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        settings = json.loads(settings_path.read_text())
        # Original data preserved
        assert settings["permissions"] == {"allow": ["read"]}
        # Both hooks present
        assert len(settings["hooks"]["Stop"]) == 2

    @pytest.mark.usefixtures("_patch_home")
    def test_already_installed_exits_0(self, home_dir: Path, claude_dir: Path, capsys):
        """Given hook already installed, prints message and exits 0."""
        settings_path = claude_dir / "settings.json"
        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                                "timeout": 60,
                            }
                        ]
                    }
                ]
            }
        }
        settings_path.write_text(json.dumps(settings))

        from s_peach.hooks import install_hook

        with pytest.raises(SystemExit) as exc_info:
            install_hook(target="settings.json")
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "already installed" in captured.out.lower()

    @pytest.mark.usefixtures("_patch_home")
    def test_existing_notifier_yaml_not_overwritten(self, home_dir: Path, config_dir: Path, capsys):
        """Given existing client.yaml, does not overwrite it."""
        notifier_cfg = config_dir / "client.yaml"
        notifier_cfg.write_text("custom: true\n")

        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        assert notifier_cfg.read_text() == "custom: true\n"
        captured = capsys.readouterr()
        assert "already exists" in captured.out.lower()

    @pytest.mark.usefixtures("_patch_home")
    def test_invalid_json_exits_1(self, home_dir: Path, claude_dir: Path, capsys):
        """Given existing settings with invalid JSON, prints error and exits 1."""
        settings_path = claude_dir / "settings.json"
        settings_path.write_text("{invalid json")

        from s_peach.hooks import install_hook

        with pytest.raises(SystemExit) as exc_info:
            install_hook(target="settings.json")
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Invalid JSON" in captured.err
        # Original file untouched
        assert settings_path.read_text() == "{invalid json"

    @pytest.mark.usefixtures("_patch_home")
    def test_non_tty_without_target_exits(self, capsys):
        """Given non-TTY stdin without --target, exits with error."""
        from s_peach.hooks import install_hook

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            with pytest.raises(SystemExit) as exc_info:
                install_hook(target=None)
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "--target" in captured.err

    @pytest.mark.usefixtures("_patch_home")
    def test_target_skips_prompt(self, home_dir: Path):
        """Given --target settings.json, prompt is skipped."""
        from s_peach.hooks import install_hook

        # Should not call input() at all
        with patch("builtins.input", side_effect=AssertionError("prompt should be skipped")):
            install_hook(target="settings.json")

        settings_path = home_dir / ".claude" / "settings.json"
        assert settings_path.exists()

    @pytest.mark.usefixtures("_patch_home")
    def test_prompt_selects_correct_file(self, home_dir: Path):
        """Given user input selecting option 1, writes to settings.json."""
        from s_peach.hooks import install_hook

        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        with patch("s_peach.hooks.sys.stdin", mock_stdin), patch("builtins.input", return_value="1"):
            install_hook(target=None)

        settings_path = home_dir / ".claude" / "settings.json"
        assert settings_path.exists()

    @pytest.mark.usefixtures("_patch_home")
    def test_script_permissions_0755(self, home_dir: Path):
        """Notifier script is copied with 0755 permissions."""
        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        script = home_dir / ".claude" / "scripts" / "s-peach-notifier.sh"
        mode = stat.S_IMODE(script.stat().st_mode)
        assert mode == 0o755

    @pytest.mark.usefixtures("_patch_home")
    def test_notifier_yaml_permissions_0600(self, home_dir: Path):
        """Notifier.yaml created with 0600 permissions."""
        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        notifier_cfg = home_dir / ".config" / "s-peach" / "client.yaml"
        mode = stat.S_IMODE(notifier_cfg.stat().st_mode)
        assert mode == 0o600

    @pytest.mark.usefixtures("_patch_home")
    def test_preserves_file_permissions(self, home_dir: Path, claude_dir: Path):
        """When modifying an existing settings file, preserves its original permissions."""
        settings_path = claude_dir / "settings.json"
        settings_path.write_text("{}")
        settings_path.chmod(0o644)

        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        mode = stat.S_IMODE(settings_path.stat().st_mode)
        assert mode == 0o644

    @pytest.mark.usefixtures("_patch_home")
    def test_creates_scripts_directory(self, home_dir: Path):
        """Creates ~/.claude/scripts/ directory if it doesn't exist."""
        from s_peach.hooks import install_hook

        scripts_dir = home_dir / ".claude" / "scripts"
        assert not scripts_dir.exists()

        install_hook(target="settings.json")

        assert scripts_dir.exists()
        assert scripts_dir.is_dir()

    @pytest.mark.usefixtures("_patch_home")
    def test_no_tool_warnings(self, capsys):
        """No jq/yq warnings since hook delegates to Python notify command."""
        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        captured = capsys.readouterr()
        assert "jq" not in captured.err
        assert "yq" not in captured.err

    @pytest.mark.usefixtures("_patch_home")
    def test_hook_entry_structure(self, home_dir: Path):
        """Hook entry has the exact structure specified in the AC."""
        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        settings_path = home_dir / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        stop_entry = settings["hooks"]["Stop"][0]
        hook = stop_entry["hooks"][0]
        assert hook == {
            "type": "command",
            "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
            "async": True,
        }
        # No matcher field
        assert "matcher" not in stop_entry

    @pytest.mark.usefixtures("_patch_home")
    def test_settings_merge_failure_reports_what_succeeded(
        self, home_dir: Path, capsys
    ):
        """If settings merge fails after script+yaml written, reports which steps succeeded."""
        from s_peach.hooks import install_hook

        # Make the settings directory read-only to cause write failure
        claude_dir = home_dir / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_path = claude_dir / "settings.json"
        settings_path.write_text("{}")

        # Patch _atomic_write_json to raise
        with patch("s_peach.hooks._atomic_write_json", side_effect=PermissionError("denied")):
            with pytest.raises(SystemExit) as exc_info:
                install_hook(target="settings.json")
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "succeeded" in captured.err.lower() or "failed" in captured.err.lower()


# ---------------------------------------------------------------------------
# Project-level install (settings.local.json)
# ---------------------------------------------------------------------------


class TestProjectLevelInstall:
    @pytest.fixture
    def project_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Create a project directory and chdir into it, with patched home."""
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(project)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        monkeypatch.delenv("HOME", raising=False)
        return project

    def test_project_install_creates_files_in_project(self, project_dir: Path):
        """Project-level install puts script in .claude/scripts/ (project root)."""
        from s_peach.hooks import install_hook

        install_hook(target="settings.local.json")

        # Script in project .claude/scripts/
        script = project_dir / ".claude" / "scripts" / "s-peach-notifier.sh"
        assert script.exists()
        assert script.stat().st_mode & 0o755 == 0o755

        # Settings in project .claude/settings.local.json
        settings_path = project_dir / ".claude" / "settings.local.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        hook = settings["hooks"]["Stop"][0]["hooks"][0]
        assert hook["command"] == "bash .claude/scripts/s-peach-notifier.sh"
        assert hook["async"] is True

    def test_project_install_does_not_touch_home(self, project_dir: Path, tmp_path: Path):
        """Project-level install does not create anything in ~/.claude/."""
        from s_peach.hooks import install_hook

        install_hook(target="settings.local.json")

        home = tmp_path / "home"
        home_claude = home / ".claude"
        # No scripts dir created in home
        assert not (home_claude / "scripts").exists()
        # No settings.json created in home
        assert not (home_claude / "settings.json").exists()

    def test_project_hook_entry_uses_relative_path(self, project_dir: Path):
        """Project-level hook command uses relative .claude/ path, not ~/."""
        from s_peach.hooks import install_hook

        install_hook(target="settings.local.json")

        settings_path = project_dir / ".claude" / "settings.local.json"
        settings = json.loads(settings_path.read_text())
        hook = settings["hooks"]["Stop"][0]["hooks"][0]
        assert hook == {
            "type": "command",
            "command": "bash .claude/scripts/s-peach-notifier.sh",
            "async": True,
        }


class TestProjectLevelUninstall:
    @pytest.fixture
    def project_with_hook(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Set up a project with the hook installed at project level."""
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(project)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        monkeypatch.delenv("HOME", raising=False)

        # Create project-level hook files
        claude_dir = project / ".claude"
        claude_dir.mkdir()
        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")
        (claude_dir / "settings.local.json").write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash .claude/scripts/s-peach-notifier.sh"}]}
                ]
            }
        }))
        return project

    def test_uninstall_removes_project_level_hook(self, project_with_hook: Path):
        """Uninstall removes hook from project-level settings and cleans up script."""
        from s_peach.hooks import uninstall_hook

        uninstall_hook()

        # Settings cleaned
        settings_path = project_with_hook / ".claude" / "settings.local.json"
        settings = json.loads(settings_path.read_text())
        assert "hooks" not in settings

        # Script removed
        assert not (project_with_hook / ".claude" / "scripts" / "s-peach-notifier.sh").exists()

    def test_uninstall_cleans_empty_project_scripts_dir(self, project_with_hook: Path):
        """Removes .claude/scripts/ if empty after uninstall."""
        from s_peach.hooks import uninstall_hook

        uninstall_hook()

        assert not (project_with_hook / ".claude" / "scripts").exists()


# ---------------------------------------------------------------------------
# Settings backup
# ---------------------------------------------------------------------------


class TestSettingsBackup:
    @pytest.mark.usefixtures("_patch_home")
    def test_install_creates_backup(self, home_dir: Path, claude_dir: Path):
        """Install creates .bak of existing settings before modifying."""
        settings_path = claude_dir / "settings.json"
        original = {"permissions": {"allow": ["read"]}}
        settings_path.write_text(json.dumps(original))

        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        bak_path = settings_path.with_suffix(".json.bak")
        assert bak_path.exists()
        assert json.loads(bak_path.read_text()) == original

    @pytest.mark.usefixtures("_patch_home")
    def test_install_no_backup_for_new_file(self, home_dir: Path, claude_dir: Path):
        """No .bak created when settings file doesn't exist yet."""
        claude_dir.mkdir(parents=True, exist_ok=True)

        from s_peach.hooks import install_hook

        install_hook(target="settings.json")

        settings_path = claude_dir / "settings.json"
        bak_path = settings_path.with_suffix(".json.bak")
        assert not bak_path.exists()

    @pytest.mark.usefixtures("_patch_home")
    def test_uninstall_creates_backup(self, home_dir: Path, claude_dir: Path):
        """Uninstall creates .bak of existing settings before modifying."""
        settings_path = claude_dir / "settings.json"
        original = {
            "permissions": {"allow": ["read"]},
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash ~/.claude/scripts/s-peach-notifier.sh"}]}
                ]
            },
        }
        settings_path.write_text(json.dumps(original))

        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")

        from s_peach.hooks import uninstall_hook

        uninstall_hook()

        bak_path = settings_path.with_suffix(".json.bak")
        assert bak_path.exists()
        assert json.loads(bak_path.read_text()) == original


# ---------------------------------------------------------------------------
# Uninstall hook
# ---------------------------------------------------------------------------


class TestUninstallHook:
    @pytest.mark.usefixtures("_patch_home")
    def test_removes_hook_from_settings_json(self, home_dir: Path, claude_dir: Path, capsys):
        """Given hook in settings.json, removes hook entry and notifier script."""
        # Set up installed state
        settings_path = claude_dir / "settings.json"
        settings = {
            "permissions": {"allow": ["read"]},
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                                "timeout": 60,
                            }
                        ]
                    }
                ]
            },
        }
        settings_path.write_text(json.dumps(settings))

        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script = scripts_dir / "s-peach-notifier.sh"
        script.write_text("#!/bin/bash\n")

        from s_peach.hooks import uninstall_hook

        uninstall_hook()

        # Hook removed from settings
        result = json.loads(settings_path.read_text())
        assert "hooks" not in result  # empty hooks dict removed
        assert result["permissions"] == {"allow": ["read"]}

        # Script removed
        assert not script.exists()
        # Empty scripts dir removed
        assert not scripts_dir.exists()

        captured = capsys.readouterr()
        assert "uninstallation complete" in captured.out.lower()

    @pytest.mark.usefixtures("_patch_home")
    def test_no_hook_exits_0(self, home_dir: Path, claude_dir: Path, capsys):
        """Given no hook in either file, prints 'no hook installed'."""
        settings_path = claude_dir / "settings.json"
        settings_path.write_text("{}")

        from s_peach.hooks import uninstall_hook

        with pytest.raises(SystemExit) as exc_info:
            uninstall_hook()
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "no hook installed" in captured.out.lower()

    @pytest.mark.usefixtures("_patch_home")
    def test_removes_from_both_files(self, home_dir: Path, claude_dir: Path, tmp_path: Path):
        """Given hook in both settings files, removes from both."""
        hook_settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                            }
                        ]
                    }
                ]
            }
        }

        # User-level
        settings_json = claude_dir / "settings.json"
        settings_json.write_text(json.dumps(hook_settings))

        # Project-level — need to patch cwd
        project_claude = tmp_path / "project" / ".claude"
        project_claude.mkdir(parents=True)
        settings_local = project_claude / "settings.local.json"
        settings_local.write_text(json.dumps(hook_settings))

        # Script
        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")

        with patch("s_peach.hooks.Path.cwd", return_value=tmp_path / "project"):
            from s_peach.hooks import uninstall_hook
            uninstall_hook()

        # Both cleaned
        assert "hooks" not in json.loads(settings_json.read_text())
        assert "hooks" not in json.loads(settings_local.read_text())

    @pytest.mark.usefixtures("_patch_home")
    def test_preserves_notifier_yaml(self, home_dir: Path, claude_dir: Path, config_dir: Path):
        """client.yaml is preserved after uninstall."""
        # Set up installed state
        notifier_cfg = config_dir / "client.yaml"
        notifier_cfg.write_text("custom: true\n")

        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash ~/.claude/scripts/s-peach-notifier.sh"}]}
                ]
            }
        }))

        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")

        from s_peach.hooks import uninstall_hook

        uninstall_hook()

        # client.yaml preserved
        assert notifier_cfg.exists()
        assert notifier_cfg.read_text() == "custom: true\n"

    @pytest.mark.usefixtures("_patch_home")
    def test_malformed_json_warns_continues(self, home_dir: Path, claude_dir: Path, capsys, tmp_path: Path):
        """Given malformed JSON in one file and valid hook in the other, warns and continues."""
        # Malformed settings.json
        settings_json = claude_dir / "settings.json"
        settings_json.write_text("{bad json")

        # Valid settings.local.json with hook
        project_claude = tmp_path / "project" / ".claude"
        project_claude.mkdir(parents=True)
        settings_local = project_claude / "settings.local.json"
        settings_local.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash ~/.claude/scripts/s-peach-notifier.sh"}]}
                ]
            }
        }))

        # Script
        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")

        with patch("s_peach.hooks.Path.cwd", return_value=tmp_path / "project"):
            from s_peach.hooks import uninstall_hook
            uninstall_hook()

        captured = capsys.readouterr()
        assert "invalid JSON" in captured.err.lower() or "warning" in captured.err.lower()

        # Hook removed from valid file
        assert "hooks" not in json.loads(settings_local.read_text())
        # Script removed
        assert not (scripts_dir / "s-peach-notifier.sh").exists()

    @pytest.mark.usefixtures("_patch_home")
    def test_readonly_settings_exits_1_keeps_script(self, home_dir: Path, claude_dir: Path, capsys):
        """Given settings file that is read-only, prints error and does not remove script."""
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash ~/.claude/scripts/s-peach-notifier.sh"}]}
                ]
            }
        }))

        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script = scripts_dir / "s-peach-notifier.sh"
        script.write_text("#!/bin/bash\n")

        # Make atomic write fail by patching
        with patch("s_peach.hooks._atomic_write_json", side_effect=PermissionError("denied")):
            with pytest.raises(SystemExit) as exc_info:
                from s_peach.hooks import uninstall_hook
                uninstall_hook()
            assert exc_info.value.code == 1

        # Script NOT removed (settings update failed)
        assert script.exists()

    @pytest.mark.usefixtures("_patch_home")
    def test_cleans_empty_scripts_dir(self, home_dir: Path, claude_dir: Path):
        """Removes ~/.claude/scripts/ directory if it is now empty."""
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash ~/.claude/scripts/s-peach-notifier.sh"}]}
                ]
            }
        }))

        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")

        from s_peach.hooks import uninstall_hook
        uninstall_hook()

        assert not scripts_dir.exists()

    @pytest.mark.usefixtures("_patch_home")
    def test_keeps_scripts_dir_if_not_empty(self, home_dir: Path, claude_dir: Path):
        """Does not remove ~/.claude/scripts/ if other scripts exist."""
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash ~/.claude/scripts/s-peach-notifier.sh"}]}
                ]
            }
        }))

        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")
        (scripts_dir / "other-script.sh").write_text("#!/bin/bash\n")

        from s_peach.hooks import uninstall_hook
        uninstall_hook()

        assert scripts_dir.exists()
        assert (scripts_dir / "other-script.sh").exists()


# ---------------------------------------------------------------------------
# Round-trip test
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.usefixtures("_patch_home")
    def test_install_uninstall_reinstall(self, home_dir: Path):
        """install -> uninstall -> reinstall succeeds, final state matches fresh install."""
        from s_peach.hooks import install_hook, uninstall_hook

        # First install
        install_hook(target="settings.json")
        settings_path = home_dir / ".claude" / "settings.json"
        first_settings = json.loads(settings_path.read_text())

        # Uninstall
        uninstall_hook()
        assert not (home_dir / ".claude" / "scripts" / "s-peach-notifier.sh").exists()

        # Reinstall
        install_hook(target="settings.json")
        second_settings = json.loads(settings_path.read_text())

        # Final state matches first install
        assert first_settings == second_settings


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    def test_install_hook_subcommand_exists(self):
        """install-hook subcommand is registered in the parser."""
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        # Parse without error
        args = parser.parse_args(["install-hook", "--target", "settings.json"])
        assert args.command == "install-hook"
        assert args.target == "settings.json"

    def test_uninstall_hook_subcommand_exists(self):
        """uninstall-hook subcommand is registered in the parser."""
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["uninstall-hook"])
        assert args.command == "uninstall-hook"

    def test_install_hook_no_target(self):
        """install-hook without --target has target=None."""
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["install-hook"])
        assert args.target is None


# ---------------------------------------------------------------------------
# Cross-platform hooks (Windows .bat / POSIX .sh)
# ---------------------------------------------------------------------------


class TestCrossPlatformHooks:
    """Test that install-hook uses .bat on Windows and .sh on POSIX."""

    @pytest.fixture
    def home_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        monkeypatch.delenv("HOME", raising=False)
        return home

    def test_windows_uses_bat_script(self, home_dir: Path):
        """On Windows, install-hook deploys .bat and uses backslash paths."""
        import s_peach.hooks as hooks_mod

        with patch.object(hooks_mod, "_IS_WINDOWS", True), \
             patch.object(hooks_mod, "HOOK_SCRIPT", "s-peach-notifier.bat"):
            hooks_mod.install_hook(target="settings.json")

        # Script file is .bat
        script = home_dir / ".claude" / "scripts" / "s-peach-notifier.bat"
        assert script.exists()

        # Hook command uses backslash and %USERPROFILE%
        settings_path = home_dir / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        hook = settings["hooks"]["Stop"][0]["hooks"][0]
        assert hook["command"] == "%USERPROFILE%\\.claude\\scripts\\s-peach-notifier.bat"
        assert hook["type"] == "command"
        assert hook["async"] is True

    def test_windows_project_level_uses_relative_backslash(self, home_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """On Windows, project-level hook uses relative backslash path."""
        import s_peach.hooks as hooks_mod

        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(project)

        with patch.object(hooks_mod, "_IS_WINDOWS", True), \
             patch.object(hooks_mod, "HOOK_SCRIPT", "s-peach-notifier.bat"):
            hooks_mod.install_hook(target="settings.local.json")

        settings_path = project / ".claude" / "settings.local.json"
        settings = json.loads(settings_path.read_text())
        hook = settings["hooks"]["Stop"][0]["hooks"][0]
        assert hook["command"] == ".claude\\scripts\\s-peach-notifier.bat"

    def test_posix_uses_sh_script(self, home_dir: Path):
        """On POSIX, install-hook deploys .sh with bash prefix."""
        import s_peach.hooks as hooks_mod

        with patch.object(hooks_mod, "_IS_WINDOWS", False), \
             patch.object(hooks_mod, "HOOK_SCRIPT", "s-peach-notifier.sh"):
            hooks_mod.install_hook(target="settings.json")

        # Script file is .sh
        script = home_dir / ".claude" / "scripts" / "s-peach-notifier.sh"
        assert script.exists()

        # Hook command uses bash + forward slashes
        settings_path = home_dir / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        hook = settings["hooks"]["Stop"][0]["hooks"][0]
        assert hook["command"] == "bash ~/.claude/scripts/s-peach-notifier.sh"

    def test_windows_skips_chmod(self, home_dir: Path):
        """On Windows, script is not chmod'd (no-op on NTFS)."""
        import s_peach.hooks as hooks_mod

        with patch.object(hooks_mod, "_IS_WINDOWS", True), \
             patch.object(hooks_mod, "HOOK_SCRIPT", "s-peach-notifier.bat"):
            hooks_mod.install_hook(target="settings.json")

        # Just verify it didn't crash — chmod would be harmless but we skip it
        script = home_dir / ".claude" / "scripts" / "s-peach-notifier.bat"
        assert script.exists()

    def test_posix_sets_chmod_755(self, home_dir: Path):
        """On POSIX, script gets 0755 permissions."""
        import s_peach.hooks as hooks_mod

        with patch.object(hooks_mod, "_IS_WINDOWS", False), \
             patch.object(hooks_mod, "HOOK_SCRIPT", "s-peach-notifier.sh"):
            hooks_mod.install_hook(target="settings.json")

        script = home_dir / ".claude" / "scripts" / "s-peach-notifier.sh"
        assert script.stat().st_mode & 0o755 == 0o755

    def test_uninstall_removes_both_variants(self, home_dir: Path):
        """Uninstall cleans up both .sh and .bat scripts."""
        import s_peach.hooks as hooks_mod

        claude_dir = home_dir / ".claude"
        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir(parents=True)

        # Create both script variants
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")
        (scripts_dir / "s-peach-notifier.bat").write_text("@echo off\n")

        # Write settings with hook
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "Stop": [{
                    "hooks": [{
                        "type": "command",
                        "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                        "async": True,
                    }]
                }]
            }
        }))

        hooks_mod.uninstall_hook()

        # Both variants should be removed
        assert not (scripts_dir / "s-peach-notifier.sh").exists()
        assert not (scripts_dir / "s-peach-notifier.bat").exists()

    def test_detection_matches_both_sh_and_bat(self):
        """Hook detection matches both .sh and .bat in command strings."""
        from s_peach.hooks import hook_exists_in_settings

        sh_settings = {
            "hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "bash ~/.claude/scripts/s-peach-notifier.sh"}
            ]}]}
        }
        bat_settings = {
            "hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "%USERPROFILE%\\.claude\\scripts\\s-peach-notifier.bat"}
            ]}]}
        }
        assert hook_exists_in_settings(sh_settings) is True
        assert hook_exists_in_settings(bat_settings) is True

    def test_bundled_bat_script_exists(self):
        """The .bat notifier script is bundled in package data."""
        from importlib.resources import files

        script = files("s_peach").joinpath("data", "s-peach-notifier.bat")
        content = script.read_text()
        assert "@echo off" in content
        assert "s-peach notify" in content

    def test_bundled_sh_script_exists(self):
        """The .sh notifier script is bundled in package data."""
        from importlib.resources import files

        script = files("s_peach").joinpath("data", "s-peach-notifier.sh")
        content = script.read_text()
        assert "#!/usr/bin/env bash" in content
        assert "s-peach notify" in content
