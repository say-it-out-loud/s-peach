"""Tests for CLI commands."""

from __future__ import annotations

from unittest.mock import patch

from tests.cli.conftest import run_main


class TestServe:
    def test_serve_starts_uvicorn(self) -> None:
        with (
            patch("uvicorn.run") as mock_run,
            patch("s_peach.config.load_settings") as mock_load,
        ):
            from s_peach.config import Settings

            mock_load.return_value = Settings()
            run_main("serve")

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["host"] == "0.0.0.0"
        assert call_kwargs.kwargs["port"] == 7777

    def test_serve_host_override(self) -> None:
        with (
            patch("uvicorn.run") as mock_run,
            patch("s_peach.config.load_settings") as mock_load,
        ):
            from s_peach.config import Settings

            mock_load.return_value = Settings()
            run_main("serve", "--host", "127.0.0.1")

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["host"] == "127.0.0.1"

    def test_serve_port_override(self) -> None:
        with (
            patch("uvicorn.run") as mock_run,
            patch("s_peach.config.load_settings") as mock_load,
        ):
            from s_peach.config import Settings

            mock_load.return_value = Settings()
            run_main("serve", "--port", "8888")

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["port"] == 8888

