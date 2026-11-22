# Whisper through strata-models (9 Nov 2026)

On omarchy one service, strata-models, now owns the RTX 3060 for model work and serves every app from one queue. strata-360 had been CPU-only there (`STRATA_GPU=0`, set for the old 2 GB GTX 1050). Speech and lyrics now ask it for Whisper.

- `audio/remote_whisper.py`: `whisper_model(name)` returns a stand-in for faster_whisper.WhisperModel (`transcribe`, `detect_language`, with the same return shapes) when the service is running and knows the model (large-v3, large-v3-turbo, small). Otherwise it loads faster-whisper here as before. `STRATA360_MODELS=local` forces the local model, and the test suite sets it.
- `speech.load_models` and `lyrics._transcribe` use it. The speech stage itself is unchanged: language per VAD chunk among the expected few, then the chunk transcribed in that language. An array chunk is written to a 16 kHz WAV in `/dev/shm` for the service to read.
- On omarchy, the JFK sample through `transcribe_multilingual` with large-v3 on the service took 5.6 s, including the first load of the model. The text matches the local model's.
- Still loaded here: the translation (OPUS-MT), word alignment (wav2vec2), faces and YOLO in the analysis scripts, AST, ECAPA, TIGER, the VLM. The strata-models registry lists them as "not served yet".

## The voice-over through strata-models (9 Nov)
- `edit/voiceover.py` has a third engine, `strata-models`, listed first: the service's `speak` role. Voice `chosen` asks for whatever its eval
  (`speak-narration`: Kokoro voices, Chatterbox and Qwen3-TTS cloning the runner's own voice, Qwen3-TTS voice design, judged blind against
  Kokoro bm_lewis on 40 Legends narration lines) put on the role; the Kokoro British male voices are offered by name too (the service's copy of
  the same model). The rate becomes `speed` as before.
- A line's cache key includes the model serving `speak` (`voice_id`), asked at most once a minute: when the eval changes the role, lines are
  spoken again instead of reusing the old voice.
- Used when the service runs and serves `speak` and STRATA360_MODELS is not `local`; else Kokoro here as before (on omarchy Kokoro was
  never installed, so the service is the voice there). Saved state `engine = kokoro` still picks local Kokoro where it is installed.
- Tests: tests/unit/test_voiceover_service.py (fake client).
- (12 Nov) The rate goes to the service as `wpm` (strata-models #37). The service measures pace in syllables and makes every line land on
  it, and it cuts pauses between words to 0.45 s, so synthetic lines no longer vary in pace from line to line. Before, cloned voices ranged
  from half to double speed on short lines.
