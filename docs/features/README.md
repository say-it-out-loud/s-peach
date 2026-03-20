# Features

| Feature | Status | Complexity | Description |
|---------|--------|------------|-------------|
| TTS Server | Done | Complex | FastAPI server with /speak, /health, /voices — see [tts-server/](tts-server/) |
| KittenTTS | Done | Simple | CPU-only TTS model backend — 80M, 40M, 15M variants (8 voices, 24kHz) |
| Kokoro-82M | Done | Simple | CPU-only 82M TTS model backend (multi-language, 24kHz, generator-based) |
| Audio Queue | Done | Simple | FIFO playback queue with depth limit, TTL, drained signal |
| IP Whitelist | Done | Simple | Middleware restricting access to configured CIDRs |
| Chatterbox Turbo | Done | Medium | Fast TTS (350M params) — zero-shot voice cloning via ref clips, paralinguistic tags, 24kHz, CPU/GPU/MPS |
| Chatterbox 500M | Done | Medium | Higher-quality TTS (500M params) — same as turbo but with CFG/exaggeration controls, slower inference |
| Chatterbox Multi | Done | Medium | Multilingual TTS (~500M params) — 23 languages, zero-shot voice cloning, `--lang` flag for language selection |
| Language Support | Done | Simple | `language` param on `/speak` and `--lang` on CLI — ISO 639-1 codes, per-language pipeline caching for Kokoro (9 langs), Chatterbox Multi (23 langs) |
| Speed Control | Done | Simple | `speed` param on `/speak` and `--speed` on CLI — per-request speed override for Kokoro and KittenTTS (config defaults: `kokoro.speed`, `kitten.speed`) |
| Say That Again | Done | Simple | `POST /say-that-again` and `s-peach say-that-again` — replays the last notification from cached audio in server memory (instant, no re-generation) |
| Voice Expressiveness | Done | Simple | `exaggeration` and `cfg_weight` params on `/speak` — controls voice cloning expressiveness (chatterbox only, ignored by other backends) |
| Config Hot-Reload | Done | Simple | `POST /reload` — re-reads server.yaml, updates voices, loads/unloads models without restart |
| Multi-Model Config | Done | Simple | `enabled_models` list, per-model health/status, graceful failure handling |
| Voice Discovery | Done | Simple | `s-peach discover --model <name>` — auditions all voices for a model via `/speak-sync`, with `--voices`, `--wait`, `--speed`, `--dry-run` flags |
| Sync Playback | Done | Simple | `POST /speak-sync` — generates TTS and plays directly (no queue), returns after playback. No lock — concurrent calls can overlap |
| Doctor | Done | Simple | `s-peach doctor` — diagnoses environment, config, deps, voices, server, and hook issues with `--json` and `--fix` flags |
| CLI Tool | Done | Medium | `s-peach` unified CLI — 19 subcommands for server lifecycle, TTS, config, services, hooks |
| API Key Auth | Done | Simple | Optional `X-API-Key` header authentication — disabled by default, protects all endpoints except `/health` |
| XDG Config Paths | Done | Simple | Config in `~/.config/s-peach/`, logs in `~/.local/state/s-peach/`, PID in `$XDG_RUNTIME_DIR/s-peach/` |
| Daemon Management | Done | Medium | `s-peach start/stop/restart/status/logs` — PID file, SIGTERM→SIGKILL escalation, log tailing |
| OS Service Install | Done | Medium | `s-peach install-service/uninstall-service` — macOS LaunchAgent, Linux systemd user service |
| Claude Code Hooks | Done | Medium | `s-peach install-hook claude-code` / `uninstall-hook claude-code` — `notify` subcommand extracts hook text in Python (no jq/yq), thin shell wrapper for settings.json integration |
| MCP Server | Done | Simple | SSE endpoint at `/mcp` — four tools: `speak`, `speak_sync`, `list_voices`, `say_that_again`. IP whitelist + API key auth. Reuses TTS pipeline |
| Install Script | Done | Simple | `curl \| bash` installer — OS detection, system deps, uv bootstrap, s-peach install |
