<h1 align="center">s-peach</h1>
<h3 align="center"><em>Give your AI a voice.</em></h3>
<p align="center">Give your AI a voice.<br>
Stop checking.<br>
Hear a short summary instead.</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/say-it-out-loud/s-peach/refs/heads/master/assets/s-peach.jpg" alt="s-peach banner" width="100%">
</p>


<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Platform macOS | Linux | Windows" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey">
</p>

---

`s-peach` is a TTS cli and notification server for AI agents that summarizes task results in two sentences.

Hook it up to notification services through CLI, REST, or MCP.

## Features

- **Multiple TTS models** — runs on everything from a potato to a high-end rig
- **Audio queue** — notifications queue up and play in order
- **Full featured CLI** — use easily from any script
- **Daemon mode** — runs as a background process; survives terminal closes
- **MCP tools** — via SSE endpoint at `/mcp` for agent use
- **Doctor diagnostics** — `s-peach doctor` helps you get started
- **Voice discovery** — audition voices easily `s-peach discover`
- **Voice cloning** — Chatterbox supports zero-shot voice cloning
- **Security first** — IP whitelist and automatic API key generation
- **Claude Code hooks** — one command to hook you up

## Platform Support

`macOS` and `Linux` — full support. <br>
`WSL` — full support (it's Linux). <br>
`Windows` — partial: `s-peach serve`, CLI client commands, and Claude Code hooks work. <br>
Daemon management (`start/stop/restart`) and OS service install require POSIX.

## TTS Models

| Model | Download | Est. RAM | Voices | Voice Cloning | Speed Control | Notes |
|-------|----------|----------|--------|---------------|---------------|-------|
| kitten-nano (int8) | 26 MB | ~40 MB | 8 | No | Yes | Fastest |
| kitten-micro | 43 MB | ~80 MB | 8 | No | Yes | Sweet spot for low-RAM setups |
| kitten-mini | 78 MB | ~150 MB | 8 | No | Yes | Good balance for CPU |
| Kokoro-82M | 339 MB | ~300 MB | 54 | No | Yes | High quality, 9 languages |
| Chatterbox | 3.0 GB | ~3.5 GB | Unlimited | Yes | No | Best quality & Zero-shot voice cloning |
| Chatterbox Turbo | 3.8 GB | ~4 GB | Unlimited | Yes | No | Faster variant |
| Chatterbox Multi | ~3.0 GB | ~3.5 GB | Unlimited | Yes | No | 23 languages & voice cloning |

Chatterbox models are **not installed by default** — they add ~750 MB of Python dependencies plus multi-GB model downloads on first use.

## Installation

### Install with uv
```bash
# default install
uv tool install s-peach-tts

# with chatterbox voice cloning (chatterbox requires some pin overrides)
uv tool install "s-peach-tts[chatterbox]" \
  --overrides <(echo -e "numpy>=2.0\ntorch>=2.6.0\ntorchaudio>=2.6.0")
```

## Quick Start

### Recommended first run
```bash
s-peach init              # scaffold config home dir
s-peach serve             # start the server in foreground
# In other terminal
s-peach say "Hello world" # test it out
```

### Discover voices
```bash
s-peach voices                                     # see all voices
s-peach discover --model "kitten-micro"            # audition all voices for a model
s-peach discover --model "kokoro" --voices "Onyx,River,Heart" # audition selected voices
```

## Configure

Default settings enable Kokoro 82M. Edit server settings to enable other models. They will download on server startup.
```bash
s-peach config             # see help screen for paths and info
s-peach config server      # edit server configurations, enable models etc
s-peach config client      # edit config for default model/voice
s-peach reload             # reload with new option
```

## Run in background

```bash
s-peach start               # start the daemon
s-peach status              # check that it's running
s-peach say "Hello World"   # test it out
s-peach stop                # stop the daemon
```

## Run as a service

```bash
s-peach install-service     # install as system service
s-peach status              # check that it's running
s-peach say "Hello World"   # test it out
s-peach uninstall-service   # remove the service
```


## Three Ways to Use

**1. CLI — send a notification from anywhere:**

```bash
# Default client configured model and voice
s-peach say "Build complete"
# Select model and voice
s-peach say "Merry Christmas" --model "kokoro" --voice "Santa_US"
# Read command outputs through pipe
echo "Done" | s-peach say --model "kitten-micro" --voice Rosie
# Multilingual (kokoro or chatterbox-multi)
s-peach say "Bonjour le monde" --lang fr --model kokoro
s-peach say "Hola mundo" --lang es --model chatterbox-multi
# Save audio as WAV
s-peach say "Done" --save
# Repeat last message
s-peach say-that-again
s-peach say-that-again --save
# List available voices
s-peach voices
```
Some flags for `s-peach say`:

| Flag | Description |
|------|-------------|
| `--help` | Display all flags |
| `--model "name"` | Select enabled model |
| `--voice "key"` | Select voice for model |
| `--speed 1.0` | `0.1 – 5.0` (kitten/kokoro) |
| `--exaggeration 0.5` | `0.0 – 2.0` (chatterbox full) |
| `--cfg-weight 0.5` | `0.0 – 2.0` (chatterbox full) |
| `--lang "en"` | Language code (kokoro: en, gb, ja, zh, es, fr, hi, it, pt; chatterbox-multi: 23 languages) |
| `--summary` | Summarize the text before speaking (uses the summary command from client.yaml) |
| `--save` | Save audio as WAV to `~/.config/s-peach/output/` |


**2. Claude Code hook — automatic TTS on task completion:**

```bash
s-peach install-hook claude-code
```

or add this stop hook to your settings.json

```json
"hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/scripts/s-peach-notifier.sh",
            "async": true
          }
        ]
      }
    ]
  }
```

This wires Claude Code to call s-peach whenever a task finishes.
You'll hear the result without looking at the terminal.

Even though summary is on by default through client config, the hook accepts all `s-peach notify` flags
so you can have separate voices for different repos. Sweet!

```json
"command": "bash ~/.claude/scripts/s-peach-notifier.sh --model kitten-micro --voice Rosie",
```

It's also possible to skip summaries
```json
"command": "bash ~/.claude/scripts/s-peach-notifier.sh --no-summary",
```

**3. MCP — tool-based TTS for agents:**

Connect your MCP client to `http://localhost:7777/mcp` (SSE transport). <br>
Available tools: `speak`, `speak_sync`, `list_voices`, `say_that_again`.

## Summaries

The client can summarize agent output before speaking it aloud. It's using `claude -p` by default.<br>
Update the command section in your client config `s-peach config client` to something appropriate (ask your AI for help):
```yaml
summary:
  command: 'ollama run llama3 "$1"'
  source: ".choices[0].message.content"
```

The summarization prompts are also configurable in the client config.

### `--summary` examples
Summarize long text before speaking — useful for piping logs, diffs, or agent output:
```bash
s-peach say --summary "$(git diff)"
cat build.log | s-peach say --summary
echo "Long explanation..." | s-peach say --summary
```

## Chatterbox and 0-shot voice cloning

- Put voice samples longer than 5s in `~/.config/s-peach/voices`
- Update server config `s-peach config server`
  - Enable `chatterbox` or `chatterbox-turbo` under `enabled_models`
  - Create a new voice in `voices.chatterbox.<voice-name>`
  - Save and exit
  - If edited in other editor, reload server with `s-peach reload`
- Use the voice like usual:
  - `s-peach say "Hello World" --model "chatterbox" --voice "Example1"`
  - `s-peach say "Hello World" --model "chatterbox-turbo" --voice "Example2"`

**Default voice `Bea` taken from [OpenSLR EmoV_DB](https://openslr.org/115/)**

### Chatterbox & Chatterbox-multi

Supports creative control:
- Add drama with `--exaggeration`, default `0.5`, range `0.0 - 2.0`
  - Higher means more drama.
- Add freedom with `--cfg-weight`, default `0.5`, range `0.0 - 2.0`.
  - Higher means more like reference audio.

### Chatterbox-turbo

- Faster generation
- Supports **paralinguistic tags** in text:
  - `[laugh]`, `[chuckle]`, `[sigh]`, `[gasp]`, `[sniff]`, `[clear throat]`, `[cough]`, `[groan]`, `[shush]` and `[pause]`

### Chatterbox-multi (multilingual)

Supported Languages (ISO 639-1)

- **Northern & Western Europe**<br> English (`en`), Swedish (`sv`), Danish (`da`), Norwegian (`no`), Finnish (`fi`), German (`de`), French (`fr`), Dutch (`nl`)

- **Southern & Eastern Europe**<br>
  Spanish (`es`), Italian (`it`), Portuguese (`pt`), Polish (`pl`), Russian (`ru`), Greek (`el`)

- **Asia**<br>
  Chinese (Mandarin) (`zh`), Japanese (`ja`), Korean (`ko`), Hindi (`hi`), Malay (`ms`)

- **Middle East & Africa**<br>
  Arabic (`ar`), Hebrew (`he`), Turkish (`tr`), Swahili (`sw`)

## Kokoro

Supported Languages (ISO 639-1)

- **Northern & Western Europe**<br>
  English (US) (`en`), English (UK) (`gb`), French (`fr`)

- **Southern & Eastern Europe**<br>
  Spanish (`es`), Italian (`it`), Portuguese (`pt`)

- **Asia**<br>
  Japanese (`ja`), Chinese (Mandarin) (`zh`), Hindi (`hi`)

- **Middle East & Africa**<br>
  _None currently_


## Troubleshooting

```bash
s-peach doctor        # diagnose everything
s-peach doctor --fix  # auto-fix safe issues
```

## Documentation

- [System architecture](docs/system.md) — tech stack, request flow, component overview
- [Feature docs](docs/features/) — detailed docs for every feature
- [Architectural decisions](docs/decisions.md) — why things are the way they are

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
