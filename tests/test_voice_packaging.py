"""Tests for voice file packaging, init copying, and path resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from s_peach.models.chatterbox import _resolve_voice_path


# --- Tests: _resolve_voice_path ---


class TestResolveVoicePath:
    def test_absolute_path_exists(self, tmp_path: Path) -> None:
        """Absolute path to existing file is returned as-is."""
        wav = tmp_path / "speaker.wav"
        wav.write_bytes(b"fake wav")
        result = _resolve_voice_path(str(wav))
        assert result == str(wav)

    def test_absolute_path_missing_raises(self) -> None:
        """Absolute path to nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Reference audio clip not found"):
            _resolve_voice_path("/nonexistent/path/speaker.wav")

    def test_relative_path_found_in_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative path found in CWD is resolved."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        wav = voices_dir / "bea_amused.wav"
        wav.write_bytes(b"fake wav")
        monkeypatch.chdir(tmp_path)

        result = _resolve_voice_path("voices/bea_amused.wav")
        assert Path(result).is_file()
        assert result == str((tmp_path / "voices" / "bea_amused.wav").resolve())

    def test_relative_path_found_in_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative path not in CWD falls back to config_dir."""
        # Set up config dir with the voice file
        config_dir = tmp_path / "config" / "s-peach"
        voices_dir = config_dir / "voices"
        voices_dir.mkdir(parents=True)
        wav = voices_dir / "bea_amused.wav"
        wav.write_bytes(b"fake wav")

        # CWD has no such file
        cwd = tmp_path / "empty_cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        # Patch config_dir to return our test config dir
        with patch("s_peach.paths.config_dir", return_value=config_dir):
            result = _resolve_voice_path("voices/bea_amused.wav")

        assert Path(result).is_file()
        assert result == str(wav)

    def test_relative_path_not_found_anywhere_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative path not in CWD or config_dir raises FileNotFoundError."""
        cwd = tmp_path / "empty_cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        config_dir = tmp_path / "empty_config"
        config_dir.mkdir()

        with patch("s_peach.paths.config_dir", return_value=config_dir):
            with pytest.raises(FileNotFoundError, match="Reference audio clip not found"):
                _resolve_voice_path("voices/missing.wav")

    def test_cwd_takes_precedence_over_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both CWD and config_dir have the file, CWD wins."""
        # CWD version
        cwd = tmp_path / "cwd"
        cwd_voices = cwd / "voices"
        cwd_voices.mkdir(parents=True)
        cwd_wav = cwd_voices / "speaker.wav"
        cwd_wav.write_bytes(b"cwd version")
        monkeypatch.chdir(cwd)

        # config_dir version
        config_dir = tmp_path / "config" / "s-peach"
        cfg_voices = config_dir / "voices"
        cfg_voices.mkdir(parents=True)
        cfg_wav = cfg_voices / "speaker.wav"
        cfg_wav.write_bytes(b"config version")

        with patch("s_peach.paths.config_dir", return_value=config_dir):
            result = _resolve_voice_path("voices/speaker.wav")

        # CWD should win
        assert result == str(cwd_wav.resolve())


# --- Tests: init copies bundled voices ---


class TestInitCopiesVoices:
    """Test that `s-peach init` copies bundled voice files."""

    def _run_main(self, *args: str) -> tuple[int, str, str]:
        """Run main() and capture output."""
        from io import StringIO
        from s_peach.cli import main

        captured_out = StringIO()
        captured_err = StringIO()

        with patch("sys.stdout", captured_out), patch("sys.stderr", captured_err):
            try:
                main(list(args))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1

        return code, captured_out.getvalue(), captured_err.getvalue()

    def test_init_creates_voices_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """init creates voices/ directory under config dir."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        code, out, _ = self._run_main("init")

        assert code == 0
        voices_dir = tmp_path / "xdg" / "s-peach" / "voices"
        assert voices_dir.is_dir()

    def test_init_copies_bea_amused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """init copies bea_amused.wav to voices/ directory."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        code, out, _ = self._run_main("init")

        assert code == 0
        wav = tmp_path / "xdg" / "s-peach" / "voices" / "bea_amused.wav"
        assert wav.is_file()
        assert wav.stat().st_size > 0
        assert "Copied voice" in out

    def test_init_skips_existing_voice_file_and_backs_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """init does not overwrite an existing voice file but creates a .bak."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        voices_dir = tmp_path / "xdg" / "s-peach" / "voices"
        voices_dir.mkdir(parents=True)
        wav = voices_dir / "bea_amused.wav"
        wav.write_bytes(b"user modified version")

        code, out, _ = self._run_main("init")
        assert code == 0
        # File should still be the user's version
        assert wav.read_bytes() == b"user modified version"
        # Backup should exist
        bak = voices_dir / "bea_amused.wav.bak"
        assert bak.is_file()
        assert bak.read_bytes() == b"user modified version"
        assert "Backed up voice" in out

    def test_init_skips_backup_if_bak_already_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """init does not overwrite an existing .bak file."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        voices_dir = tmp_path / "xdg" / "s-peach" / "voices"
        voices_dir.mkdir(parents=True)
        wav = voices_dir / "bea_amused.wav"
        wav.write_bytes(b"current version")
        bak = voices_dir / "bea_amused.wav.bak"
        bak.write_bytes(b"original backup")

        code, out, _ = self._run_main("init")
        assert code == 0
        # Backup should be untouched
        assert bak.read_bytes() == b"original backup"
        assert "Backed up voice" not in out

    def test_init_force_still_copies_missing_voices(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """init --force still copies voice files that are missing."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        # First init
        self._run_main("init")
        # Remove the voice file
        wav = tmp_path / "xdg" / "s-peach" / "voices" / "bea_amused.wav"
        wav.unlink()

        # Force re-init
        code, out, _ = self._run_main("init", "--force")
        assert code == 0
        assert wav.is_file()


# --- Tests: bundled voices accessible via importlib.resources ---


class TestBundledVoices:
    def test_bundled_voices_dir_accessible(self) -> None:
        """The bundled defaults/voices/ directory is accessible."""
        from s_peach.scaffolding import _bundled_voices_dir

        voices = _bundled_voices_dir()
        names = [item.name for item in voices.iterdir()]
        assert "bea_amused.wav" in names

    def test_bundled_bea_amused_is_readable(self) -> None:
        """The bundled bea_amused.wav can be read as bytes."""
        from s_peach.scaffolding import _bundled_voices_dir

        voices = _bundled_voices_dir()
        bea = voices.joinpath("bea_amused.wav")
        data = bea.read_bytes()
        assert len(data) > 1000  # Should be a real WAV file
