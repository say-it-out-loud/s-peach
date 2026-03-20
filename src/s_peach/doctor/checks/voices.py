"""Diagnostic check: voice configuration and reference audio files."""

from __future__ import annotations

from pathlib import Path

from s_peach.doctor.models import CheckCategory, CheckResult

# Model family prefix mapping (matches VoiceRegistry.resolve logic)
_MODEL_FAMILY: dict[str, str] = {
    "kitten-mini": "kitten",
    "kitten-micro": "kitten",
    "kitten-nano": "kitten",
    "chatterbox": "chatterbox",
    "chatterbox-turbo": "chatterbox",
    "kokoro": "kokoro",
}


def check_voices(settings=None) -> CheckCategory:
    """Check voice configuration and reference audio files."""
    from s_peach.paths import config_dir

    cat = CheckCategory(name="Voices")

    # Load settings
    if settings is None:
        try:
            from s_peach.config import load_settings
            settings = load_settings()
        except Exception:
            cat.checks.append(CheckResult(
                name="Voice configuration",
                status="warn",
                message="Cannot load settings to check voices",
            ))
            return cat

    enabled_models = settings.enabled_models
    voices = settings.voices
    cfg_dir = config_dir()

    # Check voice maps have entries per enabled model
    for model in enabled_models:
        family = _MODEL_FAMILY.get(model, model)
        voice_map = voices.get(family, {})
        if not voice_map:
            cat.checks.append(CheckResult(
                name=f"Voice map: {model}",
                status="warn",
                message=f"No voice entries for model '{model}' (family: '{family}')",
                fix=f"Add voice entries under 'voices.{family}' in server.yaml",
            ))
        else:
            cat.checks.append(CheckResult(
                name=f"Voice map: {model}",
                status="ok",
                message=f"{len(voice_map)} voice(s) configured for '{family}'",
            ))

    # Check chatterbox reference audio files
    chatterbox_enabled = any(m.startswith("chatterbox") for m in enabled_models)
    if chatterbox_enabled:
        chatterbox_voices = voices.get("chatterbox", {})

        for voice_name, native_id in chatterbox_voices.items():
            if not native_id:
                # Empty string = default voice, no file needed
                continue

            # Resolve path relative to config dir
            ref_path = Path(native_id)
            if not ref_path.is_absolute():
                ref_path = cfg_dir / ref_path

            if ref_path.exists():
                cat.checks.append(CheckResult(
                    name=f"Voice file: {voice_name}",
                    status="ok",
                    message=f"Reference audio exists: {ref_path}",
                ))
            else:
                cat.checks.append(CheckResult(
                    name=f"Voice file: {voice_name}",
                    status="error",
                    message=f"Reference audio not found: {ref_path}",
                    fix=f"Place a WAV file at {ref_path}",
                    fixable=True,
                ))

    return cat
