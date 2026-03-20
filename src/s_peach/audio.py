"""Audio playback queue — FIFO queue with depth limit, TTL, and sounddevice playback."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import numpy as np
import structlog

logger = structlog.get_logger()


def post_process(
    audio: np.ndarray,
    sample_rate: int,
    fade_ms: int = 10,
    trim_end_ms: int = 0,
) -> np.ndarray:
    """Apply trim, normalization, and fade in/out to audio.

    Returns processed audio as float32 numpy array.
    """
    if audio.ndim > 1:
        audio = audio.squeeze()
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    if not audio.flags["C_CONTIGUOUS"]:
        audio = np.ascontiguousarray(audio)

    # Trim end of clip (removes trailing artifacts e.g. from Chatterbox)
    if trim_end_ms > 0:
        trim_samples = int(sample_rate * trim_end_ms / 1000)
        if trim_samples < len(audio):
            audio = audio[:-trim_samples]

    # Normalize to peak so output is consistently loud
    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak

    # Fade in/out to avoid clicks at boundaries
    fade_samples = min(len(audio), int(sample_rate * fade_ms / 1000))
    if fade_samples > 1:
        fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        audio[:fade_samples] *= fade_in
        audio[-fade_samples:] *= fade_out

    return audio


def play_direct(
    audio: np.ndarray,
    sample_rate: int,
    fade_ms: int = 10,
    silence_pad_ms: int = 300,
    trim_end_ms: int = 0,
) -> float:
    """Play audio directly through sounddevice (blocking).

    Applies post-processing (trim, normalization, fade) then plays with silence padding.

    Returns:
        Duration of audio in seconds (before silence padding).
    """
    import sounddevice as sd

    audio = post_process(audio, sample_rate, fade_ms, trim_end_ms)
    duration = len(audio) / sample_rate

    # Append silence so the DAC can drain
    silence = np.zeros(int(sample_rate * silence_pad_ms / 1000), dtype=np.float32)
    padded = np.concatenate([audio, silence])

    with sd.OutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    ) as stream:
        stream.write(padded.reshape(-1, 1))

    return duration


@dataclass
class AudioItem:
    """An item in the playback queue."""

    audio: np.ndarray
    sample_rate: int
    enqueued_at: float
    text_preview: str = ""


class AudioQueue:
    """Async FIFO queue for audio playback with depth limit and TTL."""

    def __init__(
        self,
        max_depth: int = 10,
        ttl: float = 60.0,
        on_drained: asyncio.Event | None = None,
        fade_ms: int = 10,
        silence_pad_ms: int = 300,
        trim_end_ms: int = 0,
    ) -> None:
        self._queue: asyncio.Queue[AudioItem] = asyncio.Queue()
        self._max_depth = max_depth
        self._ttl = ttl
        self._worker_task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()
        self._drained = on_drained or asyncio.Event()
        self._drained.set()  # Starts drained (empty)
        self._current_size = 0
        self._fade_ms = fade_ms
        self._silence_pad_ms = silence_pad_ms
        self._trim_end_ms = trim_end_ms

    def enqueue(self, item: AudioItem) -> bool:
        """Try to enqueue an audio item. Returns False if queue is full."""
        if self._current_size >= self._max_depth:
            logger.warning("queue_full", max_depth=self._max_depth)
            return False
        self._queue.put_nowait(item)
        self._current_size += 1
        self._drained.clear()
        return True

    def size(self) -> int:
        return self._current_size

    def is_full(self) -> bool:
        return self._current_size >= self._max_depth

    async def start_worker(self) -> None:
        """Start the background playback worker."""
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.debug("audio_worker_started")

    async def stop(self) -> None:
        """Stop the worker: finish current playback, discard remaining items."""
        self._shutdown.set()
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        # Discard remaining items
        discarded = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                discarded += 1
            except asyncio.QueueEmpty:
                break
        if discarded:
            logger.debug("queue_shutdown_discarded", count=discarded)
        self._current_size = 0
        self._drained.set()
        logger.debug("audio_worker_stopped")

    async def _worker_loop(self) -> None:
        """Process queue items sequentially."""
        while not self._shutdown.is_set():
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=0.5
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return

            # Check TTL
            age = time.monotonic() - item.enqueued_at
            if age > self._ttl:
                self._current_size -= 1
                logger.warning(
                    "queue_item_expired",
                    age=round(age, 1),
                    ttl=self._ttl,
                    text=item.text_preview[:50],
                )
                self._check_drained()
                continue

            # Play audio — size decrements after playback completes
            try:
                await self._play(item)
            except Exception:
                logger.exception("playback_error", text=item.text_preview[:50])
            finally:
                self._current_size -= 1

            self._check_drained()

            # Brief pause between messages for natural pacing
            if not self._shutdown.is_set() and not self._queue.empty():
                await asyncio.sleep(0.5)

    def _check_drained(self) -> None:
        """Signal drained if queue is empty."""
        if self._current_size == 0 and self._queue.empty():
            self._drained.set()

    async def _play(self, item: AudioItem) -> None:
        """Play audio through sounddevice in a thread."""
        logger.debug(
            "playing_audio",
            sample_rate=item.sample_rate,
            duration=round(len(item.audio) / item.sample_rate, 2),
            text=item.text_preview[:50],
        )
        await asyncio.to_thread(self._play_sync, item)

    def _play_sync(self, item: AudioItem) -> None:
        """Blocking playback with fresh stream to avoid inter-clip clicks."""
        play_direct(item.audio, item.sample_rate, self._fade_ms, self._silence_pad_ms, self._trim_end_ms)

    @property
    def drained_event(self) -> asyncio.Event:
        return self._drained
