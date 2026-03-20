# Changelog

## 0.1.0 — 2026-03-19

Initial release.

### Features

- **TTS Server** — FastAPI server with `/speak`, `/speak-sync`, `/health`, `/voices` endpoints
- **Multiple TTS backends** — Kokoro-82M, KittenTTS (80M/40M/15M), Chatterbox (500M), Chatterbox Turbo (350M)
- **Audio queue** — FIFO playback with depth limit and TTL
- **Speed control** — per-request `speed` override for Kokoro and KittenTTS
- **Voice expressiveness** — `exaggeration` and `cfg_weight` params for Chatterbox voice cloning
- **Say that again** — replay last notification from cached audio (no re-generation)
- **Voice discovery** — `s-peach discover` auditions all voices for a model
- **Doctor diagnostics** — `s-peach doctor` diagnoses environment, config, deps, and runtime issues
- **Config hot-reload** — `POST /reload` re-reads config without restart
- **Multi-model config** — enable/disable models, per-model health, graceful failure handling
- **CLI** — 17 subcommands for server lifecycle, TTS, config, services, and hooks
- **Daemon management** — start/stop/restart/status/logs with PID tracking
- **OS service install** — macOS LaunchAgent and Linux systemd user service
- **Claude Code hooks** — one-command hook install for TTS on task completion
- **MCP server** — SSE endpoint at `/mcp` with `speak`, `speak_sync`, `list_voices`, `say_that_again` tools
- **Security** — optional API key auth, IP whitelist, XDG config paths
- **Install script** — `curl | bash` installer with OS detection and dependency bootstrap
