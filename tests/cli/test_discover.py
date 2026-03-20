"""Tests for the `s-peach discover` CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from s_peach.cli import main


# Mock voice data returned by GET /voices
_VOICES_RESPONSE = [
    {
        "model": "kitten-mini",
        "voices": [
            {"name": "Bella", "description": ""},
            {"name": "Luna", "description": ""},
            {"name": "Jasper", "description": ""},
        ],
    },
    {
        "model": "kokoro",
        "voices": [
            {"name": "Heart", "description": ""},
            {"name": "Emma", "description": ""},
        ],
    },
]

# Mock /speak-sync successful response
_SPEAK_SYNC_OK = MagicMock(
    status_code=200,
    json=lambda: {"status": "done", "duration_ms": 500},
)


def _mock_voices_response():
    """Create a fresh mock response for GET /voices."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _VOICES_RESPONSE
    return resp


def _mock_speak_sync_response():
    """Create a fresh mock response for POST /speak-sync."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"status": "done", "duration_ms": 500}
    return resp


class TestDiscoverArgParsing:
    def test_model_omitted_prints_available_and_exits(self, capsys) -> None:
        """Without --model, should list available models and exit 1."""
        mock_resp = _mock_voices_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx:
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_resp
            with pytest.raises(SystemExit) as exc_info:
                main(["discover"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "kitten-mini" in captured.err
        assert "kokoro" in captured.err
        assert "--model is required" in captured.err

    def test_default_text_used_when_omitted(self, capsys) -> None:
        """Text should default to the sample sentence."""
        mock_voices = _mock_voices_response()
        calls = []

        def capture_post(url, **kwargs):
            calls.append(kwargs)
            return _mock_speak_sync_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.side_effect = capture_post
            main(["discover", "--model", "kitten-mini"])

        # All calls should use default text
        for call in calls:
            assert call["json"]["text"] == "The quick brown fox jumps over the lazy dog"


class TestDiscoverVoiceIteration:
    def test_iterates_all_voices_with_progress(self, capsys) -> None:
        """Should print progress counter for each voice."""
        mock_voices = _mock_voices_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.return_value = _mock_speak_sync_response()
            main(["discover", "--model", "kitten-mini", "Hello"])

        captured = capsys.readouterr()
        assert "Bella (kitten-mini) [1/3]" in captured.out
        assert "Luna (kitten-mini) [2/3]" in captured.out
        assert "Jasper (kitten-mini) [3/3]" in captured.out
        assert "Played 3/3 voices for kitten-mini (0 skipped)" in captured.out

    def test_voices_filter(self, capsys) -> None:
        """--voices should filter to only specified voices."""
        mock_voices = _mock_voices_response()
        posted_voices = []

        def capture_post(url, **kwargs):
            posted_voices.append(kwargs["json"]["voice"])
            return _mock_speak_sync_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.side_effect = capture_post
            main(["discover", "--model", "kitten-mini", "--voices", "Bella,Jasper", "Hi"])

        assert posted_voices == ["Bella", "Jasper"]

    def test_voices_whitespace_stripped(self, capsys) -> None:
        """Whitespace around voice names in --voices should be stripped."""
        mock_voices = _mock_voices_response()
        posted_voices = []

        def capture_post(url, **kwargs):
            posted_voices.append(kwargs["json"]["voice"])
            return _mock_speak_sync_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.side_effect = capture_post
            main(["discover", "--model", "kitten-mini", "--voices", "Bella , Luna ", "Hi"])

        assert posted_voices == ["Bella", "Luna"]

    def test_invalid_voice_skipped_with_warning(self, capsys) -> None:
        """Invalid voice names should produce a warning but not stop iteration."""
        mock_voices = _mock_voices_response()
        posted_voices = []

        def capture_post(url, **kwargs):
            posted_voices.append(kwargs["json"]["voice"])
            return _mock_speak_sync_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.side_effect = capture_post
            main(["discover", "--model", "kitten-mini", "--voices", "Bella,Invalid,Luna", "Hi"])

        assert posted_voices == ["Bella", "Luna"]
        captured = capsys.readouterr()
        assert "Warning: voice 'Invalid' not found" in captured.err
        assert "1 skipped" in captured.out


class TestDiscoverFlags:
    def test_wait_pauses_between_voices(self) -> None:
        """--wait N should sleep N seconds between voices."""
        mock_voices = _mock_voices_response()
        sleep_calls = []

        def track_sleep(n):
            sleep_calls.append(n)

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep", side_effect=track_sleep):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.return_value = _mock_speak_sync_response()
            main(["discover", "--model", "kitten-mini", "--wait", "2", "Hi"])

        # 3 voices, sleep between each except after last = 2 sleeps
        assert len(sleep_calls) == 2
        assert all(s == 2.0 for s in sleep_calls)

    def test_speed_passed_to_speak_sync(self) -> None:
        """--speed should be passed through to /speak-sync body."""
        mock_voices = _mock_voices_response()
        calls = []

        def capture_post(url, **kwargs):
            calls.append(kwargs)
            return _mock_speak_sync_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.side_effect = capture_post
            main(["discover", "--model", "kitten-mini", "--speed", "1.5", "--voices", "Bella", "Hi"])

        assert calls[0]["json"]["speed"] == 1.5

    def test_timeout_passed_to_httpx(self) -> None:
        """--timeout should set the httpx timeout."""
        mock_voices = _mock_voices_response()
        calls = []

        def capture_post(url, **kwargs):
            calls.append(kwargs)
            return _mock_speak_sync_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.side_effect = capture_post
            main(["discover", "--model", "kitten-mini", "--timeout", "60", "--voices", "Bella", "Hi"])

        assert calls[0]["timeout"] == 60.0

    def test_dry_run_lists_without_playing(self, capsys) -> None:
        """--dry-run should list voices without calling /speak-sync."""
        mock_voices = _mock_voices_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            main(["discover", "--model", "kitten-mini", "--dry-run"])

        # Should NOT have called post (no /speak-sync)
        mock_httpx.post.assert_not_called()
        captured = capsys.readouterr()
        assert "Bella" in captured.out
        assert "Luna" in captured.out
        assert "Jasper" in captured.out
        assert "Listed 3/3" in captured.out


class TestDiscoverErrors:
    def test_model_not_found_on_server(self, capsys) -> None:
        """Unknown model should print error with available models."""
        mock_voices = _mock_voices_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            with pytest.raises(SystemExit) as exc_info:
                main(["discover", "--model", "nonexistent", "Hello"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "nonexistent" in captured.err
        assert "kitten-mini" in captured.err

    def test_server_unreachable(self, capsys) -> None:
        """Should print connection error when server is down."""
        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}):
            connect_err = type("ConnectError", (Exception,), {})
            mock_httpx.ConnectError = connect_err
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.side_effect = connect_err("refused")
            with pytest.raises(SystemExit) as exc_info:
                main(["discover", "--model", "kitten-mini", "Hello"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "cannot connect" in captured.err

    def test_speak_sync_error_skips_voice(self, capsys) -> None:
        """Server error on /speak-sync should skip voice and continue."""
        mock_voices = _mock_voices_response()
        call_count = 0

        def alternating_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                resp = MagicMock()
                resp.status_code = 500
                resp.json.return_value = {"detail": "TTS failed"}
                resp.text = "TTS failed"
                return resp
            return _mock_speak_sync_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.side_effect = alternating_post
            main(["discover", "--model", "kitten-mini", "Hi"])

        captured = capsys.readouterr()
        assert "Played 2/3" in captured.out
        assert "1 skipped" in captured.out

    def test_completion_summary_printed(self, capsys) -> None:
        """After iteration, a completion summary should be printed."""
        mock_voices = _mock_voices_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value=None), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.return_value = mock_voices
            mock_httpx.post.return_value = _mock_speak_sync_response()
            main(["discover", "--model", "kitten-mini", "Hi"])

        captured = capsys.readouterr()
        assert "Played 3/3 voices for kitten-mini (0 skipped)" in captured.out


class TestDiscoverURLAndAPIKey:
    def test_url_and_api_key_used(self) -> None:
        """Should use resolved URL and API key for requests."""
        mock_voices = _mock_voices_response()
        get_calls = []
        post_calls = []

        def capture_get(url, **kwargs):
            get_calls.append((url, kwargs))
            return mock_voices

        def capture_post(url, **kwargs):
            post_calls.append((url, kwargs))
            return _mock_speak_sync_response()

        with patch("s_peach.cli.discover.httpx") as mock_httpx, \
             patch("s_peach.cli._helpers._resolve_url", return_value="http://myhost:9999"), \
             patch("s_peach.cli._helpers._resolve_api_key", return_value="secret-key"), \
             patch("s_peach.cli._helpers._load_notifier_config", return_value={}), \
             patch("time.sleep"):
            mock_httpx.ConnectError = Exception
            mock_httpx.TimeoutException = Exception
            mock_httpx.get.side_effect = capture_get
            mock_httpx.post.side_effect = capture_post
            main(["discover", "--model", "kitten-mini", "--voices", "Bella", "Hi"])

        assert get_calls[0][0] == "http://myhost:9999/voices"
        assert get_calls[0][1]["headers"]["X-API-Key"] == "secret-key"
        assert post_calls[0][0] == "http://myhost:9999/speak-sync"
        assert post_calls[0][1]["headers"]["X-API-Key"] == "secret-key"
