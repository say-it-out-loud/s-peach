# Contributing to s-peach

Glad you're here. All contributions are welcome — bug reports, feature ideas, new TTS backends, voice packs, and documentation improvements.

## Getting Started

```bash
# Fork and clone
git clone https://github.com/<your-fork>/s-peach
cd s-peach

# Install deps (full dev setup including Chatterbox)
uv sync --extra chatterbox

# Run the tests
uv run pytest tests/
```

If you don't need Chatterbox voice cloning, `uv sync` (without the extra) is enough for most work. Some tests that exercise the Chatterbox backend require `--extra chatterbox`.

## Testing Requirements

**All changes must be covered by tests.** Every contribution needs tests covering:

- **Happy path** — the expected behavior works
- **Error path** — failures are handled correctly
- **Edge cases** — boundary conditions, empty inputs, unexpected values

A PR without adequate test coverage will not be merged. If you're not sure what to test, look at the existing test files for patterns — they show how TTS backends, the server, the CLI, and the queue are tested.

```bash
uv run pytest tests/              # run all tests
uv run pytest tests/ -v           # verbose output
uv run pytest tests/ -k "doctor"  # run a specific subset
```

## Ways to Contribute

- **Bug reports** — open an issue with reproduction steps and your `s-peach doctor --json` output
- **Feature ideas** — open an issue to discuss before implementing; helps avoid wasted effort
- **New TTS model backends** — see below
- **Voice packs** — new voice configurations for existing models
- **Documentation improvements** — fix errors, add examples, clarify anything confusing

## Adding a New TTS Model

TTS backends implement the `TTSModel` protocol defined in `src/s_peach/models/base.py`. The protocol is small — implement it, and the rest of the server works automatically.

Steps:

1. **Implement the protocol** — create `src/s_peach/models/yourmodel.py` and implement `TTSModel`. Look at `kitten.py`, `kokoro.py`, and `chatterbox.py` as references for how loading, generation, and unloading work.

2. **Register the constructor** — add your model to the `_MODEL_CONSTRUCTORS` dict in `src/s_peach/server/__init__.py`. The key is the model name used in config and CLI.

3. **Add voices to config** — add a voice map entry to `server.yaml` (or the default config template) so users can reference your model's voices by name.

4. **Write tests** — cover model loading, generation, error handling, and any model-specific parameters. Mark tests that require the actual model weights with `@pytest.mark.model` so they can be skipped in CI environments without the model.

## Code Style

The project uses `ruff` for linting. Run it before submitting:

```bash
uv run ruff check .
uv run ruff format .
```

Check `pyproject.toml` for the exact configuration. Fix any reported issues before opening a PR.

## Submitting a PR

- **Describe what and why** — the PR description should explain the problem being solved, not just what changed
- **Keep PRs focused** — one feature or fix per PR; easier to review, easier to revert if needed
- **Tests must pass** — run `uv run pytest tests/` and confirm everything is green before requesting review
- **Linter must be clean** — run `uv run ruff check .` and fix any issues

If you're working on something non-trivial, open an issue first to align on the approach. It avoids the frustrating situation where good work doesn't get merged because of a design mismatch.
