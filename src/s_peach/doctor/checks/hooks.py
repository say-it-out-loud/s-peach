"""Diagnostic check: Claude Code hook installation status."""

from __future__ import annotations

import json

from s_peach.doctor.models import CheckCategory, CheckResult


def check_hooks() -> CheckCategory:
    """Check Claude Code hook installation status."""
    from s_peach.hooks import (
        VALID_TARGETS,
        hook_exists_in_settings,
        notifier_script_dest,
        settings_path,
    )

    cat = CheckCategory(name="Hooks")

    # Check each settings location
    locations_found: list[str] = []
    for target in sorted(VALID_TARGETS):
        try:
            path = settings_path(target)
            if not path.exists():
                continue
            with open(path) as f:
                data = json.loads(f.read())
            if hook_exists_in_settings(data):
                locations_found.append(str(path))
        except Exception:
            pass

    if locations_found:
        cat.checks.append(CheckResult(
            name="Hook in settings",
            status="ok",
            message=f"Hook installed in: {', '.join(locations_found)}",
        ))
    else:
        cat.checks.append(CheckResult(
            name="Hook in settings",
            status="info",
            message="No s-peach hook found in Claude settings",
            fix="Run: s-peach install-hook claude-code",
        ))

    # Check hook script file
    script_path = notifier_script_dest()
    if script_path.exists():
        cat.checks.append(CheckResult(
            name="Hook script",
            status="ok",
            message=f"Notifier script exists: {script_path}",
        ))
    else:
        cat.checks.append(CheckResult(
            name="Hook script",
            status="info" if not locations_found else "warn",
            message=f"Notifier script not found: {script_path}",
            fix="Run: s-peach install-hook claude-code",
        ))

    return cat
