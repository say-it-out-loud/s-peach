"""FastAPI server — endpoints, middleware, lifespan."""

from __future__ import annotations

import asyncio
import signal
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable

import structlog
from fastapi import FastAPI

from s_peach.audio import AudioQueue
from s_peach.config import Settings, load_settings, setup_logging
from s_peach.models.base import TTSModel
from s_peach.models.chatterbox import ChatterboxMultilingualTTSModel, ChatterboxTTSModel, ChatterboxTurboTTSModel
from s_peach.models.kitten import KittenTTSModel
from s_peach.models.kokoro import KokoroTTSModel
from s_peach.server.middleware import api_key_middleware, ip_whitelist_middleware, request_logging_middleware
from s_peach.server.models import AppState
from s_peach.voices import VoiceRegistry

# Re-export for backward compatibility
from s_peach.server.models import (  # noqa: F401
    ErrorResponse,
    SpeakRequest,
    SpeakResponse,
    SpeakSyncResponse,
    _ValidatedRequest,
)

# Model name -> constructor mapping (defined here, not in a submodule,
# so tests can mutate in-place via `import s_peach.server as srv; srv._MODEL_CONSTRUCTORS[...] = ...`)
_MODEL_CONSTRUCTORS: dict[str, Callable[[Settings], TTSModel]] = {
    "kitten-mini": lambda s: KittenTTSModel(s, model_id="KittenML/kitten-tts-mini-0.8", model_name="kitten-mini"),
    "kitten-micro": lambda s: KittenTTSModel(s, model_id="KittenML/kitten-tts-micro-0.8", model_name="kitten-micro"),
    "kitten-nano": lambda s: KittenTTSModel(s, model_id="KittenML/kitten-tts-nano-0.8-int8", model_name="kitten-nano"),
    "kokoro": KokoroTTSModel,
    "chatterbox-turbo": ChatterboxTurboTTSModel,
    "chatterbox": ChatterboxTTSModel,
    "chatterbox-multi": ChatterboxMultilingualTTSModel,
}

logger = structlog.get_logger()


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start queue worker on startup, clean shutdown on stop."""
    state: AppState = app.state.app_state
    settings = state.settings

    # Check port availability before spending time loading models
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((settings.server.host, settings.server.port))
    except OSError as exc:
        logger.error("port_unavailable", host=settings.server.host, port=settings.server.port, error=str(exc))
        raise SystemExit(f"Port {settings.server.port} is already in use") from exc
    finally:
        sock.close()

    # Load all enabled models eagerly
    total = len(settings.enabled_models)
    logger.debug("loading_models", count=total, models=settings.enabled_models)

    for i, model_name in enumerate(settings.enabled_models, 1):
        constructor = _MODEL_CONSTRUCTORS.get(model_name)
        if constructor is None:
            logger.error("model_unknown", model=model_name)
            state.failed_models[model_name] = f"Unknown model '{model_name}'"
            continue
        try:
            logger.debug("model_loading", model=model_name, progress=f"{i}/{total}")
            model = constructor(settings)
            await asyncio.to_thread(model.load)
            state.models[model_name] = model
            logger.debug("model_ready", model=model_name, progress=f"{i}/{total}")
        except Exception as exc:
            error_msg = str(exc)
            logger.exception("model_load_failed", model=model_name)
            state.failed_models[model_name] = error_msg

    logger.debug(
        "models_loaded",
        ready=list(state.models.keys()),
        failed=list(state.failed_models.keys()) or None,
    )

    # Initialize voice registry
    state.voice_registry = VoiceRegistry(
        settings=settings, models=state.models
    )

    # Initialize audio queue
    state.queue = AudioQueue(
        max_depth=settings.queue_depth,
        ttl=settings.queue_ttl,
        fade_ms=settings.fade_ms,
        silence_pad_ms=settings.silence_pad_ms,
        trim_end_ms=settings.trim_end_ms,
    )

    await state.queue.start_worker()
    state.ready = True
    logger.debug("server_started", host=settings.server.host, port=settings.server.port)

    yield

    # Shutdown -- unload models before exiting
    logger.debug("server_stopping")
    if state.queue:
        await state.queue.stop()

    loaded = [n for n, m in state.models.items() if m.is_loaded()]
    if loaded:
        logger.debug("unloading_models", models=loaded)
        # Block SIGINT/SIGTERM during unload to avoid partial cleanup
        loop = asyncio.get_running_loop()
        signals_intercepted = False
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: logger.warning("shutdown_in_progress", hint="waiting for models to unload"))
                signals_intercepted = True
            except (NotImplementedError, OSError, RuntimeError):
                pass  # Windows, non-main thread, or test environment

        for name, model in state.models.items():
            if model.is_loaded():
                logger.debug("model_unloading", model=name)
                await asyncio.to_thread(model.unload)
                logger.debug("model_unloaded", model=name)

        # Remove our signal handlers (uvicorn will handle final cleanup)
        if signals_intercepted:
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.remove_signal_handler(sig)
                except (NotImplementedError, OSError, RuntimeError):
                    pass

    logger.debug("server_stopped")


# --- App factory ---


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    if settings is None:
        settings = load_settings()

    setup_logging(settings.log_level)

    app = FastAPI(title="s-peach", lifespan=lifespan)
    app_state = AppState(settings)
    app.state.app_state = app_state

    app.middleware("http")(request_logging_middleware)
    app.middleware("http")(api_key_middleware)
    app.middleware("http")(ip_whitelist_middleware)

    # Register route handlers
    from s_peach.server.endpoints import register_routes
    register_routes(app)

    # Mount MCP SSE endpoint at /mcp
    try:
        from s_peach.mcp_server import attach_app_state, create_mcp_sse_app

        attach_app_state(app_state)
        mcp_app = create_mcp_sse_app()
        app.mount("/mcp", mcp_app)
        logger.debug("mcp_mounted", path="/mcp")
    except ImportError:
        logger.debug("mcp_not_available", hint="install 'mcp' package for MCP support")

    return app
