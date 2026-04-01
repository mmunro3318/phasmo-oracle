"""Radio preview tool — type text, hear it through the CB radio FX chain.

Usage:
    python tools/radio_preview.py
    python tools/radio_preview.py --save output.wav
    python tools/radio_preview.py --candidates 3

Requires: pip install -e '.[voice]'
"""

import argparse
import sys
from pathlib import Path

# Add project root to path so oracle package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np


def main():
    parser = argparse.ArgumentParser(
        description="Oracle Radio FX Preview — type text, hear radio voice"
    )
    parser.add_argument(
        "--save", type=str, default=None,
        help="Save last output to WAV file instead of playing",
    )
    parser.add_argument(
        "--candidates", type=int, default=15,
        help="Simulated candidate count for confidence-coded FX (default: 15)",
    )
    args = parser.parse_args()

    try:
        from oracle.voice.tts import KokoroTTS
        from oracle.voice.radio_fx import RadioFX, get_device_sample_rate, resample_for_device
        import sounddevice as sd
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Install with: pip install -e '.[voice]'")
        sys.exit(1)

    print("Loading Kokoro TTS model...")
    tts = KokoroTTS()
    radio = RadioFX()
    device_sr = get_device_sample_rate()
    print(f"Ready. Device sample rate: {device_sr}Hz")
    print(f"Candidate count: {args.candidates} (use --candidates N to change)")
    print("Type text and press Enter to hear it. Ctrl+C to quit.\n")

    while True:
        try:
            text = input("Text > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not text:
            continue

        audio, sr = tts.synthesize(text)
        processed = radio.apply(audio, sr, args.candidates)

        # Resample for device if needed
        if device_sr != sr:
            processed = resample_for_device(processed, sr, device_sr)
            sr = device_sr

        if args.save:
            from scipy.io import wavfile
            # Convert to int16 for WAV
            int16_audio = (processed * 32767).astype(np.int16)
            wavfile.write(args.save, sr, int16_audio)
            print(f"Saved to {args.save} ({len(processed)/sr:.2f}s)")
        else:
            sd.stop()
            sd.play(processed, sr)
            sd.wait()
            print(f"({len(processed)/sr:.2f}s)")


if __name__ == "__main__":
    main()
