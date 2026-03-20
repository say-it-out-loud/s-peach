"""MCP server — exposes a `speak` tool that reuses the existing TTS pipeline."""

from __future__ import annotations

import asyncio
import hmac
import time
from ipaddress import IPv4Address

import structlog
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger()

mcp = FastMCP("s-peach")


def _get_app_state():
    """Get the shared AppState, or None if not ready."""
    from s_peach.server.models import AppState

    app_state: AppState | None = getattr(mcp, "_app_state", None)
    return app_state


@mcp.tool()
async def speak(
    text: str,
    model: str | None = None,
    voice: str | None = None,
    speed: float | None = None,
) -> dict:
    """Speak text aloud. Omit model/voice to use the first available. Call list_voices to discover options."""
    text = text.strip()
    if not text:
        return {"error": "Text must not be empty"}

    app_state = _get_app_state()
    if app_state is None or not app_state.ready:
        return {"error": "TTS server is not ready"}

    max_len = app_state.settings.max_text_length
    if len(text) > max_len:
        return {"error": f"Text must not exceed {max_len} characters"}

    # Validate numeric parameters
    if speed is not None and not (0.1 <= speed <= 5.0):
        return {"error": "speed must be between 0.1 and 5.0"}

    # Default to first available model
    if not model:
        available = list(app_state.models.keys())
        if not available:
            return {"error": "No models loaded"}
        model = available[0]

    # Validate model
    if model not in app_state.models:
        if model in app_state.failed_models:
            return {
                "error": f"Model '{model}' is unavailable: {app_state.failed_models[model]}",
                "available_models": list(app_state.models.keys()),
            }
        return {
            "error": f"Unknown model '{model}'",
            "available_models": list(app_state.models.keys()),
        }

    # Default to first available voice for the model
    registry = app_state.voice_registry
    if not voice:
        voices = registry.list_voices().get(model, [])
        if not voices:
            return {"error": f"No voices configured for model '{model}'"}
        voice = voices[0].name

    # Resolve voice
    try:
        resolved = registry.resolve(voice_name=voice, model_name=model)
    except KeyError:
        return {"error": f"Voice '{voice}' not found for model '{model}'"}

    # Generate audio
    tts_model = app_state.models[resolved.model_name]
    speak_kwargs: dict[str, float] = {}
    if speed is not None:
        speak_kwargs["speed"] = speed

    try:
        audio, sr = await asyncio.to_thread(
            tts_model.speak, text, resolved.native_id, **speak_kwargs
        )
    except TimeoutError:
        return {"error": "TTS generation timed out"}
    except Exception as exc:
        logger.exception("mcp_tts_generation_error")
        return {"error": f"TTS generation failed: {exc}"}

    # Enqueue audio
    from s_peach.audio import AudioItem

    item = AudioItem(
        audio=audio,
        sample_rate=sr,
        enqueued_at=time.monotonic(),
        text_preview=text[:50],
    )
    if not app_state.queue.enqueue(item):
        return {"error": "Queue is full, try again later"}

    app_state.last_audio = item
    return {"status": "queued", "queue_size": app_state.queue.size()}


@mcp.tool()
async def speak_sync(
    text: str,
    model: str | None = None,
    voice: str | None = None,
    speed: float | None = None,
) -> dict:
    """Speak text aloud and wait until playback finishes. Bypasses the queue — plays directly. Useful for sequential voice auditions or when you need confirmation that playback is done."""
    text = text.strip()
    if not text:
        return {"error": "Text must not be empty"}

    app_state = _get_app_state()
    if app_state is None or not app_state.ready:
        return {"error": "TTS server is not ready"}

    max_len = app_state.settings.max_text_length
    if len(text) > max_len:
        return {"error": f"Text must not exceed {max_len} characters"}

    if speed is not None and not (0.1 <= speed <= 5.0):
        return {"error": "speed must be between 0.1 and 5.0"}

    # Default to first available model
    if not model:
        available = list(app_state.models.keys())
        if not available:
            return {"error": "No models loaded"}
        model = available[0]

    if model not in app_state.models:
        if model in app_state.failed_models:
            return {
                "error": f"Model '{model}' is unavailable: {app_state.failed_models[model]}",
                "available_models": list(app_state.models.keys()),
            }
        return {
            "error": f"Unknown model '{model}'",
            "available_models": list(app_state.models.keys()),
        }

    # Default to first available voice for the model
    registry = app_state.voice_registry
    if not voice:
        voices = registry.list_voices().get(model, [])
        if not voices:
            return {"error": f"No voices configured for model '{model}'"}
        voice = voices[0].name

    try:
        resolved = registry.resolve(voice_name=voice, model_name=model)
    except KeyError:
        return {"error": f"Voice '{voice}' not found for model '{model}'"}

    tts_model = app_state.models[resolved.model_name]
    speak_kwargs: dict[str, float] = {}
    if speed is not None:
        speak_kwargs["speed"] = speed

    start = time.monotonic()
    try:
        audio, sr = await asyncio.to_thread(
            tts_model.speak, text, resolved.native_id, **speak_kwargs
        )
    except TimeoutError:
        return {"error": "TTS generation timed out"}
    except Exception as exc:
        logger.exception("mcp_tts_generation_error")
        return {"error": f"TTS generation failed: {exc}"}

    from s_peach.audio import AudioItem, play_direct

    item = AudioItem(
        audio=audio,
        sample_rate=sr,
        enqueued_at=time.monotonic(),
        text_preview=text[:50],
    )
    app_state.last_audio = item

    await asyncio.to_thread(
        play_direct, audio, sr,
        app_state.settings.fade_ms, app_state.settings.silence_pad_ms,
        app_state.settings.trim_end_ms,
    )
    duration_ms = round((time.monotonic() - start) * 1000)
    return {"status": "done", "duration_ms": duration_ms}


@mcp.tool()
async def list_voices() -> dict:
    """List all available TTS models and their voices."""
    app_state = _get_app_state()
    if app_state is None or not app_state.ready:
        return {"error": "TTS server is not ready"}

    registry = app_state.voice_registry
    grouped = registry.list_voices()
    return {
        "models": [
            {
                "model": model_name,
                "voices": [
                    {"name": v.name, "description": v.description}
                    for v in voice_list
                ],
            }
            for model_name, voice_list in grouped.items()
        ]
    }


@mcp.tool()
async def say_that_again() -> dict:
    """Replay the last spoken notification from cached audio (instant, no re-generation)."""
    app_state = _get_app_state()
    if app_state is None or not app_state.ready:
        return {"error": "TTS server is not ready"}

    if app_state.last_audio is None:
        return {"error": "No previous speak to replay"}

    from s_peach.audio import AudioItem

    replayed = AudioItem(
        audio=app_state.last_audio.audio,
        sample_rate=app_state.last_audio.sample_rate,
        enqueued_at=time.monotonic(),
        text_preview=app_state.last_audio.text_preview,
    )
    if not app_state.queue.enqueue(replayed):
        return {"error": "Queue is full, try again later"}

    return {"status": "queued", "queue_size": app_state.queue.size()}


class _SecurityMiddleware:
    """ASGI middleware enforcing IP whitelist and API key auth on the MCP sub-app.

    The parent FastAPI middleware doesn't apply to mounted sub-apps, so we
    replicate the same checks here using the shared AppState.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        app_state = getattr(mcp, "_app_state", None)
        if app_state is None:
            response = JSONResponse(status_code=503, content={"detail": "TTS server not ready"})
            await response(scope, receive, send)
            return

        # IP whitelist check
        client_ip = request.client.host if request.client else None
        if client_ip is None:
            response = JSONResponse(status_code=403, content={"detail": "Could not determine client IP"})
            await response(scope, receive, send)
            return

        networks = app_state.settings.ip_networks
        if networks:
            try:
                ip = IPv4Address(client_ip)
            except ValueError:
                logger.warning("mcp_ip_invalid", client_ip=client_ip)
                response = JSONResponse(status_code=403, content={"detail": f"Invalid client IP: {client_ip}"})
                await response(scope, receive, send)
                return
            if not any(ip in net for net in networks):
                logger.warning("mcp_ip_denied", client_ip=client_ip)
                response = JSONResponse(status_code=403, content={"detail": f"IP {client_ip} not in whitelist"})
                await response(scope, receive, send)
                return

        # API key check
        expected_key = app_state.settings.api_key
        if expected_key is not None:
            provided_key = request.headers.get("x-api-key")
            if not provided_key:
                response = JSONResponse(status_code=401, content={"detail": "Missing API key. Provide X-API-Key header."})
                await response(scope, receive, send)
                return
            if not hmac.compare_digest(provided_key, expected_key):
                logger.warning("mcp_api_key_rejected", client_ip=client_ip)
                response = JSONResponse(status_code=403, content={"detail": "Invalid API key"})
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def create_mcp_sse_app():
    """Create the MCP SSE Starlette app for mounting, wrapped with security middleware."""
    return _SecurityMiddleware(mcp.sse_app())


def attach_app_state(app_state) -> None:
    """Attach the shared AppState so MCP tools can access the TTS pipeline."""
    mcp._app_state = app_state
