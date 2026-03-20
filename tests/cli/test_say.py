"""Tests for CLI commands."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from tests.cli.conftest import run_main


class TestSay:
    def test_say_sends_post(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, out, _ = run_main("say", "hello world")

        assert code == 0
        assert "Queued." in out
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["text"] == "hello world"

    def test_say_voice_flag(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--voice", "samantha", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["json"]["voice"] == "samantha"

    def test_say_model_flag(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--model", "kokoro", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["json"]["model"] == "kokoro"

    def test_say_exaggeration_flag(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--exaggeration", "1.5", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["json"]["exaggeration"] == 1.5

    def test_say_cfg_weight_flag(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--cfg-weight", "1.0", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["json"]["cfg_weight"] == 1.0

    def test_say_all_model_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All say flags forwarded into body together."""
        monkeypatch.setattr("s_peach.cli._helpers._load_notifier_config", lambda: {})
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main(
                "say", "--model", "chatterbox", "--voice", "Bea",
                "--exaggeration", "1.5", "--cfg-weight", "1.0", "hello"
            )

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body == {
            "text": "hello",
            "model": "chatterbox",
            "voice": "Bea",
            "exaggeration": 1.5,
            "cfg_weight": 1.0,
        }

    def test_say_omitted_params_not_in_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Params not passed on CLI should not appear in the POST body."""
        monkeypatch.setattr("s_peach.cli._helpers._load_notifier_config", lambda: {})
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "hello")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body == {"text": "hello"}
        assert "exaggeration" not in body
        assert "cfg_weight" not in body

    def test_say_summary_flag_summarizes_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--summary pipes text through the summary command from client.yaml."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {
                "summary": {
                    "command": 'cat',  # passthrough — just echo stdin
                    "max_length": 100,
                },
            },
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--summary", "--url", "http://localhost:9999", "hello world")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "hello world"

    def test_say_summary_uses_client_yaml_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Summary command from client.yaml is used, not hardcoded default."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {
                "summary": {
                    "command": 'echo "summarized output"',
                },
            },
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--summary", "--url", "http://localhost:9999", "long text here")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "summarized output"

    def test_say_summary_respects_max_length(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Summary output is truncated to max_length from client.yaml."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {
                "summary": {
                    "command": 'echo "a]b]c]d]e]f]g]h]i]j"',
                    "max_length": 5,
                },
            },
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--summary", "--url", "http://localhost:9999", "text")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert len(body["text"]) <= 5

    def test_say_summary_falls_back_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If summary command fails, original text is used."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {
                "summary": {
                    "command": "exit 1",
                },
            },
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--summary", "--url", "http://localhost:9999", "original text")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "original text"

    def test_say_summary_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If summary command times out, original text is used."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {
                "summary": {
                    "command": "sleep 60",
                    "timeout": 1,
                },
            },
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, err = run_main("say", "--summary", "--url", "http://localhost:9999", "original text")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "original text"
        assert "timed out" in err

    def test_say_without_summary_flag_skips_summarization(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without --summary, text passes through unchanged even if summary config exists."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {
                "summary": {"command": 'echo "should not appear"'},
            },
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--url", "http://localhost:9999", "original text")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "original text"

    def test_say_json_flag(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 3}
            )
            code, out, _ = run_main("say", "--json", "hello")

        assert code == 0
        assert '"status": "queued"' in out
        assert '"queue_size": 3' in out

    def test_say_json_flag_overrides_quiet(self) -> None:
        """--json still prints even when --quiet is also set."""
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, out, _ = run_main("say", "--json", "--quiet", "hello")

        assert code == 0
        assert '"status": "queued"' in out

    def test_say_url_flag(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--url", "http://myserver:8888", "hello")

        assert code == 0
        assert mock_post.call_args.args[0] == "http://myserver:8888/speak"

    def test_say_url_from_client_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """say resolves host/port from client.yaml when no --url flag or env var."""
        monkeypatch.delenv("S_PEACH_URL", raising=False)
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {"host": "host.docker.internal", "port": 7777},
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "hello")

        assert code == 0
        assert mock_post.call_args.args[0] == "http://host.docker.internal:7777/speak"

    def test_say_url_flag_beats_client_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--url flag takes precedence over client.yaml host/port."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {"host": "wrong-host", "port": 9999},
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--url", "http://right-host:8888", "hello")

        assert code == 0
        assert mock_post.call_args.args[0] == "http://right-host:8888/speak"

    def test_say_api_key_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S_PEACH_API_KEY", "my-secret")
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["headers"]["X-API-Key"] == "my-secret"

    def test_say_timeout_flag(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--timeout", "5.5", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["timeout"] == 5.5

    def test_say_quiet_flag(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, out, _ = run_main(
                "say", "--quiet", "--url", "http://localhost:9999", "hello"
            )

        assert code == 0
        assert "Queued." not in out

    def test_say_stdin(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, out, _ = run_main("say", stdin_text="hello from pipe")

        assert code == 0
        assert "Queued." in out
        assert mock_post.call_args.kwargs["json"]["text"] == "hello from pipe"

    def test_say_no_text_tty_exits_1(self) -> None:
        tty_stdin = StringIO("")
        tty_stdin.isatty = lambda: True  # type: ignore[assignment]

        with patch("sys.stdin", tty_stdin):
            code, _, err = run_main("say")

        assert code == 1
        assert "no text provided" in err.lower()

    def test_say_empty_stdin_exits_1(self) -> None:
        code, _, err = run_main("say", stdin_text="")
        assert code == 1
        assert "no text" in err.lower()

    def test_say_connection_error_with_hint(self) -> None:
        with patch(
            "s_peach.cli.say.httpx.post",
            side_effect=httpx.ConnectError("refused"),
        ):
            code, _, err = run_main("say", "--url", "http://localhost:9999", "hello")

        assert code == 1
        assert "cannot connect" in err.lower()
        assert "s-peach serve" in err

    def test_say_timeout_error(self) -> None:
        with patch(
            "s_peach.cli.say.httpx.post",
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            code, _, err = run_main("say", "--url", "http://localhost:9999", "hello")

        assert code == 1
        assert "timed out" in err.lower()

    def test_say_server_error(self) -> None:
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=500, json={"detail": "TTS generation failed"}
            )
            code, _, err = run_main("say", "--url", "http://localhost:9999", "hello")

        assert code == 1
        assert "TTS generation failed" in err

    def test_say_env_var_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S_PEACH_URL", "http://envserver:9999")
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "hello")

        assert code == 0
        assert mock_post.call_args.args[0] == "http://envserver:9999/speak"

    def test_say_env_var_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("S_PEACH_API_KEY", "env-secret")
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--url", "http://localhost:9999", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["headers"]["X-API-Key"] == "env-secret"

    def test_say_api_key_from_notifier_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """say reads api_key from client.yaml when env var is unset."""
        monkeypatch.delenv("S_PEACH_API_KEY", raising=False)
        cfg_dir = tmp_path / "xdg" / "s-peach"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "client.yaml").write_text('api_key: "yaml-secret"\n')
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--url", "http://localhost:9999", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["headers"]["X-API-Key"] == "yaml-secret"

    def test_say_env_api_key_beats_notifier_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """S_PEACH_API_KEY env var takes precedence over client.yaml."""
        cfg_dir = tmp_path / "xdg" / "s-peach"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "client.yaml").write_text('api_key: "yaml-secret"\n')
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("S_PEACH_API_KEY", "env-wins")

        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--url", "http://localhost:9999", "hello")

        assert code == 0
        assert mock_post.call_args.kwargs["headers"]["X-API-Key"] == "env-wins"

    def test_say_no_api_key_header_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No X-API-Key header when neither env var nor client.yaml has a key."""
        monkeypatch.delenv("S_PEACH_API_KEY", raising=False)
        # Point to empty config dir — no client.yaml
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        # Pre-create dir so auto-init doesn't scaffold a client.yaml with an API key
        (tmp_path / "xdg" / "s-peach").mkdir(parents=True)

        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--url", "http://localhost:9999", "hello")

        assert code == 0
        assert "X-API-Key" not in mock_post.call_args.kwargs.get("headers", {})

    def test_say_model_voice_speed_from_notifier_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """say reads model, voice, speed defaults from client.yaml."""
        monkeypatch.delenv("S_PEACH_API_KEY", raising=False)
        cfg_dir = tmp_path / "xdg" / "s-peach"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "client.yaml").write_text(
            'model: "kokoro"\nvoice: "Heart"\nspeed: 1.3\n'
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--url", "http://localhost:9999", "hello")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["model"] == "kokoro"
        assert body["voice"] == "Heart"
        assert body["speed"] == 1.3

    def test_say_cli_flags_override_notifier_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI flags take precedence over client.yaml defaults."""
        monkeypatch.delenv("S_PEACH_API_KEY", raising=False)
        cfg_dir = tmp_path / "xdg" / "s-peach"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "client.yaml").write_text(
            'model: "kokoro"\nvoice: "Heart"\nspeed: 1.3\n'
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main(
                "say", "--url", "http://localhost:9999",
                "--model", "kitten-mini", "--voice", "Bella", "--speed", "2.0",
                "hello",
            )

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["model"] == "kitten-mini"
        assert body["voice"] == "Bella"
        assert body["speed"] == 2.0

    def test_say_save_writes_wav(self, tmp_path: Path) -> None:
        """--save should write WAV to output directory."""
        wav_bytes = b"RIFF\x00\x00\x00\x00WAVEfmt "  # fake WAV header
        mock_response = httpx.Response(
            status_code=202,
            content=wav_bytes,
            headers={"content-type": "audio/wav", "x-queue-size": "1"},
        )
        with (
            patch("s_peach.cli.say.httpx.post", return_value=mock_response),
            patch("s_peach.paths.config_dir", return_value=tmp_path),
        ):
            code, out, _ = run_main("say", "--save", "hello")

        assert code == 0
        assert "Saved:" in out
        output_dir = tmp_path / "output"
        assert output_dir.exists()
        wav_files = list(output_dir.glob("*.wav"))
        assert len(wav_files) == 1
        assert wav_files[0].read_bytes() == wav_bytes

    def test_say_save_sends_return_audio(self) -> None:
        """--save should include return_audio in request body."""
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202,
                content=b"RIFF",
                headers={"content-type": "audio/wav"},
            )
            code, _, _ = run_main("say", "--save", "hello")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["return_audio"] is True

    def test_say_lang_flag_sends_language(self) -> None:
        """--lang flag should include language in request body."""
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--lang", "fr", "bonjour")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["language"] == "fr"

    def test_say_without_lang_flag_omits_language(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without --lang, language should not appear in the POST body."""
        monkeypatch.setattr("s_peach.cli._helpers._load_notifier_config", lambda: {})
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "hello")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert "language" not in body

    def test_say_language_from_client_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Language from client.yaml should be used when --lang is not passed."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {"language": "ja"},
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "hello")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["language"] == "ja"

    def test_say_lang_flag_overrides_client_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--lang flag should override language from client.yaml."""
        monkeypatch.setattr(
            "s_peach.cli._helpers._load_notifier_config",
            lambda: {"language": "ja"},
        )
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202, json={"status": "queued", "queue_size": 1}
            )
            code, _, _ = run_main("say", "--lang", "fr", "hello")

        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body["language"] == "fr"

    def test_say_that_again_save_writes_wav(self, tmp_path: Path) -> None:
        """say-that-again --save should write WAV to output directory."""
        wav_bytes = b"RIFF\x00\x00\x00\x00WAVEfmt "
        mock_response = httpx.Response(
            status_code=202,
            content=wav_bytes,
            headers={"content-type": "audio/wav", "x-queue-size": "1"},
        )
        with (
            patch("s_peach.cli.say.httpx.post", return_value=mock_response),
            patch("s_peach.paths.config_dir", return_value=tmp_path),
        ):
            code, out, _ = run_main("say-that-again", "--save")

        assert code == 0
        assert "Saved:" in out
        wav_files = list((tmp_path / "output").glob("*.wav"))
        assert len(wav_files) == 1
        assert wav_files[0].read_bytes() == wav_bytes

    def test_say_that_again_save_sends_return_audio_param(self) -> None:
        """say-that-again --save should include return_audio query param."""
        with patch("s_peach.cli.say.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(
                status_code=202,
                content=b"RIFF",
                headers={"content-type": "audio/wav"},
            )
            code, _, _ = run_main("say-that-again", "--save")

        assert code == 0
        params = mock_post.call_args.kwargs.get("params", {})
        assert params.get("return_audio") == "true"

