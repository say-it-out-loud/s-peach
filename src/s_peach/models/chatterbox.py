"""Chatterbox TTS backends — voice cloning with paralinguistic tags."""

from __future__ import annotations

import sys
import threading
from typing import Any

import numpy as np
import structlog

from s_peach.config import Settings
from s_peach.models.base import VoiceInfo

logger = structlog.get_logger()




def _resolve_voice_path(voice: str) -> str:
    """Resolve a voice reference audio path.

    - Absolute paths are used as-is.
    - Relative paths are tried against CWD first (backwards compat with dev
      workflow), then against config_dir() (~/.config/s-peach/).
    - Raises FileNotFoundError if the file cannot be found.
    """
    import os
    from pathlib import Path

    # Absolute — use directly
    if os.path.isabs(voice):
        if os.path.isfile(voice):
            return voice
        raise FileNotFoundError(f"Reference audio clip not found: {voice}")

    # Relative — try CWD first
    if os.path.isfile(voice):
        return str(Path(voice).resolve())

    # Relative — try config_dir
    from s_peach.paths import config_dir

    config_path = config_dir() / voice
    if config_path.is_file():
        return str(config_path)

    raise FileNotFoundError(
        f"Reference audio clip not found: {voice}\n"
        f"Searched: ./{voice} and {config_path}"
    )


class _ChatterboxBase:
    """Shared logic for Chatterbox Turbo (350M) and Chatterbox (500M).

    Subclasses set _model_name, _import_module, and _import_class.
    """

    _model_name: str
    _import_module: str  # e.g. "chatterbox.tts_turbo"
    _import_class: str   # e.g. "ChatterboxTurboTTS"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: Any | None = None
        self._lock = threading.Lock()
        self._voice_map: dict[str, str] = settings.voices.get(self._model_name) or settings.voices.get("chatterbox", {})

    def speak(self, text: str, voice: str, **kwargs: Any) -> tuple[np.ndarray, int]:
        """Generate audio. Blocks until complete or timeout.

        Extra kwargs (exaggeration, cfg_weight) are passed to generate()
        for models that support them. Ignored by other backends.
        """
        self._ensure_loaded()

        if voice:
            voice = _resolve_voice_path(voice)

        timeout = self._settings.tts_timeout
        result: list[np.ndarray | None] = [None]
        error: list[BaseException | None] = [None]
        gen_kwargs = {k: v for k, v in kwargs.items()
                      if k in ("exaggeration", "cfg_weight")}

        def _generate() -> None:
            try:
                # Suppress tqdm progress bars and PyTorch stft warnings
                import warnings
                from unittest.mock import patch as _patch
                from functools import partial
                import tqdm as _tqdm_mod

                _silent_tqdm = partial(_tqdm_mod.tqdm, disable=True)
                with warnings.catch_warnings(), \
                     _patch("chatterbox.models.t3.t3.tqdm", _silent_tqdm), \
                     _patch("chatterbox.models.s3gen.flow_matching.tqdm", _silent_tqdm):
                    warnings.filterwarnings("ignore", category=UserWarning)
                    warnings.filterwarnings("ignore", category=FutureWarning)
                    warnings.filterwarnings("ignore", message="S3 Token")
                    warnings.filterwarnings("ignore", message=".*sdpa.*")
                    if voice:
                        wav = self._model.generate(
                            text, audio_prompt_path=voice, **gen_kwargs,
                        )
                    else:
                        wav = self._model.generate(text, **gen_kwargs)
                result[0] = wav.squeeze().float().cpu().numpy()
            except Exception as e:
                error[0] = e

        gen_thread = threading.Thread(target=_generate, daemon=True)
        gen_thread.start()
        gen_thread.join(timeout=timeout)

        if gen_thread.is_alive():
            if "torch" in sys.modules:
                import torch
                if torch.cuda.is_available():
                    logger.warning(
                        "tts_generation_timeout_cuda",
                        model=self._model_name,
                        timeout=timeout,
                        text_len=len(text),
                        hint="daemon thread continues running and holds GPU memory",
                    )
            logger.error(
                "tts_generation_timeout",
                model=self._model_name,
                timeout=timeout,
                text_len=len(text),
            )
            raise TimeoutError(
                f"TTS generation timed out after {timeout}s"
            )

        if error[0] is not None:
            raise error[0]

        audio = result[0]
        if audio is None:
            raise RuntimeError(f"{self._model_name} TTS generation returned None")

        if not isinstance(audio, np.ndarray):
            audio = np.array(audio, dtype=np.float32)

        from chatterbox.models.s3gen import S3GEN_SR

        return audio, S3GEN_SR

    def voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(name=friendly_name, native_id=native_id)
            for friendly_name, native_id in self._voice_map.items()
        ]

    def name(self) -> str:
        return self._model_name

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            device = self._settings.chatterbox.device
            logger.debug("model_loading", model=self._model_name, device=device)

            import warnings
            import importlib

            # Suppress diffusers LoRA deprecation warning throughout loading
            warnings.filterwarnings("ignore", category=FutureWarning,
                                    module="diffusers")

            # Import the model class
            try:
                mod = importlib.import_module(self._import_module)
                cls = getattr(mod, self._import_class)
            except ImportError:
                raise ImportError(
                    "chatterbox-tts is not installed. See README for instructions: https://github.com/say-it-out-loud/s-peach/"
                ) from None

            try:
                # Workaround 1: patch HF download functions for token=False + local cache.
                # tts_turbo uses snapshot_download, tts uses hf_hub_download.
                _patched_attrs: list[tuple[Any, str, Any]] = []

                def _make_patch(orig_fn: Any, use_local_cache: bool) -> Any:
                    def _patched(*args: Any, **kwargs: Any) -> Any:
                        kwargs["token"] = False
                        if use_local_cache:
                            import os
                            repo_id = kwargs.get("repo_id") or (args[0] if args else "")
                            cache_dir = os.path.join(
                                os.path.expanduser("~"), ".cache", "huggingface", "hub",
                                f"models--{repo_id.replace('/', '--')}",
                            )
                            if os.path.isdir(os.path.join(cache_dir, "snapshots")):
                                kwargs.setdefault("local_files_only", True)
                        return orig_fn(*args, **kwargs)
                    return _patched

                for fn_name in ("snapshot_download", "hf_hub_download"):
                    if hasattr(mod, fn_name):
                        orig = getattr(mod, fn_name)
                        _patched_attrs.append((mod, fn_name, orig))
                        # Only skip network for snapshot_download (whole repo).
                        # hf_hub_download fetches individual files that may not
                        # all be cached even if snapshots/ dir exists.
                        use_local = fn_name == "snapshot_download"
                        setattr(mod, fn_name, _make_patch(orig, use_local))

                # Workaround 2: perth watermarker may be None
                import perth
                if perth.PerthImplicitWatermarker is None:
                    from perth.dummy_watermarker import DummyWatermarker
                    perth.PerthImplicitWatermarker = DummyWatermarker

                # Workaround 3: mtl_tts.from_pretrained doesn't pass map_location
                # to torch.load, so weights saved on CUDA fail on MPS/CPU.
                import torch
                _orig_torch_load = torch.load

                def _patched_torch_load(*args: Any, **kwargs: Any) -> Any:
                    kwargs.setdefault("map_location", device)
                    return _orig_torch_load(*args, **kwargs)

                torch.load = _patched_torch_load  # type: ignore[assignment]
                _patched_attrs.append((torch, "load", _orig_torch_load))

                try:
                    self._model = cls.from_pretrained(device)
                except (FileNotFoundError, OSError) as dl_err:
                    # local_files_only found a stale/incomplete snapshot — retry with network
                    logger.debug(
                        "model_cache_miss",
                        model=self._model_name,
                        error=str(dl_err),
                    )
                    for obj, attr, orig in _patched_attrs:
                        setattr(obj, attr, orig)
                    _patched_attrs.clear()
                    # Re-patch with local_files_only=False
                    for fn_name in ("snapshot_download", "hf_hub_download"):
                        if hasattr(mod, fn_name):
                            orig = getattr(mod, fn_name)
                            _patched_attrs.append((mod, fn_name, orig))
                            setattr(mod, fn_name, _make_patch(orig, use_local_cache=False))
                    self._model = cls.from_pretrained(device)
                finally:
                    for obj, attr, orig in _patched_attrs:
                        setattr(obj, attr, orig)

                # Workaround 3: multilingual AlignmentStreamAnalyzer needs
                # output_attentions=True which requires eager attention, not SDPA.
                if hasattr(self._model, "t3") and hasattr(self._model.t3, "tfmr"):
                    cfg = getattr(self._model.t3.tfmr, "config", None)
                    if cfg is not None and getattr(cfg, "_attn_implementation", None) == "sdpa":
                        cfg._attn_implementation = "eager"

                # Workaround 4: float64 from librosa.load breaks voice cloning
                self._patch_prepare_conditionals()

                logger.debug("model_loaded", model=self._model_name)
            except Exception:
                logger.exception("model_load_failed", model=self._model_name)
                raise

    def _patch_prepare_conditionals(self) -> None:
        """Replace prepare_conditionals with float32-safe version."""
        _orig_prepare = self._model.prepare_conditionals
        model_ref = self._model
        import_module = self._import_module

        def _f32_prepare(wav_fpath: Any, **kwargs: Any) -> None:
            import numpy as _np
            import librosa as _librosa
            import torch
            from chatterbox.models.s3gen import S3GEN_SR
            from chatterbox.models.s3tokenizer import S3_SR
            from chatterbox.models.t3.modules.cond_enc import T3Cond
            import importlib
            _cb_mod = importlib.import_module(import_module)
            Conditionals = _cb_mod.Conditionals

            m = model_ref
            exaggeration = kwargs.get("exaggeration", 0.5)
            norm_loudness = kwargs.get("norm_loudness", True)

            s3gen_ref_wav, _sr = _librosa.load(wav_fpath, sr=S3GEN_SR)
            s3gen_ref_wav = s3gen_ref_wav.astype(_np.float32)

            assert len(s3gen_ref_wav) / _sr > 5.0, \
                "Audio prompt must be longer than 5 seconds!"

            if norm_loudness and hasattr(m, "norm_loudness"):
                s3gen_ref_wav = m.norm_loudness(s3gen_ref_wav, _sr)

            ref_16k_wav = _librosa.resample(
                s3gen_ref_wav, orig_sr=S3GEN_SR, target_sr=S3_SR,
            ).astype(_np.float32)

            s3gen_ref_wav = s3gen_ref_wav[:m.DEC_COND_LEN]
            s3gen_ref_dict = m.s3gen.embed_ref(
                s3gen_ref_wav, S3GEN_SR, device=m.device,
            )

            plen = m.t3.hp.speech_cond_prompt_len
            if plen:
                s3_tokzr = m.s3gen.tokenizer
                t3_cond_prompt_tokens, _ = s3_tokzr.forward(
                    [ref_16k_wav[:m.ENC_COND_LEN]], max_len=plen,
                )
                t3_cond_prompt_tokens = torch.atleast_2d(
                    t3_cond_prompt_tokens,
                ).to(m.device)

            ve_embed = torch.from_numpy(
                m.ve.embeds_from_wavs(
                    [ref_16k_wav], sample_rate=S3_SR,
                ),
            ).float()
            ve_embed = ve_embed.mean(axis=0, keepdim=True).to(m.device)

            t3_cond = T3Cond(
                speaker_emb=ve_embed,
                cond_prompt_speech_tokens=t3_cond_prompt_tokens,
                emotion_adv=exaggeration * torch.ones(1, 1, 1),
            ).to(device=m.device)

            m.conds = Conditionals(t3_cond, s3gen_ref_dict)

        self._model.prepare_conditionals = _f32_prepare

    def unload(self) -> None:
        with self._lock:
            if self._model is None:
                return
            logger.debug("model_unloading", model=self._model_name)
            self._model = None
            if "torch" in sys.modules:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            logger.debug("model_unloaded", model=self._model_name)

    def _ensure_loaded(self) -> None:
        if self._model is None:
            self.load()


class ChatterboxTurboTTSModel(_ChatterboxBase):
    """Chatterbox Turbo (350M) — fast, good quality."""

    _model_name = "chatterbox-turbo"
    _import_module = "chatterbox.tts_turbo"
    _import_class = "ChatterboxTurboTTS"


class ChatterboxTTSModel(_ChatterboxBase):
    """Chatterbox (500M) — slower, higher quality, better emotion/CFG control."""

    _model_name = "chatterbox"
    _import_module = "chatterbox.tts"
    _import_class = "ChatterboxTTS"


# ISO 639-1 language codes supported by ChatterboxMultilingualTTS.
CHATTERBOX_MULTI_LANGUAGES: list[str] = [
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
    "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
    "sw", "tr", "zh",
]


class ChatterboxMultilingualTTSModel(_ChatterboxBase):
    """Chatterbox Multilingual — voice cloning across 23 languages."""

    _model_name = "chatterbox-multi"
    _import_module = "chatterbox.mtl_tts"
    _import_class = "ChatterboxMultilingualTTS"

    def speak(self, text: str, voice: str, **kwargs: Any) -> tuple[np.ndarray, int]:
        """Generate audio with optional language override.

        Args:
            text: Text to synthesize.
            voice: Reference audio path for voice cloning.
            language: Optional ISO 639-1 language code (e.g. "en", "fr").
            **kwargs: Additional params passed to generate() (exaggeration, cfg_weight).
        """
        self._ensure_loaded()

        if voice:
            voice = _resolve_voice_path(voice)

        timeout = self._settings.tts_timeout
        result: list[np.ndarray | None] = [None]
        error: list[BaseException | None] = [None]
        gen_kwargs = {k: v for k, v in kwargs.items()
                      if k in ("exaggeration", "cfg_weight")}
        language = kwargs.get("language")
        if language is not None:
            gen_kwargs["language_id"] = language

        def _generate() -> None:
            try:
                import warnings
                from unittest.mock import patch as _patch
                from functools import partial
                import tqdm as _tqdm_mod

                _silent_tqdm = partial(_tqdm_mod.tqdm, disable=True)
                with warnings.catch_warnings(), \
                     _patch("chatterbox.models.t3.t3.tqdm", _silent_tqdm), \
                     _patch("chatterbox.models.s3gen.flow_matching.tqdm", _silent_tqdm):
                    warnings.filterwarnings("ignore", category=UserWarning)
                    warnings.filterwarnings("ignore", category=FutureWarning)
                    warnings.filterwarnings("ignore", message="S3 Token")
                    warnings.filterwarnings("ignore", message=".*sdpa.*")
                    if voice:
                        wav = self._model.generate(
                            text, audio_prompt_path=voice, **gen_kwargs,
                        )
                    else:
                        wav = self._model.generate(text, **gen_kwargs)
                result[0] = wav.squeeze().float().cpu().numpy()
            except Exception as e:
                error[0] = e

        gen_thread = threading.Thread(target=_generate, daemon=True)
        gen_thread.start()
        gen_thread.join(timeout=timeout)

        if gen_thread.is_alive():
            if "torch" in sys.modules:
                import torch
                if torch.cuda.is_available():
                    logger.warning(
                        "tts_generation_timeout_cuda",
                        model=self._model_name,
                        timeout=timeout,
                        text_len=len(text),
                        hint="daemon thread continues running and holds GPU memory",
                    )
            logger.error(
                "tts_generation_timeout",
                model=self._model_name,
                timeout=timeout,
                text_len=len(text),
            )
            raise TimeoutError(
                f"TTS generation timed out after {timeout}s"
            )

        if error[0] is not None:
            raise error[0]

        audio = result[0]
        if audio is None:
            raise RuntimeError(f"{self._model_name} TTS generation returned None")

        if not isinstance(audio, np.ndarray):
            audio = np.array(audio, dtype=np.float32)

        from chatterbox.models.s3gen import S3GEN_SR

        return audio, S3GEN_SR

    def languages(self) -> list[str]:
        """Return supported ISO 639-1 language codes."""
        return list(CHATTERBOX_MULTI_LANGUAGES)
