# Whisper through strata-models (9 Nov 2026)

On omarchy one service, strata-models, now owns the RTX 3060 for model work and serves every app from one queue. strata-360 had been CPU-only there (`STRATA_GPU=0`, set for the old 2 GB GTX 1050). Speech and lyrics now ask it for Whisper.

- `audio/remote_whisper.py`: `whisper_model(name)` returns a stand-in for faster_whisper.WhisperModel (`transcribe`, `detect_language`, with the same return shapes) when the service is running and knows the model (large-v3, large-v3-turbo, small). Otherwise it loads faster-whisper here as before. `STRATA360_MODELS=local` forces the local model, and the test suite sets it.
- `speech.load_models` and `lyrics._transcribe` use it. The speech stage itself is unchanged: language per VAD chunk among the expected few, then the chunk transcribed in that language. An array chunk is written to a 16 kHz WAV in `/dev/shm` for the service to read.
- On omarchy, the JFK sample through `transcribe_multilingual` with large-v3 on the service took 5.6 s, including the first load of the model. The text matches the local model's.
- Still loaded here: the translation (OPUS-MT), word alignment (wav2vec2), faces and YOLO in the analysis scripts, AST, ECAPA, TIGER, the VLM. The strata-models registry lists them as "not served yet".
