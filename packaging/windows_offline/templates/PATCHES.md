# Bundle-only dependency patch

## Faster-Whisper 1.2.1: optional PyAV path

The application passes an in-memory `numpy.ndarray` to
`WhisperModel.transcribe`; it does not ask Faster-Whisper to decode an audio
path or file object. Upstream `faster_whisper.audio` nevertheless imports PyAV
at module import time.

This bundle deliberately excludes PyAV and applies a narrow source patch after
installing the official Faster-Whisper 1.2.1 wheel:

- remove the top-level `import av`;
- import `av` inside `decode_audio` before the first PyAV use;
- import `av` inside the two private frame helpers that reference it.

The package therefore supports the Agent's in-memory PCM/NumPy path only.
Direct file/path decoding through `faster_whisper.decode_audio` requires PyAV
and is outside the offline bundle contract. `MANIFEST.json` records the hash of
the patched file. Import and NumPy-entry validation is not evidence of a real
model transcription; the latter is recorded separately by the smoke test.

