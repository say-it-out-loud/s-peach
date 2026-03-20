# s-peach

## Overview
TTS notification server — Claude Code agents speak status updates aloud via `POST /speak`.

## System
Read `docs/system.md` for architecture, tech stack, and how to get oriented.
Read `docs/brotips.md` for known gotchas before making changes.
Read `docs/features/README.md` for what's implemented.

## Build & Run
```bash
uv sync                                 # Install deps (kokoro + kitten + spaCy model)
uv sync --extra chatterbox              # Also install chatterbox-tts (adds ~750MB)
s-peach init                             # Scaffold config files
s-peach serve                            # Run server in foreground
s-peach start                            # Or daemonize it
s-peach say "Build complete"             # Send TTS notification via CLI
s-peach say "Fast" --speed 1.5           # With speed override
s-peach say "Bonjour" --lang fr          # Language override (ISO 639-1)
s-peach say --summary "$(git log -5)"    # Summarize before speaking
s-peach say "Done" --save                # Save WAV to ~/.config/s-peach/output/
s-peach say-that-again                   # Replay last say
s-peach say-that-again --save            # Replay and save WAV
s-peach voices                           # List available voices from server
s-peach voices --json                    # Raw JSON output
s-peach doctor                           # Diagnose issues
s-peach doctor --fix                     # Auto-fix safe issues
s-peach discover --model kitten-mini       # Audition all voices for a model
s-peach discover --model kokoro --dry-run  # List voices without playing
s-peach install-hook claude-code         # Add Claude Code TTS hook
s-peach uninstall-hook claude-code       # Remove Claude Code TTS hook
uv run pytest tests/                     # Run tests
```

## Testing
All changes must be covered by tests. Every contribution needs:
- **Happy path** — expected behavior works
- **Error path** — failures handled correctly
- **Edge cases** — boundary conditions, empty inputs, unexpected values

```bash
uv sync --extra chatterbox              # Full dev setup (some tests need this)
uv run pytest tests/                     # Run all tests
uv run pytest tests/ -k "doctor"         # Run a specific subset
uv run ruff check .                      # Lint before committing
```

Mark tests requiring actual model weights with `@pytest.mark.model`.

## Config Files
- `server.yaml` — server config (models, voices, queue, API key, IP whitelist)
- `client.yaml` — client config (server host/port, default model/voice, summary settings)
- Hook install: user-level (`~/.claude/`) or project-level (`.claude/`) based on `--target`
- `notify` subcommand `source` config: dot-path expression (`.last_assistant_message`), `claude_jsonl`, or `raw`
- Summary prompts: `notify_prompt` (`s-peach notify` / hook) and `say_prompt` (`s-peach say --summary`)
- Notifier shell script is a thin wrapper — all logic lives in `s-peach notify` (Python, no jq/yq deps)

## Conventions
- TTS backends implement `TTSModel` protocol in `src/s_peach/models/base.py`
- Voice maps live in `server.yaml`, not hardcoded
- All config overridable via `S_PEACH_*` env vars
- Blocking calls (TTS generation, audio playback) go through `asyncio.to_thread`
- MCP endpoint at `/mcp` (SSE transport) exposes `speak`, `speak_sync`, `list_voices`, `say_that_again` tools — reuses the same TTS pipeline as `POST /speak`, secured by IP whitelist + API key middleware
- `/speak-sync` bypasses the queue and plays directly — no lock, concurrent calls can overlap
