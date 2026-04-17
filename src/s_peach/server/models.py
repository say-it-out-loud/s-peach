"""Request/response models and server state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from s_peach.audio import AudioItem, AudioQueue
from s_peach.config import Settings
from s_peach.models.base import TTSModel
from s_peach.voices import VoiceRegistry


# --- Request/Response models ---


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = None
    model: str | None = None
    speed: float | None = None
    exaggeration: float | None = None
    cfg_weight: float | None = None
    language: str | None = None
    return_audio: bool = False


class SpeakResponse(BaseModel):
    status: str = "queued"
    queue_size: int


class SpeakSyncResponse(BaseModel):
    status: str = "done"
    duration_ms: int


class ErrorResponse(BaseModel):
    detail: str
    available_models: list[str] | None = None


@dataclass
class _ValidatedRequest:
    """Holds validated and resolved parameters ready for TTS generation."""

    text: str
    model: TTSModel
    native_id: str
    speak_kwargs: dict[str, Any]
    return_audio: bool


# --- App state ---


class AppState:
    """Container for server-wide state."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.models: dict[str, TTSModel] = {}
        self.failed_models: dict[str, str] = {}  # model_name -> error message
        self.queue: AudioQueue | None = None
        self.voice_registry: VoiceRegistry | None = None
        self.last_audio: AudioItem | None = None
        self.ready: bool = False
