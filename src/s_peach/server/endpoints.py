"""Route handlers — registered via register_routes(app)."""

from __future__ import annotations

import asyncio
import time

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from s_peach.audio import AudioItem, play_direct, post_process
from s_peach.server.helpers import generate_audio, perform_reload, validate_and_generate, validate_request
from s_peach.server.models import AppState, SpeakRequest, SpeakResponse, SpeakSyncResponse, _ValidatedRequest

logger = structlog.get_logger()


def register_routes(app: FastAPI) -> None:
    """Register all route handlers on the FastAPI app."""

    @app.post("/speak", response_model=SpeakResponse, status_code=202)
    async def speak(req: SpeakRequest, request: Request) -> SpeakResponse | JSONResponse:
        app_state: AppState = request.app.state.app_state

        # return_audio requires waiting for generation -- fall back to sync path
        if req.return_audio:
            result = await validate_and_generate(req, app_state)
            if isinstance(result, JSONResponse):
                return result

            audio, sr, text = result
            item = AudioItem(
                audio=audio,
                sample_rate=sr,
                enqueued_at=time.monotonic(),
                text_preview=text[:50],
            )
            if not app_state.queue.enqueue(item):
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Queue is full, try again later"},
                )
            app_state.last_audio = item

            import io
            import soundfile as sf
            processed = post_process(
                audio, sr,
                fade_ms=app_state.settings.fade_ms,
                trim_end_ms=app_state.settings.trim_end_ms,
            )
            buf = io.BytesIO()
            sf.write(buf, processed, sr, format="WAV")
            buf.seek(0)
            from starlette.responses import Response
            return Response(
                content=buf.read(),
                media_type="audio/wav",
                headers={"X-Queue-Size": str(app_state.queue.size())},
            )

        # Fast path: validate, respond 202 immediately, generate in background
        validated = validate_request(req, app_state)
        if isinstance(validated, JSONResponse):
            return validated

        # Pre-flight queue capacity check
        if app_state.queue.is_full():
            return JSONResponse(
                status_code=503,
                content={"detail": "Queue is full, try again later"},
            )

        async def _background_generate(v: _ValidatedRequest) -> None:
            result = await generate_audio(v)
            if isinstance(result, JSONResponse):
                logger.error("background_tts_failed", text=v.text[:50])
                return
            audio, sr, text = result
            item = AudioItem(
                audio=audio,
                sample_rate=sr,
                enqueued_at=time.monotonic(),
                text_preview=text[:50],
            )
            if not app_state.queue.enqueue(item):
                logger.warning("queue_full_background", text=text[:50])
                return
            app_state.last_audio = item

        asyncio.create_task(_background_generate(validated))
        return SpeakResponse(status="queued", queue_size=app_state.queue.size())

    @app.post("/speak-sync", response_model=SpeakSyncResponse)
    async def speak_sync(req: SpeakRequest, request: Request) -> SpeakSyncResponse | JSONResponse:
        app_state: AppState = request.app.state.app_state
        start = time.monotonic()

        result = await validate_and_generate(req, app_state)
        if isinstance(result, JSONResponse):
            return result

        audio, sr, text = result

        # Save last audio for say-that-again
        item = AudioItem(
            audio=audio,
            sample_rate=sr,
            enqueued_at=time.monotonic(),
            text_preview=text[:50],
        )
        app_state.last_audio = item

        # Play directly -- no queue, no lock. Concurrent calls can overlap.
        await asyncio.to_thread(
            play_direct, audio, sr,
            app_state.settings.fade_ms, app_state.settings.silence_pad_ms,
            app_state.settings.trim_end_ms,
        )

        duration_ms = round((time.monotonic() - start) * 1000)
        return SpeakSyncResponse(status="done", duration_ms=duration_ms)

    @app.post("/say-that-again", response_model=SpeakResponse, status_code=202)
    async def say_that_again(request: Request, return_audio: bool = False) -> SpeakResponse | JSONResponse:
        app_state: AppState = request.app.state.app_state

        if app_state.last_audio is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "No previous /speak to replay"},
            )
        # Re-enqueue the cached audio with a fresh timestamp
        replayed = AudioItem(
            audio=app_state.last_audio.audio,
            sample_rate=app_state.last_audio.sample_rate,
            enqueued_at=time.monotonic(),
            text_preview=app_state.last_audio.text_preview,
        )
        if not app_state.queue.enqueue(replayed):
            return JSONResponse(
                status_code=503,
                content={"detail": "Queue is full, try again later"},
            )

        if return_audio:
            import io
            import soundfile as sf
            processed = post_process(
                app_state.last_audio.audio, app_state.last_audio.sample_rate,
                fade_ms=app_state.settings.fade_ms,
                trim_end_ms=app_state.settings.trim_end_ms,
            )
            buf = io.BytesIO()
            sf.write(buf, processed, app_state.last_audio.sample_rate, format="WAV")
            buf.seek(0)
            from starlette.responses import Response
            return Response(
                content=buf.read(),
                media_type="audio/wav",
                headers={"X-Queue-Size": str(app_state.queue.size())},
            )

        return SpeakResponse(status="queued", queue_size=app_state.queue.size())

    @app.get("/health")
    async def health(request: Request) -> dict:
        app_state: AppState = request.app.state.app_state

        models_status = {}
        for name, model in app_state.models.items():
            models_status[name] = {
                "loaded": model.is_loaded(),
                "enabled": True,
                "voices": len(model.voices()),
            }
        # Include failed models in health report
        for name, error_msg in app_state.failed_models.items():
            models_status[name] = {
                "loaded": False,
                "enabled": True,
                "error": error_msg,
                "voices": 0,
            }

        # Check audio device
        audio_device = {"available": False, "name": "unknown"}
        try:
            import sounddevice as sd

            default = sd.query_devices(kind="output")
            audio_device = {
                "available": True,
                "name": default.get("name", "unknown") if isinstance(default, dict) else "unknown",
            }
        except Exception:
            pass

        queue_info = {
            "size": app_state.queue.size() if app_state.queue else 0,
            "max": app_state.settings.queue_depth,
        }

        if not app_state.ready:
            status = "starting"
        elif not app_state.models:
            status = "unavailable"
        elif app_state.failed_models:
            status = "degraded"
        else:
            status = "ok"

        response_body = {
            "status": status,
            "models": models_status,
            "queue": queue_info,
            "audio_device": audio_device,
        }

        if status == "unavailable":
            return JSONResponse(status_code=503, content=response_body)

        return response_body

    @app.post("/reload")
    async def reload_config(request: Request) -> dict:
        """Hot-reload server.yaml -- updates voices, settings, and loads new models."""
        app_state: AppState = request.app.state.app_state
        return await perform_reload(app_state)

    @app.get("/voices")
    async def voices(request: Request) -> list[dict]:
        app_state: AppState = request.app.state.app_state
        registry = app_state.voice_registry
        grouped = registry.list_voices()
        result = []
        for model_name, voice_list in grouped.items():
            model = app_state.models.get(model_name)
            model_languages: list[str] = (
                model.languages() if model is not None and hasattr(model, "languages") else []
            )
            result.append({
                "model": model_name,
                "voices": [
                    {"name": v.name, "description": v.description}
                    for v in voice_list
                ],
                "languages": model_languages,
            })
        return result
