"""Tests for audio playback queue."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from s_peach.audio import AudioItem, AudioQueue, play_direct, post_process


def _make_item(text: str = "test", age: float = 0.0) -> AudioItem:
    """Create an AudioItem for testing."""
    return AudioItem(
        audio=np.zeros(100, dtype=np.float32),
        sample_rate=24000,
        enqueued_at=time.monotonic() - age,
        text_preview=text,
    )


class TestEnqueueDequeue:
    @pytest.mark.asyncio
    async def test_enqueue_and_play_in_order(self) -> None:
        queue = AudioQueue(max_depth=10, ttl=60)
        played: list[str] = []

        async def fake_play(self, item: AudioItem) -> None:
            played.append(item.text_preview)

        with patch.object(AudioQueue, "_play", fake_play):
            await queue.start_worker()
            queue.enqueue(_make_item("first"))
            queue.enqueue(_make_item("second"))
            queue.enqueue(_make_item("third"))
            # Give worker time to process (includes 500ms gap between items)
            await asyncio.sleep(1.5)
            await queue.stop()

        assert played == ["first", "second", "third"]

    def test_queue_rejects_at_depth_limit(self) -> None:
        queue = AudioQueue(max_depth=2, ttl=60)
        assert queue.enqueue(_make_item("a")) is True
        assert queue.enqueue(_make_item("b")) is True
        assert queue.enqueue(_make_item("c")) is False

    def test_queue_reports_correct_size(self) -> None:
        queue = AudioQueue(max_depth=5, ttl=60)
        assert queue.size() == 0
        assert queue.is_full() is False
        queue.enqueue(_make_item())
        assert queue.size() == 1
        queue.enqueue(_make_item())
        assert queue.size() == 2


class TestTTL:
    @pytest.mark.asyncio
    async def test_expired_items_discarded(self) -> None:
        queue = AudioQueue(max_depth=10, ttl=1)
        played: list[str] = []

        async def fake_play(self, item: AudioItem) -> None:
            played.append(item.text_preview)

        with patch.object(AudioQueue, "_play", fake_play):
            # Enqueue an expired item (age > TTL)
            queue.enqueue(_make_item("expired", age=5.0))
            queue.enqueue(_make_item("fresh", age=0.0))

            await queue.start_worker()
            await asyncio.sleep(0.3)
            await queue.stop()

        assert played == ["fresh"]


class TestPlaybackErrors:
    @pytest.mark.asyncio
    async def test_playback_error_skips_item(self) -> None:
        queue = AudioQueue(max_depth=10, ttl=60)
        played: list[str] = []
        call_count = 0

        async def failing_then_ok(self, item: AudioItem) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("device busy")
            played.append(item.text_preview)

        with patch.object(AudioQueue, "_play", failing_then_ok):
            queue.enqueue(_make_item("fail"))
            queue.enqueue(_make_item("ok"))

            await queue.start_worker()
            await asyncio.sleep(1.0)
            await queue.stop()

        assert played == ["ok"]


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_discards_remaining(self) -> None:
        queue = AudioQueue(max_depth=10, ttl=60)

        async def slow_play(self, item: AudioItem) -> None:
            await asyncio.sleep(10)  # Very slow — will be cancelled

        with patch.object(AudioQueue, "_play", slow_play):
            for i in range(5):
                queue.enqueue(_make_item(f"item-{i}"))

            await queue.start_worker()
            await asyncio.sleep(0.1)
            await queue.stop()

        assert queue.size() == 0


class TestDrained:
    @pytest.mark.asyncio
    async def test_signals_drained_when_empty(self) -> None:
        drained = asyncio.Event()
        queue = AudioQueue(max_depth=10, ttl=60, on_drained=drained)

        async def fast_play(self, item: AudioItem) -> None:
            pass  # instant

        with patch.object(AudioQueue, "_play", fast_play):
            assert drained.is_set()  # Starts drained

            queue.enqueue(_make_item("x"))
            assert not drained.is_set()

            await queue.start_worker()
            await asyncio.sleep(0.3)

            assert drained.is_set()
            await queue.stop()

    def test_full_status(self) -> None:
        queue = AudioQueue(max_depth=2, ttl=60)
        assert queue.is_full() is False
        queue.enqueue(_make_item())
        queue.enqueue(_make_item())
        assert queue.is_full() is True


class TestPostProcess:
    """Tests for the post_process() function used by --save."""

    def test_normalizes_to_peak_1(self) -> None:
        audio = np.full(24000, 0.5, dtype=np.float32)  # 1 second, peak 0.5
        result = post_process(audio, 24000, fade_ms=0)
        assert np.abs(result).max() == pytest.approx(1.0)

    def test_trims_end(self) -> None:
        audio = np.ones(2400, dtype=np.float32)  # 100ms at 24kHz
        result = post_process(audio, 24000, trim_end_ms=50)
        assert len(result) == 1200  # 50ms trimmed

    def test_applies_fade(self) -> None:
        audio = np.ones(24000, dtype=np.float32)
        result = post_process(audio, 24000, fade_ms=10)
        # First sample should be faded to ~0
        assert result[0] == pytest.approx(0.0, abs=0.01)
        # Last sample should be faded to ~0
        assert result[-1] == pytest.approx(0.0, abs=0.01)
        # Middle should be 1.0
        assert result[12000] == pytest.approx(1.0)

    def test_no_silence_padding(self) -> None:
        """post_process should NOT add silence padding (unlike play_direct)."""
        audio = np.ones(2400, dtype=np.float32)
        result = post_process(audio, 24000, fade_ms=0, trim_end_ms=0)
        assert len(result) == 2400


class TestPlayDirect:
    """Tests for the module-level play_direct() function."""

    def test_normalizes_to_peak_1(self) -> None:
        """Audio should be normalized so peak amplitude is 1.0."""
        mock_stream = MagicMock()
        mock_output_stream = MagicMock()
        mock_output_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_output_stream.__exit__ = MagicMock(return_value=False)
        mock_sd = MagicMock()
        mock_sd.OutputStream.return_value = mock_output_stream

        # Use enough samples so fade doesn't dominate; peak at 0.5
        audio = np.full(2400, 0.5, dtype=np.float32)
        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            play_direct(audio, 24000)

        written = mock_stream.write.call_args[0][0].flatten()
        # Middle samples (away from fade) should be normalized to 1.0
        mid = len(audio) // 2
        assert written[mid] == pytest.approx(1.0, abs=0.01)

    def test_fade_in_out_applied(self) -> None:
        """Audio should have fade in/out applied at boundaries."""
        mock_stream = MagicMock()
        mock_output_stream = MagicMock()
        mock_output_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_output_stream.__exit__ = MagicMock(return_value=False)
        mock_sd = MagicMock()
        mock_sd.OutputStream.return_value = mock_output_stream

        audio = np.ones(2400, dtype=np.float32)
        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            play_direct(audio, 24000)

        written = mock_stream.write.call_args[0][0].flatten()
        # First sample should be faded in (close to 0)
        assert abs(written[0]) < 0.1
        # Last audio sample (before silence) should be faded out (close to 0)
        last_audio_idx = len(audio) - 1
        assert abs(written[last_audio_idx]) < 0.1

    def test_silence_padding_appended(self) -> None:
        """300ms of silence should be appended after audio."""
        mock_stream = MagicMock()
        mock_output_stream = MagicMock()
        mock_output_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_output_stream.__exit__ = MagicMock(return_value=False)
        mock_sd = MagicMock()
        mock_sd.OutputStream.return_value = mock_output_stream

        sr = 24000
        audio = np.ones(2400, dtype=np.float32)
        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            play_direct(audio, sr)

        written = mock_stream.write.call_args[0][0]
        expected_silence_samples = int(sr * 0.3)
        assert written.shape[0] == len(audio) + expected_silence_samples

    def test_returns_duration_in_seconds(self) -> None:
        """play_direct should return duration of audio in seconds."""
        mock_stream = MagicMock()
        mock_output_stream = MagicMock()
        mock_output_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_output_stream.__exit__ = MagicMock(return_value=False)
        mock_sd = MagicMock()
        mock_sd.OutputStream.return_value = mock_output_stream

        audio = np.ones(24000, dtype=np.float32)  # 1 second at 24kHz
        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            duration = play_direct(audio, 24000)

        assert duration == pytest.approx(1.0)

    def test_play_sync_delegates_to_play_direct(self) -> None:
        """AudioQueue._play_sync should delegate to play_direct."""
        item = AudioItem(
            audio=np.ones(100, dtype=np.float32),
            sample_rate=24000,
            enqueued_at=time.monotonic(),
            text_preview="test",
        )
        queue = AudioQueue()
        with patch("s_peach.audio.play_direct") as mock_pd:
            mock_pd.return_value = 0.004
            queue._play_sync(item)
            mock_pd.assert_called_once()
            args = mock_pd.call_args
            np.testing.assert_array_equal(args[0][0], item.audio)
            assert args[0][1] == 24000

    def test_trim_end_ms_removes_trailing_samples(self) -> None:
        """Audio should be shorter after trimming when trim_end_ms > 0."""
        mock_stream = MagicMock()
        mock_output_stream = MagicMock()
        mock_output_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_output_stream.__exit__ = MagicMock(return_value=False)
        mock_sd = MagicMock()
        mock_sd.OutputStream.return_value = mock_output_stream

        sr = 24000
        trim_ms = 100  # 100ms = 2400 samples at 24kHz
        audio = np.ones(4800, dtype=np.float32)  # 200ms of audio

        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            duration = play_direct(audio, sr, trim_end_ms=trim_ms)

        # Duration should reflect trimmed audio: 200ms - 100ms = 100ms = 0.1s
        expected_duration = (len(audio) - int(sr * trim_ms / 1000)) / sr
        assert duration == pytest.approx(expected_duration)

    def test_trim_end_ms_larger_than_audio_does_not_crash(self) -> None:
        """When trim_end_ms exceeds audio length, audio is left as-is (no crash)."""
        mock_stream = MagicMock()
        mock_output_stream = MagicMock()
        mock_output_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_output_stream.__exit__ = MagicMock(return_value=False)
        mock_sd = MagicMock()
        mock_sd.OutputStream.return_value = mock_output_stream

        sr = 24000
        audio = np.ones(100, dtype=np.float32)  # ~4ms of audio
        trim_ms = 5000  # 5 seconds — much larger than audio

        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            # Should not raise; audio length is preserved
            duration = play_direct(audio, sr, trim_end_ms=trim_ms)

        # trim_samples >= len(audio), so audio stays as-is
        assert duration == pytest.approx(len(audio) / sr)

    def test_play_sync_passes_custom_audio_params_to_play_direct(self) -> None:
        """AudioQueue with custom audio params should forward them to play_direct."""
        item = AudioItem(
            audio=np.ones(100, dtype=np.float32),
            sample_rate=24000,
            enqueued_at=time.monotonic(),
            text_preview="test",
        )
        queue = AudioQueue(fade_ms=50, silence_pad_ms=100, trim_end_ms=20)
        with patch("s_peach.audio.play_direct") as mock_pd:
            mock_pd.return_value = 0.004
            queue._play_sync(item)
            mock_pd.assert_called_once_with(item.audio, item.sample_rate, 50, 100, 20)


class TestPlaybackAtomicity:
    """Verify OutputStream is opened and written correctly in _play_sync."""

    def test_play_sync_calls_play_then_wait(self) -> None:
        """_play_sync must open an OutputStream with correct params and write audio."""
        mock_stream = MagicMock()
        mock_output_stream = MagicMock()
        mock_output_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_output_stream.__exit__ = MagicMock(return_value=False)

        mock_sd = MagicMock()
        mock_sd.OutputStream.return_value = mock_output_stream

        item = _make_item("hello")
        item = AudioItem(
            audio=np.ones(2400, dtype=np.float32),
            sample_rate=24000,
            enqueued_at=item.enqueued_at,
            text_preview="hello",
        )

        queue = AudioQueue()
        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            queue._play_sync(item)

        mock_sd.OutputStream.assert_called_once_with(
            samplerate=24000,
            channels=1,
            dtype="float32",
        )
        mock_stream.write.assert_called_once()
        written = mock_stream.write.call_args[0][0]
        # Should be a 2D column array (N, 1) and longer than source (silence padding)
        assert written.ndim == 2
        assert written.shape[1] == 1
        assert written.shape[0] > len(item.audio)

    @pytest.mark.asyncio
    async def test_play_delegates_to_play_sync_once(self) -> None:
        """_play should make exactly one to_thread call to _play_sync."""
        queue = AudioQueue(max_depth=10, ttl=60)
        item = _make_item("hello")

        with patch.object(AudioQueue, "_play_sync") as mock_sync:
            await queue._play(item)
            mock_sync.assert_called_once_with(item)
