"""Diagnostic check: required Python packages and model dependencies."""

from __future__ import annotations

import importlib.util

from s_peach.doctor.models import CheckCategory, CheckResult


def check_dependencies(settings=None) -> CheckCategory:
    """Check that required model packages are importable."""
    cat = CheckCategory(name="Dependencies")

    # Determine enabled models
    enabled_models: list[str] = []
    if settings is not None:
        enabled_models = settings.enabled_models
    else:
        try:
            from s_peach.config import load_settings
            enabled_models = load_settings().enabled_models
        except Exception:
            pass

    # kokoro
    _check_package(cat, "kokoro", "kokoro", "pip install kokoro")

    # spaCy model
    _check_package(cat, "en_core_web_sm", "en_core_web_sm (spaCy model)", "python -m spacy download en_core_web_sm")

    # kittentts
    _check_package(cat, "kittentts", "kittentts", "pip install kittentts")

    # chatterbox — only error if enabled
    chatterbox_enabled = any(
        m.startswith("chatterbox") for m in enabled_models
    )
    spec = importlib.util.find_spec("chatterbox_tts")
    if spec is not None:
        cat.checks.append(CheckResult(
            name="chatterbox_tts",
            status="ok",
            message="chatterbox_tts is available",
        ))
    elif chatterbox_enabled:
        cat.checks.append(CheckResult(
            name="chatterbox_tts",
            status="error",
            message="chatterbox_tts not installed but chatterbox model is enabled",
            fix="See README for instructions https://github.com/say-it-out-loud/s-peach/",
        ))
    else:
        cat.checks.append(CheckResult(
            name="chatterbox_tts",
            status="info",
            message="chatterbox_tts not installed (not enabled, skipping)",
        ))

    return cat


def _check_package(cat: CheckCategory, module_name: str, label: str, install_cmd: str) -> None:
    """Check if a Python package is importable via find_spec."""
    spec = importlib.util.find_spec(module_name)
    if spec is not None:
        cat.checks.append(CheckResult(
            name=label,
            status="ok",
            message=f"{label} is available",
        ))
    else:
        cat.checks.append(CheckResult(
            name=label,
            status="error",
            message=f"{label} not installed",
            fix=f"Install: {install_cmd}",
        ))
