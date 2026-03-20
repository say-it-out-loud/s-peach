# Voice Cloning Tips

## Reference Audio Requirements

- **Format**: WAV, mono, 16-bit PCM, 22050+ Hz
- **Duration**: 2-5 seconds of clear speech
- **Content**: Minimal background noise, single speaker

## Where to Find Reference Audio

### Public speech datasets
- **LJSpeech** — single-speaker English audiobook clips, perfect format: https://keithito.com/LJ-Speech-Dataset/
- **LibriSpeech test-clean** — multi-speaker English: https://www.openslr.org/12
- **JSUT corpus** — Japanese female speech: https://sites.google.com/site/shinaborumorita/home/jsut
- **JVS corpus** — 100 Japanese speakers, various styles

### HuggingFace
- Search for `voice cloning samples`, `tts reference audio`, `speaker embeddings`
- Community datasets with character voice clips (e.g., search "genshin voice")
- Check the IndexTTS2 repo — some forks include sample reference audios in `examples/` or `prompts/`

### Extract from video/audio
```bash
# Download audio from a video
yt-dlp -x --audio-format wav "URL" -o raw.wav

# Cut a 5-second clip starting at 0:05, convert to correct format
ffmpeg -i raw.wav -ss 00:00:05 -t 5 -ac 1 -ar 22050 -sample_fmt s16 voices/speaker.wav
```

### Generate with existing TTS
```bash
# Use kitten to generate a reference clip
curl -X POST http://localhost:7777/speak \
  -H 'Content-Type: application/json' \
  -d '{"text": "This is my reference voice for cloning.", "model": "kitten"}'
```

## Cross-Language Cloning

Using a reference audio in one language (e.g., Japanese) to generate speech in another (e.g., English) will partially work:

**What transfers well:**
- Voice timbre, pitch, vocal texture, breathiness

**What doesn't transfer well:**
- Accent and pronunciation — phonemes that don't exist in the reference language (e.g., English "th", "r/l" distinction, "v" from Japanese) will sound unnatural
- Prosody and rhythm patterns from the reference language bleed through

**Tips for cross-language use:**
- Pick a reference clip with vowel-heavy, clearly articulated speech
- Avoid clips with very fast speech patterns
- Keep the reference short (2-3 seconds) — longer clips won't fix the cross-language gap
- For best results, match the reference and target language (English ref → English output)
- If you want an anime-style English voice, use English voice actors from anime dubs — same kawaii tone but clean English phonemes
