# Changelog

## 1.0.7 — 2026-04-17

### Fixed

- **Claude Code summary hook recursion** — Summary subprocesses now run from the isolated s-peach config directory instead of the active project, so `claude -p` no longer walks the triggering repo and loads unrelated `CLAUDE.md` files.
- **Stop hooks emitted by the summary subprocess** — `s-peach notify` now ignores Claude Stop-hook payloads whose `cwd` is the isolated summary workdir (`config_dir()`), which prevents recursive notifications even when the summary output text changes between runs.
- **Duplicate real hook deliveries** — Dedup is still applied before summary and before `/speak`, using the text extracted from `client.yaml` `summary.source` as the key. With the default config, repeated Stop-hook payloads that share the same `.last_assistant_message` only play once even if `session_id` or `transcript_path` differ.
- **Server-down summary waste** — `/dedup/check` is now treated as the liveness gate. If it cannot connect, times out, or returns an error, `notify` aborts immediately without running the summary command or calling `/speak`. The dedup check uses a short 3-second timeout.

## 1.0.6 — 2026-04-17

- **Improvements to claude code summary defaults** Improved claude summary command and prompt.


## 1.0.5 — 2026-04-17

- **Abort notify when server is down** - The last fix had an edge case where it the notification workflow could continue to summary even if s-peach server was down. Now it exits.

## 1.0.4 — 2026-04-17

### Fixed

- **Repeated Claude Code Stop-hook notifications on newer Claude Code versions** — `s-peach notify` now dedupes before summary and before `/speak`, using the hashed text extracted from `client.yaml` `.summary.source` as the key.
Depending on which version you are using, you might want to `s-peach uninstall-hook claude-code` and then `s-peach install-hook claude-code`

## 1.0.3 — 2026-03-21

### Added

- **Skip sessions when doing summaries with claude** — `claude -p` now running with extra flag ` --no-session-persistence`

## 1.0.2 — 2026-03-20

### Added

- **Array indexing in dot-path expressions** — `source: ".choices[0].message.content"` now works in notify config
- **Auto-init on first run** — commands that need config automatically scaffold defaults when `~/.config/s-peach/` doesn't exist (prints what was created; falls back to a hint on failure)

## 1.0.1 — 2026-03-20

### Added

- **Windows support (partial)** — `s-peach serve`, CLI client commands, and Claude Code hooks now work on Windows
- **Windows hook script** — `.bat` notifier for Claude Code hooks on Windows (`.sh` on POSIX)
- **Platform-aware paths** — config uses `%APPDATA%`, runtime uses `%TEMP%`, state uses `%LOCALAPPDATA%` on Windows
- **Platform-aware CLI** — editor fallback (`notepad` on Windows), display paths use `%USERPROFILE%`

### Fixed

- **Daemon startup** — fixed `No module named s_peach.main` crash (refactor missed `daemon.py` subprocess command)
- **Structlog exception rendering** — fixed `ModuleNotFoundError: pygments.lexers.python` crash when `logger.exception()` was called
- **Stale doc references** — fixed `main.py` references in CONTRIBUTING.md and feature docs after module split

### Changed

- Pinned `kokoro==0.9.4` and `ruff==0.15.6`
- Replaced `print()` calls in `service.py` with structured logging
- POSIX-only commands (`start/stop/restart/status/logs`, `install-service`) show a clear error on Windows
- Doctor server check skips daemon PID check on Windows, still checks port and health

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
