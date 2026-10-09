## 0. Quick start: running the pipeline on a new race collection

The analysis stages are scripted, cached and safe to re-run. Everything is local; nothing is uploaded.

```bash
scripts/setup_env.sh --fetch-models          # once per machine: virtual environment, pinned packages, models (about 6 GB)
./strata360 doctor                           # checks the environment and says how to fix anything missing
./strata360 init belgium-2026 --library "/path/to/card/or/folder" \
      --languages en,fr,nl,de --clock-offset-hours 1      # one race = one folder of camera files
./strata360 run belgium-2026                 # ingest, audio, transcribe, align, exposure
./strata360 status belgium-2026              # per clip and stage: ok / FAIL / stale / -
./strata360 report belgium-2026              # race summary (report.md and report.json)
```

- **What `run` does, per clip** (each stage writes one JSON file into `races/<race>/clips/<clip>/`): `ingest` (`clip.json`: facts and the definitive UTC time), `audio` (`audio.json`: loudness, clipping, wind/speech/crowd labels), `transcribe` (`transcript.json`: multilingual speech, per-segment language, English translation, hallucination flags), `align` (`alignment.json`: accurate word times and safe cut points), `exposure` (`exposure.json`: brightness every N frames for a later auto-gain). `proxy` (the upright analysis proxy video) is opt-in: `./strata360 run belgium-2026 --stages proxy`.
- **Caching and safety.** A stage is skipped when nothing it depends on has changed (the clip's content, the stage's code version, the config keys it uses, and upstream results). Change a setting in `races/<race>/race.json` and only the stages that use it re-run; `--force` re-runs everything; `--clips PATTERN` selects clips; a failure in one clip does not stop the others (`status --errors` shows why); artefacts are written atomically; only one run per race at a time.
- **Set the camera clock.** Absolute times come from the camera's clock, which has no GPS to check it. Give `--clock-offset-hours` (how far the camera clock is from UTC; 1 if it shows Belgian winter local time) and add `--clock-verified` only after checking against the GPX or a known event. Until then every clip's start time is reported `provisional`.
- **Other cameras.** Discovery reports files it cannot process (Insta360 `.insv`, flat MP4 exports) instead of ignoring them; an Insta360 adapter is future work (section 14).
- **Platforms.** macOS (Apple Silicon, the development machine) and Linux are tested in CI; Windows unit tests run in CI but are not blocking yet, and the bash launcher `./strata360` and `scripts/setup_env.sh` are POSIX-only (use `python -m strata360`). Hardware video options are chosen per OS in `src/strata360/hw.py`: VideoToolbox decode and encode on macOS, NVENC on Windows when ffmpeg has it, and software libx264/libx265 with software decode elsewhere (slower, same results). Override with `STRATA_HWACCEL=none|<name>` and `STRATA_ENCODER=software`; `STRATA_GPU=1` lets the person detector use Apple's GPU or CUDA. `./strata360 doctor` reports what was detected.
- **Data and privacy.** `races/` is gitignored: transcripts contain other people's speech. The DJI factory lens calibration comes from the OSV files themselves, and the IMU offsets are a fitted constant (progress.md).
- **Rendering** is not part of `run`, except the opt-in `proxy` stage: the film preview and final render are made from the app or `./strata360 film PROJECT` / `./strata360 final PROJECT` (18.4o); a single clip: `./strata360 render CAM.OSV out.mp4 --mode heading --fov 90 ...` (arguments as for the flat renderer, 14.2) or `--path camera.json`. The lenses are joined with a carved seam and a parallax warp by default (14.1).
- **Tests:** `pip install -r requirements-test.txt`, then `pytest tests/unit --cov` (about 15 s) and `pytest tests/integration` (needs ffmpeg with libx265; builds a synthetic clip, about 2 min). Web: `cd web && npm run test:coverage`. By hand with real footage and models: `.venv/bin/python spike/test_audio.py`, `spike/test_camera.py`, `spike/test_render_smoke.py`. See AGENTS.md.

---
