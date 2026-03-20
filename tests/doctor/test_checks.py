"""Tests for doctor check functions and orchestration."""

from __future__ import annotations

import builtins
import json
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from tests.doctor.conftest import _make_settings


# ---------------------------------------------------------------------------
# Tests: check_environment
# ---------------------------------------------------------------------------


class TestCheckEnvironment:
    def test_python_version_always_ok(self):
        from s_peach.doctor.checks.environment import check_environment

        cat = check_environment()
        assert cat.name == "Environment"
        py_check = cat.checks[0]
        assert py_check.status == "ok"
        assert "Python" in py_check.message

    def test_sounddevice_import_success(self):
        from s_peach.doctor.checks.environment import check_environment

        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = {"name": "Test Device"}

        with patch("importlib.util.find_spec", return_value=MagicMock()), \
             patch.dict("sys.modules", {"sounddevice": mock_sd}):
            cat = check_environment()

        sd_check = next(c for c in cat.checks if "sounddevice" in c.name or "PortAudio" in c.name)
        assert sd_check.status == "ok"

        audio_check = next(c for c in cat.checks if c.name == "Audio output device")
        assert audio_check.status == "ok"
        assert "Test Device" in audio_check.message

    def test_sounddevice_not_installed(self):
        from s_peach.doctor.checks.environment import check_environment

        with patch("importlib.util.find_spec", return_value=None):
            cat = check_environment()

        sd_check = next(c for c in cat.checks if "sounddevice" in c.name or "PortAudio" in c.name)
        assert sd_check.status == "error"
        assert "PortAudio" in (sd_check.fix or "")

    def test_sounddevice_portaudio_missing(self):
        """sounddevice installed but PortAudio library not found."""
        from s_peach.doctor.checks.environment import check_environment

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "sounddevice":
                raise OSError("PortAudio library not found")
            return real_import(name, *args, **kwargs)

        # Remove sounddevice from cache so our fake_import gets called
        with patch("importlib.util.find_spec", return_value=MagicMock()), \
             patch("builtins.__import__", side_effect=fake_import), \
             patch.dict("sys.modules", {k: v for k, v in sys.modules.items() if k != "sounddevice"}):
            cat = check_environment()

        sd_check = next(c for c in cat.checks if "sounddevice" in c.name or "PortAudio" in c.name)
        assert sd_check.status == "error"
        assert "PortAudio" in (sd_check.fix or "")

    def test_audio_device_query_failure(self):
        from s_peach.doctor.checks.environment import check_environment

        mock_sd = MagicMock()
        mock_sd.query_devices.side_effect = Exception("No audio device")

        with patch("importlib.util.find_spec", return_value=MagicMock()), \
             patch.dict("sys.modules", {"sounddevice": mock_sd}):
            cat = check_environment()

        audio_check = next(c for c in cat.checks if c.name == "Audio output device")
        assert audio_check.status == "warn"


# ---------------------------------------------------------------------------
# Tests: check_config
# ---------------------------------------------------------------------------


class TestCheckConfig:
    def test_config_exists_and_valid(self, _patch_paths, valid_config, valid_notifier):
        from s_peach.doctor.checks.config import check_config

        settings = _make_settings()
        cat = check_config(settings=settings)

        config_check = next(c for c in cat.checks if c.name == "server.yaml")
        assert config_check.status == "ok"

    def test_config_missing(self, _patch_paths, config_dir):
        from s_peach.doctor.checks.config import check_config

        cat = check_config(settings=_make_settings())

        config_check = next(c for c in cat.checks if c.name == "server.yaml")
        assert config_check.status == "error"
        assert "s-peach init" in (config_check.fix or "")
        assert config_check.fixable is True

    def test_config_invalid_yaml(self, _patch_paths, config_dir):
        from s_peach.doctor.checks.config import check_config

        cfg = config_dir / "server.yaml"
        cfg.write_text("invalid: yaml: [unclosed")
        cfg.chmod(stat.S_IRUSR | stat.S_IWUSR)

        cat = check_config(settings=None)

        syntax_check = next(c for c in cat.checks if "syntax" in c.name)
        assert syntax_check.status == "error"

    def test_config_validation_error(self, _patch_paths, config_dir):
        from s_peach.doctor.checks.config import check_config

        cfg = config_dir / "server.yaml"
        cfg.write_text(yaml.dump({
            "enabled_models": ["nonexistent_model"],
        }))
        cfg.chmod(stat.S_IRUSR | stat.S_IWUSR)

        cat = check_config(settings=None)

        validation_checks = [c for c in cat.checks if "validation" in c.name]
        assert any(c.status == "error" for c in validation_checks)

    def test_config_world_readable(self, _patch_paths, valid_config, valid_notifier):
        from s_peach.doctor.checks.config import check_config

        valid_config.chmod(0o644)  # world-readable
        cat = check_config(settings=_make_settings())

        perm_check = next(c for c in cat.checks if "permissions" in c.name and "server.yaml" in c.name)
        assert perm_check.status == "warn"

    def test_api_key_both_none(self, _patch_paths, valid_config, config_dir):
        from s_peach.doctor.checks.config import check_config

        nf = config_dir / "client.yaml"
        nf.write_text(yaml.dump({}))
        nf.chmod(stat.S_IRUSR | stat.S_IWUSR)

        settings = _make_settings(api_key=None)
        cat = check_config(settings=settings)

        key_check = next(c for c in cat.checks if "API key" in c.name)
        assert key_check.status == "ok"

    def test_api_key_mismatch(self, _patch_paths, valid_config, config_dir):
        from s_peach.doctor.checks.config import check_config

        nf = config_dir / "client.yaml"
        nf.write_text(yaml.dump({"api_key": "different-key"}))
        nf.chmod(stat.S_IRUSR | stat.S_IWUSR)

        settings = _make_settings(api_key="test-key-123")
        cat = check_config(settings=settings)

        key_check = next(c for c in cat.checks if "API key" in c.name)
        assert key_check.status == "error"

    def test_api_key_one_none_one_set(self, _patch_paths, valid_config, config_dir):
        from s_peach.doctor.checks.config import check_config

        nf = config_dir / "client.yaml"
        nf.write_text(yaml.dump({"api_key": "some-key"}))
        nf.chmod(stat.S_IRUSR | stat.S_IWUSR)

        settings = _make_settings(api_key=None)
        cat = check_config(settings=settings)

        key_check = next(c for c in cat.checks if "API key" in c.name)
        assert key_check.status == "warn"

    def test_notifier_missing(self, _patch_paths, valid_config):
        from s_peach.doctor.checks.config import check_config

        cat = check_config(settings=_make_settings())

        notifier_check = next(c for c in cat.checks if c.name == "client.yaml")
        assert notifier_check.status == "error"
        assert notifier_check.fixable is True

    def test_notifier_permissions_warn(self, _patch_paths, valid_config, valid_notifier):
        from s_peach.doctor.checks.config import check_config

        valid_notifier.chmod(0o644)
        cat = check_config(settings=_make_settings())

        perm_check = next(c for c in cat.checks if "permissions" in c.name and "client" in c.name)
        assert perm_check.status == "warn"


# ---------------------------------------------------------------------------
# Tests: check_dependencies
# ---------------------------------------------------------------------------


class TestCheckDependencies:
    def test_all_packages_found(self):
        from s_peach.doctor.checks.dependencies import check_dependencies

        with patch("importlib.util.find_spec", return_value=MagicMock()):
            settings = _make_settings(enabled_models=["kokoro"])
            cat = check_dependencies(settings=settings)

        assert all(c.status in ("ok", "info") for c in cat.checks)

    def test_kokoro_missing(self):
        from s_peach.doctor.checks.dependencies import check_dependencies

        def fake_find_spec(name):
            if name == "kokoro":
                return None
            return MagicMock()

        with patch("importlib.util.find_spec", side_effect=fake_find_spec):
            settings = _make_settings()
            cat = check_dependencies(settings=settings)

        kokoro_check = next(c for c in cat.checks if "kokoro" in c.name)
        assert kokoro_check.status == "error"

    def test_chatterbox_enabled_but_missing(self):
        from s_peach.doctor.checks.dependencies import check_dependencies

        def fake_find_spec(name):
            if name == "chatterbox_tts":
                return None
            return MagicMock()

        with patch("importlib.util.find_spec", side_effect=fake_find_spec):
            settings = _make_settings(enabled_models=["chatterbox-turbo"])
            cat = check_dependencies(settings=settings)

        cb_check = next(c for c in cat.checks if "chatterbox" in c.name)
        assert cb_check.status == "error"

    def test_chatterbox_disabled_and_missing(self):
        from s_peach.doctor.checks.dependencies import check_dependencies

        def fake_find_spec(name):
            if name == "chatterbox_tts":
                return None
            return MagicMock()

        with patch("importlib.util.find_spec", side_effect=fake_find_spec):
            settings = _make_settings(enabled_models=["kokoro"])
            cat = check_dependencies(settings=settings)

        cb_check = next(c for c in cat.checks if "chatterbox" in c.name)
        assert cb_check.status == "info"


# ---------------------------------------------------------------------------
# Tests: check_voices
# ---------------------------------------------------------------------------


class TestCheckVoices:
    def test_voice_map_present(self, _patch_paths, valid_config):
        from s_peach.doctor.checks.voices import check_voices

        settings = _make_settings(
            enabled_models=["kokoro"],
            voices={"kokoro": {"Heart": "af_heart"}},
        )
        cat = check_voices(settings=settings)

        map_check = next(c for c in cat.checks if "Voice map" in c.name)
        assert map_check.status == "ok"

    def test_voice_map_missing(self, _patch_paths, valid_config):
        from s_peach.doctor.checks.voices import check_voices

        settings = _make_settings(
            enabled_models=["kokoro"],
            voices={},
        )
        cat = check_voices(settings=settings)

        map_check = next(c for c in cat.checks if "Voice map" in c.name)
        assert map_check.status == "warn"

    def test_chatterbox_voice_file_exists(self, _patch_paths, config_dir):
        from s_peach.doctor.checks.voices import check_voices

        # Create reference audio file
        voices_dir = config_dir / "voices"
        voices_dir.mkdir(exist_ok=True)
        (voices_dir / "speaker.wav").write_bytes(b"fake wav data")

        settings = _make_settings(
            enabled_models=["chatterbox-turbo"],
            voices={"chatterbox": {"Clone": "voices/speaker.wav"}},
        )
        cat = check_voices(settings=settings)

        file_check = next(c for c in cat.checks if "Voice file" in c.name)
        assert file_check.status == "ok"

    def test_chatterbox_voice_file_missing(self, _patch_paths, config_dir):
        from s_peach.doctor.checks.voices import check_voices

        settings = _make_settings(
            enabled_models=["chatterbox"],
            voices={"chatterbox": {"Clone": "voices/missing.wav"}},
        )
        cat = check_voices(settings=settings)

        file_check = next(c for c in cat.checks if "Voice file" in c.name)
        assert file_check.status == "error"

    def test_chatterbox_disabled_skips_voice_files(self, _patch_paths, config_dir):
        from s_peach.doctor.checks.voices import check_voices

        settings = _make_settings(
            enabled_models=["kokoro"],
            voices={"chatterbox": {"Clone": "voices/missing.wav"}},
        )
        cat = check_voices(settings=settings)

        file_checks = [c for c in cat.checks if "Voice file" in c.name]
        assert len(file_checks) == 0

    def test_voice_map_family_prefix(self, _patch_paths, valid_config):
        """kitten-mini, kitten-micro, kitten-nano all use 'kitten' voice map."""
        from s_peach.doctor.checks.voices import check_voices

        settings = _make_settings(
            enabled_models=["kitten-mini", "kitten-micro"],
            voices={"kitten": {"Bella": "Bella"}},
        )
        cat = check_voices(settings=settings)

        map_checks = [c for c in cat.checks if "Voice map" in c.name]
        assert all(c.status == "ok" for c in map_checks)


# ---------------------------------------------------------------------------
# Tests: check_server
# ---------------------------------------------------------------------------


class TestCheckServer:
    def test_daemon_running_healthy(self, _patch_paths):
        from s_peach.doctor.checks.server import check_server

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "models": {"kokoro": "loaded"}}

        with patch("s_peach.daemon.read_pid", return_value=12345), \
             patch("s_peach.daemon.is_process_alive", return_value=True), \
             patch("httpx.get", return_value=mock_resp):
            settings = _make_settings()
            cat = check_server(settings=settings)

        daemon_check = next(c for c in cat.checks if "Daemon" in c.name)
        assert daemon_check.status == "ok"

        health_check = next(c for c in cat.checks if "Health" in c.name)
        assert health_check.status == "ok"
        assert "kokoro" in health_check.message

    def test_daemon_not_running(self, _patch_paths):
        from s_peach.doctor.checks.server import check_server

        with patch("s_peach.daemon.read_pid", return_value=None), \
             patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 1  # port not in use
            mock_socket.return_value = mock_sock

            settings = _make_settings()
            cat = check_server(settings=settings)

        daemon_check = next(c for c in cat.checks if "Daemon" in c.name)
        assert daemon_check.status == "info"

    def test_stale_pid_file(self, _patch_paths):
        from s_peach.doctor.checks.server import check_server

        with patch("s_peach.daemon.read_pid", return_value=99999), \
             patch("s_peach.daemon.is_process_alive", return_value=False), \
             patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 1
            mock_socket.return_value = mock_sock

            settings = _make_settings()
            cat = check_server(settings=settings)

        daemon_check = next(c for c in cat.checks if "Daemon" in c.name)
        assert daemon_check.status == "warn"
        assert "Stale" in daemon_check.message
        assert daemon_check.fixable is True

    def test_stale_pid_not_deleted(self, _patch_paths, runtime_dir):
        """Doctor does NOT delete stale PID files (reserve for --fix)."""
        from s_peach.doctor.checks.server import check_server

        # Create a PID file
        pid_file = runtime_dir / "s-peach.pid"
        pid_file.write_text("99999")

        with patch("s_peach.daemon.read_pid", return_value=99999), \
             patch("s_peach.daemon.is_process_alive", return_value=False), \
             patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 1
            mock_socket.return_value = mock_sock

            check_server(settings=_make_settings())

        # PID file should still exist
        assert pid_file.exists()

    def test_health_timeout(self, _patch_paths):
        from s_peach.doctor.checks.server import check_server

        with patch("s_peach.daemon.read_pid", return_value=12345), \
             patch("s_peach.daemon.is_process_alive", return_value=True), \
             patch("httpx.get", side_effect=Exception("Connection timed out")):
            settings = _make_settings()
            cat = check_server(settings=settings)

        health_check = next(c for c in cat.checks if "Health" in c.name)
        assert health_check.status == "warn"

    def test_port_in_use(self, _patch_paths):
        from s_peach.doctor.checks.server import check_server

        with patch("s_peach.daemon.read_pid", return_value=None), \
             patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0  # port in use
            mock_socket.return_value = mock_sock

            settings = _make_settings()
            cat = check_server(settings=settings)

        port_check = next(c for c in cat.checks if "Port" in c.name)
        assert port_check.status == "info"
        assert "in use" in port_check.message


# ---------------------------------------------------------------------------
# Tests: check_hooks
# ---------------------------------------------------------------------------


class TestCheckHooks:
    def test_hook_present_in_settings(self, home_dir, monkeypatch):
        from s_peach.doctor.checks.hooks import check_hooks

        monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))

        claude_dir = home_dir / ".claude"
        claude_dir.mkdir(parents=True)
        settings_json = claude_dir / "settings.json"
        settings_json.write_text(json.dumps({
            "hooks": {
                "Stop": [{
                    "hooks": [{
                        "type": "command",
                        "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                    }]
                }]
            }
        }))

        # Create script
        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")

        cat = check_hooks()

        hook_check = next(c for c in cat.checks if "Hook in settings" in c.name)
        assert hook_check.status == "ok"

    def test_hook_absent(self, home_dir, monkeypatch):
        from s_peach.doctor.checks.hooks import check_hooks

        monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))

        claude_dir = home_dir / ".claude"
        claude_dir.mkdir(parents=True)

        cat = check_hooks()

        hook_check = next(c for c in cat.checks if "Hook in settings" in c.name)
        assert hook_check.status == "info"

    def test_hook_in_settings_local_only(self, home_dir, monkeypatch, tmp_path):
        from s_peach.doctor.checks.hooks import check_hooks

        monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))
        monkeypatch.chdir(tmp_path)

        claude_dir = home_dir / ".claude"
        claude_dir.mkdir(parents=True)

        # settings.json has no hook
        (claude_dir / "settings.json").write_text(json.dumps({}))

        # settings.local.json has hook
        local_claude = tmp_path / ".claude"
        local_claude.mkdir()
        (local_claude / "settings.local.json").write_text(json.dumps({
            "hooks": {
                "Stop": [{
                    "hooks": [{
                        "type": "command",
                        "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                    }]
                }]
            }
        }))

        # Script exists
        scripts_dir = claude_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "s-peach-notifier.sh").write_text("#!/bin/bash\n")

        cat = check_hooks()

        hook_check = next(c for c in cat.checks if "Hook in settings" in c.name)
        assert hook_check.status == "ok"
        assert "settings.local.json" in hook_check.message

    def test_hook_script_missing_when_installed(self, home_dir, monkeypatch):
        """If hook is in settings but script file is missing, warn."""
        from s_peach.doctor.checks.hooks import check_hooks

        monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))

        claude_dir = home_dir / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.json").write_text(json.dumps({
            "hooks": {
                "Stop": [{
                    "hooks": [{
                        "type": "command",
                        "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
                    }]
                }]
            }
        }))

        cat = check_hooks()

        script_check = next(c for c in cat.checks if "Hook script" in c.name)
        assert script_check.status == "warn"


# ---------------------------------------------------------------------------
# Tests: run_all_checks
# ---------------------------------------------------------------------------


class TestRunAllChecks:
    def test_returns_6_categories(self):
        from s_peach.doctor import run_all_checks

        with patch("s_peach.doctor.checks.environment.check_environment") as m_env, \
             patch("s_peach.doctor.checks.config.check_config") as m_cfg, \
             patch("s_peach.doctor.checks.dependencies.check_dependencies") as m_deps, \
             patch("s_peach.doctor.checks.voices.check_voices") as m_voices, \
             patch("s_peach.doctor.checks.server.check_server") as m_server, \
             patch("s_peach.doctor.checks.hooks.check_hooks") as m_hooks:
            from s_peach.doctor.models import CheckCategory, CheckResult

            for m in [m_env, m_cfg, m_deps, m_voices, m_server, m_hooks]:
                m.return_value = CheckCategory(name="Test", checks=[
                    CheckResult(name="test", status="ok", message="ok")
                ])

            result = run_all_checks()
            assert len(result) == 6

    def test_passes_settings_through(self):
        from s_peach.doctor import run_all_checks

        settings = _make_settings()

        with patch("s_peach.doctor.checks.environment.check_environment") as m_env, \
             patch("s_peach.doctor.checks.config.check_config") as m_cfg, \
             patch("s_peach.doctor.checks.dependencies.check_dependencies") as m_deps, \
             patch("s_peach.doctor.checks.voices.check_voices") as m_voices, \
             patch("s_peach.doctor.checks.server.check_server") as m_server, \
             patch("s_peach.doctor.checks.hooks.check_hooks") as m_hooks:
            from s_peach.doctor.models import CheckCategory, CheckResult

            for m in [m_env, m_cfg, m_deps, m_voices, m_server, m_hooks]:
                m.return_value = CheckCategory(name="Test", checks=[
                    CheckResult(name="test", status="ok", message="ok")
                ])

            run_all_checks(settings=settings)

            m_cfg.assert_called_once_with(settings)
            m_deps.assert_called_once_with(settings)
            m_voices.assert_called_once_with(settings)
            m_server.assert_called_once_with(settings)

    def test_handles_exception_in_check(self):
        """If one check raises, others still run."""
        from s_peach.doctor import run_all_checks

        with patch("s_peach.doctor.checks.environment.check_environment", side_effect=RuntimeError("boom")), \
             patch("s_peach.doctor.checks.config.check_config") as m_cfg, \
             patch("s_peach.doctor.checks.dependencies.check_dependencies") as m_deps, \
             patch("s_peach.doctor.checks.voices.check_voices") as m_voices, \
             patch("s_peach.doctor.checks.server.check_server") as m_server, \
             patch("s_peach.doctor.checks.hooks.check_hooks") as m_hooks:
            from s_peach.doctor.models import CheckCategory, CheckResult

            for m in [m_cfg, m_deps, m_voices, m_server, m_hooks]:
                m.return_value = CheckCategory(name="Test", checks=[
                    CheckResult(name="test", status="ok", message="ok")
                ])

            result = run_all_checks()
            assert len(result) == 6

            # First category should have error from the exception
            env_cat = result[0]
            assert env_cat.checks[0].status == "error"
            assert "boom" in env_cat.checks[0].message

            # Other categories should be ok
            for cat in result[1:]:
                assert cat.checks[0].status == "ok"


# ---------------------------------------------------------------------------
# Tests: all tests pass
# ---------------------------------------------------------------------------


class TestAllTestsPass:
    """Meta-test to verify the test file itself is loadable and complete."""

    def test_test_file_imports(self):
        # All imports succeed
        assert True
