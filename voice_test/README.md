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
pip install -r voice_test/requirements.txt
```

Or manually:

```bash
pip install kokoro-onnx sounddevice scipy python-dotenv rich
```

## 2 — Find your audio output device

Run this to list all available audio devices:

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

You'll see output like:

```
  0 Built-in Microphone           [...]
  1 Built-in Output               [...]
  5 Headphones (VK81), MME
 14 Headphones (VK81), Windows DirectSound
 20 Headphones (VK81), Windows WASAPI     <- most modern, preferred
 ...
```

**Important:** On Windows with WASAPI, if you see the same device name with multiple APIs (MME, DirectSound, WASAPI), **use the full string including the API name** for exact matching. For example: `Headphones (VK81), Windows WASAPI`

If the device name is unique, you can use just the name: `Built-in Output`

## 3 — Configure your audio device

```bash
cp voice_test/.env.local.example voice_test/.env.local
```

Edit `.env.local` and set `AUDIO_DEVICE` to your device name (from step 2):

```
# Option A: Device with unique name
AUDIO_DEVICE=Built-in Output

# Option B: Device with multiple APIs (Windows) — use full string
AUDIO_DEVICE=Headphones (VK81), Windows WASAPI

# Option C: Use device index (always works)
AUDIO_DEVICE=20
```

Leave blank to use the system default.

## 4 — Run it

```bash
python voice_test/app.py
```

On first launch it will download `kokoro-v1.0.int8.onnx` and `voices-v1.0.bin`
directly from the kokoro-onnx GitHub releases (~90 MB). After that it loads
instantly from the local copies.

You'll see a table of all available voices. Type any voice name at the prompt
and the Oracle will deliver a random field dispatch in that voice. Press `q` to quit.

---

## Troubleshooting

**"Invalid sample rate \[-9997\]" error:** This happens on Windows with WASAPI when the sample rate doesn't match. Make sure you're using the full device string including the API name (e.g., `Headphones (VK81), Windows WASAPI` not just `Headphones (VK81)`). The app automatically resamples audio to match the device's native rate once it's configured correctly.
