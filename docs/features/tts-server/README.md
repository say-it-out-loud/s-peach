# Feature: TTS Server

## Overview
HTTP server that accepts text, generates speech audio via TTS models, and plays it through host speakers. Designed for Claude Code agents to announce status updates during long-running tasks.

## Architecture

```
POST /speak {text, model, voice, speed?, exaggeration?, cfg_weight?}
    -> IP whitelist check (403 if denied)
    -> API key check (401 if configured and missing/wrong)
    -> Input validation (400 if invalid)
    -> Voice resolution (server.yaml voice map)
    -> TTS generation in thread (asyncio.to_thread)
    -> Enqueue audio (503 if full)
    -> 202 Accepted (async playback)

Background worker:
    -> Dequeue item
    -> Check TTL (discard if expired)
    -> Play via sounddevice (in thread)
    -> Signal drained -> unload model
```

### Key Files
- `src/s_peach/server.py` -- FastAPI app, endpoints, middleware, lifespan, `_MODEL_CONSTRUCTORS` registry
- `src/s_peach/config.py` -- Settings model (incl. `KokoroConfig`, `enabled_models`), YAML + env var loading
- `src/s_peach/audio.py` -- AudioQueue with FIFO playback worker
- `src/s_peach/voices.py` -- VoiceRegistry for name resolution (per-model fallback)
- `src/s_peach/models/base.py` -- TTSModel protocol
- `src/s_peach/models/kitten.py` -- KittenTTS backend (CPU, 24kHz)
- `src/s_peach/models/kokoro.py` -- Kokoro-82M backend (CPU, 24kHz)
- `src/s_peach/models/chatterbox.py` -- Chatterbox backends (CPU/GPU, 24kHz, voice cloning)

## API

### `POST /speak`
```json
{"text": "Hello world", "voice": "Bella", "model": "kitten-mini"}
```
- `text` (required): 1-1000 chars, non-empty after strip
- `voice` (required): voice name from config
- `model` (required): model name
- Returns: `202 {status: "queued", queue_size: N}`
- Errors: 400 (bad input), 401 (bad/missing API key), 403 (IP denied), 503 (queue full or timeout)

### `GET /health`
```json
{"status": "ok", "models": {"kitten-mini": {"loaded": false, "enabled": true, "voices": 8}}, "queue": {"size": 0, "max": 10}, "audio_device": {"available": true, "name": "..."}}
```
- Models that failed to load show `enabled: true, loaded: false` with an `error` field

### `GET /voices`
```json
[{"model": "kitten-mini", "voices": [{"name": "Bella", "description": ""}, ...]}]
```

## Configuration

All settings live in `server.yaml` and can be overridden via environment variables with the `S_PEACH_` prefix.

For **nested** config fields (under `server:` or `kokoro:`), use double underscore (`__`) as the delimiter:

| Config field | Env var |
|---|---|
| `log_level` | `S_PEACH_LOG_LEVEL` |
| `queue_depth` | `S_PEACH_QUEUE_DEPTH` |
| `api_key` | `S_PEACH_API_KEY` |
| `server.host` | `S_PEACH_SERVER__HOST` |
| `server.port` | `S_PEACH_SERVER__PORT` |
| `kokoro.speed` | `S_PEACH_KOKORO__SPEED` |
| `kokoro.lang_code` | `S_PEACH_KOKORO__LANG_CODE` |

Priority (highest wins): env vars > YAML file > defaults.

## Caveats
- Server must run on the host (not in a container) for audio hardware access
- `sounddevice` requires PortAudio -- fails with clear error if not installed
- TestClient uses "testclient" as client IP -- not valid IPv4, tests bypass whitelist with `ip_whitelist = []`
- API key auth is optional (disabled when `api_key` is null). When set, all endpoints except `/health` require `X-API-Key` header
- Models are loaded eagerly at startup (no cold-start delay on first `/speak`), stay loaded for the server lifetime, and are unloaded on shutdown (Ctrl+C waits for clean unload)
- If a model fails to register at startup, the server continues with remaining models (503 on /speak for that model)
- Voice fallback stays within the requested model's voice map -- requesting a kitten voice on kokoro won't cross-model
