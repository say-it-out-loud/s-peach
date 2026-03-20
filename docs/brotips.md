# Brotips

Hard-won lessons. Read before making changes.

## Architecture

- **Model lifecycle is eager-load + keep-alive**: All enabled models load at startup (blocking until ready) and stay loaded for the server lifetime. They unload on shutdown (SIGINT/SIGTERM is deferred during unloading to ensure clean GPU memory release). The `enabled_models` config controls which models are registered.
- **Single model instance**: Never load the same model twice. `KittenTTSModel` uses a threading lock to prevent duplicate loads — respect this pattern when adding new backends.
- **Shutdown discards, doesn't drain**: On shutdown, finish the item currently playing, then log and discard remaining items. Don't try to play everything — shut down fast.

## Audio Playback

- **Use fresh `sd.OutputStream` per clip, not `sd.play()`**: `sd.play()` reuses a default stream that carries stale buffer state between clips, causing clicks. Open a new `OutputStream` context for each clip and `stream.write()` the audio.
- **Fade in/out to avoid boundary clicks**: Apply a 10ms linear fade-in and fade-out to every audio clip before playback. Without this, abrupt sample transitions at start/end cause audible clicks.
- **Pad 300ms silence at end before closing stream**: The DAC needs time to drain its buffer. Closing the `OutputStream` immediately after the last sample causes an end-of-clip click. 50ms wasn't enough — 300ms reliably eliminates it.

- **`/speak-sync` has no lock — overlapping audio is intentional**: `/speak-sync` bypasses the queue and plays directly with no serialization. Concurrent sync calls or simultaneous queue playback can overlap, allowing layered voices.

## Async Correctness

- **`sounddevice` playback is blocking**: Always run it via `asyncio.to_thread` to avoid blocking the event loop.
- **`TTSModel.speak()` is sync/blocking**: The server offloads it via `asyncio.to_thread`. New backends must follow this pattern — never make `speak()` async.
- **Worker loop is strictly sequential**: Dequeue → play to completion → next item. Never parallel. The queue's `_current_size` tracks items through playback (decrements after play, not on dequeue) so `is_full()` is accurate.

## Doctor / Diagnostics

- **`sounddevice` raises `OSError` at import when PortAudio is missing, not `ImportError`**: On systems without libportaudio, `import sounddevice` throws `OSError` (shared lib not found). The doctor check must catch both `ImportError` and `OSError` around the import.
- **Doctor uses `find_spec` not actual imports for model checks**: `importlib.util.find_spec()` avoids side effects — importing chatterbox triggers CUDA/torch init which blows the <2s budget.
- **Doctor is read-only by default**: Without `--fix`, doctor does not mutate state (no PID cleanup, no config writes). `--fix` is limited to safe, idempotent operations: init scaffolding and stale PID removal.

## Testing

- **Always `uv sync --extra chatterbox` during development**: Without the chatterbox extra, 15 chatterbox tests fail with `ModuleNotFoundError: No module named 'perth'` — the test mocks can't fully isolate from chatterbox's internal import chain.
- **Patch `_MODEL_CONSTRUCTORS` dict, not model classes**: The server lifespan reads from `_MODEL_CONSTRUCTORS` dict (captured at import time). Patching `s_peach.server.KittenTTSModel` won't affect the lifespan. Instead: `srv._MODEL_CONSTRUCTORS["kitten"] = lambda s: mock_model`.
- **Patching KittenTTS in tests requires `create=True`**: The `from kittentts import KittenTTS` happens inside `load()`, so the symbol doesn't exist at module level. Use `@patch("kittentts.KittenTTS", create=True)`.
- **Patch torch via `sys.modules`, not module attribute**: Qwen3's `load()`/`unload()` import torch locally. `patch("module.torch")` at module level doesn't work. Use `patch.dict("sys.modules", {"torch": mock_torch})`.
- **FastAPI TestClient uses "testclient" as client host**: Not a valid IPv4 address. The IP whitelist middleware handles this gracefully (returns 403). For functional tests, set `ip_whitelist = []` to bypass.
- **Patch target for lazy imports follows the source module**: When code uses `from s_peach.scaffolding import init_scaffolding` inside a function body (lazy import), the correct patch target is `s_peach.scaffolding.init_scaffolding`, not the calling module. The local import re-resolves each call.

## CLI

- **argparse subparsers don't auto-help on missing subcommand (Python 3.11+)**: You must explicitly check for absent subcommand and call `parser.print_help()` + `sys.exit(0)`. argparse won't do it for you.
- **`$EDITOR` may contain flags (e.g., `code --wait`)**: Always use `shlex.split(editor) + [str(path)]` with `subprocess.run()`. Never use `shell=True` or `os.system()` — command injection risk.
- **Follow `$VISUAL` > `$EDITOR` > `vi` fallback chain**: This is the standard Unix convention. Many terminal users set `$VISUAL` for full-screen editors and `$EDITOR` for line editors.

## Models / spaCy

- **spaCy vendor patch must be called before model load**: `patch_spacy()` from `s_peach._vendor` must be called before `spacy.load("en_core_web_sm")`. Kokoro's `load()` does this automatically. The patch is deferred (not at import time) to avoid a ~1s spaCy import on every CLI invocation.

## Audio Queue

- **Reload updates audio queue settings directly**: `/reload` mutates `queue._fade_ms`, `._silence_pad_ms`, `._trim_end_ms` on the live `AudioQueue` instance. The queue is NOT recreated — just the attributes change. New values take effect on the next item played.

## Gotchas

- **KittenTTS package is `kittentts`, not `kitten-tts`**: Installed from a GitHub wheel, not PyPI. API: `KittenTTS(model_id).generate(text, voice='Name')` returns numpy array at 24000 Hz. Voices are plain names (Bella, Jasper), not prefixed IDs.
- **Qwen3-TTS uses `generate_custom_voice` not `generate`**: API: `model.generate_custom_voice(text=..., language=..., speaker=...)` returns `(list[ndarray], int)`. Access first element: `wavs[0]`. Sample rate is 12000 Hz.
- **Kokoro needs spaCy model**: `en_core_web_sm` is a default dependency (installed by `uv sync`). If missing, `KPipeline()` tries `spacy.cli.download()` via pip which raises `SystemExit(1)` in uv venvs. The `load()` method catches `SystemExit` and gives a clear error.
- **Chatterbox `from_pretrained(device)` is positional**: Signature is `from_pretrained(device)`, not keyword. Both turbo and 500M variants.
- **No `model.sr` on ChatterboxTurboTTS**: Sample rate is `S3GEN_SR = 24000` from `chatterbox.models.s3gen`. Import the constant directly.
- **Chatterbox `from_pretrained()` forces HF auth on public repos**: Uses `token=os.getenv("HF_TOKEN") or True`. When unset, requires cached credentials. Patched in `load()` to use `token=False`.
- **`perth.PerthImplicitWatermarker` silently None**: Import fails, sets to `None`, then `__init__` calls `None()`. Patched with `DummyWatermarker` in `load()`.
- **librosa.load() returns float64, breaks Chatterbox voice cloning**: Model weights are float32 but librosa returns float64. Causes dtype mismatches in S3Tokenizer and VoiceEncoder. `prepare_conditionals` is reimplemented with `.astype(np.float32)` casts.
- **`T3Cond` import path is `chatterbox.models.t3.modules.cond_enc`**: Not re-exported from `chatterbox.models.t3`.
- **Chatterbox 500M uses `hf_hub_download`, turbo uses `snapshot_download`**: Different HF download functions. The `local_files_only` cache optimization only works for `snapshot_download` — individual file downloads may be partially cached.
- **Chatterbox-multi `local_files_only` finds wrong snapshot**: The multilingual model shares the `ResembleAI/chatterbox` HF repo with regular chatterbox. If the regular model is cached but the multilingual weights aren't, `local_files_only=True` finds the incomplete snapshot and fails with `FileNotFoundError`. The `load()` method catches this and retries with network download.
- **Chatterbox-multi `torch.load` fails on MPS/CPU**: The multilingual weights were saved on CUDA. `mtl_tts.from_pretrained` doesn't pass `map_location` to `torch.load`. Patched in `load()` to force `map_location=device`.
- **Chatterbox-multi needs eager attention, not SDPA**: The multilingual model's `AlignmentStreamAnalyzer` sets `output_attentions=True` during inference, which is incompatible with SDPA. After loading, `load()` patches `t3.tfmr.config._attn_implementation = "eager"`.
