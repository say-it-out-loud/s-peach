"""Tests for doctor fix application and CLI integration."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

from s_peach.doctor.models import CheckCategory, CheckResult


# ---------------------------------------------------------------------------
# Tests: apply_fixes
# ---------------------------------------------------------------------------


class TestApplyFixes:
    def test_fixable_config_triggers_init(self):
        from s_peach.doctor import apply_fixes

        categories = [
            CheckCategory(name="Configuration", checks=[
                CheckResult(name="server.yaml", status="error", message="missing", fixable=True),
            ])
        ]

        with patch("s_peach.scaffolding.init_scaffolding", return_value=["Created /tmp/server.yaml"]) as mock_init:
            fixes = apply_fixes(categories)

        mock_init.assert_called_once_with(force=False)
        assert len(fixes) > 0

    def test_non_fixable_items_skipped(self):
        from s_peach.doctor import apply_fixes

        categories = [
            CheckCategory(name="Dependencies", checks=[
                CheckResult(name="kokoro", status="error", message="missing", fixable=False),
            ])
        ]

        fixes = apply_fixes(categories)
        assert len(fixes) == 0

    def test_stale_pid_cleanup(self, tmp_path, monkeypatch):
        from s_peach.doctor import apply_fixes

        # Create stale PID file
        runtime = tmp_path / "run" / "s-peach"
        runtime.mkdir(parents=True)
        pid_file = runtime / "s-peach.pid"
        pid_file.write_text("99999")

        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

        categories = [
            CheckCategory(name="Server", checks=[
                CheckResult(
                    name="Daemon process",
                    status="warn",
                    message="Stale PID file (PID 99999 is not running)",
                    fixable=True,
                ),
            ])
        ]

        fixes = apply_fixes(categories)
        assert not pid_file.exists()
        assert any("stale PID" in f.lower() or "PID" in f for f in fixes)


# ---------------------------------------------------------------------------
# Tests: CLI integration
# ---------------------------------------------------------------------------


class TestCLIDoctor:
    def _run_main(self, *args: str) -> tuple[int, str, str]:
        """Run main() and capture exit code and output."""
        from io import StringIO
        from s_peach.cli import main

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()

        exit_code = 0
        try:
            main(list(args))
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 1
        finally:
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        return exit_code, stdout, stderr

    def test_doctor_exit_0_on_no_errors(self):
        """doctor exits 0 when all checks pass."""
        mock_cats = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="ok", status="ok", message="fine"),
            ])
        ]

        with patch("s_peach.doctor.run_all_checks", return_value=mock_cats):
            code, out, err = self._run_main("doctor")

        assert code == 0
        assert "\u2713" in out  # checkmark symbol

    def test_doctor_exit_1_on_errors(self):
        """doctor exits 1 when errors found."""
        mock_cats = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="bad", status="error", message="broken"),
            ])
        ]

        with patch("s_peach.doctor.run_all_checks", return_value=mock_cats):
            code, out, err = self._run_main("doctor")

        assert code == 1
        assert "\u2717" in out  # cross symbol

    def test_doctor_json_valid(self):
        """doctor --json outputs valid JSON."""
        mock_cats = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="ok", status="ok", message="fine"),
            ])
        ]

        with patch("s_peach.doctor.run_all_checks", return_value=mock_cats):
            code, out, err = self._run_main("doctor", "--json")

        assert code == 0
        data = json.loads(out)
        assert "categories" in data
        assert "summary" in data

    def test_doctor_fix_applies_and_rechecks(self):
        """doctor --fix applies fixes then re-runs checks."""
        # First run: has errors, second run: all ok
        call_count = [0]

        def mock_run_all_checks(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return [CheckCategory(name="Config", checks=[
                    CheckResult(name="server.yaml", status="error", message="missing", fixable=True),
                ])]
            return [CheckCategory(name="Config", checks=[
                CheckResult(name="server.yaml", status="ok", message="found"),
            ])]

        with patch("s_peach.doctor.run_all_checks", side_effect=mock_run_all_checks), \
             patch("s_peach.doctor.apply_fixes", return_value=["Created server.yaml"]):
            code, out, err = self._run_main("doctor", "--fix")

        assert code == 0
        assert "Applied fixes" in out
        assert call_count[0] == 2

    def test_doctor_fix_json(self):
        """doctor --fix --json outputs JSON after applying fixes."""
        mock_cats = [
            CheckCategory(name="Test", checks=[
                CheckResult(name="ok", status="ok", message="fine"),
            ])
        ]

        with patch("s_peach.doctor.run_all_checks", return_value=mock_cats), \
             patch("s_peach.doctor.apply_fixes", return_value=[]):
            code, out, err = self._run_main("doctor", "--fix", "--json")

        assert code == 0
        data = json.loads(out)
        assert "categories" in data

    def test_doctor_help(self):
        """doctor --help shows description."""
        code, out, err = self._run_main("doctor", "--help")
        assert code == 0
        assert "diagnose" in (out + err).lower() or "diagnostic" in (out + err).lower()
