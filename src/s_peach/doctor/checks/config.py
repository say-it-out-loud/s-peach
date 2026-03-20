"""Diagnostic check: configuration files, validation, and API key consistency."""

from __future__ import annotations

from pathlib import Path

import yaml

from s_peach.doctor.models import CheckCategory, CheckResult


def check_config(settings=None) -> CheckCategory:
    """Check config files, validation, API key consistency, and permissions."""
    from s_peach.paths import config_file, notifier_file

    cat = CheckCategory(name="Configuration")

    cfg_path = config_file()
    notifier_path = notifier_file()

    # server.yaml exists
    if not cfg_path.exists():
        cat.checks.append(CheckResult(
            name="server.yaml",
            status="error",
            message=f"Config file not found: {cfg_path}",
            fix="Run: s-peach init",
            fixable=True,
        ))
        # Can't do further config checks without the file
        _check_notifier(cat, notifier_path, None)
        return cat

    cat.checks.append(CheckResult(
        name="server.yaml",
        status="ok",
        message=f"Found: {cfg_path}",
    ))

    # server.yaml parses as valid YAML
    try:
        with open(cfg_path) as f:
            yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        cat.checks.append(CheckResult(
            name="server.yaml syntax",
            status="error",
            message=f"Invalid YAML: {exc}",
            fix="Fix YAML syntax in server.yaml, or run: s-peach config server",
        ))
        _check_notifier(cat, notifier_path, None)
        return cat

    cat.checks.append(CheckResult(
        name="server.yaml syntax",
        status="ok",
        message="Valid YAML",
    ))

    # config loads into Settings without validation errors
    server_api_key = None
    if settings is not None:
        cat.checks.append(CheckResult(
            name="config validation",
            status="ok",
            message="Settings valid",
        ))
        server_api_key = settings.api_key
    else:
        try:
            from s_peach.config import load_settings
            loaded = load_settings()
            cat.checks.append(CheckResult(
                name="config validation",
                status="ok",
                message="Settings valid",
            ))
            server_api_key = loaded.api_key
        except Exception as exc:
            # Extract sub-errors from ValidationError
            error_details = _extract_validation_errors(exc)
            for detail in error_details:
                cat.checks.append(CheckResult(
                    name=f"config validation: {detail['field']}",
                    status="error",
                    message=detail["message"],
                    fix="Fix the value in server.yaml, or run: s-peach config server",
                ))

    # File permissions
    _check_file_permissions(cat, cfg_path, "server.yaml")

    # Notifier checks (including API key match)
    _check_notifier(cat, notifier_path, server_api_key)

    return cat


def _extract_validation_errors(exc: Exception) -> list[dict[str, str]]:
    """Extract field-level errors from a pydantic ValidationError or generic exception."""
    errors = []
    # Try pydantic ValidationError
    if hasattr(exc, "errors") and callable(exc.errors):
        for err in exc.errors():
            loc = " -> ".join(str(x) for x in err.get("loc", []))
            msg = err.get("msg", str(err))
            errors.append({"field": loc or "unknown", "message": msg})
    if not errors:
        errors.append({"field": "config", "message": str(exc)})
    return errors


def _check_file_permissions(cat: CheckCategory, path: Path, label: str) -> None:
    """Warn if a config file is world-readable."""
    try:
        mode = path.stat().st_mode
        if mode & 0o077:
            cat.checks.append(CheckResult(
                name=f"{label} permissions",
                status="warn",
                message=f"{label} is world-readable (mode: {oct(mode & 0o777)})",
                fix=f"Run: chmod 600 {path}",
            ))
        else:
            cat.checks.append(CheckResult(
                name=f"{label} permissions",
                status="ok",
                message=f"{label} permissions OK ({oct(mode & 0o777)})",
            ))
    except OSError:
        pass  # Can't check permissions — skip silently


def _check_notifier(cat: CheckCategory, notifier_path: Path, server_api_key: str | None) -> None:
    """Check client.yaml existence, permissions, and API key consistency."""
    if not notifier_path.exists():
        cat.checks.append(CheckResult(
            name="client.yaml",
            status="error",
            message=f"Notifier config not found: {notifier_path}",
            fix="Run: s-peach init",
            fixable=True,
        ))
        return

    cat.checks.append(CheckResult(
        name="client.yaml",
        status="ok",
        message=f"Found: {notifier_path}",
    ))

    # File permissions
    _check_file_permissions(cat, notifier_path, "client.yaml")

    # API key match
    try:
        with open(notifier_path) as f:
            notifier_data = yaml.safe_load(f) or {}
        notifier_api_key = notifier_data.get("api_key")
        # Normalize: treat empty string same as None
        if notifier_api_key == "":
            notifier_api_key = None
        if isinstance(notifier_api_key, str):
            notifier_api_key = notifier_api_key.strip() or None

        if server_api_key is not None and isinstance(server_api_key, str):
            server_api_key = server_api_key.strip() or None

        if server_api_key is None and notifier_api_key is None:
            cat.checks.append(CheckResult(
                name="API key match",
                status="ok",
                message="No API key configured (both None)",
            ))
        elif server_api_key is None and notifier_api_key is not None:
            cat.checks.append(CheckResult(
                name="API key match",
                status="warn",
                message="API key set in client.yaml but not in server.yaml",
                fix="Set api_key in server.yaml or remove from client.yaml",
            ))
        elif server_api_key is not None and notifier_api_key is None:
            cat.checks.append(CheckResult(
                name="API key match",
                status="warn",
                message="API key set in server.yaml but not in client.yaml",
                fix="Set api_key in client.yaml or remove from server.yaml",
            ))
        elif server_api_key == notifier_api_key:
            cat.checks.append(CheckResult(
                name="API key match",
                status="ok",
                message="API keys match",
            ))
        else:
            cat.checks.append(CheckResult(
                name="API key match",
                status="error",
                message="API key mismatch between server.yaml and client.yaml",
                fix="Run: s-peach init --force (regenerates matching keys)",
            ))
    except Exception as exc:
        cat.checks.append(CheckResult(
            name="API key match",
            status="warn",
            message=f"Cannot check API key: {exc}",
        ))
