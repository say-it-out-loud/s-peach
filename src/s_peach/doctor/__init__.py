"""Diagnostic checks for s-peach installation, configuration, and runtime.

Provides `s-peach doctor` functionality: probes local state (files, imports,
processes, network) and reports issues with actionable fix suggestions.

Public API (re-exported here for backward compatibility):
    - run_all_checks(settings=None) -> list[CheckCategory]
    - apply_fixes(categories) -> list[str]
    - CheckResult, CheckCategory
    - render_text(categories) -> str
    - render_json(categories) -> dict

Individual check functions are NOT re-exported here — import them directly
from ``s_peach.doctor.checks.<module>``.
"""

from __future__ import annotations

from s_peach.doctor.models import CheckCategory, CheckResult
from s_peach.doctor.render import render_json, render_text

__all__ = [
    "run_all_checks",
    "apply_fixes",
    "CheckResult",
    "CheckCategory",
    "render_text",
    "render_json",
]


def run_all_checks(settings=None) -> list[CheckCategory]:
    """Run all diagnostic check categories.

    Each check function is wrapped in try/except so one failure
    does not prevent other categories from running.

    Args:
        settings: Optional pre-loaded Settings object. If None,
                  each check will load settings independently.
    """
    from s_peach.doctor.checks.config import check_config
    from s_peach.doctor.checks.dependencies import check_dependencies
    from s_peach.doctor.checks.environment import check_environment
    from s_peach.doctor.checks.hooks import check_hooks
    from s_peach.doctor.checks.server import check_server
    from s_peach.doctor.checks.voices import check_voices

    check_fns = [
        ("Environment", lambda: check_environment()),
        ("Configuration", lambda: check_config(settings)),
        ("Dependencies", lambda: check_dependencies(settings)),
        ("Voices", lambda: check_voices(settings)),
        ("Server", lambda: check_server(settings)),
        ("Hooks", lambda: check_hooks()),
    ]

    categories: list[CheckCategory] = []
    for name, fn in check_fns:
        try:
            categories.append(fn())
        except Exception as exc:
            cat = CheckCategory(name=name)
            cat.checks.append(CheckResult(
                name=f"{name} check",
                status="error",
                message=f"Check failed with exception: {exc}",
            ))
            categories.append(cat)

    return categories


def apply_fixes(categories: list[CheckCategory]) -> list[str]:
    """Apply fixable items and return descriptions of applied fixes.

    Fixable items:
    - Missing server.yaml/client.yaml -> init scaffolding
    - Missing voice files -> copy bundled voices
    - Stale PID file -> delete it
    """
    applied: list[str] = []

    needs_init = False
    needs_pid_cleanup = False

    for cat in categories:
        for check in cat.checks:
            if not check.fixable:
                continue

            if check.name in ("server.yaml", "client.yaml") and check.status == "error":
                needs_init = True

            if check.name == "Daemon process" and "Stale PID" in check.message:
                needs_pid_cleanup = True

            if check.name.startswith("Voice file:") and check.status == "error":
                # Copy bundled voices
                try:
                    from s_peach.scaffolding import _copy_bundled_voices_lib
                    from s_peach.paths import config_dir

                    voice_actions = _copy_bundled_voices_lib(config_dir())
                    applied.extend(voice_actions)
                except Exception as exc:
                    applied.append(f"Failed to copy voices: {exc}")

    if needs_init:
        try:
            from s_peach.scaffolding import init_scaffolding

            actions = init_scaffolding(force=False)
            applied.extend(actions)
        except FileExistsError:
            # Some configs exist — that's fine, init what we can
            pass
        except Exception as exc:
            applied.append(f"Failed to run init scaffolding: {exc}")

    if needs_pid_cleanup:
        try:
            from s_peach.paths import pid_file

            pf = pid_file()
            if pf.exists():
                pf.unlink()
                applied.append(f"Removed stale PID file: {pf}")
        except Exception as exc:
            applied.append(f"Failed to remove PID file: {exc}")

    return applied
