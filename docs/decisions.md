# Decisions

Cross-cutting architectural decisions for s-peach.

## Python over Go for the server
**Date:** 2026-03-15
**Context:** TTS models are Python-native; need to serve them with minimal latency.
**Options considered:**
1. Python (FastAPI) — zero IPC overhead, direct model access
2. Go server + Python workers — adds IPC complexity (gRPC/HTTP between processes)
**Decision:** Python. TTS models live in-process, no serialization overhead.
**Consequences:** Single-threaded GIL limitations mitigated by `asyncio.to_thread` for blocking calls.

## IP whitelist + optional API key auth
**Date:** 2026-03-15 (updated 2026-03-17)
**Context:** Server is local/Docker-only. Need access control without key management overhead. API key support added later for environments where IP whitelisting alone is insufficient.
**Options considered:**
1. IP whitelist — simple, no credentials to manage
2. API keys — more flexible, but adds key generation/storage/rotation
3. Both, with API key optional — defense in depth without breaking existing setups
**Decision:** IP whitelist as the default layer. Optional API key (`X-API-Key` header) as a second layer, disabled by default (`api_key: null`). `/health` is exempt from API key checks.
**Consequences:** Existing deployments are unaffected. Users who need API key auth set `api_key` in config or `S_PEACH_API_KEY` env var. CLI supports `--api-key` flag.

## Lazy-load + auto-unload model lifecycle
**Date:** 2026-03-15
**Context:** Models use significant memory. Server may be idle for long periods between notifications.
**Options considered:**
1. Persistent — always loaded, fast response, wastes memory when idle
2. Per-request — load/unload each time, slow, complex concurrency
3. Lazy-load + auto-unload — loads on first request, unloads when queue drains
**Decision:** Lazy-load + auto-unload. First request pays the load cost (~1s for KittenTTS), subsequent requests are fast. Memory freed when idle.
**Consequences:** Need a drained-event signal from queue to trigger unload. Threading lock prevents duplicate loads.

## Queue depth tracks items through playback
**Date:** 2026-03-15
**Context:** Queue `is_full()` must accurately reflect capacity including the item currently being played.
**Decision:** `_current_size` decrements after playback completes, not when dequeued from the internal asyncio.Queue. This prevents accepting new items while playback is in progress when queue is at capacity.

## FIFO queue with discard-on-shutdown
**Date:** 2026-03-15
**Context:** On SIGTERM, need fast shutdown. Draining the queue could take minutes.
**Decision:** Finish the currently playing item, log and discard remaining items.
**Consequences:** Notifications in the queue at shutdown time are lost. Acceptable — they're ephemeral status updates.

## enabled_models config + graceful failure
**Date:** 2026-03-15
**Context:** Server needs to support multiple models but not crash if one fails (e.g., no GPU).
**Options considered:**
1. Hardcode model list — inflexible
2. Config-driven `enabled_models` with try/except per model — graceful
**Decision:** `enabled_models` list in Settings. Lifespan wraps each model init in try/except. Failed models logged, excluded from active dict, 503 on /speak.
**Consequences:** Server always starts. `/health` reports per-model status (loaded, enabled, error).

## Chatterbox: shared base class for turbo (350M) and full (500M)
**Date:** 2026-03-18
**Context:** Both Chatterbox variants have identical APIs, same upstream bugs, same workarounds. Only differ in import path and model class name.
**Decision:** `_ChatterboxBase` with `_model_name`, `_import_module`, `_import_class` overrides. Subclasses are one-liners. Shared voice map key `chatterbox` (like kitten variants share `kitten`).
**Consequences:** Adding new chatterbox variants (e.g., multilingual) is trivial — just add a subclass with three class attributes.

## Chatterbox: reimplement prepare_conditionals for float32
**Date:** 2026-03-18
**Context:** `librosa.load()` returns float64 numpy arrays. Chatterbox's `prepare_conditionals` passes these through S3Tokenizer and VoiceEncoder which have float32 weights, causing dtype mismatches. Patching `librosa.load` was unreliable.
**Decision:** Fully reimplement `prepare_conditionals` in our wrapper, casting to float32 immediately after `librosa.load()`.
**Consequences:** Tightly coupled to upstream API — if `prepare_conditionals` signature changes, our reimplementation breaks. Acceptable tradeoff for reliability.

## Fresh audio OutputStream per clip
**Date:** 2026-03-18
**Context:** `sd.play()` reuses a default stream that carries stale buffer state, causing inter-clip clicks.
**Decision:** Open a fresh `sd.OutputStream` context per clip, write audio, close. Add 10ms fade in/out and 300ms silence padding.
**Consequences:** Slightly more overhead per clip (~1ms). Eliminates all audible clicks.

## Constructor registry over class patching
**Date:** 2026-03-15
**Context:** Lifespan needs to conditionally instantiate model backends. Direct class references are captured at import time, making test mocking fragile.
**Decision:** `_MODEL_CONSTRUCTORS` dict maps model names to constructor classes. Lifespan iterates `enabled_models` and looks up constructors. Tests patch the dict directly.
**Consequences:** Adding new models = add entry to dict + implement TTSModel protocol.

## Project rename: tts-notify → s-peach
**Date:** 2026-03-18
**Context:** `tts-notify` is taken on PyPI. Need a name available for future publishing.
**Decision:** Rename to `s-peach` (module: `s_peach`, env prefix: `S_PEACH_`).
**Consequences:** All imports, env vars, config paths, docs updated. Breaking change for existing users (none yet).

## Unified CLI over separate entry points
**Date:** 2026-03-18
**Context:** Had separate `notify` CLI and `uvicorn` invocation. Users need to remember multiple tools.
**Decision:** Single `s-peach` binary with subcommands: `say`, `serve`, `start`, `stop`, `restart`, `status`, `logs`, `init`, `config`, `reload`, `install-service`, `uninstall-service`, `install-hook`, `uninstall-hook`.
**Consequences:** One tool to learn. `s-peach` with no args shows help. argparse with subparsers, no extra deps.

## XDG Base Directory paths
**Date:** 2026-03-18
**Context:** Config, cache, runtime, and state files need standard locations across Linux and macOS.
**Decision:** Follow XDG spec: config in `$XDG_CONFIG_HOME/s-peach/`, cache in `$XDG_CACHE_HOME/s-peach/`, PID in `$XDG_RUNTIME_DIR/s-peach/`, logs in `$XDG_STATE_HOME/s-peach/`. Sensible fallbacks when vars are unset.
**Consequences:** `paths.py` centralizes all path resolution. Config files get 0600 permissions (sensitive).

## Daemon via subprocess.Popen, not os.fork
**Date:** 2026-03-18
**Context:** Need `s-peach start` to daemonize the server. Traditional approach is `os.fork()` + `os.setsid()`.
**Decision:** Use `subprocess.Popen` to spawn `s-peach serve` as a detached process. Simpler, more testable, avoids fork pitfalls with threads and file descriptors.
**Consequences:** PID file written by parent after spawn. PID ownership verified before `stop` to prevent killing unrelated processes.

## Hook settings backup before modify
**Date:** 2026-03-18
**Context:** `install-hook` and `uninstall-hook` modify Claude Code's `settings.json`. Corruption would break Claude Code.
**Decision:** Copy settings to `.bak` before any modification. Atomic writes (temp file + `os.replace`) prevent partial writes. Existing file permissions preserved.
**Consequences:** Users can recover from `.bak` if anything goes wrong. Belt-and-suspenders with atomic writes.

## Notifier script uses `s-peach say`, not raw curl
**Date:** 2026-03-18
**Context:** Hook notifier script needs to call the TTS server. Raw `curl` requires shell-level URL construction from config values.
**Decision:** Script calls `s-peach say` instead. Eliminates shell injection risks from config values, avoids duplicating TTS connection config.
**Consequences:** Script is simpler and safer. Requires `s-peach` on PATH (guaranteed if installed via `uv tool install`).

## Synchronous playback bypasses queue, no lock
**Date:** 2026-03-18
**Context:** `s-peach discover` needs to play voices sequentially and know when each finishes. The async queue is fire-and-forget with no completion signal.
**Options considered:**
1. Track queue items by ID and poll for completion — complex, wasteful
2. Bypass queue, play directly via `play_direct()` — simple, blocks until done
3. Add lock to serialize sync playback — prevents overlapping audio
**Decision:** Bypass queue with direct playback. No lock — concurrent `/speak-sync` calls and queue playback can overlap intentionally (allows layered voices).
**Consequences:** `/speak-sync` is not suitable for high-throughput use. Overlapping audio is a feature, not a bug. `play_direct()` is a shared module-level function in `audio.py` used by both queue and sync paths.

## Shared validation helper for /speak and /speak-sync
**Date:** 2026-03-18
**Context:** `/speak` and `/speak-sync` have identical request validation and TTS generation logic. Duplicating it violates DRY and risks divergence.
**Decision:** Extract `_validate_and_generate(req)` as a closure inside `create_app()`. Returns either `(audio, sr, text)` tuple on success or `JSONResponse` on error. Both endpoints call it.
**Consequences:** Adding new validation rules or TTS parameters only needs one change. Closure captures `app_state` from `create_app()` scope.

## Doctor: read-only by default, --fix for safe mutations
**Date:** 2026-03-18
**Context:** Diagnostic tools should be safe to run anytime. But some issues (missing config, stale PID files) can be auto-fixed.
**Options considered:**
1. Always fix — convenient but surprising side effects
2. Read-only only — safe but unhelpful
3. Read-only default, `--fix` for safe mutations — best of both
**Decision:** `s-peach doctor` is purely diagnostic. `--fix` applies only idempotent, non-destructive fixes: init scaffolding (missing config/notifier files), stale PID cleanup, copying bundled voices.
**Consequences:** Safe to recommend in all error messages. `--fix` can be expanded later without breaking the read-only default.

## Doctor: find_spec over actual imports
**Date:** 2026-03-18
**Context:** Doctor must complete in <2s. Importing chatterbox triggers CUDA/torch initialization (5-30s).
**Decision:** Use `importlib.util.find_spec()` for all dependency checks. Never actually import model packages in doctor.
**Consequences:** Can't verify models load correctly — only that packages are installed. Acceptable tradeoff for speed.

## Doctor: error isolation per check category
**Date:** 2026-03-18
**Context:** Six check categories probe different subsystems. A crash in one (e.g., broken config parse) shouldn't prevent others from running.
**Decision:** Each check category wrapped in try/except in `run_all_checks()`. Failed check produces an error-status CheckResult with the exception message.
**Consequences:** Doctor always returns results for all categories. Debugging is slightly harder when exceptions are caught, but the error message is preserved.

## Move pytest to dependency-groups (not optional-dependencies)
**Date:** 2026-03-18
**Context:** `uv run pytest` was picking up `/opt/venv`'s pytest (Python 3.11) instead of the project's `.venv` (Python 3.12). Chatterbox/perth packages were only in the project venv.
**Decision:** Move pytest from `[project.optional-dependencies] dev` to `[dependency-groups] dev`. uv auto-includes dependency groups in `uv run`.
**Consequences:** `uv run pytest` just works — no need for `--extra dev` or `python3 -m pytest`.

## PyPI package rename: s-peach → s-peach-tts
**Date:** 2026-03-19
**Context:** `s-peach` was too similar to an existing project on PyPI and risked name conflicts.
**Decision:** Rename the PyPI package to `s-peach-tts`. The CLI command remains `s-peach` — only the installable package name changes.
**Consequences:** Users install via `uv tool install s-peach-tts` (or `pip install s-peach-tts`) but run the same `s-peach` binary. Import paths (`s_peach`) and all internal module names are unchanged.

## Unified language codes across models
**Date:** 2026-03-19
**Context:** Kokoro uses internal single-letter codes ("a" for American English, "b" for British) while Chatterbox Multilingual uses ISO 639-1 codes ("en", "fr"). Users shouldn't need to know model-specific encoding.
**Decision:** Standardize on ISO 639-1 two-letter codes everywhere (config, CLI `--lang`, API `language` field). Kokoro translates via `KOKORO_LANG_MAP`. Pipelines are cached per language code for Kokoro to avoid reloading.
**Consequences:** `kokoro.lang_code: "a"` replaced by `kokoro.language: "en"`. Breaking config change for existing users. Same `--lang fr` flag works for both kokoro and chatterbox-multi.

## Chatterbox Multilingual workarounds
**Date:** 2026-03-19
**Context:** `chatterbox.mtl_tts.ChatterboxMultilingualTTS` has three upstream issues: (1) shared HF repo with regular chatterbox causes `local_files_only` cache misses, (2) weights saved on CUDA fail on MPS/CPU without `map_location`, (3) `AlignmentStreamAnalyzer` requires `output_attentions=True` which is incompatible with SDPA attention.
**Decision:** Add three workarounds in `_ChatterboxBase.load()`: retry download on `FileNotFoundError`, patch `torch.load` with `map_location=device`, force `eager` attention on T3 transformer config after loading.
**Consequences:** All workarounds are in `load()` and cleaned up in `finally` blocks. They apply to all chatterbox variants but only activate when needed (e.g. SDPA patch only fires if `_attn_implementation == "sdpa"`).

## Module split: monolithic files → focused packages
**Date:** 2026-03-19
**Context:** Three files had grown too large for humans and LLMs to navigate: `main.py` (1,688 lines), `doctor.py` (850 lines), `server.py` (747 lines). Finding and modifying specific functionality required scanning hundreds of lines.
**Options considered:**
1. Keep monoliths, add better docs — doesn't improve LLM context usage
2. Split into packages with focused modules — better navigation, smaller files
**Decision:** Split into `cli/`, `doctor/`, `server/` packages. Extract shared `scaffolding.py` to break circular deps between CLI and doctor. No behavior changes — pure structural refactor.
**Consequences:** No file exceeds 600 lines (except `daemon.py` at 624, deferred). Entry point moved from `s_peach.main:main` to `s_peach.cli:main`. All imports updated — no backward-compat shims.

## CLI: co-located arg definitions via register(subparsers)
**Date:** 2026-03-19
**Context:** Splitting the CLI needed a pattern for each command to define its own args without a central spaghetti file.
**Options considered:**
1. Centralized `_parser.py` with all args — same problem as before (one huge file)
2. Each command module defines `register(subparsers)` — self-contained, easy to find
**Decision:** Each command module exports `register(subparsers)` that adds its subparser and args. `_parser.py` imports all command modules and calls `register()` on each.
**Consequences:** Adding a new command = new file + import in `_parser.py`. Each command owns its args.

## Server DI: explicit app_state parameter over closures
**Date:** 2026-03-19
**Context:** Server helpers were closures inside `create_app()`, capturing `app_state` from outer scope. This made them untestable in isolation.
**Options considered:**
1. Keep closures — works but untestable without spinning up the full app
2. Plain functions with explicit `app_state` param — testable, inspectable
3. FastAPI `Depends()` — more idiomatic but adds complexity for this codebase size
**Decision:** Plain functions with `app_state` parameter. Extracted to `server/helpers.py` and `server/endpoints.py`.
**Consequences:** Helper tests can construct minimal `AppState` objects. If the server grows, `Depends()` remains an option.

## Shared scaffolding module for circular dependency breaking
**Date:** 2026-03-19
**Context:** `main.py` and `doctor.py` both needed `init_scaffolding()` and voice helper functions. Putting these in `cli/init.py` would create a dependency from `doctor/` to `cli/`.
**Decision:** Dedicated `scaffolding.py` at the `s_peach` package level. Both `cli/` and `doctor/` import from it.
**Consequences:** Clean dependency graph: `cli/` → `scaffolding`, `doctor/` → `scaffolding`. No circular imports.
