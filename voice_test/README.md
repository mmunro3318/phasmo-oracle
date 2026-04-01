# Oracle Voice Tester

A small terminal app that lets you audition all the Kokoro ONNX voices
speaking Phasmophobia-themed investigation dispatches.

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

## 2 — Download the model files

Grab both files from [Kokoro-82M on Hugging Face](https://huggingface.co/hexgrad/Kokoro-82M)
and place them inside the `voice_test/` folder:

| File | Where to find it |
|------|-----------------|
| `kokoro-v0_19.onnx` | Files tab → `kokoro-v0_19.onnx` |
| `voices.bin` | Files tab → `voices.bin` |

## 3 — Configure your audio device (optional)

```bash
cp voice_test/.env.local.example voice_test/.env.local
```

To find your device name, run:

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Paste the device name (or a unique substring of it) into `.env.local`:

```
AUDIO_DEVICE=MacBook Pro Speakers
```

Leave `AUDIO_DEVICE` blank to use the system default.

## 4 — Run it

```bash
python voice_test/app.py
```

You'll see a table of all available voices. Type any voice name at the prompt
and the Oracle will deliver a random field dispatch in that voice. Press `q` to quit.
