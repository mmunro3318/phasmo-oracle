# Kokoro TTS Benchmark Guide

Measure Kokoro-onnx inference latency on your machine to validate the 200ms estimate.

## Prerequisites

```bash
pip install -e ".[voice]"

# Download model files (one-time, ~300MB total)
# Place in project root, oracle/voice/, or ~/.cache/kokoro-onnx/
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

On Windows without wget, download manually from:
- https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
- https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

## Quick Benchmark

```bash
python -c "
from kokoro_onnx import Kokoro
import time
import numpy as np

print('Loading model...')
t0 = time.perf_counter()
model = Kokoro('kokoro-v1.0.onnx', 'voices-v1.0.bin')
print(f'Model load: {(time.perf_counter()-t0)*1000:.0f}ms')

phrases = [
    'OK.',                                              # ~5 chars
    'Copy that.',                                       # ~10 chars
    'EMF 5 confirmed. Five ghosts remain.',             # ~40 chars
    'That is three. We have identified the ghost as a Deogen. Evidence: spirit box, ghost writing, and D.O.T.S projector.',  # ~120 chars
]

for phrase in phrases:
    times = []
    for _ in range(5):
        t = time.perf_counter()
        audio, sr = model.create(phrase, voice='af_heart', speed=1.0, lang='en-us')
        elapsed = (time.perf_counter() - t) * 1000
        times.append(elapsed)
    avg = np.mean(times)
    print(f'{len(phrase):>4} chars | {avg:>6.0f}ms avg | {min(times):>6.0f}ms min | {max(times):>6.0f}ms max')
"
```

## What to Look For

| Result | Action |
|--------|--------|
| Avg < 200ms | On target. No changes needed. |
| Avg 200-400ms | Acceptable. Total pipeline still < 1 second. |
| Avg 400-600ms | Investigate DirectML acceleration (see below). |
| Avg > 600ms | Consider a smaller TTS model or chunked streaming. |

## DirectML Acceleration (Windows)

If CPU is too slow, try DirectML (uses your GPU):

```bash
pip install onnxruntime-directml
```

Then re-run the benchmark. Kokoro-onnx should auto-detect DirectML.

## Benchmarking the Full Pipeline

```bash
python -c "
from oracle.voice.tts import KokoroTTS
from oracle.voice.radio_fx import RadioFX, get_device_sample_rate, resample_for_device
import time

tts = KokoroTTS()
radio = RadioFX()
device_sr = get_device_sample_rate()
text = 'Copy that. Spirit box confirmed. Five ghosts remain.'

times = []
for _ in range(5):
    t = time.perf_counter()
    audio, sr = tts.synthesize(text)
    processed = radio.apply(audio, sr, candidate_count=10)
    if device_sr != sr:
        processed = resample_for_device(processed, sr, device_sr)
    elapsed = (time.perf_counter() - t) * 1000
    times.append(elapsed)

import numpy as np
print(f'Full pipeline: {np.mean(times):.0f}ms avg, {min(times):.0f}ms min')
print(f'Target: < 500ms (< 1000ms acceptable)')
"
```
