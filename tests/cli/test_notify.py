"""Tests for s-peach notify — text extraction, summarization, and command flow."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# _extract_json_field
# ---------------------------------------------------------------------------


class TestExtractJsonField:
    """Test the dot-path JSON field extractor that replaces jq."""

    def test_simple_top_level_field(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"last_assistant_message": "Build succeeded"}
        assert _extract_json_field(data, ".last_assistant_message") == "Build succeeded"

    def test_nested_field(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"output": {"text": "Custom output here"}}
        assert _extract_json_field(data, ".output.text") == "Custom output here"

    def test_deeply_nested_field(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"a": {"b": {"c": "deep value"}}}
        assert _extract_json_field(data, ".a.b.c") == "deep value"

    def test_missing_field_returns_none(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"other": "value"}
        assert _extract_json_field(data, ".nonexistent") is None

    def test_missing_nested_field_returns_none(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"output": {"other": "value"}}
        assert _extract_json_field(data, ".output.text") is None

    def test_non_string_value_returns_none(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"count": 42}
        assert _extract_json_field(data, ".count") is None

    def test_dict_value_returns_none(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"nested": {"key": "val"}}
        assert _extract_json_field(data, ".nested") is None

    def test_empty_expression_returns_none(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"key": "val"}
        assert _extract_json_field(data, "") is None

    def test_no_leading_dot_returns_none(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"key": "val"}
        assert _extract_json_field(data, "key") is None

    def test_empty_dict(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        assert _extract_json_field({}, ".anything") is None

    def test_intermediate_non_dict_returns_none(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"output": "string_not_dict"}
        assert _extract_json_field(data, ".output.text") is None

    # --- Array indexing ---

    def test_array_index_simple(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"choices": [{"message": {"content": "Hello"}}]}
        assert _extract_json_field(data, ".choices[0].message.content") == "Hello"

    def test_array_index_non_first(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"items": ["a", "b", "c"]}
        assert _extract_json_field(data, ".items[2]") == "c"

    def test_array_index_out_of_bounds(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"items": ["a"]}
        assert _extract_json_field(data, ".items[5]") is None

    def test_array_index_on_non_list(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"items": "not a list"}
        assert _extract_json_field(data, ".items[0]") is None

    def test_array_index_nested(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"a": [{"b": [{"c": "deep"}]}]}
        assert _extract_json_field(data, ".a[0].b[0].c") == "deep"

    def test_array_index_returns_none_for_non_string(self) -> None:
        from s_peach.cli.notify import _extract_json_field

        data = {"items": [42]}
        assert _extract_json_field(data, ".items[0]") is None

    def test_openai_style_response(self) -> None:
        """The README example: .choices[0].message.content"""
        from s_peach.cli.notify import _extract_json_field

        data = {
            "choices": [
                {"message": {"role": "assistant", "content": "Build complete."}}
            ]
        }
        assert _extract_json_field(data, ".choices[0].message.content") == "Build complete."


# ---------------------------------------------------------------------------
# _extract_claude_jsonl
# ---------------------------------------------------------------------------


class TestExtractClaudeJsonl:
    """Test JSONL transcript parsing that replaces jq pipeline."""

    def test_extracts_assistant_text(self, tmp_path: Path) -> None:
        from s_peach.cli.notify import _extract_claude_jsonl

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "I fixed the bug"}]}}),
            json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "thanks"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "All done"}]}}),
        ]
        transcript.write_text("\n".join(lines) + "\n")

        result = _extract_claude_jsonl(str(transcript), tail_lines=20)
        assert result is not None
        assert "I fixed the bug" in result
        assert "All done" in result
        # User messages should not be included
        assert "thanks" not in result

    def test_tail_lines_truncation(self, tmp_path: Path) -> None:
        from s_peach.cli.notify import _extract_claude_jsonl

        transcript = tmp_path / "transcript.jsonl"
        # Create many assistant messages, each on its own line
        lines = []
        for i in range(50):
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": f"line {i}"}]},
            }))
        transcript.write_text("\n".join(lines) + "\n")

        result = _extract_claude_jsonl(str(transcript), tail_lines=5)
        assert result is not None
        result_lines = result.splitlines()
        assert len(result_lines) == 5
        assert "line 49" in result_lines[-1]

    def test_missing_file_returns_none(self) -> None:
        from s_peach.cli.notify import _extract_claude_jsonl

        assert _extract_claude_jsonl("/nonexistent/file.jsonl", tail_lines=20) is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        from s_peach.cli.notify import _extract_claude_jsonl

        transcript = tmp_path / "empty.jsonl"
        transcript.write_text("")
        assert _extract_claude_jsonl(str(transcript), tail_lines=20) is None

    def test_no_assistant_messages_returns_none(self, tmp_path: Path) -> None:
        from s_peach.cli.notify import _extract_claude_jsonl

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "hello"}]}}),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        assert _extract_claude_jsonl(str(transcript), tail_lines=20) is None

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        from s_peach.cli.notify import _extract_claude_jsonl

        transcript = tmp_path / "transcript.jsonl"
        content = "not valid json\n" + json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "valid line"}]},
        }) + "\n"
        transcript.write_text(content)

        result = _extract_claude_jsonl(str(transcript), tail_lines=20)
        assert result is not None
        assert "valid line" in result


# ---------------------------------------------------------------------------
# _cmd_notify — integration tests with mocked HTTP
# ---------------------------------------------------------------------------


def _make_args(
    quiet: bool = False,
    summary: bool = False,
    no_summary: bool = False,
    model: str | None = None,
    voice: str | None = None,
    speed: float | None = None,
    exaggeration: float | None = None,
    cfg_weight: float | None = None,
    lang: str | None = None,
    url: str | None = None,
    timeout: float = 30.0,
):
    """Create a mock args namespace for notify command."""
    import argparse

    return argparse.Namespace(
        quiet=quiet,
        summary=summary,
        no_summary=no_summary,
        model=model,
        voice=voice,
        speed=speed,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        lang=lang,
        url=url,
        timeout=timeout,
    )


def _mock_notifier_config(source: str = ".last_assistant_message", **overrides):
    """Build a mock notifier config dict."""
    cfg = {
        "host": "localhost",
        "port": 7777,
        "model": "kokoro",
        "voice": "Bella_US",
        "summary": {
            "enabled": False,
            "source": source,
            "tail_lines": 20,
            "max_length": 500,
        },
    }
    cfg["summary"].update(overrides)
    return cfg


class TestCmdNotifyJqExpression:
    """Notify with jq-expression source mode."""

    def test_extracts_default_field_and_speaks(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Build succeeded"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        assert mock_post.call_count == 2
        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "Build succeeded"

    def test_extracts_nested_field(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"output": {"text": "Custom output"}})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config(".output.text")),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "Custom output"

    def test_session_id_does_not_override_generic_fallback(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"session_id": "abc123"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "Session abc123 complete."

    def test_fallback_to_generic_message(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"something_else": "value"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "All tasks complete."


class TestCmdNotifyRaw:
    """Notify with raw source mode."""

    def test_raw_passes_text_through(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO("Hello plain text")),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config("raw")),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "Hello plain text"

    def test_raw_with_json_input(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        json_text = '{"key": "value"}'
        with (
            patch("sys.stdin", StringIO(json_text)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config("raw")),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == json_text


class TestCmdNotifyClaudeJsonl:
    """Notify with claude_jsonl source mode."""

    def test_reads_transcript_file(self, tmp_path: Path) -> None:
        from s_peach.cli.notify import _cmd_notify

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "I fixed the bug"}]}}),
            json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "thanks"}]}}),
        ]
        transcript.write_text("\n".join(lines) + "\n")

        hook_json = json.dumps({"transcript_path": str(transcript)})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config("claude_jsonl")),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert "I fixed the bug" in body["text"]

    def test_falls_back_to_last_assistant_message(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({
            "last_assistant_message": "Fallback message",
            "transcript_path": "/nonexistent/file.jsonl",
        })
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config("claude_jsonl")),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "Fallback message"

    def test_generic_fallback_when_no_data(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"some_unrelated": "data"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config("claude_jsonl")),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "All tasks complete."


class TestCmdNotifyEmptyStdin:
    """Notify with empty or missing stdin."""

    def test_empty_stdin_gives_fallback(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO("")),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "All tasks complete."

    def test_tty_stdin_gives_fallback(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", mock_stdin),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "All tasks complete."


class TestCmdNotifyTailLines:
    """Test tail_lines truncation before summarization."""

    def test_max_length_truncation(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        long_text = "x" * 1000
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config("raw", max_length=100)

        with (
            patch("sys.stdin", StringIO(long_text)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert len(body["text"]) == 100


class TestCmdNotifySummarization:
    """Test summarization integration in notify."""

    def test_summarize_called_when_enabled(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Detailed build output here"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config(enabled=True)

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt", return_value="Build done.") as mock_summarize,
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        mock_summarize.assert_called_once()
        # Verify it used notify_prompt key
        assert mock_summarize.call_args.args[2] == "notify_prompt"
        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "Build done."

    def test_no_summarize_when_disabled(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Build output"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config(enabled=False)

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt") as mock_summarize,
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response),
        ):
            _cmd_notify(_make_args())

        mock_summarize.assert_not_called()

    def test_no_summarize_for_fallback_message(self) -> None:
        """Summarization should not run for generic fallback messages."""
        from s_peach.cli.notify import _cmd_notify

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config(enabled=True)

        with (
            patch("sys.stdin", StringIO("")),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt") as mock_summarize,
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response),
        ):
            _cmd_notify(_make_args())

        mock_summarize.assert_not_called()


    def test_no_summary_flag_overrides_config(self) -> None:
        """--no-summary disables summarization even when config says enabled."""
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Detailed output"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config(enabled=True)

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt") as mock_summarize,
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response),
        ):
            _cmd_notify(_make_args(no_summary=True))

        mock_summarize.assert_not_called()

    def test_summary_flag_overrides_config(self) -> None:
        """--summary enables summarization even when config says disabled."""
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Detailed output"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config(enabled=False)

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt", return_value="Summary.") as mock_summarize,
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response),
        ):
            _cmd_notify(_make_args(summary=True))

        mock_summarize.assert_called_once()


class TestCmdNotifyErrorHandling:
    """Notify always exits 0, even on errors."""

    def test_connection_error_prints_to_stderr(self, capsys) -> None:
        from s_peach.cli.notify import _cmd_notify

        import httpx

        hook_json = json.dumps({"last_assistant_message": "test"})

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", side_effect=httpx.ConnectError("refused")),
        ):
            # Should not raise
            _cmd_notify(_make_args())

        captured = capsys.readouterr()
        assert "cannot connect" in captured.err

    def test_invalid_json_stdin_uses_fallback(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO("not valid json at all")),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["text"] == "All tasks complete."

    def test_quiet_suppresses_stdout(self, capsys) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "test"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response),
        ):
            _cmd_notify(_make_args(quiet=True))

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_server_error_prints_to_stderr(self, capsys) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "test"})
        mock_response = MagicMock()
        mock_response.status_code = 500

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response),
        ):
            _cmd_notify(_make_args())

        captured = capsys.readouterr()
        assert "500" in captured.err


class TestCmdNotifyRequestBody:
    """Verify that notify sends correct model/voice/speed from config."""

    def test_sends_model_voice_from_config(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "test"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config()
        cfg["model"] = "kitten-mini"
        cfg["voice"] = "Heart"
        cfg["speed"] = 1.5
        cfg["language"] = "fr"

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value="test-key"),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args())

        body = mock_post.call_args.kwargs["json"]
        assert body["model"] == "kitten-mini"
        assert body["voice"] == "Heart"
        assert body["speed"] == 1.5
        assert body["language"] == "fr"

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["X-API-Key"] == "test-key"


    def test_cli_args_override_config(self) -> None:
        """CLI flags like --voice, --model override client.yaml values."""
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "test"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config()
        cfg["model"] = "kokoro"
        cfg["voice"] = "Heart"
        cfg["speed"] = 1.0

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args(model="kitten-mini", voice="Luna", speed=1.2))

        body = mock_post.call_args.kwargs["json"]
        assert body["model"] == "kitten-mini"
        assert body["voice"] == "Luna"
        assert body["speed"] == 1.2

    def test_cli_exaggeration_and_cfg_weight(self) -> None:
        """CLI --exaggeration and --cfg-weight are sent in request body."""
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "test"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args(exaggeration=0.8, cfg_weight=0.5))

        body = mock_post.call_args.kwargs["json"]
        assert body["exaggeration"] == 0.8
        assert body["cfg_weight"] == 0.5

    def test_cli_url_and_timeout(self) -> None:
        """CLI --url and --timeout are used for the request."""
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "test"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=_mock_notifier_config()),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://myhost:9999") as mock_url,
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response) as mock_post,
        ):
            _cmd_notify(_make_args(url="http://myhost:9999", timeout=60.0))

        mock_url.assert_called_with("http://myhost:9999")
        assert mock_post.call_args.kwargs["timeout"] == 60.0


class TestCmdNotifyBooleanNormalization:
    """Test that string 'true'/'false' from YAML config is handled."""

    def test_string_false_disables_summary(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "test"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config(enabled="false")

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt") as mock_summarize,
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response),
        ):
            _cmd_notify(_make_args())

        mock_summarize.assert_not_called()

    def test_string_true_enables_summary(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "test"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"queue_size": 1}

        cfg = _mock_notifier_config(enabled="true")

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt", return_value="summary") as mock_summarize,
            patch("s_peach.cli.notify.httpx.post", return_value=mock_response),
        ):
            _cmd_notify(_make_args())

        mock_summarize.assert_called_once()


# ---------------------------------------------------------------------------
# Dedup — prevent repeat notifications from claude -p Stop-hook cascade
# ---------------------------------------------------------------------------


class _RouteMockPost:
    """Route `httpx.post` mocks by URL suffix — /dedup/check vs /speak."""

    def __init__(self, dedup_responses: list[bool] | None = None) -> None:
        # Queue of bool replies for /dedup/check. Defaults to "always new".
        self.dedup_replies = list(dedup_responses or [])
        self.speak_calls: list[dict] = []
        self.dedup_calls: list[dict] = []

    def __call__(self, url: str, **kwargs):
        body = kwargs.get("json", {})
        if url.endswith("/dedup/check"):
            self.dedup_calls.append(body)
            seen = self.dedup_replies.pop(0) if self.dedup_replies else False
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"seen": seen}
            return resp
        if url.endswith("/speak"):
            self.speak_calls.append(body)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"queue_size": 1}
            return resp
        raise AssertionError(f"unexpected URL: {url}")


class TestNotifyDedup:
    """Skip duplicate notifications when the server says the hash was just seen."""

    def test_fires_when_server_reports_not_seen(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Task done"})
        route = _RouteMockPost([False])
        cfg = _mock_notifier_config(enabled=True)

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt", return_value="Task done."),
            patch("s_peach.cli.notify.httpx.post", side_effect=route),
        ):
            _cmd_notify(_make_args())

        assert len(route.dedup_calls) == 1
        assert len(route.speak_calls) == 1

    def test_skips_when_server_reports_seen(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Task done"})
        route = _RouteMockPost([True])
        cfg = _mock_notifier_config(enabled=True)

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt", return_value="summary") as mock_summarize,
            patch("s_peach.cli.notify.httpx.post", side_effect=route),
        ):
            _cmd_notify(_make_args())

        assert len(route.dedup_calls) == 1
        # Skip means no summarize and no /speak — those are the calls we want to avoid.
        mock_summarize.assert_not_called()
        assert route.speak_calls == []

    def test_dedup_request_uses_hash_not_raw_message(self) -> None:
        """The client must send a short hash, not the raw assistant message."""
        from s_peach.cli.notify import _cmd_notify, _dedup_key

        message = "secret internal task details"
        hook_json = json.dumps({
            "session_id": "abc123",
            "hook_event_name": "Stop",
            "last_assistant_message": message,
        })
        route = _RouteMockPost([False])
        cfg = _mock_notifier_config(enabled=True)

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt", return_value="summary"),
            patch("s_peach.cli.notify.httpx.post", side_effect=route),
        ):
            _cmd_notify(_make_args())

        assert route.dedup_calls[0] == {"key": _dedup_key(message)}
        assert message not in route.dedup_calls[0]["key"]

    def test_dedup_still_applies_when_summary_disabled(self) -> None:
        """Repeated identical hook payloads should still only notify once."""
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Task done"})
        route = _RouteMockPost([True])
        cfg = _mock_notifier_config(enabled=False)

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", side_effect=route),
        ):
            _cmd_notify(_make_args())

        assert len(route.dedup_calls) == 1
        assert route.speak_calls == []

    def test_no_dedup_call_when_no_content(self) -> None:
        """Empty stdin dedupes on the fallback spoken text."""
        from s_peach.cli.notify import _cmd_notify

        route = _RouteMockPost()
        cfg = _mock_notifier_config(enabled=True)

        with (
            patch("sys.stdin", StringIO("")),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli.notify.httpx.post", side_effect=route),
        ):
            _cmd_notify(_make_args())

        assert len(route.dedup_calls) == 1
        assert len(route.speak_calls) == 1

    def test_repeated_stop_events_with_different_metadata_only_speak_once(self) -> None:
        from s_peach.cli.notify import _cmd_notify

        hook_json_1 = json.dumps({
            "session_id": "00b4d1ca-bf08-446a-b88e-adb5de52c219",
            "transcript_path": "/home/claude/.claude/projects/-workspace-tuibridge-dev/00b4d1ca-bf08-446a-b88e-adb5de52c219.jsonl",
            "cwd": "/workspace/tuibridge-dev",
            "permission_mode": "default",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Here is a basic Kubernetes Service YAML your tuibridge relay",
        })
        hook_json_2 = json.dumps({
            "session_id": "6bf5878f-efea-4f2f-8c07-6f75db6c8bb4",
            "transcript_path": "/home/claude/.claude/projects/-workspace-tuibridge-dev/6bf5878f-efea-4f2f-8c07-6f75db6c8bb4.jsonl",
            "cwd": "/workspace/tuibridge-dev",
            "permission_mode": "default",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Here is a basic Kubernetes Service YAML your tuibridge relay",
        })
        route = _RouteMockPost([False, True])
        cfg = _mock_notifier_config(enabled=True)

        with (
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt", return_value="Kubernetes Service YAML ready."),
            patch("s_peach.cli.notify.httpx.post", side_effect=route),
        ):
            with patch("sys.stdin", StringIO(hook_json_1)):
                _cmd_notify(_make_args())
            with patch("sys.stdin", StringIO(hook_json_2)):
                _cmd_notify(_make_args())

        assert len(route.dedup_calls) == 2
        assert len(route.speak_calls) == 1

    def test_dedup_failure_falls_through_to_notify(self) -> None:
        """If /dedup/check errors, we notify anyway rather than silently drop."""
        import httpx
        from s_peach.cli.notify import _cmd_notify

        hook_json = json.dumps({"last_assistant_message": "Task done"})
        cfg = _mock_notifier_config(enabled=True)

        def side_effect(url: str, **kwargs):
            if url.endswith("/dedup/check"):
                raise httpx.ConnectError("unreachable")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"queue_size": 1}
            return resp

        with (
            patch("sys.stdin", StringIO(hook_json)),
            patch("s_peach.cli._helpers._load_notifier_config", return_value=cfg),
            patch("s_peach.cli._helpers._resolve_url", return_value="http://localhost:7777"),
            patch("s_peach.cli._helpers._resolve_api_key", return_value=None),
            patch("s_peach.cli._helpers._summarize_text_with_prompt", return_value="summary"),
            patch("s_peach.cli.notify.httpx.post", side_effect=side_effect) as mock_post,
        ):
            _cmd_notify(_make_args())

        # One /dedup/check (failed) + one /speak.
        assert mock_post.call_count == 2
        assert any(call.args[0].endswith("/speak") for call in mock_post.call_args_list)

    def test_dedup_key_is_stable_hash(self) -> None:
        from s_peach.cli.notify import _dedup_key

        assert _dedup_key("hello") == _dedup_key("hello")
        assert _dedup_key("hello") != _dedup_key("world")
        # 16 hex chars = 64 bits — enough for a FIFO of tens.
        assert len(_dedup_key("x")) == 16


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


class TestNotifySubcommand:
    """Verify the notify subcommand is wired up in the CLI parser."""

    def test_notify_subcommand_exists(self) -> None:
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["notify"])
        assert args.command == "notify"
        assert args.quiet is False

    def test_notify_quiet_flag(self) -> None:
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["notify", "--quiet"])
        assert args.quiet is True

    def test_notify_q_flag(self) -> None:
        from s_peach.cli._parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["notify", "-q"])
        assert args.quiet is True


# ---------------------------------------------------------------------------
# Notifier shell script — verify it's a thin wrapper
# ---------------------------------------------------------------------------


class TestNotifierScriptWrapper:
    """Verify the shell script is now a thin wrapper."""

    def test_script_is_minimal(self) -> None:
        from importlib.resources import files

        script = files("s_peach").joinpath("data", "s-peach-notifier.sh")
        content = script.read_text()
        lines = [line for line in content.strip().splitlines() if line.strip() and not line.strip().startswith("#")]
        # Should be just 2 non-comment lines: the s-peach notify call and exit 0
        assert len(lines) == 2
        assert "s-peach notify" in content
        assert "exit 0" in content

    def test_script_delegates_to_notify(self) -> None:
        from importlib.resources import files

        script = files("s_peach").joinpath("data", "s-peach-notifier.sh")
        content = script.read_text()
        assert "s-peach notify --quiet" in content
