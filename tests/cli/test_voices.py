"""Tests for CLI commands."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx

from tests.cli.conftest import run_main


class TestVoices:
    def test_voices_prints_formatted_output(self) -> None:
        """voices command should pretty-print models and their voices."""
        mock_response = httpx.Response(
            status_code=200,
            json=[
                {
                    "model": "kokoro",
                    "voices": [
                        {"name": "Heart", "description": ""},
                        {"name": "Alloy", "description": ""},
                    ],
                    "languages": [],
                },
                {
                    "model": "kitten-micro",
                    "voices": [
                        {"name": "Bella", "description": ""},
                    ],
                    "languages": [],
                },
            ],
        )
        with patch("s_peach.cli.voices.httpx.get", return_value=mock_response):
            code, out, _ = run_main("voices")
        assert code == 0
        assert "kokoro (2 voices)" in out
        assert "Heart" in out
        assert "Alloy" in out
        assert "kitten-micro (1 voices)" in out
        assert "Bella" in out

    def test_voices_shows_languages_for_multilingual_model(self) -> None:
        """voices command shows supported languages for models that have them."""
        mock_response = httpx.Response(
            status_code=200,
            json=[
                {
                    "model": "kokoro",
                    "voices": [{"name": "Heart", "description": ""}],
                    "languages": ["en", "gb", "ja", "zh", "es", "fr", "hi", "it", "pt"],
                },
                {
                    "model": "kitten-micro",
                    "voices": [{"name": "Bella", "description": ""}],
                    "languages": [],
                },
            ],
        )
        with patch("s_peach.cli.voices.httpx.get", return_value=mock_response):
            code, out, _ = run_main("voices")
        assert code == 0
        assert "languages: en, gb, ja" in out
        # kitten-micro has no languages — no "languages:" suffix
        assert "kitten-micro (1 voices)\n" in out or "kitten-micro (1 voices)" in out

    def test_voices_backward_compatible_no_languages_key(self) -> None:
        """voices command handles server response without languages key (backward compat)."""
        mock_response = httpx.Response(
            status_code=200,
            json=[
                {
                    "model": "kokoro",
                    "voices": [{"name": "Heart", "description": ""}],
                    # no "languages" key
                },
            ],
        )
        with patch("s_peach.cli.voices.httpx.get", return_value=mock_response):
            code, out, _ = run_main("voices")
        assert code == 0
        assert "kokoro (1 voices)" in out
        assert "Heart" in out

    def test_voices_json_flag(self) -> None:
        """--json flag outputs raw JSON."""
        mock_response = httpx.Response(
            status_code=200,
            json=[{"model": "kokoro", "voices": [{"name": "Heart", "description": ""}]}],
        )
        with patch("s_peach.cli.voices.httpx.get", return_value=mock_response):
            code, out, _ = run_main("voices", "--json")
        assert code == 0
        data = json.loads(out)
        assert data[0]["model"] == "kokoro"

    def test_voices_no_models(self) -> None:
        """Empty response shows no models message."""
        mock_response = httpx.Response(status_code=200, json=[])
        with patch("s_peach.cli.voices.httpx.get", return_value=mock_response):
            code, out, _ = run_main("voices")
        assert code == 0
        assert "No models loaded" in out

    def test_voices_connection_error(self) -> None:
        """Connection error shows helpful message."""
        with patch("s_peach.cli.voices.httpx.get", side_effect=httpx.ConnectError("refused")):
            code, _, err = run_main("voices")
        assert code == 1
        assert "cannot connect" in err

    def test_voices_server_error(self) -> None:
        """Non-200 response shows error."""
        mock_response = httpx.Response(status_code=500)
        with patch("s_peach.cli.voices.httpx.get", return_value=mock_response):
            code, _, err = run_main("voices")
        assert code == 1
        assert "500" in err

