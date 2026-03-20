# Feature: Unified CLI

## Overview
Single `s-peach` binary with 19 subcommands for the full lifecycle: TTS requests, server management, daemon control, OS service installation, config editing, and Claude Code hook integration.

## Architecture

```
s-peach <command> [args]
    ├── say              → httpx POST to /speak (or stdin pipe)
    ├── say-that-again   → POST /say-that-again (replay cached audio)
    ├── serve        → uvicorn in foreground
    ├── start        → subprocess.Popen → detached `serve`
    ├── stop         → read PID file → SIGTERM (→ SIGKILL after 5s)
    ├── restart      → stop + start
    ├── status       → PID file + /health check
    ├── logs         → tail -f on log file
    ├── init         → scaffold server.yaml + client.yaml
    ├── config       → open in $EDITOR, reload after save
    ├── reload       → POST /reload
    ├── install-service    → launchd plist / systemd unit
    ├── uninstall-service  → remove service files
    ├── install-hook <target>   → notifier script + settings.json merge
    ├── uninstall-hook <target> → remove hook from settings + script
    ├── doctor             → diagnose environment, config, deps, voices
    ├── voices             → list available voices from running server
    ├── notify             → process hook JSON from stdin, extract + summarize + speak
    ├── discover           → audition all voices for a TTS model
    └── --version          → print package version
```

### Key Files
- `src/s_peach/cli/__init__.py` — entry point and dispatch
- `src/s_peach/cli/_parser.py` — argparse subparsers (calls `register()` on each command module)
- `src/s_peach/cli/*.py` — per-command modules (say, notify, discover, doctor, etc.)
- `src/s_peach/paths.py` — XDG path resolution
- `src/s_peach/daemon.py` — start/stop/restart/status/logs
- `src/s_peach/service.py` — OS service install/uninstall
- `src/s_peach/hooks.py` — Claude Code hook install/uninstall

## Subcommands

### TTS
| Command | Description |
|---------|-------------|
| `say <text>` | Send speak request. Supports stdin piping, `--model`, `--voice`, `--speed`, `--exaggeration`, `--cfg-weight`, `--summary`, `--url`, `--json`, `--quiet`. API key via `S_PEACH_API_KEY` env var. URL resolved from `--url` > `S_PEACH_URL` > `client.yaml` host/port > `server.yaml` > default |
| `notify` | Process Claude Code hook JSON from stdin. Extracts text via configurable `source` (dot-path like `.last_assistant_message`, `claude_jsonl`, or `raw`), optionally summarizes with `notify_prompt`, speaks via `/speak`. Flags: `--summary`/`--no-summary` (override config), `--quiet`. All logic in Python — no `jq`/`yq` needed |
| `say-that-again` | Replay the last notification from server memory (instant, no re-generation) |

### Server Lifecycle
| Command | Description |
|---------|-------------|
| `serve` | Run server in foreground (`--host`, `--port`) |
| `start` | Daemonize server (`--host`, `--port`) |
| `stop` | Stop daemon (`--force` for SIGKILL) |
| `restart` | Stop + start cycle |
| `status` | Show PID, uptime, health |
| `logs` | Tail log file (`-n` lines, `--no-follow`) |

### Configuration
| Command | Description |
|---------|-------------|
| `init` | Create config files (`--force` overwrites with backup, `--defaults` non-interactive) |
| `config server` | Open server config in `$EDITOR`, reload after save |
| `config client` | Open client/notifier config in `$EDITOR` |
| `reload` | POST /reload to running server |

### Installation
| Command | Description |
|---------|-------------|
| `install-service` | Install OS auto-start (launchd/systemd) |
| `uninstall-service` | Remove OS service |
| `install-hook claude-code` | Install Claude Code TTS hook (`--target` for settings file). User-level (`settings.json`) installs to `~/.claude/scripts/`, project-level (`settings.local.json`) installs to `.claude/scripts/` |
| `uninstall-hook claude-code` | Remove Claude Code hook from all settings files, clean up scripts from both locations |

### Diagnostics & Discovery
| Command | Description |
|---------|-------------|
| `doctor` | Diagnose environment, config, deps, voices, server, and hook issues (`--json`, `--fix`) |
| `discover` | Audition all voices for a model (`--model`, `--text`, `--speed`, `--dry-run`) |

## Caveats
- `s-peach` with no args or `s-peach help` shows usage (argparse doesn't auto-help on missing subcommand in Python 3.11+)
- `config` uses `$VISUAL` > `$EDITOR` > `vi` fallback; editor string is `shlex.split()`'d to handle flags safely
- `install-hook` and `uninstall-hook` require a target argument (currently only `claude-code` is supported)
- `install-hook claude-code` backs up settings.json to `.bak` before modifying
- `uninstall-hook claude-code` checks both `settings.json` and `settings.local.json`
- `notify` is designed for Claude Code's Stop hook — the shell wrapper (`s-peach-notifier.sh`) just calls `s-peach notify --quiet`
- `notify` summarization uses `notify_prompt` from `client.yaml` (not `say_prompt` which `say --summary` uses)
