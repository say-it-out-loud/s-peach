"""Shared validation and TTS generation helpers (DI via explicit app_state param)."""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import structlog
from fastapi.responses import JSONResponse

from s_peach.config import load_settings
from s_peach.server.models import AppState, SpeakRequest, _ValidatedRequest
from s_peach.voices import VoiceRegistry

logger = structlog.get_logger()


def validate_request(req: SpeakRequest, app_state: AppState) -> _ValidatedRequest | JSONResponse:
    """Validate request parameters and resolve voice.

    Returns:
        On success: _ValidatedRequest with resolved parameters.
        On failure: JSONResponse with error details.
    """
    text = req.text.strip()
    if not text:
        return JSONResponse(
            status_code=400,
            content={"detail": "Text must not be empty"},
        )
    max_len = app_state.settings.max_text_length
    if len(text) > max_len:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Text must not exceed {max_len} characters"},
        )

    # Validate numeric parameters
    if req.speed is not None and not (0.1 <= req.speed <= 5.0):
        return JSONResponse(
            status_code=400,
            content={"detail": "speed must be between 0.1 and 5.0"},
        )
    if req.exaggeration is not None and not (0.0 <= req.exaggeration <= 2.0):
        return JSONResponse(
            status_code=400,
            content={"detail": "exaggeration must be between 0.0 and 2.0"},
        )
    if req.cfg_weight is not None and not (0.0 <= req.cfg_weight <= 2.0):
        return JSONResponse(
            status_code=400,
            content={"detail": "cfg_weight must be between 0.0 and 2.0"},
        )

    # Require model
    if not req.model:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "model is required",
                "available_models": list(app_state.models.keys()),
            },
        )

    # Require voice
    if not req.voice:
        return JSONResponse(
            status_code=400,
            content={"detail": "voice is required"},
        )

    # Validate model name
    registry = app_state.voice_registry
    if req.model not in app_state.models:
        # Distinguish: disabled/unknown (400) vs failed-to-load (503)
        if req.model in app_state.failed_models:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": f"Model '{req.model}' is unavailable: {app_state.failed_models[req.model]}",
                    "available_models": list(app_state.models.keys()),
                },
            )
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Unknown model '{req.model}'",
                "available_models": list(app_state.models.keys()),
            },
        )

    # Resolve voice
    try:
        resolved = registry.resolve(
            voice_name=req.voice, model_name=req.model
        )
    except KeyError:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Voice '{req.voice}' not found for model '{req.model}'",
            },
        )

    # Build optional kwargs for models that support them
    speak_kwargs: dict[str, Any] = {}
    if req.speed is not None:
        speak_kwargs["speed"] = req.speed
    if req.exaggeration is not None:
        speak_kwargs["exaggeration"] = req.exaggeration
    if req.cfg_weight is not None:
        speak_kwargs["cfg_weight"] = req.cfg_weight
    if req.language is not None:
        speak_kwargs["language"] = req.language

    return _ValidatedRequest(
        text=text,
        model=app_state.models[resolved.model_name],
        native_id=resolved.native_id,
        speak_kwargs=speak_kwargs,
        return_audio=req.return_audio,
    )


async def generate_audio(
    validated: _ValidatedRequest,
) -> tuple[np.ndarray, int, str] | JSONResponse:
    """Generate TTS audio from a validated request."""
    try:
        audio, sr = await asyncio.to_thread(
            validated.model.speak,
            validated.text,
            validated.native_id,
            **validated.speak_kwargs,
        )
    except TimeoutError:
        return JSONResponse(
            status_code=503,
            content={"detail": "TTS generation timed out"},
        )
    except Exception:
        logger.exception("tts_generation_error")
        return JSONResponse(
            status_code=500,
            content={"detail": "TTS generation failed"},
        )

    return (audio, sr, validated.text)


async def validate_and_generate(
    req: SpeakRequest, app_state: AppState,
) -> tuple[np.ndarray, int, str] | JSONResponse:
    """Validate request and generate TTS audio (used by /speak-sync)."""
    validated = validate_request(req, app_state)
    if isinstance(validated, JSONResponse):
        return validated
    return await generate_audio(validated)


async def perform_reload(app_state: AppState) -> dict | JSONResponse:
    """Hot-reload server.yaml -- updates voices, settings, and loads new models.

    Returns a dict with status/changes on success, or a JSONResponse on failure.
    """
    try:
        new_settings = load_settings()
    except Exception as exc:
        logger.exception("config_reload_failed")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Config reload failed: {exc}"},
        )

    changes: list[str] = []

    # Update voice maps on existing models
    for model_name, model in app_state.models.items():
        if model_name.startswith("kitten"):
            voice_key = "kitten"
        elif model_name == "chatterbox-multi":
            voice_key = "chatterbox-multi" if "chatterbox-multi" in new_settings.voices else "chatterbox"
        elif model_name.startswith("chatterbox"):
            voice_key = "chatterbox"
        else:
            voice_key = model_name
        new_voices = new_settings.voices.get(voice_key, {})
        if hasattr(model, "_voice_map"):
            model._voice_map = new_voices
    changes.append("voices")

    # Load newly enabled models -- access _MODEL_CONSTRUCTORS at call-time
    # to avoid circular imports and to see test mutations.
    import s_peach.server
    for model_name in new_settings.enabled_models:
        if model_name in app_state.models:
            continue
        constructor = s_peach.server._MODEL_CONSTRUCTORS.get(model_name)
        if constructor is None:
            continue
        try:
            logger.info("reload_loading_model", model=model_name)
            model = constructor(new_settings)
            await asyncio.to_thread(model.load)
            app_state.models[model_name] = model
            app_state.failed_models.pop(model_name, None)
            changes.append(f"loaded:{model_name}")
        except Exception as exc:
            logger.exception("reload_model_failed", model=model_name)
            app_state.failed_models[model_name] = str(exc)

    # Unload models no longer enabled
    for model_name in list(app_state.models.keys()):
        if model_name not in new_settings.enabled_models:
            logger.info("reload_unloading_model", model=model_name)
            model = app_state.models.pop(model_name)
            try:
                await asyncio.to_thread(model.unload)
            except Exception as exc:
                logger.exception("reload_unload_failed", model=model_name)
                app_state.failed_models[model_name] = str(exc)
            changes.append(f"unloaded:{model_name}")

    # Commit new settings now that model load/unload work is done
    app_state.settings = new_settings

    # Update audio queue settings
    if app_state.queue is not None:
        app_state.queue._fade_ms = new_settings.fade_ms
        app_state.queue._silence_pad_ms = new_settings.silence_pad_ms
        app_state.queue._trim_end_ms = new_settings.trim_end_ms
        changes.append("audio")

    # Rebuild voice registry
    app_state.voice_registry = VoiceRegistry(
        settings=new_settings, models=app_state.models,
    )

    logger.info("config_reloaded", changes=changes)
    return {"status": "reloaded", "changes": changes}
