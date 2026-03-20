# System: s-peach

## Overview
A TTS notification server that lets Claude Code agents (and any HTTP client) speak status updates aloud via `POST /speak`. One Python process running on the host machine, playing audio through host speakers.

## Tech Stack
- **Language**: Python (see pyproject.toml for version range)
- **Framework**: FastAPI + uvicorn
- **TTS**: KittenTTS (CPU, 80M, 24kHz) + Kokoro-82M (CPU, 82M, 24kHz) + Chatterbox Turbo (CPU/GPU, 350M, 24kHz, voice cloning) + Chatterbox (CPU/GPU, 500M, 24kHz, voice cloning, CFG/exaggeration)
- **Audio**: sounddevice (PortAudio)
- **Config**: YAML + Pydantic Settings (env var overrides via `S_PEACH_` prefix)
- **Package manager**: uv
- **Logging**: structlog (structured, configurable level)

## Architecture

```
CLI (s-peach say) ─┐
                   ├─→ HTTP Request → IP Whitelist MW → API Key MW → Request Logging MW
Shell/Agent ───────┘
                                        ↓
                         Voice Registry (resolve name → model)
                                        ↓
                          TTS Model Facade (generate audio)
                                        ↓
                        ┌───────────────┴───────────────┐
                  /speak (async)                /speak-sync (direct)
                        ↓                               ↓
              Audio Playback Queue           play_direct() — no queue
              (FIFO, depth/TTL)                (blocks until done)
                        ↓                               ↓
                        └───────────────┬───────────────┘
                               Host Speakers
```

- **Server** (`server/`): FastAPI app package. `__init__.py` has `create_app()` factory, lifespan, and `_MODEL_CONSTRUCTORS`. `models.py` has Pydantic request/response models and `AppState`. `middleware.py` has IP whitelist, API key, and request logging. `endpoints.py` has route handlers with DI via `app_state` param. `helpers.py` has `validate_request()` and `generate_audio()`. Endpoints: `/speak`, `/speak-sync`, `/say-that-again`, `/health`, `/voices`, `/reload`. MCP SSE endpoint mounted at `/mcp` (via `mcp_server.py`). Lifespan manages queue worker and model unload watcher. `/reload` hot-reloads `server.yaml` — updates voices, loads/unloads models, and applies audio post-processing settings (`fade_ms`, `silence_pad_ms`, `trim_end_ms`) without restart. `/say-that-again` replays the last successful `/speak` or `/speak-sync` from cached audio in memory (instant, no re-generation). `/speak-sync` bypasses the queue and plays directly via `play_direct()`, returning only after playback completes — used by the `discover` command for sequential voice auditions.
- **Config** (`config.py`): Pydantic Settings loaded from `server.yaml` with `S_PEACH_*` env var overrides.
- **Models** (`models/`): `TTSModel` protocol in `base.py`, `KittenTTSModel` in `kitten.py`, `KokoroTTSModel` in `kokoro.py`, `ChatterboxTurboTTSModel` and `ChatterboxTTSModel` in `chatterbox.py` (shared `_ChatterboxBase`). All enabled models are loaded eagerly at startup (blocking until ready), stay loaded for the lifetime of the server, and are unloaded on shutdown. SIGINT/SIGTERM is deferred during model unloading to ensure clean GPU memory release. `enabled_models` config controls which models are registered.
  - **Chatterbox Turbo** (350M params, by Resemble AI): Fast TTS with zero-shot voice cloning via reference audio clips. Supports paralinguistic tags (`[laugh]`, `[chuckle]`, `[cough]`, `[sigh]`, `[gasp]`, `[groan]`). Sample rate: 24kHz. Device: CPU, CUDA, or MPS.
  - **Chatterbox** (500M params, by Resemble AI): Higher-quality variant with CFG and exaggeration controls. Same voice cloning and paralinguistic tag support. Slower but better quality. Both variants share the `chatterbox` voice map and `ChatterboxConfig` settings.
  - Voice cloning setup: place a reference audio clip (~10s WAV/MP3) and map it in `voices.chatterbox` config. Both chatterbox variants share the same voice map.
  - **Speed control**: `/speak` accepts optional `speed` (float, 0.1–5.0). Supported natively by Kokoro and KittenTTS (config defaults in `kokoro.speed` and `kitten.speed`). Per-request speed overrides config default. Chatterbox ignores it (no native support).
  - **Expressiveness controls**: `/speak` accepts optional `exaggeration` (0.0–1.0, voice cloning intensity) and `cfg_weight` (0.0–1.0, classifier-free guidance strength). Passed to chatterbox `generate()`, ignored by other backends. The 500M model responds to these better than turbo.
- **Audio** (`audio.py`): `play_direct()` module-level function for blocking audio playback with peak normalization, fade in/out, and silence padding. Used by both `AudioQueue._play_sync` and `/speak-sync`. `AudioQueue` is an async FIFO queue with depth limit, TTL expiry, and drained-event signaling for model lifecycle.
- **Voices** (`voices.py`): Registry resolving friendly voice names to model + native ID pairs. Voice map lives in `server.yaml`.
- **MCP Server** (`mcp_server.py`): FastMCP server over SSE transport at `/mcp`. Exposes four tools: `speak` (async, queued), `speak_sync` (blocks until playback done, bypasses queue), `list_voices` (discover available models and voices), and `say_that_again` (replay last notification from cache). Reuses the same AppState, voice registry, and TTS pipeline as the HTTP endpoints — no duplication. Wrapped with IP whitelist and API key middleware (parent FastAPI middleware doesn't apply to mounted sub-apps). Mounted on the existing FastAPI app so no separate process is needed.
- **CLI** (`cli/`): `s-peach` unified CLI package. `__init__.py` has `main()` entry point and dispatch. `_parser.py` builds the ArgumentParser, calling `register(subparsers)` on each command module. `_helpers.py` has shared utilities (URL resolution, API key, config loading, summarization). Per-command modules: `say.py`, `notify.py`, `voices.py`, `discover.py`, `init.py`, `serve.py`, `daemon.py`, `doctor.py`, `hooks.py`, `service.py` — each with `register()` for arg definitions and handler functions. `say` POSTs to `/speak` with `--model`, `--voice`, `--speed`, `--exaggeration`, `--cfg-weight`, `--summary`, `--url`, `--timeout`, `--quiet`, stdin piping. `notify` reads Claude Code hook JSON from stdin, extracts text (configurable `source`: jq-like dot-path, `claude_jsonl`, or `raw`), optionally summarizes with `notify_prompt`, and speaks — all in Python (no external `jq`/`yq` deps). URL resolution: `--url` > `S_PEACH_URL` env > `client.yaml` host/port > `server.yaml` > default. `discover` iterates all voices for a model via `POST /speak-sync`. `doctor` delegates to the `doctor/` package (see [features/cli/](features/cli/)). API key via `S_PEACH_API_KEY` env var.
- **Doctor** (`doctor/`): Diagnostic package. `__init__.py` has `run_all_checks()` and `apply_fixes()`. `models.py` has `CheckResult`, `CheckCategory`, `Status`. `render.py` has `render_text()` and `render_json()`. `checks/` subpackage with one file per check category: `environment.py`, `config.py`, `dependencies.py`, `voices.py`, `server.py`, `hooks.py`.

## Key Entry Points
- `src/s_peach/cli/` — CLI package (`s-peach` binary), 19 subcommands via `register(subparsers)` pattern
- `src/s_peach/doctor/` — Diagnostic package: per-check modules in `checks/`, rendering in `render.py`
- `src/s_peach/server/` — Server package: `create_app()` factory, endpoints, middleware, helpers
- `src/s_peach/scaffolding.py` — Shared init/voice helpers (used by both CLI and doctor)
- `src/s_peach/paths.py` — XDG-standard path resolution (config, cache, runtime, state)
- `src/s_peach/daemon.py` — Daemon lifecycle (start/stop/restart/status/logs)
- `src/s_peach/service.py` — OS service install (macOS LaunchAgent, Linux systemd)
- `src/s_peach/mcp_server.py` — MCP server (FastMCP) with `speak`, `speak_sync`, `list_voices`, `say_that_again` tools, mounted at `/mcp`
- `src/s_peach/hooks.py` — Claude Code hook install/uninstall (user-level `~/.claude/` or project-level `.claude/`)
- `src/s_peach/data/s-peach-notifier.sh` — Hook script: thin bash wrapper that delegates to `s-peach notify`
- `server.yaml` — all server configuration with documented defaults
- `client.yaml` — client/hook configuration: server host/port, default model/voice, summary settings (`source`, `say_prompt`, `notify_prompt`, `tail_lines`, `max_length`)
- `scripts/install.sh` — curl-pipe installer (OS detection, uv bootstrap, deps)

## Build & Run

```bash
uv sync                                  # Install deps
uv sync --extra chatterbox               # Also install chatterbox-tts
s-peach init                             # Scaffold config files
s-peach serve                            # Run server in foreground
s-peach start                            # Or daemonize it
s-peach say "Build complete"             # Send TTS notification
s-peach say "Fast" --speed 1.5           # With speed override
s-peach say-that-again                   # Replay last notification
s-peach doctor                           # Diagnose issues
s-peach doctor --fix                     # Auto-fix safe issues (init, stale PID)
s-peach discover --model kitten-mini       # Audition all voices for a model
s-peach discover --model kokoro --voices "Heart,Alloy" "Test"  # Filter voices
s-peach discover --model kitten-mini --dry-run  # List voices without playing
s-peach install-hook claude-code         # Add Claude Code TTS hook
s-peach uninstall-hook claude-code       # Remove Claude Code TTS hook
uv run pytest tests/                     # Run all tests
```

## Project Docs
- `docs/features/` — feature documentation
- `docs/brotips.md` — hard-won lessons and gotchas
- `docs/decisions.md` — architectural decisions
- `docs/plans/` — execution plans (historical intent)

## How to Get Oriented
1. Read this file for the big picture
2. Check `docs/features/README.md` for what's implemented
3. Check `docs/brotips.md` before making changes
4. Read `server.yaml` — it's heavily commented and documents all defaults
