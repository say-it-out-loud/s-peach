"""Rendering functions for diagnostic check results.

Provides text and JSON output formatters for check categories.
"""

from __future__ import annotations

from s_peach.doctor.models import CheckCategory

_STATUS_SYMBOLS = {
    "ok": "\u2713",    # checkmark
    "warn": "\u26A0",  # warning
    "error": "\u2717", # cross
    "info": "\u2139",  # info
}


def render_text(categories: list[CheckCategory]) -> str:
    """Render check results as human-readable text with symbols."""
    lines: list[str] = []

    for cat in categories:
        lines.append(f"\n{cat.name}")
        lines.append("-" * len(cat.name))
        for check in cat.checks:
            symbol = _STATUS_SYMBOLS.get(check.status, "?")
            lines.append(f"  {symbol} {check.name}: {check.message}")
            if check.fix:
                lines.append(f"    Fix: {check.fix}")

    # Summary
    total = sum(len(c.checks) for c in categories)
    errors = sum(
        1 for c in categories for ch in c.checks if ch.status == "error"
    )
    warnings = sum(
        1 for c in categories for ch in c.checks if ch.status == "warn"
    )

    lines.append("")
    if errors:
        lines.append(f"Found {errors} error(s) and {warnings} warning(s) in {total} checks.")
    elif warnings:
        lines.append(f"All clear with {warnings} warning(s) in {total} checks.")
    else:
        lines.append(f"All {total} checks passed.")

    return "\n".join(lines)


def render_json(categories: list[CheckCategory]) -> dict:
    """Render check results as a JSON-serializable dict."""
    result: dict = {"categories": []}

    for cat in categories:
        cat_data: dict = {
            "name": cat.name,
            "checks": [],
        }
        for check in cat.checks:
            check_data: dict = {
                "name": check.name,
                "status": check.status,
                "message": check.message,
            }
            if check.fix is not None:
                check_data["fix"] = check.fix
            if check.fixable:
                check_data["fixable"] = True
            cat_data["checks"].append(check_data)
        result["categories"].append(cat_data)

    # Summary counts
    total = sum(len(c.checks) for c in categories)
    errors = sum(
        1 for c in categories for ch in c.checks if ch.status == "error"
    )
    warnings = sum(
        1 for c in categories for ch in c.checks if ch.status == "warn"
    )
    result["summary"] = {
        "total": total,
        "errors": errors,
        "warnings": warnings,
    }

    return result
