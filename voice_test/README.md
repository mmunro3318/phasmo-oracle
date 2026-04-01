# Oracle Voice Tester

A small terminal app that lets you audition all the Kokoro ONNX voices
speaking Phasmophobia-themed investigation dispatches.

Model files (~90 MB total) are downloaded automatically on first run.

---

## Prerequisites

- Python 3.11+
- [PortAudio](https://www.portaudio.com/) (needed by `sounddevice`)
  - macOS: `brew install portaudio`
  - Ubuntu/Debian: `sudo apt install portaudio19-dev`
  - Windows: usually bundled with the `sounddevice` wheel

## 1 — Install dependencies

From the repo root:

```bash
pip install kokoro-onnx sounddevice python-dotenv rich
```

## 2 — Configure your audio device (optional)

```bash
cp voice_test/.env.local.example voice_test/.env.local
```

To find your device name, run:

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Paste the device name (or a unique substring) into `.env.local`:

```
AUDIO_DEVICE=MacBook Pro Speakers
```

Leave `AUDIO_DEVICE` blank to use the system default.

## 3 — Run it

```bash
python voice_test/app.py
```

On first launch it will download `kokoro-v1.0.int8.onnx` and `voices-v1.0.bin`
directly from the kokoro-onnx GitHub releases (~90 MB). After that it loads
instantly from the local copies.

You'll see a table of all available voices. Type any voice name at the prompt
and the Oracle will deliver a random field dispatch in that voice. Press `q` to quit.
