# Sprint 3b — Voice Pipeline

**Status:** COMPLETE (2026-04-01)
**Depends on:** Sprint 3a (text mode rewrite) — COMPLETE on `refactor/voice-first-pivot`
**Design doc:** `~/.gstack/projects/mmunro3318-phasmo-oracle/mmunr-unknown-design-20260401-030722.md`
**Eng review plan:** `~/.claude/plans/elegant-knitting-river.md`

## Goal

Add voice I/O to Oracle: player speaks commands, Oracle responds through speakers with a radio-filtered voice. The text mode REPL from Sprint 3a remains as fallback.

## Architecture

```
[Microphone]
    |
    v
[Wake Word: "Oracle"] — OpenWakeWord
    |
    v
[STT: faster-whisper] — chunk-based transcription (CPU ok, CUDA optional)
    |
    v
[Command Parser] — oracle/parser.py (already built, includes STT fuzzy matching)
    |
    v
[Investigation Engine] — oracle/engine.py (already built)
    |
    v
[Response Builder] — oracle/responses.py (already built — see Ghost Card note below)
    |
    v
[TTS: Kokoro] — text to speech (82M params, near real-time on CPU)
    |
    v
[Radio FX: scipy] — band-pass 300-3400Hz + soft compression + subtle static
    |
    v
[Speaker Output]
```

## Voice Interaction Model

1. **Continuous listening:** Single `sounddevice` InputStream at 16kHz mono. State machine:
   - **IDLE:** Frames fed to OpenWakeWord. On "Oracle" detected → LISTENING.
   - **LISTENING:** Frames buffered. Silero VAD detects end-of-speech (1.5s silence) or 10s hard timeout.
   - **PROCESSING:** Buffer → faster-whisper → parser → engine → response → TTS → radio FX → playback → IDLE.
2. **Push-to-talk fallback:** Keyboard hotkey (F9) triggers LISTENING directly.
3. **Audio sharing:** Wake word and STT share one `sounddevice` stream via state machine.

## New Modules to Build

```
oracle/voice/
    stt.py           — faster-whisper chunk-based wrapper
    tts.py           — Kokoro TTS wrapper
    wake_word.py     — OpenWakeWord listener
    radio_fx.py      — band-pass + compression + static overlay
    audio_config.py  — device selection, sample rates
```

## Radio FX Specification

1. Band-pass filter: 4th-order Butterworth, 300Hz–3400Hz
2. Soft compression: threshold 0.3, gain-reduction 30% of excess above threshold
3. Static overlay: additive Gaussian noise, sigma 0.01
4. Output clipping: [-1.0, 1.0] as float32

## Dependencies

```
faster-whisper>=1.0
kokoro-onnx>=0.4
openwakeword>=0.6
sounddevice>=0.4
scipy>=1.11
numpy>=1.24
```

Install: `pip install -e ".[voice]"`

## Known TODOs (from eng review)

1. **Kokoro short-sentence padding** — kokoro-onnx produces poor audio for <8 phonemes. `responses.py` has `_ensure_minimum_length()` at 40 chars. Verify with actual TTS output.
2. **Async I/O pattern** — Current `InputProvider`/`OutputHandler` protocols are synchronous. `VoiceInput` needs async or callback pattern. Runner loop may need async variant.
3. **Ghost card narration** — Current ghost query responses dump structured data (evidence lists, test entries). For voice, these need a conversational narrative scaffold that nests card content into natural speech. Example: "The Banshee is a female ghost. Evidence: D.O.T.S., Ghost Orb, and Ultraviolet. Its key behavior — it targets one player and won't switch until that player dies. Community test: watch who it chases during a hunt."

## Latency Budget

STT ~300ms (CPU) + engine ~10ms + TTS ~200ms + radio FX ~10ms = ~520ms total.
Target: < 1 second end-to-end.

## Feasibility Notes

- **faster-whisper on Windows:** CPU-only works. No FFmpeg needed (uses PyAV). CUDA optional.
- **Kokoro on Windows:** Supports DirectML. CPU near real-time for short utterances.
- **Audio coexistence:** Oracle uses system default output. Separate routing (VB-Cable) is future work.

## Success Criteria

1. "Oracle, confirm EMF 5" → radio-voiced response in < 1 second
2. Wake word detection works while Phasmo is running
3. Text fallback (`--text`) still works without audio dependencies
4. Kayden can install and run within 15 minutes
