## 8. Cross-cutting concerns

### 8.1 Configuration
- Layered: defaults → user config → per-race config → CLI flags. Each run records the effective config in its output (for reproducibility).
- Key settings: race timezone, cameras and lens parameters, output resolution/fps/aspect, target duration, role duration bounds, sampling intervals, LLM model choices and budgets, music path, beat tolerance, speed-adjust on/off, chronological order on/off, privacy (face blur) on/off.

### 8.2 Coordinate and orientation conventions (document precisely and test)
- Equirectangular: yaw ∈ [-180°, 180°), 0° = camera front (define which lens, and verify on DJI and Insta360), positive to the right. Pitch ∈ [-90°, 90°], positive up. Roll positive clockwise. All modules use these; convert at the adapter boundary only.
- The seam sits at yaw ±180° (behind the camera). Every angle calculation must handle wraparound. This is the source of many bugs, hence the explicit seam tests above.

### 8.3 Caching and idempotence
- Cache key = hash(input content hash + phase version + relevant config subset). Store artefacts with a manifest listing their inputs. `--force` for a phase invalidates its dependants only.
- All writes atomic (temp + rename).

### 8.4 LLM usage
- Model choice per task: a cheaper model for per-frame captions, a stronger one for candidate ranking and master review. Configurable, with pinned model IDs.
- **Structured output only**, validated against schemas, with retries and a deterministic fallback.
- Prompts versioned in the repo. Every call logs its prompt hash, model, tokens, cost, and cached response ID.
- Treat all transcript and OCR text as untrusted data (prompt-injection defence): clearly delimited, never treated as instructions.
- Cost tracking and per-race budget caps (§P2-11). **Implemented so far:** every Gemini call is logged with its model, key tier and token counts in `<project>/gemini_usage.jsonl`, and the transcript panel shows the paid-key spend (`analysis/transcript_fix.usage_summary`, list prices in `PRICES`); there is no budget cap yet.
- **Gemini keys** (`secrets.env`, never committed; `edit/llm_remote.py`): `GEMINI_API_KEY` (free tier) is tried first for Flash and transcription models; on a rate limit (429) the call falls back to `GEMINI_PAID_API_KEY`, which alone serves Pro. `VERTEX_API_KEY` is the older Google Cloud route. The voice-over script writer uses Gemini Pro (`llm` in `race.json`); the audio check of the transcript uses Pro too (18.4p).
- Recorded-response fixtures for tests.

### 8.5 Performance and storage (rough)
- Hardware encode of an 8K HEVC master is roughly real-time or faster on recent Apple Silicon; plan for it to be the slowest step. Two hours of footage is therefore a few hours of compute, run overnight.
- Storage per race: raw (tens of GB) + master (comparable or larger; budget it) + proxies (small). Preflight disk checks, and an option to delete masters after the final render.
- Analysis on the proxy is light on CPU. The vision-model cost is the main variable cost, so cache aggressively.

### 8.6 Privacy and safety
- Other runners and spectators appear in the footage. Provide an optional face-blur step, and never upload full-resolution video to any service. Only stills from proxies are sent to the LLM. Document what leaves the machine.
- The GPX and the camera location data are personal. Keep them local.
- **Biometrics stay local.** Face recognition of the user (and re-identification embeddings) runs entirely on the machine. Identity profiles, embeddings and face crops are never sent to an LLM or any external service and are stored under the race/identity working directory only. Stills sent to a vision model for captioning can optionally have faces of non-enrolled people blurred first (config, default on), and the model is never asked to identify anyone. The identity profile can be deleted with one command, which also invalidates the identity-dependent caches.

### 8.7 Logging, observability, and review
- Structured logs per clip and phase. A per-race HTML or Markdown report: the clip table, the analysis highlights, chosen versus rejected candidates, warnings (clock uncertainty, obstruction, LLM fallbacks), and cost.

### 8.11 Environment and installed tools
- **Python:** the project uses two virtual environments (both gitignored). `.venv` (Python 3.13, `--system-site-packages`): numpy 2.2.6 **from the OpenBLAS wheel** (`macosx_11_0_arm64`), because the default numpy on this Mac uses Accelerate's BLAS, which raised warnings and could return bad values from `matmul`; faster-whisper 1.2.1, deepfilternet 0.5.6 (with torchaudio 2.9.1, and one local patch in `df/io.py` replacing a removed torchaudio import with a stub), transformers with sentencepiece and sacremoses (OPUS-MT translation). `.venv-cv`: an isolated environment for ClearerVoice-Studio (MossFormer2), which pins numpy 1.x and an old OpenCV.
- **Models (downloaded on first use, cached under `~/.cache/huggingface` and `~/Library/Caches/DeepFilterNet`, about 6 GB):** whisper small and large-v3-turbo, OPUS-MT fr/nl/de to English, MossFormer2_SE_48K, DeepFilterNet3 (bundled with its package).
- **System:** ffmpeg 9.0.2, exiftool 13.55 (Homebrew). No models or data leave the machine.
- **Reproducing:** `scripts/setup_env.sh [--with-cv] [--no-dfn] [--fetch-models]` builds the environment from scratch from `requirements.txt` (pinned), installs numpy's OpenBLAS wheel, installs and patches DeepFilterNet, and runs `strata360 doctor`. Verified on a clean scratch environment (all checks pass). `strata360 doctor` reports anything missing and how to fix it; `strata360 fetch-models` pre-downloads the models.

### 8.10 Quality-preservation policy (the source is soft; lose nothing after it)
The DJI footage is already limited (about 21 px/° and heavily compressed at about 83 Mbit/s per lens), so everything after the source must add as little loss as possible. Rules, in priority order:
1. **One resample from the source to the output.** Flat views are rendered straight from the two fisheye frames (no equirect stage), through 16-bit precision, in linear light, with the BT.709 matrix and tags correct (§8.9).
2. **The full-resolution lens streams are the only source of detail.** Any task that needs fine detail (face recognition, bib and kit reading, the framing solve's quality checks) renders a crop straight from them. Proxies and stills are for locating things, not for reading them.
3. **Final and per-segment outputs use very high quality HEVC.** Measured on a rendered 4K view (24 frames): VideoToolbox at about 100 Mbit/s keeps 94% of the detail (SSIM 0.976), at about 190 Mbit/s 96% (0.989), at about 360 Mbit/s 97% (0.995, effectively transparent); software x265 gives no better quality per bit on this smooth, upsampled material (crf 22 ≈ 100 Mbit/s: 0.975) and is 10× slower. **Default: hardware HEVC Main 10 at 200 Mbit/s, with a 350 Mbit/s "archive" preset**, because the overlay tool re-encodes these files and any loss compounds. These sizes are affordable because only the selected shots are rendered (a 5-minute film at 200 Mbit/s is about 7.5 GB).
4. **The analysis proxy is high bitrate too** (see Phase 1): on detail-dense 3840×1920 material a typical hardware-encoder bitrate loses most of the fine detail (34 Mbit/s keeps 42%, 78 Mbit/s 62%, 145 Mbit/s 76%; x265 CRF 24 at 97 Mbit/s keeps 77%, CRF 20 at 168 Mbit/s keeps 86%, individual JPEG q90 frames keep 100% at 2.5 MB per frame). This is a further reason recognition is done from source crops.
5. **Resampling kernel:** bicubic by default for speed. Lanczos (5× slower on the remap) is a per-render quality option for finals; compare on the sample before enabling.
6. **Decode without extra loss:** the HEVC source decodes bit-exactly on hardware or software; the 4:2:0 to RGB conversion uses the accurate, full-chroma path. No denoising or sharpening is applied unless it is explicitly chosen and shown to help.
7. **Recompression budget:** source → (single encode) final → overlay tool's encode. Nothing else may re-encode video between them; proxies are never used as a source for outputs.

### 8.9 Colour policy (SDR output, HDR/log handling in between)
- **The final output is SDR, Rec.709**, tagged explicitly (primaries, transfer, matrix, range).
- The camera can record Normal (already tone-mapped 10-bit), D-Log M (flat log) or HLG. The clip header records the mode (`StreamMeta.4`: 0 Normal, 19 D-Log M, 9 HLG). Phase 0 reads it into `clip.json` (`colour_mode`). The sample is Normal, so the log path is untested until a D-Log M sample is available.
- **What HDR/log buys us is a better tone map, not an HDR deliverable:** log/HLG footage keeps more highlight and shadow detail (bright sky through trees against dark forest is the typical case), so it gives a cleaner SDR result than Normal mode's baked-in curve. The pipeline therefore: keeps masters in the camera's own encoding (no premature grading, tagged correctly), blends the two lenses and reframes in **linear light** with at least 16-bit precision, then applies **one** conversion to Rec.709 per shot in Phase 7, with per-shot exposure and tone-map adjustment (so consecutive clips look consistent, an automatic-exposure-matching step) and a gentle highlight roll-off.
- Analysis (Phase 2/4) runs on an SDR-tone-mapped proxy, so vision models see normal-looking images.
- Reference implementation to compare against: OpenOSV's D-Log M to Rec.709 pipeline (matches DJI Studio's look, dE2000 ≤ 0.5 as they report). We may reuse its published transfer curves and LUTs (`luts/` in the repo, Apache-2.0) instead of deriving our own.
- Tests: a synthetic log ramp converts to the expected Rec.709 values within tolerance; a Normal-mode clip passes through unchanged apart from tagging; exposure matching brings two clips of the same scene at different exposures to within a set difference; final files carry the correct colour tags (ffprobe).

### 8.8 Codec and container policy
- **Everything is MP4 with H.265/HEVC video** (tag `hvc1` so Apple software plays it) and AAC audio: equirect masters (Main 10, 10-bit), analysis proxies (Main, 8-bit), per-segment intermediates and outputs, and the final film. The only non-HEVC video is the camera's original files (the DJI `.LRF` is H.264 and is read, not written).
- **Quality first for outputs.** The segment MP4s and the final film feed a further composite-and-encode step (the map overlay), so they are written at a high, near-transparent quality (10-bit Main 10, hardware HEVC at 200 Mbit/s by default and 350 Mbit/s for archive, measured in §8.10) to limit generation loss. File size is a lesser concern than fidelity for these files; the overlay tool makes the final delivery encode.
- Hardware (VideoToolbox) is the default encoder, with software x265 as the quality option. Quality is set by a constant-quality or bitrate target per artefact class in config, not hard-coded.
- Constant frame rate output. Preserve BT.709 for SDR and tag the streams explicitly (no reliance on player defaults).
- Chained encodes lose quality, so segments are rendered once from the master (never re-encoded from an earlier output). The final film is made by concatenating same-parameter segment files without re-encoding where possible, and re-encoded only when transitions require it.

---
