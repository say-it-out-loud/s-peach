"""Diagnostic check: Python environment, PortAudio, and audio output."""

from __future__ import annotations

import importlib.util
import sys

from s_peach.doctor.models import CheckCategory, CheckResult


def check_environment() -> CheckCategory:
    """Check Python version, PortAudio, and audio output device."""
    cat = CheckCategory(name="Environment")

    # Python version (informational — always ok)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    cat.checks.append(CheckResult(
        name="Python version",
        status="ok",
        message=f"Python {ver}",
    ))

    # sounddevice importable (proxy for PortAudio)
    sd_spec = importlib.util.find_spec("sounddevice")
    if sd_spec is None:
        cat.checks.append(CheckResult(
            name="PortAudio (sounddevice)",
            status="error",
            message="sounddevice not installed (PortAudio bindings)",
            fix="Install PortAudio: apt install libportaudio2 (Linux) or brew install portaudio (macOS), then pip install sounddevice",
        ))
    else:
        # Try to actually import — sounddevice raises OSError at import time if
        # the PortAudio shared library isn't on the system.
        try:
            sd = __import__("sounddevice")
            cat.checks.append(CheckResult(
                name="PortAudio (sounddevice)",
                status="ok",
                message="sounddevice is available",
            ))
        except (OSError, ImportError) as exc:
            cat.checks.append(CheckResult(
                name="PortAudio (sounddevice)",
                status="error",
                message=f"sounddevice installed but PortAudio library not found: {exc}",
                fix="Install PortAudio: apt install libportaudio2 (Linux) or brew install portaudio (macOS)",
            ))
            return cat

        # Audio output device queryable
        try:
            device = sd.query_devices(kind="output")
            name = device.get("name", "unknown") if isinstance(device, dict) else str(device)
            cat.checks.append(CheckResult(
                name="Audio output device",
                status="ok",
                message=f"Default output: {name}",
            ))
        except Exception as exc:
            cat.checks.append(CheckResult(
                name="Audio output device",
                status="warn",
                message=f"Cannot query audio output device: {exc}",
                fix="Check audio drivers and PortAudio installation",
            ))

    return cat
