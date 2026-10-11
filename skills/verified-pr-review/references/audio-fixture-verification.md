# Audio fixture verification

## 1. Establish the fixture contract

Read the task's language, duration, format, source/permission and transcript requirements. Fetch the exact PR head and extract its binary files into an isolated snapshot. Inspect every changed file, including the accompanying transcript and source declaration. Keep fixture preparation separate from downstream real-model transcription acceptance.

## 2. Decode bytes, not just metadata

For PCM WAV, use Python's `wave.open` to read all declared frames. Record `getnchannels()`, `getframerate()`, `getsampwidth()`, `getnframes()` and the actual decoded byte count. Compute duration as frames/sample rate and check payload length against frames × channels × sample width. For signed 16-bit PCM, decode with explicit little-endian interpretation and compute peak, RMS and nonzero sample count. These checks distinguish real PCM payload from empty or all-zero fixtures; they do not establish intelligible speech.

Independently decode the entire file with:

```sh
ffmpeg -v error -i <fixture.wav> -f null -
```

Require successful exit and inspect decoder errors. Compare measured format and duration against the documented values using the stated rounding precision. Use `hashlib.sha256` when a reproducible content identifier is useful; file existence or a plausible extension is not decoding evidence.

## 3. Evaluate content and provenance separately

Treat a submitter's self-recording and permission declaration as attributed provenance evidence, not a fact independently established by waveform statistics. Review the written transcript for suitability and sensitive content. For language-specific usable speech samples with a verbatim transcript requirement, treat intelligibility, language and material transcript agreement as required content checks, not optional merely because the acceptance text does not separately say “listen.” Obtain actual listening or suitable recognition evidence and review meaningful discrepancies; ASR output alone is fallible and does not establish provenance. If the reviewer cannot obtain necessary content evidence, classify acceptance as unverified and the review as INCOMPLETE rather than approving or closing solely from decode/RMS results. If the task explicitly requires only encoding fixtures, state that narrower contract and mark speech-content checks not applicable. Do not upload recordings to an external recognizer without appropriate authorization.

Do not claim that sample delivery proves recognition accuracy, timestamp alignment or cross-platform capture. RMS and nonzero counts prove signal presence only. Distinguish generated test signals, synthetic speech and human-recording declarations rather than silently substituting one for another.

## 4. Publish proportionate evidence

For binary/document-only changes, prioritize actual decode and contract checks over unrelated build repetition. Still check the exact head's CI and inspect all changes before approval. Report a compact table of measured duration, format and decode result, followed by provenance/content and platform limitations. Publish the formal verdict and merge only through the umbrella review gates; close linked acceptance work only when its own complete criteria are supported.
