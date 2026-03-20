"""Doctor CLI command.

Note: This module shadows s_peach.doctor — it contains the thin CLI wrapper
that delegates to the doctor package for actual diagnostic functionality.
"""

from __future__ import annotations

import argparse
import sys


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register doctor subcommand."""
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Diagnose common installation, configuration, and runtime issues",
        description="Diagnose common installation, configuration, and runtime issues. "
        "Runs checks across environment, config, dependencies, voices, server, and hooks.",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        help="Auto-apply safe fixes (init scaffolding, stale PID cleanup)",
    )


def _cmd_doctor(args: argparse.Namespace) -> None:
    """Run diagnostic checks and report issues."""
    import json as json_mod

    from s_peach.doctor import apply_fixes, render_json, render_text, run_all_checks

    use_json = args.json
    use_fix = args.fix

    if use_fix:
        # Run checks first to find fixable items
        categories = run_all_checks()
        fixes = apply_fixes(categories)

        if not use_json:
            if fixes:
                print("Applied fixes:")
                for fix in fixes:
                    print(f"  - {fix}")
                print()
            else:
                print("No fixable issues found.\n")

        # Re-run checks after fixes
        categories = run_all_checks()
    else:
        categories = run_all_checks()

    if use_json:
        data = render_json(categories)
        print(json_mod.dumps(data, indent=2))
    else:
        print(render_text(categories))

    # Exit code: 0 if no errors, 1 if any errors
    has_errors = any(
        check.status == "error"
        for cat in categories
        for check in cat.checks
    )
    sys.exit(1 if has_errors else 0)
