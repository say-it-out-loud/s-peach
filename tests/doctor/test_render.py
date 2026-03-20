"""Tests for doctor rendering functions."""

from __future__ import annotations

import json

from s_peach.doctor.models import CheckCategory, CheckResult
from s_peach.doctor.render import render_json, render_text


# ---------------------------------------------------------------------------
# Tests: render_text
# ---------------------------------------------------------------------------


class TestRenderText:
    def test_contains_symbols(self):
        categories = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="ok check", status="ok", message="all good"),
                CheckResult(name="warn check", status="warn", message="minor issue", fix="do something"),
                CheckResult(name="error check", status="error", message="broken"),
            ])
        ]
        output = render_text(categories)

        assert "\u2713" in output  # checkmark
        assert "\u26A0" in output  # warning
        assert "\u2717" in output  # cross
        assert "Fix:" in output

    def test_summary_with_errors(self):
        categories = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="err", status="error", message="bad"),
            ])
        ]
        output = render_text(categories)
        assert "1 error" in output

    def test_summary_all_clear(self):
        categories = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="ok", status="ok", message="fine"),
            ])
        ]
        output = render_text(categories)
        assert "1 checks passed" in output


# ---------------------------------------------------------------------------
# Tests: render_json
# ---------------------------------------------------------------------------


class TestRenderJson:
    def test_valid_json(self):
        categories = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="check1", status="ok", message="fine"),
                CheckResult(name="check2", status="error", message="bad", fix="fix it", fixable=True),
            ])
        ]

        data = render_json(categories)
        # Verify it's JSON-serializable
        json_str = json.dumps(data)
        parsed = json.loads(json_str)

        assert "categories" in parsed
        assert len(parsed["categories"]) == 1
        assert len(parsed["categories"][0]["checks"]) == 2
        assert parsed["summary"]["total"] == 2
        assert parsed["summary"]["errors"] == 1

    def test_fixable_included(self):
        categories = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="check", status="error", message="bad", fixable=True),
            ])
        ]

        data = render_json(categories)
        assert data["categories"][0]["checks"][0].get("fixable") is True
