# strata-360: Automated 360° Race Video Editing Pipeline

Turn dozens of short 360° clips shot during an ultramarathon (DJI 360 today, Insta360 for older races) into a single edited highlight film. The film is reframed to flat video, trimmed, optionally beat-synced to music, and stays time-aligned with the race GPX so an existing moving-map renderer can overlay it.

This document is the developer brief: goals, architecture, data contracts, phase-by-phase requirements, and a test plan for each phase. `progress.md` is the running log of what was tried and learned.

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
- **Data and privacy.** `races/` is gitignored: transcripts contain other people's speech. The DJI factory lens calibration comes from the OSV files themselves, and the IMU offsets are a fitted constant (progress.md).
- **Rendering** is not part of `run` yet: `./strata360 render CAM.OSV out.mp4 --mode heading --fov 90 ...` (arguments as for the flat renderer, README 14.2) or `--path camera.json`.
- **Tests:** `.venv/bin/python tests/test_pipeline.py` (about 30 s; `--slow` adds transcription and alignment), `spike/test_audio.py`, `spike/test_camera.py`, `spike/test_render_smoke.py`.

---

## 1. Goals and non-goals

### Goals
1. **Fully automated export** of raw 360 files (DJI `.OSV`, Insta360 `.INSV`/`.MP4`) into a common, well-understood intermediate format. No manual use of vendor GUIs in the normal path.
2. **Per-clip analysis and rich options, not decisions.** For each clip, produce (a) several ranked candidate time ranges with flexible trim handles and (b) an *attention map*: a description of everything worth looking at on the sphere over time, including where **the user** is. No camera move (zoom, pan, perspective, centring) is chosen at this stage, because the right choice depends on the final length of the shot, its neighbours and the music.
3. **Master assembly.** Given all clips' candidates, a target total duration, and optionally a music track, choose which candidates to use and their exact in/out points. Output one edit decision list (EDL). Then, once each shot's exact length is known, a separate **framing solve** picks the camera moves for it.
4. **Timestamp preservation.** Every second of output video maps back to a known wall-clock UTC time, so the map/GPX overlay can be driven from it.
5. **Optional beat sync.** Cut points and clip lengths flex slightly so cuts land on musical beats.
6. **Human-in-the-loop by default.** Every stage writes inspectable files. The user can override any decision before the final render.

### Non-goals (for now)
- A GUI editor. The interface is CLI, files, and later an MCP server.
- Colour grading, titles, or audio mixing beyond music ducking/normalisation.
- Rendering the GPX map. That already exists. This project only supplies it the timing map (see §9).
- Live/real-time processing.

### Scale assumptions
- 20–100 clips per race, each roughly 5 s to a few minutes (the sample is 4.8 s). Assume total raw footage is under about 2 hours per race.
- The DJI sample is 3840×3840 HEVC 10-bit ×2 lenses at about 50 fps, roughly 170 Mbit/s. A race's raw footage can be tens of GB.
- Output: 4K UHD, at the source frame rate.
- Target hardware: Apple Silicon Mac, Python 3.11+, ffmpeg, exiftool available via Homebrew.

---

## 2. What we know about the input files

Findings from the sample in `videos/`:

| File | Container | Contents |
|---|---|---|
| `CAM_20260221120007_0019_D.OSV` | MP4 | Two HEVC Main10 streams, each 3840×3840, nominally 50 fps (239 frames in 4.82 s, so a couple of frames were dropped; ffprobe's 49.59 is only the average), one per fisheye lens. AAC stereo audio. Two `djmd` metadata tracks, two `dbgi` debug tracks (see metadata findings below). Attached JPEG thumbnail (688×344). |
| `CAM_20260221120007_0019_D.LRF` | MP4 | Low-res proxy: H.264, 2048×1024 showing the **two fisheye circles side by side (dual-fisheye, not stitched)**, about 24.8 fps, with the same audio and `djmd` tracks. About 5% of the OSV's size. |

Implications:
- **The LRF is NOT stitched** (found in M0, see `progress.md`): it is the same dual-fisheye layout at low resolution. So it cannot be used directly as the equirect analysis proxy. It is still a cheap-to-decode reference: our own stitch of the OSV can be compared to it (by rendering our lens model back to the same layout), and it could be stitched with the same lens model as a fast proxy source. Our pipeline generates its own equirect proxy from the master or from the LRF.
- The OSV needs dual-fisheye to equirectangular conversion to produce a high-quality master. The lens model and calibration are the highest technical risk (§13).
- **Frame timing is not perfectly regular.** The sample is nominally 50 fps but has dropped-frame gaps (frame spacing 20 ms, occasionally 60 ms), so the effective rate averages 49.59. The LRF proxy is nominally 25 fps. All time handling must use each frame's real timestamp (rational), never "frame number / nominal fps", and the clip's `fps` field records the nominal rate plus a dropped-frame count.
- The filename and the container `CreateDate` both say 2026-02-21 12:00:07. The file's modification time is 14:00:13 at +02:00, which is 12:00:13 UTC, about 6 s after the 4.8 s clip started. So `CreateDate` and the filename are **UTC**, not local time (verified on one file only; P0-03 must re-check on more clips). See §6.1.
- **Insta360 `.insv`** also uses two fisheye streams, often one file per lens (`_00_` and `_10_`), and carries gyro data in a proprietary trailer. Exact details must be verified on real files during Phase 1. The pipeline treats it as a second "adapter" behind the same interface.

### 2.1 Metadata findings (decoded from the sample, Osmo 360 model OQ001)

The `djmd` tracks are Protocol Buffers (schema name `dvtm_oq101.proto`, version 2.0.8), one packet every 20 ms (50 Hz), so 239 packets for the 4.8 s clip.

| Track | Content found |
|---|---|
| `djmd` track 1 (about 640 B/packet, 50 Hz) | Per-frame exposure (ISO, shutter, colour temperature, gain), a **unit quaternion orientation** at the frame rate, and further blocks holding **several quaternion samples per packet** (a higher-rate orientation series, likely the gyro-fused attitude at the IMU rate) and a 3-vector that is probably acceleration. This is the stabilisation and horizon-lock source. |
| `djmd` track 2 (about 143 B/packet) | The same per-frame exposure block for the second lens, plus device identity (model `Osmo OQ001`, serial, firmware) and a nominal 50 Hz rate. No motion data. |
| `dbgi` tracks (about 4 KB/packet) | Debug info (`dbginfo_oq101.proto`). Not needed. |
| Container tags | `CreateDate`, encoder `Osmo 360`, original SD-card path, thumbnail, and DJI beauty-filter flags (all zero). |

**No GPS was found** in the tracks. A scan for lat/long-range values and location strings found nothing, and the camera has no built-in GPS. The Osmo 360 can only log position when paired with a phone or GPS remote, and the short clips make that unlikely. **The design therefore assumes no GPS and relies on the camera clock** (§6). GPS decoding is kept as an optional adapter hook in case later footage has it.

**Lens calibration is embedded in the file** (found in M0, see `progress.md`): the first `djmd` packet holds 24 lens-parameter slots (focal length, principal point, five Kannala–Brandt distortion terms, extrinsic quaternion), so stitching does not need a hand-fitted lens model. The sample's colour mode is Normal (D-Log M and HLG are also possible and need a colour pipeline). **Prior art:** [OpenOSV](https://github.com/Kemerd/OpenOSV) (Apache-2.0, C++, Metal on Apple Silicon) already decodes this calibration, stitches with optical-flow seams and multi-band blending, stabilises from the gyro and converts D-Log M to Rec.709/PQ/HLG. Its CLI (`osvtool render --mode equirect`) does not support animated reframing, so the plan is to use it (or our own projection from the same calibration) for the stitch/colour/stabilise stage and do the keyframed reframing ourselves.

**Colour (M0):** decode to 16-bit, blend in linear light with the BT.709 transfer, weight lenses with OpenOSV's FOV-feather-times-occlusion rule (render blend inset 2.6°), and encode BT.709 limited-range Main 10 with correct tags. Normal-mode footage is rendered **as recorded** (DJI's own export adds an undocumented scene-adaptive lift, which is not a reference for absolute brightness). The lens-to-lens exposure match from OpenOSV is implemented but off by default because the seam statistics are unreliable on wet-lens, near-object clips. A bug fixed in M0: the first renders used ffmpeg's default BT.601 RGB-to-YUV matrix with no tags, giving colour errors up to ±36 levels in a player. See `progress.md`.

**Stabilisation and renderer validated (M0):** the per-frame attitude quaternion (`FrameMeta.2.9`, fields read as w,x,y,z) plus two constant matrices reproduces DJI's own stabilised export (correlation 0.993–0.998 on held-out frames; DJI applies exactly the raw attitude, so we can choose our own stabilisation policy). A direct fisheye-to-flat renderer (`spike/render4k.py`, one resample per pixel, no equirect stage) renders 4K at about 10–14 fps on an M4 (roughly 3–5× slower than real time). So the equirect master is **not needed for output**: Phase 7 renders straight from the two lens streams, using the calibration and the telemetry. An equirect proxy is still useful for Phase 2/4 analysis.

**Stitch validated (M0):** a stitch built from the embedded calibration alone reproduces DJI's own export (correlation 0.97–0.98 against a raw DJI 360 export). Confirmed conventions: `d_lens = R(q)·d_body` (not transposed); **video stream 0 is the rear lens and stream 1 the front lens**; refined slots (2, 1); standard equirect layout with the front lens at the centre column. Residual differences are seam parallax near close objects (such as the user's hand on the selfie stick) and a small exposure lift. Details in `progress.md`. DJI's own 360 export applies horizon lock (and a raw, unstabilised export is available with rocksteady off), and its file timestamps are the export time, so timing must always come from the OSV.

Still to do in M0: confirm the quaternion frame convention (axes and handedness), the exact units of the accelerometer block, and whether the proxy `.LRF` carries the same orientation data (it has the same tracks at half the packet count, so probably yes). Insta360 files will need the same investigation.

---

## 3. Architecture overview

```
 raw files ──► P0 Ingest/Catalog ──► P1 Normalize (stitch, stabilise, proxy)
                                              │
                                              ▼
                                   P2 Analyse (per clip, cached)
                                              │
                                              ▼
                              P3 Propose candidate ranges (per clip, LLM-assisted)
                                              │
                                              ▼
                              P4 Attention map (per clip: where to look, when,
                                 and where "me" is; options, not paths)
                                              │
        music track ─► P5a Music analysis     │
                                   ▼          ▼
                            P5 Master assembly: choose shots + exact in/out
                                              │        ▲
                                              ▼        │ (re-trim / swap if no good framing)
                            P6 Framing solve: choose zoom/pan/centring per shot
                                              │
                                              ▼
                                  P7 Render (H.265 MP4s + timecode map)
                                              │
                                              ▼
                        P8 Handoff to GPX/map renderer (existing)
```

Principles:
1. **The LLM never edits video. It reads text and stills and emits structured JSON.** Everything else is deterministic code. Results are reproducible, cheap to re-run, and reviewable.
2. **Every phase reads and writes files in a defined schema.** No hidden state. Phases can be re-run individually.
3. **Everything is cached by content hash plus parameters.** Re-running the pipeline after tweaking phase 5 must not redo phase 1.
4. **Two-tier resolution.** Analysis works on a proxy. Only the final render touches full-resolution masters.
5. **Defer decisions; emit options with valid ranges.** Early phases record what is *possible* (time ranges with handles, look targets with the times they exist), never a single committed choice. Decisions are made as late as the information allows: shot lengths in Phase 5, camera moves in Phase 6.
6. **Time is sacred.** A single canonical timeline (UTC, in rational or nanosecond units) is used everywhere. See §6.

---

## 4. Repository layout

```
strata-360/
  README.md  progress.md  NOTICE  requirements.txt  requirements-cv.txt
  strata360                       # launcher for the CLI (uses .venv, or STRATA_PYTHON)
  scripts/                        # setup_env.sh (build the environment), patch_deepfilternet.py
  src/strata360/
    cli.py                        # init, catalog, run, status, show, report, doctor, fetch-models, render
    pipeline/                     # config.py (race.json), clips.py (discovery), ingest.py, stages.py (stage definitions), runner.py (caching, state, locking)
    osv/                          # pbdump.py (protobuf reader), calib.py (lens calibration), telemetry.py, meta.py (device, colour mode), mp4.py (fast index reader), data/ (IMU offsets)
    render/                       # flat.py (fisheye -> 4K flat renderer), camera.py (paths, heading-follow), photo.py (linear-light blend, weights), proxy.py (upright proxy)
    analysis/                     # exposure.py
    audio/                        # dsp.py (analysis, chains, mix planner), speech.py (multilingual transcription, translation), wordtimes.py (forced alignment, cut points), align.py (alignment stage with gate)
  tests/                          # test_pipeline.py (end-to-end on the sample)
  spike/                          # early experiments and studies (asr_eval, encoder_study, proxy_study, ...), tests (test_audio, test_camera, test_render_smoke, test_wordtimes), and thin shims for the moved modules
  races/<race-name>/              # working data per race (gitignored)
    race.json  catalog.json  report.json  report.md  run.log
    clips/<clip-id>/  clip.json  audio.json  transcript.json  alignment.json  exposure.json  [proxy.mp4  proxy.json]  stages.json
```

Working data lives under `races/<race-name>/`. The layout is fixed so every tool can find every artefact. Planned modules not yet written (attention map, proposals, framing solve, assembly, music, handoff, MCP) keep the names in the phase descriptions (section 7).

---

## 5. Data contracts

Schemas are versioned (`schema_version` field). Store as JSON, one file per clip per phase, so any stage can be re-run per clip. Validate on read and write with a schema library (e.g. pydantic). Fail loudly on unknown versions.

### 5.1 Clip manifest (P0/P1 output), `clip.json`
| Field | Meaning |
|---|---|
| `clip_id` | Stable ID derived from camera, original filename, and a short content hash. |
| `source_files` | List of original paths (one OSV, or a pair of INSV files) plus their hashes. |
| `camera_model` | `dji_360` or `insta360_*`. Selects the adapter. |
| `duration_s`, `fps` | Fps as a rational number (e.g. 50000/1008). |
| `start_utc` | **The definitive UTC start of this clip**: ISO 8601, UTC (`Z`), with fractional seconds, after all overrides and offsets are applied. The single source of truth for time in the whole pipeline (see the rule below). |
| `end_utc` | `start_utc` plus the exact clip duration. Stored so nobody has to recompute it. |
| `utc_status` | `definitive` (checks passed or the user confirmed) or `provisional` (a check warned, e.g. container and filename disagree). Downstream phases run on provisional clips but the map handoff refuses to finalise until every clip is `definitive` or explicitly accepted. |
| `start_utc_source` | One of `container_metadata`, `filename`, `manual`, `anchor_interpolated`, or (optional, if a camera ever has it) `gps_track`. |
| `start_utc_uncertainty_s` | Estimated error bound. |
| `clock_offset_applied_s` | Correction from the optional clock check (§6.2). Zero by default. |
| `master_path`, `proxy_path` | Paths to normalised equirectangular master and analysis proxy. |
| `telemetry_path` | Extracted orientation/accelerometer sidecar (normalised format; GPS only if present). |
| `audio_path` | Extracted audio for analysis and mixing. |
| `orientation_convention` | How yaw 0 relates to the camera front (see §8.2). |

**The definitive-UTC rule.** `clip.json` is written once per clip in Phase 0 (and rewritten only by a Phase 0 re-run, an override, or a config offset change). It is the *only* place time is decided. Every other per-clip JSON (`analysis.json`, `attention.json`, `proposals.json`, framing plan, segment sidecars) stores **clip-relative seconds** for all times, and carries a read-only header copy of `clip_id`, `start_utc` and a `utc_hash` (hash of `start_utc`, offset and `end_utc`). On load, each phase compares the header with `clip.json` and fails loudly on a mismatch, and if `start_utc` changes, downstream caches are invalidated automatically. Absolute UTC for any moment is always `start_utc + relative_seconds`. This keeps one definition of time and makes stale files detectable.

### 5.2 Analysis bundle (P2 output), `analysis.json` plus sidecar files
Time-series stored as compact arrays with a shared time base, not per-frame objects:
- `shots`: list of {start_s, end_s, type: hard_cut | camera_stationary | continuous}.
- `speech`: transcript segments with word timestamps and confidence.
- `audio_energy`: loudness per 0.25 s, plus flags for wind noise, cheering, and music-in-background.
- `motion_energy`: optical-flow magnitude per 0.25 s, split into camera-ego-motion and scene motion.
- `keyframe_captions`: for each sampled time, a text caption and tags from the vision model, plus the views it was based on.
- `subjects`: tracked entities (people, faces, aid station signs, bibs, vehicles) with tracks of (t, yaw, pitch, size, confidence).
- `quality`: per-interval flags such as lens obscured, over/under-exposed, blur, shaky, horizon tilted, nadir/tripod visible.
- `telemetry_summary`: speed, heading changes, jumps/impacts, from the orientation/accelerometer sidecar.

### 5.3 Candidate proposal (P3/P4 output), `proposals.json`
One file per clip. Each clip carries an ordered list of candidates, each with:

| Field | Meaning |
|---|---|
| `candidate_id` | Unique within clip. |
| `core_in_s`, `core_out_s` | The essential moment, always kept. |
| `min_in_s`, `max_out_s` | Extra footage available around the core that may be added if the master needs longer (the "handles"). Must respect quality flags and shot boundaries. |
| `ideal_duration_s`, `min_duration_s`, `max_duration_s` | Preferred, floor, and ceiling lengths. |
| `score` | 0–1 overall interest score, with a `score_breakdown` (visual, speech, energy, novelty, story). |
| `role` | `establishing`, `action`, `emotional`, `scenery`, `aid_station`, `finish`, `filler`, etc. |
| `description` | One-sentence human-readable summary (for review and for the master LLM step). |
| `reasons` | Why it was chosen and known weaknesses. |
| `attention_ref` | Pointer to this clip's attention map (§5.4). The candidate carries **no** camera path. Framing is chosen after the final trim (Phase 6). |
| `protagonist_coverage` | Fraction of the core range in which "me" is identified in view (see Phase 2/4), used for scoring. |
| `cut_points` | Allowed in and out points inside the handle range, ranked by cut quality (e.g. pause in speech, step between frames, no mid-word). Beat matching picks from these. |
| `speed` | Allowed speed range (default 1.0 only; opt-in up to 1.25× for beat matching). |
| `audio_policy` | `keep_natural`, `duck_under_music`, or `mute`. |
| `mutually_exclusive_with` | Other candidates from the same clip that overlap, so the master cannot pick both. |

### 5.4 Attention map (Phase 4 output), `attention.json` plus a compact array sidecar
The rich, decision-free description of a clip's sphere over time. Heavy series live in a binary sidecar (e.g. NumPy `.npz` or Parquet) referenced from the JSON, so the JSON stays readable and small.

| Part | Content |
|---|---|
| `time_grid` | Sample times (default 4 Hz for maps, the analysis rate for tracks). |
| `targets[]` | Tracked things worth looking at. Each has `target_id`, `type` (`protagonist`, `other_person`, `group`, `face`, `sign`, `vehicle`, `landmark`, `view`, `path_ahead`, `sound_source`), a `label` and one-line description, `identity` (`me`, `known:<name>`, `unknown`), identity confidence, and per-time samples: yaw, pitch, angular width and height (the target's extent in degrees), detection confidence, salience (0–1), and flags (in seam zone, occluded, obstructed lens, at the edge of the sharp region). Also its `alive` intervals, so a solver knows when it exists. |
| `salience_field` | A coarse equirect heat map per time slice (e.g. 36×18 cells at 2 Hz) combining motion, people, faces, vision-model interest, and sky/scenery. Lets the solver evaluate any candidate camera path, including ones we did not foresee. |
| `reference_directions` | Direction of travel (heading) over time, gravity/horizon, the wearer's own bearing, and the camera-mount type if detected. |
| `look_options[]` | A menu of framing *intents*, each valid over a time window. Fields: `option_id`, `kind` (`follow_target`, `hold_direction`, `forward_look`, `reveal_pan` from target A to B, `pull_back_wide`, `look_back`, `two_shot`), referenced `target_ids`, `valid_from_s`, `valid_to_s` (any sub-window at least `min_useful_s` long is valid), suggested zoom range (tight, medium, wide, as FOV bounds), movement limits, score, a one-line reason, and `compatible_with` (e.g. keeps speech source in view). Options describe intent and constraints, **not keyframes**. |
| `defaults` | Always-present fallbacks covering the whole clip: `forward_wide` and `best_salience_medium`, so the solver never has nothing to choose from. |
| `quality_zones` | Directions and time intervals to avoid (stitch seam, obstruction, wearer's body or pole, over-exposure). |

### 5.4a Framing plan (Phase 6 output), `framing/<edl_id>.json`
Per EDL segment: chosen `option_id` (or a composed sequence of options), dense camera keyframes over the segment's *final* in/out (time, yaw, pitch, roll ≈ 0 after horizon lock, fov, easing), the aspect (16:9), the followed `target_id`, the reason, a framing quality score, and two or three ranked **alternative framings** for quick swapping. Paths obey angular velocity and acceleration limits (see Phase 6).

### 5.4b Camera path file (implemented in `spike/camera.py`; what the renderer accepts)
```
{"ref": "world" | "heading" | "body",
 "smooth_s": 0.0,
 "heading": {"axis_body": [0, 1, 0], "tau_s": 2.0, "min_horizontal": 0.25},
 "keyframes": [{"t": 0.0, "yaw": -20, "pitch": 5, "roll": 0, "fov": 100, "ease": "spline"}, ...]}
```
`t` is clip-relative seconds; angles in degrees; `ease` per segment: `spline` (default), `smooth`, `linear`. Reference frames: `world` = the upright stabilised frame (yaw 0 = the DJI upright datum), `heading` = world plus the runner's smoothed heading, `body` = fixed in the camera body (yaw 180 = the user on a selfie stick, horizon still levelled by gravity). The Phase 6 framing plan (§5.4a) is expressed in this same form (dense keyframes over a segment's final in/out), so a solver output can be rendered directly.

### 5.5 Music analysis, `music.json`
Track duration, tempo estimate and its stability, beat times, downbeat times, bar starts, section boundaries (intro/verse/chorus/drop), energy curve, and confidence per beat. Variable-tempo tracks are flagged.

### 5.6 Master EDL, `edl.json`
| Field | Meaning |
|---|---|
| `edl_id`, `inputs_hash` | For reproducibility. |
| `stage` | `timed` (after Phase 5) or `framed` (after Phase 6). A `timed` EDL is complete enough for the timemap and the map handoff; framing does not change times. |
| `target_duration_s`, `actual_duration_s` | |
| `segments[]` | Ordered list. Each segment has `clip_id`, `candidate_id`, `src_in_s`, `src_out_s`, `speed`, `framing_ref` (filled after Phase 6; absent in a time-only EDL), `transition` (cut, dip, crossfade, with duration), and `out_start_s` on the output timeline. |
| `music` | Track path, offset, gain, ducking settings. |
| `output` | Resolution, fps, aspect, codec settings (see the codec policy in §8.8). |
| `explanations` | Per-segment reason for selection (surfaced in review). |

### 5.7 Timecode map (P7 output), `timemap.json` (also a CSV variant)
The bridge to the map renderer. See §9.

### 5.8 Per-segment output JSON, `out/segments/NNN_<clip_id>.json`
One file beside every rendered segment MP4 (`NNN_<clip_id>.mp4`), the definitive record of that output clip's time:

| Field | Meaning |
|---|---|
| `segment_index`, `clip_id`, `candidate_id` | Identity and order in the film. |
| `utc_start`, `utc_end` | **Exact definitive UTC** of the first and last frame of the footage in this file (fractional seconds), computed as `clip.start_utc + src_in_s` and `+ src_out_s`. |
| `src_in_s`, `src_out_s`, `duration_s`, `speed` | Trim in clip-relative seconds. Speed is 1.0 unless the user opted in. |
| `mp4_creation_time` | The value written into the file's `creation_time` tag (whole seconds, rounded), and `creation_time_error_s` = difference from `utc_start`, so any rounding is explicit. |
| `fps`, `frame_count`, `first_frame_utc`, `last_frame_utc` | Exact frame timing. |
| `clip_utc_hash`, `utc_status`, `utc_source` | Copies from `clip.json` for traceability. |
| `framing_ref`, `edl_id` | Which plan produced it. |

The map handoff (Phase 8) reads these files, so it never has to infer time from filenames. A combined `film.json` lists all the segments in order.

### 5.9 Per-clip exposure export, `exposure.json` (implemented in `spike/exposure_stats.py`)
Written once per clip during analysis (Phase 2, and cheap enough to run at ingest). It records brightness data every N source frames (default 10, i.e. 5 Hz at 50 fps; configurable, 10–20 recommended) so an **auto-gain / exposure-matching step can be added to the final render later without decoding the video again**. All times are clip-relative (`t_s`, `frame` index matching the telemetry rows); UTC comes from `clip.json` (§5.1) and is not duplicated here.

| Field | Meaning |
|---|---|
| `schema_version`, `tool`, `source` | Versioning, the file, camera, colour mode as read from the clip header. |
| `sampling` | Sample interval, sample count, analysis resolutions (lens frames at 960 px, stabilised sphere at 720×360), grid size (24×12 cells of 15°). |
| `frames[].camera` | The camera's own per-lens metadata: `iso`, `shutter_den`, `colour_temp_k`, and `exposure_index_ev` = log2(ISO / shutter denominator). Shows the camera's auto-exposure changes (for example ISO 801 to 1049 with shutter 1/500 to 1/612 in the sample). |
| `frames[].sphere` | Statistics on a low-resolution **stabilised (world-locked), linear-light sphere**, weighted by solid angle and built with the render's lens weights and occlusion mask: `mean_lin`, `mean_lin_rgb`, `mean_luma_code`, luma percentiles p1/5/25/50/75/95/99 in BT.709 code space, `clipped_frac`, `crushed_frac`, `sky_mean_lin` (above the horizon), `ground_mean_lin`, `coverage`, and `grid_mean_lin` (24×12 world-frame brightness map). |
| `frames[].lens` | Mean linear RGB of each lens over its own useful area (θ < 90°, outside the occlusion polygon) and that area's share. Content-dependent (the lens looking at the sky reads brighter), so it is for diagnostics, not a gain estimate. |
| `frames[].naive_gain_to_clip_median` | Informational only: the gain that would bring this sample to the clip median. Not applied anywhere. |
| `summary` | Min / median / max of `mean_lin`, the range in stops, and the range of the camera exposure index. |

How it is meant to be used later: (1) Phase 6/7 estimates the brightness of an actual framing from the world-frame `grid_mean_lin` (average the cells the virtual camera sees), so a shot's exposure can be chosen before rendering; (2) per-shot and per-clip gains are smoothed over time and against neighbouring shots (target: consistent look across the film, with highlight protection using `clipped_frac` and the percentiles); (3) the camera's own exposure changes (`exposure_index_ev`) can be separated from scene changes. The render itself can also emit per-frame statistics of the final framed view (cheap, same definitions), which would refine step 1. Nothing in the renderer applies a gain yet.

### 5.10 Per-clip audio analysis, `audio.json` (implemented in `spike/audio.py`; example `spike/example_audio.json`)
Written once per clip during analysis. All times are clip-relative seconds (UTC from `clip.json`).

| Field | Meaning |
|---|---|
| `summary` | Duration, channels, `dual_mono` (the Osmo 360's stereo is two identical channels, so stereo cues such as wind incoherence are unavailable), BS.1770 integrated loudness (LUFS), loudness range, true peak and sample peak (dBFS), speech-band noise floor, clipped-sample count and the times of clipped windows. |
| `windows` | Arrays at a 0.1 s hop over 0.4 s windows: RMS, peak, momentary LUFS, share of energy below 150 Hz (`lf_share`), speech-band share and level, high-frequency share, spectral flatness, voiced fraction (autocorrelation), median f0, clipped samples. |
| `window_labels` | Per window: `speech` (close, voiced, clearly above the noise floor), `crowd` (energy concentrated in the speech band, not one clean voice), `wind` (energy mostly below 150 Hz), `ambience`, `silence`. Majority-filtered. |
| `segments` | Merged labelled ranges with mean loudness, peak, speech-band SNR, voiced fraction, `excitement_lu` (loudness above the clip median, for crowd and speech), a `clipped` flag and a `use` recommendation (which chain to run). |

The labels are heuristic (no model) and are the hook for stronger classifiers later; thresholds are named constants at the top of `audio.py`. Identification of *whose* voice it is (the wearer) needs speaker embeddings and belongs with the identity profile (§Phase 2, 6a).

### 5.11 Per-clip transcript, `transcript.json` (implemented in `spike/speech.py`)
Multilingual speech recognition with per-segment language identification and English translation. Everything runs locally; nothing is uploaded. Times are clip-relative seconds.

| Field | Meaning |
|---|---|
| `source`, `model`, `denoise`, `languages` | Provenance: the file, the recognition model, which enhancer (if any) preceded recognition, and the languages the identifier may choose from (default English, French, Dutch, German for a race in Belgium; configurable per race). |
| `segments[]` | One per recognised phrase (typically 2–8 s): `t0`, `t1`, `lang` (identified separately for each voice-activity chunk, so a clip can mix languages), `lang_prob` (probability among the allowed languages), `lang_scores`, `whisper_top_lang` (the unrestricted guess, kept to expose misdetections), `text` (native language), `text_en` (English; identical to `text` for English), `avg_logprob`, `no_speech`, and `words[]` with `t0`, `t1` and confidence `p`. |

**Word timestamps: what can and cannot be trusted (measured, `spike/test_wordtimes.py`).** Whisper's own word times are attention-based estimates and are **not usable for edit points**: on words with known true boundaries they are early by a median of 120-190 ms, only 2-8% of boundaries fall within 40 ms of the truth, and 77% of words have exactly zero gap to the next word (each word's end stretches over the following pause; some words come out over a second long). Cut points chosen from them landed *inside a word* 81-97% of the time even at real pauses. The pipeline therefore adds `alignment.json` (stage `align`): CTC forced alignment of the transcript to a wav2vec2 character model (20 ms frames), refined with the speech energy, then a **cut finder** that places the cut inside a run of low speech probability (Silero VAD, 32 ms windows) at the quietest 5 ms of that pause's inner half, snapped to a zero crossing. Measured against known truth: median boundary error 25-50 ms (start) and 27-35 ms (end) instead of 120-190 ms, about 92-96% of boundaries within 100 ms; cuts inside the true pause 100% (clean), 87% (wind, +9 dB), 62% (babble, +3 dB); **no touching word seam was ever flagged safe**, and where the audio is noisy the finder flags fewer cuts as safe (12% in babble) rather than risk clipping a word. A **consistency gate** marks any word whose aligned start differs from whisper's by more than 0.4 s or whose aligner confidence is below 0.25 as `ok: false` and never flags cuts next to it as safe (a real example: the first four words of a segment around a filler "um" came out 500-900 ms early). Only English has an alignment model installed; French, Dutch and German need language-specific models (`wordtimes.LANGUAGE_MODELS`, about 1.2 GB each).

Edit-point policy: cut only at cuts marked `safe`; otherwise keep the word whole and cut at a speech-chunk boundary or in non-speech. For an in-point use the word's `a0` minus about 60 ms and for an out-point `a1` plus about 120 ms (CTC starts are late by about 50 ms and ends early by about 110 ms), and round to video frames (20 ms at 50 fps) only at the end. On the Belgian library 12% of word gaps in the English speech are safe cuts, so most cuts will fall at phrase boundaries.

`alignment.json`: `model`, `method`, `gate`, `summary` (segments, words, words ok, gaps, safe cuts), `segments[]` with `index` (into `transcript.json` segments), `quality` (fraction of words ok), `words[]` (`a0`, `a1`, `score`, `ok`, parallel to the transcript's words) and `cuts[]` (one per gap between consecutive words: `t`, `pause_s`, `safe`).

Design decisions and why:
- **Per-segment language identification, restricted to the plausible languages.** A single language per clip is wrong for mixed-language clips and unreliable for short ones: on the Belgian race library, clip-level detection reported Norwegian, Korean and Dutch for clips with under 15 recognised words.
- **Translation with a dedicated model applied to the native text** (Helsinki-NLP OPUS-MT, French/Dutch/German to English), not whisper's built-in translate task, which summarised and drifted on noisy speech (measured on the sample French clip; see `progress.md`). The native transcript is always kept, because both recognition and translation of noisy multilingual speech are imperfect and a reader should be able to check.
- **Use for editing:** transcript word times give cut points (never mid-word), speech ranges feed candidate scoring (§Phase 3), and `text_en` supports search, captions and the LLM's understanding of what people are saying.
- **Privacy:** other people's speech is transcribed locally and never leaves the machine; whether it is kept, subtitled or discarded is a per-race setting.

---

## 6. Time model and timestamp preservation

This underpins the GPX map overlay, so it gets its own section.

### 6.1 Establishing each clip's absolute start time
**The camera clock is trusted.** There is no GPS in the footage, so there is nothing to sync against per clip. Sources, in priority order (record which one won in `start_utc_source`):
1. Manual override table (CSV), for a clip or a whole camera.
2. Container `CreateDate`, treated as **UTC** (evidence in §2). The config has a `container_time_is_utc` flag, defaulting to true, in case another camera stores local time.
3. Filename timestamp, using the same UTC assumption. Used only if the container time is missing or disagrees with it by more than a second (log a warning).
4. Optional GPS time from telemetry, if a camera ever provides it.

Everything is stored as UTC. The race timezone lives in config only to display local times and to convert the GPX if the GPX is not in UTC.

### 6.2 Clock sanity check (light, optional)
Because the clock is trusted, there is no calibration step in the main path. Provide cheap safeguards instead:
- **Consistency checks:** clips must be time-ordered in the same way as their filename counters; clip start times must fall inside the GPX time range (warn if not); gaps and overlaps between consecutive clips must be plausible for the race (e.g. two clips overlapping in time by more than a second is suspicious).
- **Single global offset:** an optional `camera_clock_offset_s` per camera in config (default 0), for the case where the user notices later that the whole camera clock is off by a constant amount (for example by comparing one clip to a known point on the course).
- **Clock correction feature (`strata360 clock RACE`; `gps/anchors.py`).** Camera clocks that have been offline for a long time are wrong by a constant amount (once corrected, the clock stays in sync through the race; drift support exists but is off unless anchors hours apart disagree). Three ways to set it, all ending in one re-time of every clip (only `ingest` re-runs; nothing else is recomputed):
  1. **`--suggest`:** running starts and stops are found in the GPS/FIT (speed) and in each clip's accelerometer step rhythm (`motion.json` `steps`); every camera event votes for the offset that would match each GPS event of the same kind within 30 minutes; the offsets with the most votes are listed. `--use-suggestion N` applies one.
  2. **`--anchor CLIP:SECONDS`:** what the GUI does when the user selects a clip and clicks the point on its timeline where the running starts (or stops). The click snaps to the nearest detected step event within 8 s; the matching GPS event nearest to the current estimate is used (`--utc ISO` overrides; the result flags an ambiguous match so the GUI can ask). Anchors are stored in `race.json` (`camera_clock.anchors`).
  3. **Manual:** `camera_clock.offset_seconds` (camera minus UTC).
  **Auto-detect on the real library (30 Sep):** matching every running start/stop against the FIT alone is not decisive (the watch has about 1,700 start/stop events over four days and only about a dozen clips contain a transition), and two other cues were tried and rejected (step cadence and camera heading against GPS course: no peak at the true offset). What works is the **mass start**: the earliest clip with a crowd (people stage) in which the wearer sets off and keeps going is paired with the FIT's first running start (the watch was started at the gun). That gave +358 s against the hand-set +370 s: 12 s out, because the camera's "start" is the first shuffle and the watch's is the first speed above 1.2 m/s. So the automatic answer is right to about 15 s and is shown as a suggestion with its confidence; the GUI tweak (an anchor on the exact moment the running starts) finishes it.
  Two or more anchors at least 6 hours apart also fit a steady drift (`drift_s_per_day`), applied by ingest; a single anchor, or anchors close together, give a constant offset. Tests: `tests/test_clock.py`.
- **Verified example (Legends 2026):** the camera clock was 370 s ahead of UTC, found by matching the moment the wearer starts running at the race start (clip accelerometer step energy) with the running onset in the Garmin FIT (`camera_clock.offset_seconds`; progress.md). Daylight (scene brightness vs sun elevation) bounds the offset to about 15 minutes and is a good sanity check; a sudden event gives seconds.
- **Manual anchors (optional):** "this clip, at this moment, was at this GPX time." Two or more anchors allow a linear drift correction. Not automatic, and not needed unless the clock turns out to be wrong.
- The Insta360 clock is separate and must be checked against the same anchors, because older footage may have been recorded with a different offset or timezone.

### 6.3 Preserving time through editing
For every output segment, the render writes a mapping from output time to source UTC:
`utc(out_t) = clip.start_utc + clock_offset + src_in_s + (out_t - out_start_s) × speed`

Rules:
- Speed changes and any freeze frames are represented explicitly. Never approximate.
- Transitions (crossfades) overlap two source times. The map uses the **outgoing clip until the midpoint, then the incoming clip**, and this rule is documented.
- The map is sampled to a fixed grid (e.g. every output frame or every 0.1 s) and also stored as piecewise-linear segments.
- Segments are also emitted in a form that expresses the *non-contiguity*: the race position "jumps" between clips, and the map renderer needs to know when to animate a jump versus a smooth advance (§9).

---

## 7. Phase specifications

Each phase lists purpose, inputs, outputs, behaviour, edge cases, and a test plan. Test IDs are prefixed by phase for traceability.

Testing conventions across all phases:
- **Fixtures:** a small committed set of synthetic and real clips. Include the sample OSV/LRF, and synthetic videos generated with known geometry (e.g. a coloured-grid equirectangular test pattern with a moving marker at a known yaw/pitch) so that framing and stitching can be verified numerically.
- **Golden files:** expected JSON outputs for fixtures, compared with tolerances.
- **LLM calls are mocked** in unit tests using recorded responses. A separate opt-in "live" suite hits the real API with a small budget.
- Long jobs must have a "fast mode" (short clips, low-res) for CI.

---

### Phase 0: Ingest and catalog

**Purpose:** discover files, group them into logical clips, extract metadata, and anchor each clip in absolute time.

**Behaviour**
- Scan a raw folder recursively. Recognise DJI (`.OSV` with optional `.LRF`, plus thumbnail files) and Insta360 (`.INSV` pairs, `.LRV` proxies, `.INSP`) by extension, naming pattern, and container probing.
- Pair dual-lens Insta360 files into one logical clip. Detect and warn about orphans.
- Probe with ffprobe and exiftool. Capture stream layout, codecs, fps (rational), duration, audio tracks, creation times, lens/serial info, and telemetry track presence.
- Compute content hashes (fast: size plus sampled-block hash, with an optional full hash) for cache keys.
- Determine `start_utc` per §6.1. Write `clip.json` and a race-level `catalog.csv` with one row per clip (for the user to review and edit clock overrides).
- Detect and skip duplicates and zero-length or corrupt files, with a clear report.

**Edge cases:** clips split by the camera at file-size limits (chain of sequential files that should be treated as continuous, or at least adjacent in time); corrupted moov atom; mixed DJI/Insta360 in one folder; timezone/DST boundary during an overnight race; leap seconds (ignore, document).

**Test cases**
- P0-01: Sample OSV+LRF folder yields one logical clip with both paths recorded and stream layout matching ffprobe.
- P0-02: The nominal rate is stored as an exact rational (50/1) together with the measured average rate and the number of dropped-frame gaps (the sample: 239 frames, one or more gaps of 60 ms); frame timestamps are read from the file, not assumed.
- P0-03: Container `CreateDate` 12:00:07 and filename `CAM_20260221120007_…` both give 2026-02-21T12:00:07Z with the default flag; with `container_time_is_utc` off and a configured timezone, the UTC value shifts accordingly. A disagreement of over 1 s between container and filename logs a warning.
- P0-04: Priority order: a manual override wins over container time, which wins over the filename; optional GPS time (synthetic fixture) is used only when present; the source label is always recorded.
- P0-05: Insta360 pair (`_00_`/`_10_`) is grouped into one clip; a lone file produces an orphan warning, not a crash.
- P0-06: Corrupt/truncated file is reported and skipped; the other clips still process.
- P0-07: Duplicate file (same hash, different name) is flagged.
- P0-08: Re-running ingest is idempotent (no changes, no re-hashing when size and mtime match).
- P0-09: Two consecutive camera-split files are linked as a continuation when timestamps abut.
- P0-10: `catalog.csv` round-trips: user edits to the override columns are read back and change `start_utc`.
- P0-11: DST change inside a race window yields correct monotonic UTC times.
- P0-12: `clip.json` contains `start_utc`, `end_utc` (= start + exact duration), and `utc_status`, and the timestamp is ISO 8601 UTC with fractional seconds.
- P0-13: Single source of truth: `analysis.json`, `attention.json` and `proposals.json` contain only clip-relative times plus the header copy; changing an override in `catalog.csv` changes `start_utc` and makes every downstream file fail its header check until re-run (stale detection).
- P0-14: A clip with conflicting container/filename times is `provisional` with a warning; adding a manual override makes it `definitive`.
- P0-15: Header mismatch (tampered `start_utc` in a downstream file) is rejected on load with a clear error.

---

### Phase 1: Normalize (stitch, stabilise, proxy, telemetry)

**Purpose:** convert every clip to a standard intermediate: one equirectangular master, one low-res proxy, one audio file, one telemetry sidecar. All later phases are camera-agnostic.

**Behaviour**
- **Adapters** per camera implement a fixed interface: `probe`, `extract_telemetry`, `stitch_to_equirect`, `make_proxy`. New cameras can be added without touching other phases.
- **Stitching (DJI):** dual-fisheye to equirectangular using a configurable lens model (per-lens FOV, centre offset, rotation, blend width). Use our own calibration-based stitch (validated in M0, see §2.1); ffmpeg's `v360` is only a quick preview path (it takes a generic FOV, not the per-lens calibration). Compare against the LRF's lens layout (see the acceptance criteria below). Investigate whether DJI embeds calibration data in metadata to seed the parameters.
- **Master format (optional; analysis and preview only, since Phase 7 renders straight from the original lens streams):** equirectangular, 10-bit HEVC (VideoToolbox hardware encode) at the source's native equirect resolution (for the Osmo 360 about 7680×3840; never upsample the master). **Reality check on 4K output:** an equirect 7680 px wide has about 21 px per degree, while a 3840 px wide rectilinear frame at 90° field of view needs about 43 px per degree. So a 4K flat frame at 90° is roughly 2× upsampled from the source, and a tighter zoom is upsampled more. **This is an accepted trade-off:** the flat video is always rendered at the full 3840×2160 because the GPX map overlay is composited at 4K, and a 4K base gives the overlay (lines, text, markers) its full detail even where the underlying picture is softer. The picture is therefore rendered at the maximum output resolution from the full-resolution master with a high-quality scaler, never from the proxy and never through an intermediate downscale. Phase 6 still reports an *effective resolution* per shot (source pixels per output pixel) and applies a soft preference against very tight zooms, purely as information and a tie-breaker, not a limit. Keep the source fps.
- **Proxy (one canonical file per clip, `spike/make_proxy.py`):** the single reduced-resolution file used by every visual analysis step. **Upright** (horizon-locked, world-locked with the per-frame telemetry rotation) **equirectangular, 3840×1920** (about 10.7 px/° against the source's 21 px/°), rendered from the full-resolution lens streams with the same calibration, lens weights and linear-light blending as the final renderer, **12.5 fps by default** (every 4th source frame; configurable), HEVC 8-bit `hvc1` BT.709 tagged, at a **high bitrate** (default VideoToolbox 80 Mbit/s requested, about 100 Mbit/s delivered at 25 fps; software x265 CRF 24 is about 1.4× more efficient per bit but about 10× slower). Why upright: detectors and vision models see people the right way up (the body-frame view is tilted 50–90° on a selfie stick). A JSON sidecar holds, per proxy frame, the source frame index and the authoritative clip-relative time (the mp4's own timestamps are nominal and drift by up to 0.06 s around dropped source frames), and the stabilisation used. **Cheaper copies are derived from this file on the fly (scale filter); there is no second proxy.** The camera's own `.LRF` is not used as the proxy (see §8.10). **Recognition-grade detail is never taken from the proxy:** identity, faces, bibs and kit are re-cropped from the full-resolution lens streams using the proxy detections as locations.
- **Telemetry:** decode `djmd`/Insta360 gyro streams into a normalised sidecar: timestamps, orientation quaternion (or angular velocity plus accel), GPS if present. Document units and axes conventions.
- **Stabilisation and horizon lock:** apply gyro-based stabilisation and gravity alignment at the master stage, so downstream yaw/pitch values are stable and the horizon is level. Decide during the spike between (a) a Gyroflow-style external tool, (b) applying orientation in the v360 rotation step, or (c) vendor SDK export. Record whichever is used in `clip.json`.
- **Audio:** extract to a lossless WAV (48 kHz) for analysis. Preserve the original stereo track in the master too. Note: 360 cameras' audio may be spatial or 4-mic. Take the mix-down and flag it if more channels exist.
- **Job control:** resumable, parallel across clips but bounded (the hardware encoder is the bottleneck), progress output, per-clip logs, temp files cleaned up on failure.

**Acceptance criteria for the stitch spike (decide before building more):** seam visibility at 6–10 sample angles is judged acceptable on real running footage by the user; alignment error against the LRF proxy is below a defined threshold (e.g. mean per-pixel difference after downscale below a set value, or feature-match reprojection error under a few pixels); colour and exposure match the LRF within tolerance.

**Test cases**
- P1-01: Synthetic dual-fisheye pattern (rendered from a known equirect test image) converts back to something within a defined error of the original test image.
- P1-02: Yaw/pitch landmarks in the synthetic pattern appear at the expected pixel coordinates in the output (±1 px).
- P1-03: Consistency with the LRF: our lens model applied to the sample OSV reproduces the LRF's dual-fisheye layout (each lens circle in the same position, size and orientation), with structural similarity above the agreed threshold at 20 sampled frames after downscaling.
- P1-04: Master duration equals source duration within one frame; audio duration matches within 20 ms.
- P1-05: Frame count and timestamps preserved for variable-frame-rate input (synthetic VFR fixture); no drift over a 10-minute synthetic.
- P1-06: Proxy time mapping: for every proxy frame the sidecar `source_frame` and `t_s` equal the source frame index and pts (including across the dropped-frame gap), and the sidecar time, not the mp4 timestamp, is what analysis uses.
- P1-15: The proxy is upright: on a fixture with a known camera tilt the horizon is level and a known vertical marker is vertical in the proxy (within 1°); its correlation with DJI's upright export on the sample is at least 0.97.
- P1-16: Proxy fidelity: against a lossless render of the same frames, structural similarity is at least the agreed threshold at the default settings, and the fine-detail retention (Laplacian variance ratio) is reported (measured on the sample: about 76% at 145 Mbit/s, 62% at 78 Mbit/s and 42% at 34 Mbit/s for the hardware encoder at 3840×1920 and 25 fps).
- P1-17: Timing and size preflight: the proxy generator reports estimated size and time before starting (about 10 MB/s of footage at the default settings) and fails early when disk space is insufficient.
- P1-18: Recrop path: given a proxy detection box, the recrop function returns a rectilinear crop rendered directly from the full-resolution lens frames of the matching source frame, and its sharpness is at least that of a crop taken from a lossless proxy render.
- P1-07: Telemetry sidecar has monotonic timestamps and plausible ranges (gravity magnitude near 1 g, no gaps beyond a threshold); a clip without telemetry produces an empty-but-valid sidecar and a warning, and stabilisation is skipped.
- P1-08: Stabilised output on a shaky fixture has measurably lower ego-motion energy than the unstabilised output.
- P1-09: Horizon lock on a fixture with a known 20° camera tilt produces an output whose horizon deviates by under 1°.
- P1-10: Interrupted run resumes without re-encoding finished clips; partial outputs never pass as complete (write to temp, atomic rename).
- P1-11: 10-bit input remains 10-bit (or an explicit, logged, downconversion happens).
- P1-12: An adapter for a second camera type can be registered and used without any change to other modules (interface conformance test with a stub adapter).
- P1-13: Insta360 fixture (once available) runs through the same pipeline and passes P1-04/06/07.
- P1-14: Disk-space preflight fails early with a clear message when the estimated output exceeds free space.

---

### Phase 2: Analyse (per clip)

**Purpose:** turn each proxy plus telemetry into cheap, factual, machine-readable signals for the editing stages. This is mostly classical CV/audio; the LLM enters only for the semantic captions.

**Behaviour**
1. **Shot/segment detection:** scene cuts (some clips may contain camera stops/starts) and stable-vs-moving segments from telemetry.
2. **Speech:** Whisper (or similar) for timestamped transcripts with confidence; language configurable. Voice-activity detection to find pauses (good cut points).
3. **Audio events:** loudness curve, wind detection (low-frequency broadband noise), cheering/applause, laughter, breathing/footsteps, music. Classification model or heuristics.
   **Audio use cases and their processing (implemented in `spike/audio.py`, tests in `spike/test_audio.py`):**
   - **Wearer speech (quiet or muffled voice to camera):** `enhance_speech`: high-pass at 100 Hz (wind and handling rumble), adaptive FFT denoise, speech EQ (a small cut around 250 Hz, a lift around 3 kHz), speech-aware auto gain that only lifts above a threshold (so pauses and room tone are not boosted), and a peak limiter. Two outputs: an **ASR version** (16 kHz mono, for the recogniser) and a **mix version** (48 kHz, gentler denoise, set to −18 LUFS, peak-safe). Verified: a −45 dBFS voice is lifted to a usable level while room tone stays 25 dB below it; output never clips.
   - **Crowd and excitement (start, finish, aid stations):** `condition_ambience(kind='crowd')`: light high-pass, gentle compression, de-clip if the input clips (ffmpeg `adeclip`), loudness set to a target, and a true-peak limit (default −1.5 dBTP); reports gain applied, loudness and true peak before and after.
   - **General background (ambience):** `condition_ambience(kind='bed')`: stronger rumble filter, levelled quietly, same peak protection.
   - **Classification** into these cases per window and segment is the analysis in §5.10.
   **Measured limits (be honest about what classical DSP gives):** on real non-stationary noise (wind plus people talking nearby) the denoiser changes speech intelligibility (STOI, a phase-insensitive metric) by only −0.004 to +0.007, while never making it worse; waveform metrics such as SI-SDR are misleading here because they punish every filter's phase delay and any auto-gain, and were dropped. The chain therefore guarantees levels, peak safety and a usable, consistent speech level, but real noise removal needs a neural denoiser and an actual recogniser to evaluate against (§14.6).
   **Recognition is measured, not assumed (word error rate, `spike/asr_eval.py`).** Known sentences buried in real noise excerpts from the Belgian race library (wind, crowd babble, ambience) at speech-band SNRs of −3, +3 and +9 dB, transcribed by faster-whisper: **feeding the recogniser raw audio is best, and a larger model helps more than any enhancer.** `small`: raw 0.16, classical chain 0.16, DeepFilterNet3 0.19, DeepFilterNet3 with a 20 dB attenuation limit 0.18, MossFormer2 (the benchmark leader) 0.22. `large-v3-turbo`: raw **0.12**, hp+EQ+level 0.14, DeepFilterNet3 0.14. Enhancers helped only against wind (DeepFilterNet3 and MossFormer2 0.14 → 0.11) and hurt against crowd babble (MossFormer2 0.19 → 0.35) and ambience. **Rules: the recogniser gets raw audio (resampled to 16 kHz); enhancement is for the mix; use a large model; consider an enhancer only for wind-dominated segments.** Benchmark rankings (PESQ, SI-SDR on clean-speech test sets) do not predict recognition accuracy here.
4. **Motion:** optical flow on rectilinear views. Separate the camera's own motion (from gyro) from scene motion.
5. **Vision sampling:** at a configurable interval (default 1–2 s, denser near candidate hotspots), render N rectilinear views (e.g. 4 horizontal at 90° plus up/down, or 6 cube faces) from the proxy. Send to a vision model for: a caption, tags, detected people count, aid station/finish/sign indicators, visibility of the athlete (the user, presumably the camera wearer or nearby), and obstruction flags. Cost control: prefilter with cheap signals; batch several views per call; cache by content hash.
6. **Subject detection and tracking:** person detection and tracking in the equirect or rectilinear views, mapped back to yaw/pitch. Face detection for optional blur/exclusion (privacy). Bib/sign OCR is useful for aid stations and identifying named runners.
6a. **Identify "me" (protagonist recognition).** Several people appear in most clips and the film should focus on the user.
   - **Enrolment by selection (primary method).** No reference photos are required. The first time (or whenever the profile is weak), the tool runs person detection and tracking over a sample of clips and shows a **"which one is me?" sheet**: one labelled thumbnail per distinct person track, best face crop first, grouped by likely same person. The user picks the tracks that are them. The picks build the local identity profile (`identities/me/`): face embeddings, appearance embeddings (clothing, pack, build), and optionally bib numbers read from the selected tracks. The profile is saved and reused on future runs and future races. It grows with each confirmed track (corrections and additions are welcome), and is versioned so the previous state can be restored. Race-specific appearance (kit, bib) is stored as a per-race layer, so that a new race keeps the face embeddings but needs kit confirmation only once.
   - **Enrolment from reference material (optional shortcut).** The user may instead, or additionally, supply 5–20 photos or a short clip covering different angles, lighting, and headwear, plus bib numbers and a kit description. This seeds the same profile.
   - **Auto-suggestion to make the selection one click.** With a pole-held camera (see wearer detection), the tool proposes the most likely track first: the closest, largest, persistently present person at a roughly constant bearing. The user confirms or corrects with a single click, and only tracks where the tool is unsure need attention.
   - **Face recognition:** face detection plus a face-embedding model, run **locally**, matched by similarity to the profile with calibrated thresholds. Faces from a 360 lens at distance are small and often distorted, so run on rectilinear crops rendered at the detected person's direction from the full-resolution master where needed, not from the proxy.
   - **Body/appearance re-identification:** faces are often not visible (seen from behind, hat, sunglasses, night, or too far). Use a person re-identification embedding (clothing, pack, build) plus **bib OCR** and kit colour, and **carry the identity along the tracker's track** so that a confident face match in one frame labels the whole track, and a track split (occlusion, crossing the seam) is re-joined by appearance and position.
   - **Wearer detection and the selfie-stick prior.** The camera is normally **held on a short selfie stick by the user**, so "me" is usually the closest, largest person track, persistently visible (whenever the user is facing the lens or is alongside it) at a roughly constant bearing and distance (arm plus stick, about 0.5–1 m) relative to the camera, and moving with the camera. Detect this by looking for a consistent body, arm or hand near a fixed direction, and by the mount signature in telemetry (regular arm-swing/stride motion, stable orientation relative to the runner's heading). Consequences:
     - Face recognition works well at this distance (large, well-lit faces), so it is the primary cue. Use the full-resolution master crops for it.
     - The stick itself is normally hidden by the stitch. Any visible remains of the stick (or the hand holding it) at the seam or nadir go into `quality_zones` and are avoided by framing.
     - The stick-held view has a stable "selfie" look option (camera facing back at the user, wide enough to show the surroundings), plus a "look where I'm looking" option (forward along the heading), and clips that switch between the two are common. Because the stick moves with the user, the protagonist's bearing changes little, so tracking is easy but *other* runners are the ones needing detection and choosing.
     - When the user swaps hands, holds the stick out sideways, or hands the camera to someone else, the prior weakens: the tool falls back on the identity profile alone and marks the intervals `uncertain` if needed.
     - If the camera is static or held by someone else, "me" is expected to appear as a normal person track.
   - **Fusion and confidence:** combine face, bib, appearance and track continuity into a per-track, per-time identity confidence with a source label. Low-confidence intervals are marked `uncertain`, never silently guessed. Provide a **review sheet** (contact sheet of the tracks labelled `me?` with confidences) so the user can confirm or correct identities once per race, and corrections feed back as extra reference samples.
   - **Other people:** unknown people are tracked as `other_person` (never identified by name unless the user enrols them).
   - **Privacy:** all biometric processing and embeddings stay on the machine (§8.6). No face crops or embeddings are sent to any external service.
6b. **Who is speaking (audio-visual speaker attribution; design, not yet built).** Audio and faces are combined so that every speech segment, and every transcript word, is attributed to a person, and the film can focus on the speaker.
   - **Voice side.** Voice-activity detection then speaker embeddings (SpeechBrain ECAPA-TDNN, Apache-2.0 and ungated; pyannote's pipelines are excellent but their weights are gated behind a licence acceptance and token) clustered into voices within a clip and matched across clips. Each cluster is a *voice*, not yet a person.
   - **The wearer's voice profile**, enrolled the same way as the face profile: from segments where the identified wearer is on camera with the mouth moving, or by the user's pick on a review sheet ("which voice is me?"). It is saved locally and reused across clips and races. The wearer is also strongly favoured by a **proximity prior** (the camera is on a selfie stick about 0.5 m from the mouth, so the wearer is the loudest, cleanest voice), which works even when the face is not in view.
   - **Visual side (active speaker detection).** For every tracked face, render a rectilinear crop straight from the full-resolution lens frames (§Phase 2 recrop) at about 12.5 fps and measure mouth activity from facial landmarks (MediaPipe face landmarks, Apache-2.0), or use a trained active-speaker model (TalkNet-ASD or Light-ASD, MIT). Mouth-opening motion is correlated with the audio's voiced energy over a sliding window. In a 360 clip every face in the scene is visible at once, which is an advantage over a flat camera.
   - **Fusion.** A voice is linked to a face track when the mouth-activity of that track and the voice's speech intervals correlate across the clip (and across the race, which accumulates evidence for people who are only briefly on camera). Result per speech segment: `speaker` (`me`, `person:<track>`, `voice:<cluster>` when no face is linked), a confidence and the sources that agree. Intervals where the evidence conflicts or is thin are `uncertain`, never guessed. Bystanders are tracked as anonymous voices and faces; nobody is named unless enrolled.
   - **What it is used for.** (1) Transcripts labelled by speaker, so the LLM and the editor know who said what. (2) **Framing:** during speech the attention map (Phase 4) offers a `follow_target` option on the speaker's face track (a two-shot when both are in view), and the framing solve prefers it. (3) **Selection:** candidates where the wearer speaks to camera with a good signal are scored as key shots; a bystander's speech is scored by how much it says (translated for foreign speech). (4) **Audio:** speech is enhanced for the mix per speaker and the music ducks under the wearer (§5c-3). (5) **Cuts:** edit points come from the refined word boundaries (§5.11).
   - **Privacy and licences.** Voice embeddings and face embeddings stay on the machine, are stored only for enrolled people, and can be deleted with the profile. InsightFace's pretrained weights are non-commercial only; MediaPipe, SpeechBrain and TalkNet code and weights are permissive. Voiceprints of bystanders are held in memory for clustering during a run and not written to disk unless the user enrols them.
   - **Output (per clip, `speakers.json`):** voice clusters (with an embedding reference), per-segment speaker assignments with confidence and evidence, links between voices and face tracks, and the wearer's segments.
7. **Quality assessment:** blur, exposure, lens obstruction (finger/mud/hair over a lens), extreme tilt, tripod/nadir visible, stitching-line artefacts near the subject.
8. **Highlights and novelty:** an interest score time series combining energy, speech, subject count, and novelty relative to other clips (so the film doesn't contain 15 near-identical trail shots).
9. **Whole-race context** (a later pass across clips): cluster clips by location and time via clock plus GPX, so the master step can ensure coverage along the course and by race stage (start, night, aid stations, finish).

**Edge cases:** silent clips; clips with heavy wind; night footage (dark, noisy: lower vision confidence, use auto-exposure heuristics); clips with no people; camera mounted on a pole versus handheld versus on a backpack (config or auto-detect from motion signature); very short clips (under 3 s) which may just get "keep whole" treatment.

**Test cases**
- P2-01: Synthetic clip with three hard cuts at known times yields exactly three boundaries within ±2 frames.
- P2-02: Audio fixture with known speech segments produces a transcript with word-error-rate under a set bound and correct timestamps within 200 ms.
- P2-03: Wind-noise fixture is flagged; clean speech fixture is not.
- P2-04: Synthetic moving object at a known yaw/pitch is detected, and the reported track stays within a few degrees of truth over time, including across the ±180° seam.
- P2-05: A track that crosses the equirect wraparound seam is one continuous track, not two.
- P2-06: Camera-motion vs scene-motion separation: a stationary scene with a rotating camera reports high ego-motion and low scene-motion; a still camera with a moving subject reports the opposite.
- P2-07: Obstruction fixture (a large blurred blob over one lens region) sets the obstruction flag over the correct time range.
- P2-08: Dark/noisy fixture is flagged as low-quality without crashing the captioner.
- P2-09: Caching: second run of the same clip and config performs zero LLM/vision calls and zero heavy compute; changing the sampling interval invalidates only the relevant artefacts.
- P2-10: Vision call failure or malformed response for one frame yields a recorded gap and continues, with retry and backoff; the run finishes with a summary of failures.
- P2-11: Cost guard: a per-clip and per-race budget cap stops or downgrades sampling (with a logged warning) instead of overspending.
- P2-12: The interest score is deterministic given fixed inputs (the LLM captions are mocked).
- P2-13: Face detection privacy option: with it enabled, detected faces are listed for downstream blurring (no blur is applied here).
- P2-16: Identity enrolment: given reference photos of a test person, a fixture clip containing that person among 3 others labels the right track `me` (precision and recall above set thresholds on a labelled fixture set).
- P2-17: Rear/occluded view: a track in which the face is never visible but a bib number is readable is labelled `me` via bib OCR; without a bib or face it falls back to appearance and is marked lower confidence.
- P2-18: Identity propagation: a single confident face frame labels its whole track; a track broken by an occlusion or by crossing the ±180° seam is re-joined and keeps the label.
- P2-19: Look-alike safety: a fixture with a different runner in similar kit is not labelled `me` above the confidence threshold (false-positive rate measured); uncertain tracks are flagged, not guessed.
- P2-20: Hat/sunglasses/night variants of the reference person still match at the required recall, and confidence drops accordingly.
- P2-21: Selfie-stick prior: a fixture with a pole-held camera proposes the closest, persistent, constant-bearing track as the top "likely me" suggestion; a static-camera fixture does not apply the prior.
- P2-25: "Which one is me?" flow: given three tracks and the user's pick (a test double for the UI), the profile is created locally, contains face and appearance embeddings from the picked track only, and the other tracks stay `other_person`.
- P2-26: Persistence across runs: after the profile is saved, a second run on new clips of the same person labels them `me` with no user interaction and no new prompts (only tracks below the confidence threshold prompt).
- P2-27: Correction: the user moves a wrongly assigned track from `me` to `other_person`; the profile removes those samples, previously wrong labels change on re-run, and only identity-dependent caches are invalidated.
- P2-28: Cold start with no reference photos works end to end (the selection sheet is generated and accepted). Adding reference photos later improves recall without changing the stored picks.
- P2-29: Profile layering: a new race with a different kit keeps the face profile and asks for kit confirmation only once; a wrong kit layer does not override a strong face match.
- P2-30: Profile versioning: the previous version can be restored, and each run records which profile version it used (for reproducibility).
- P2-31: Selfie-stick hand-over: an interval where the camera is held by someone else (user visible as a normal track at a varying bearing) is labelled `me` by identity alone, and the prior does not mis-label the holder as `me`.
- P2-32: Stick remnants near the seam/nadir are added to the quality zones for that clip.
- P2-33: `exposure.json` has one sample per N frames (default 10), `frame` and `t_s` consistent with the telemetry and pts, and validates against its schema (all arrays the declared length).
- P2-34: On a synthetic clip with a known constant brightness, `mean_lin` equals the expected linear value within tolerance; a clip with a known 1-stop step at frame 100 shows a 1-stop step (within 0.05 stop) in `mean_lin` and `grid_mean_lin` at that sample.
- P2-35: The sky/ground split is correct for a synthetic bright-top/dark-bottom scene under a known camera tilt (the stabilised world frame, not the camera frame).
- P2-36: Camera metadata columns match the telemetry (ISO, shutter denominator, colour temperature per lens) at spot-checked frames; a clip with an auto-exposure change shows it in `exposure_index_ev`.
- P2-37: `clipped_frac` and `crushed_frac` are 0 for a mid-grey scene and match the known fractions for a synthetic scene with a 10% blown-out area.
- P2-39: Loudness: integrated LUFS and true peak agree with ffmpeg's ebur128 within 0.15 LU on sines, noise, speech and the sample clip (implemented).
- P2-40: Classification on a synthetic timeline of speech in low noise, rumble, digital near-silence and six overlapping voices: at least 60% of windows in each region get the right label (measured 65–100%, implemented).
- P2-41: Clipping: a clipped signal is reported (count and times) and `condition_ambience` returns output with no clipped samples and true peak at or below −1.4 dBTP (implemented).
- P2-42: Speech chain safety on speech buried in the clip's own real noise at −5, 0, +5 and +10 dB speech-band SNR: STOI never drops by more than 0.01, output never clips, and the mix version lands within 2 LU of −18 LUFS (implemented).
- P2-43: Quiet voice: a −45 dBFS voice is lifted above −30 dBFS RMS while following room tone stays more than 25 dB below the speech (implemented).
- P2-44: Recogniser-based evaluation (implemented, `spike/asr_eval.py`): WER of each chain variant on speech-in-noise mixes with real noise; a variant is kept for recognition only if it lowers WER (result: none does; raw audio is the default).
- P2-45: Language identification is per segment and restricted to the configured languages: a clip mixing French and English gets both labels; a one-word clip is not labelled Norwegian or Korean (implemented, `spike/speech.py`; measured on the sample French clip).
- P2-46: Translation: every non-English segment carries `text` (native) and `text_en`; the English text is produced from the native text by the translation model, and the native text is always kept.
- P2-47: Hallucination flags: segments matching known invented phrases (subtitle credits, sign-offs), with a probably-no-speech score above 0.6, or with strong word repetition are flagged `suspect` and excluded from counts and captions by default (implemented; the sample clip's "Sous-titrage Société Radio-Canada" over noise is caught).
- P2-48: Timing: every word has clip-relative start and end times within its segment and inside the clip; segments are ordered and non-overlapping within a voice-activity chunk.
- P2-50 (future): Speaker turns on a synthetic multi-speaker recording with known turn boundaries (several text-to-speech voices, overlaps and pauses): diarisation error rate below the agreed threshold, and speaker changes located within 100 ms.
- P2-51 (future): Wearer voice: after enrolment from a few segments, the wearer's voice is labelled `me` in other clips with at least the agreed recall and a false-positive rate near zero on look-alike voices; `uncertain` is used rather than guessing.
- P2-52 (future): Active speaker: on a fixture with a known speaking face and a silent face in the same view, the speaking face is chosen (mouth activity correlated with the voice) and a face seen only from behind is never assigned speech.
- P2-53 (future): Voice-to-face linking accumulates across clips: a person on camera briefly in many clips gets a stable voice identity; conflicting evidence lowers confidence.
- P2-54: Word boundaries against known truth (implemented, `spike/test_wordtimes.py`): forced alignment plus energy refinement has median boundary error under 60 ms in clean, wind and babble conditions, and is at least 3 times better than whisper's own times; the study reports whisper's bias.
- P2-55: Cut safety (implemented): no cut between words that touch (no pause) is ever flagged safe; in clean audio at least 95% of cuts at real pauses land inside the true pause.
- P2-56: The consistency gate: a segment whose alignment disagrees with whisper by more than 0.4 s is marked `ok: false` and has no safe cuts next to those words.
- P2-49 (future): translation quality is reviewed by a native speaker on a sample of French and Dutch (Flemish) segments; recognition WER on real (not synthetic) speech uses a hand-checked transcript set.
- P2-38: The export is deterministic (same file twice gives identical JSON) and fast (a 5 s clip in seconds), and works with `--every 20`.
- P2-22: Enrolment profile is stored locally, and a network-blocked test confirms no face embedding or face crop leaves the machine.
- P2-23: User corrections (relabel a track) are honoured on re-run and improve later matches (adds reference samples) without invalidating unrelated caches.
- P2-24: Multiple people with the same kit/bib partial reads: conflicting evidence yields `uncertain` with both candidates listed.
- P2-14: Very short clips (under 3 s) still produce a valid analysis bundle.
- P2-15: Output schema validates, and all arrays share the declared time base and length.

---

### Phase 3: Propose candidate ranges (per clip)

**Purpose:** for each clip produce a menu of good, self-contained segments with quality-aware trim handles and cut points. The master step chooses from these. This is the main LLM-assisted step.

**Protagonist focus:** the score of a candidate includes `protagonist_coverage` (the fraction of the core range in which "me" is identified in view, from the Phase 2 identity tracks). The default preference is for candidates where the user is visible or clearly the subject. Scenery and other-people shots remain eligible according to their role and score; the weight is configurable, and `uncertain` intervals count partially.

**Approach (hybrid, to keep it reliable and cheap)**
1. **Deterministic candidate generation** proposes windows around interest-score peaks, subject-in-view intervals, and speech utterances. It snaps edges to natural boundaries (shot boundaries, pauses, stable motion), and rejects anything that intersects a hard quality flag.
2. **LLM ranking and description.** Provide the LLM with: the compact timeline (captions, transcript, energy, quality), the user's intent for the film, and the deterministic candidates. Ask it to (a) score and rank candidates, (b) assign a `role`, (c) write a one-line description and reasons, (d) propose merges, splits, or trims, and (e) flag anything the deterministic step missed. Require strict schema-validated output.
3. **Validation and repair.** Reject or clamp any LLM output that is out of range, overlapping illegally, or violates minimum length. Fall back to the deterministic candidate on failure. Log every fallback.
4. **Handles and cut points.** For each candidate compute how far the range can be extended in each direction without hitting a hard boundary or quality flag, and list ranked cut points inside the handles. A cut is good when it is in a speech pause, outside mid-gesture motion peaks, and away from bad frames. Cut quality also feeds beat matching later.
5. **Length flexibility.** Each candidate declares `min`, `ideal`, `max` durations. Defaults, configurable per role: action clips 3–8 s, scenery 2–5 s, speech clips whole utterance plus a small pad (no mid-sentence cuts), aid station 3–6 s. The spread between `min` and `max` is what gives the beat matcher room to work in §5.
6. **Diversity within a clip.** Aim for 2–5 non-identical candidates per clip; mark overlapping ones as mutually exclusive.
7. **"Keep as is" shortcut:** clips shorter than the configured threshold get one whole-clip candidate.

**Timestamp handling:** all times are clip-relative seconds. Absolute UTC is always derived (§6.3), never stored in duplicate.

**Test cases**
- P3-01: Every candidate lies within `[0, duration]`, and `min_in ≤ core_in < core_out ≤ max_out`.
- P3-02: No candidate overlaps a hard-flag interval (obstruction, mid-word speech cut) in its core; handles never extend into a hard-flag interval.
- P3-03: A speech clip yields a candidate that starts and ends at pauses, never mid-word (test against word timestamps).
- P3-04: With the LLM stubbed to return garbage, the pipeline falls back to the deterministic candidates and reports it.
- P3-05: LLM returns out-of-range times: they are clamped or rejected, and the reason is logged.
- P3-06: Determinism: with recorded LLM responses, the same input produces identical `proposals.json` (byte-for-byte after sorting).
- P3-07: Mutually exclusive candidates are correctly marked when their cores or handles overlap.
- P3-08: A clip of 4 s returns one whole-clip candidate with sensible min/ideal/max.
- P3-09: Duration bounds respect role defaults and per-race config overrides.
- P3-10: Cut-point list is sorted by quality, and each point lies inside the handle range.
- P3-11: A clip with no interesting content still yields at least one low-score `filler` candidate (so the master can use it for coverage) or an explicit "none" with a reason. Behaviour is configurable.
- P3-12: Prompt-injection safety: transcript text such as "ignore previous instructions" doesn't change the output structure or behaviour (test with adversarial transcript fixtures).
- P3-13: Token budget: the prompt for a very long clip is chunked and results merged without duplicate candidates.
- P3-14: Human override file (pin or ban a candidate, force a range) is honoured and survives a re-run.

---

### Phase 4: Attention map (framing options, per clip)

**Purpose:** describe, for the whole clip and independent of any trim, *what is worth looking at, where, and when*, and offer a menu of framing intents. It deliberately makes **no** commitment on zoom, pan, perspective or centring; those depend on the final shot length, its neighbours and the music, so they are decided in Phase 6. This keeps the phase rich and re-usable when the target duration or music changes.

**Behaviour**
1. **Target tracks.** Take the Phase 2 subject tracks and identities and produce `targets[]` (§5.4): the protagonist (`me`) as the highest-priority target, other people and groups, faces, signs, vehicles, and scenery landmarks or views (sky, ridge line, water) found by the vision model. Each track has per-time direction, angular extent, confidence, salience and flags. Positions and extents always come from detectors and telemetry (geometry), while the LLM contributes only labels, descriptions and interest.
2. **Pointing the LLM at the sphere reliably.** For the vision-model step, render labelled rectilinear views on a fixed grid of directions (each view tagged with its yaw/pitch). The model refers to views and detected target IDs by tag, never invents coordinates. Fine offsets come from the detectors. This makes LLM output verifiable and reproducible.
3. **Salience field.** Build a coarse per-time equirect heat map from motion (with ego-motion removed), people and faces (protagonist boosted), vision-model interest, and scenery cues. This lets the solver score *any* camera path, including ones we did not enumerate.
4. **Reference directions.** Direction of travel from telemetry, gravity/horizon, wearer bearing, and mount type, so "look ahead" and "look back" are well defined.
5. **Look options.** Generate a menu of framing intents over the clip: follow the protagonist (tight/medium/wide), forward look, reveal pan from A to B, pull back wide, look back at the following runner, two-shot (protagonist plus another person), hold on a landmark, and so on. Each option has a validity window and is valid for any sub-window of at least `min_useful_s` inside it, so it survives whatever trim Phase 5 chooses. Rank by score, with protagonist options favoured, and let the LLM add a one-line reason and propose extra options for special moments, validated against detectors.
6. **Quality zones.** Directions to avoid (stitching seam, lens obstruction, the wearer's body or pole, blown-out sky) by time.
7. **Always a fallback.** Guarantee `defaults` cover the whole clip, so the solver can always frame something acceptable.
8. **Protagonist gaps.** Mark intervals where "me" is expected but not found (behind the camera, obscured), so Phase 5 can avoid trimming into them if the protagonist is wanted.
9. **Cheap preview.** For review, render a contact sheet or short proxy video with the target boxes and identities overlaid, so the user can see what the system saw.

**Design note:** the map is descriptive, so it can be re-generated with different vision prompts or a new identity profile without touching candidates or EDLs (cache keys reflect this).

**Test cases**
- P4-01: A synthetic scene with objects at known yaw/pitch produces target tracks whose directions and extents match truth within tolerance, including across the ±180° seam (one track, not two).
- P4-02: Schema validity: every target has an `alive` interval, samples fall inside it, and all arrays share the declared time grid.
- P4-03: The protagonist is always `type=protagonist` with the highest default priority when identified, and other people never inherit `identity=me`.
- P4-04: Every look option has a valid window inside the clip, references existing target IDs, and remains valid for every sub-window of at least `min_useful_s` (property test with random sub-windows).
- P4-05: `defaults` cover 100% of the clip duration even for a clip with no detected targets.
- P4-06: Quality zones exclude the seam and a synthetic obstruction: no option's suggested direction lies in a zone when an alternative exists.
- P4-07: LLM pointing: a stubbed LLM that refers to a nonexistent view tag or target ID is rejected and logged, and does not create a target; one that references valid tags produces targets at the tag's direction.
- P4-08: The salience field peaks at the known location of the moving marker and at the protagonist in fixtures, and is deterministic for fixed inputs.
- P4-09: With the protagonist absent for an interval, that interval is flagged as a protagonist gap and the options fall back to scenery or others.
- P4-10: Re-running with a corrected identity profile changes only identity-dependent fields and options, and leaves candidates untouched.
- P4-11: Size budget: the JSON stays under a set size for a 2-minute clip, with the heavy arrays in the sidecar, which loads lazily.
- P4-12: Determinism: identical inputs and recorded LLM responses give identical output.
- P4-13: Heading reference: for a fixture with a known turn, forward look tracks the heading through the turn (no lag beyond a tolerance).
- P4-14: The review overlay render draws each target's box at the correct direction (marker test) with the identity label.

---

### Phase 5: Master assembly (global selection, length fitting, beat sync)

**Purpose:** given the whole race's candidates, choose a subset and exact in/out points to hit the target duration, tell a coherent story, and, if music is supplied, land cuts on beats.

**Inputs:** all `proposals.json` and a summary of each clip's attention map (target presence and option windows); catalog with UTC start times and GPX-derived race position (distance and time) per candidate; target duration (plus tolerance); optional music analysis; config for the desired pace and structure.

**5a. Music analysis (optional)**
- Beat and downbeat tracking (e.g. librosa/madmom-class tools), tempo curve, section boundaries, an energy curve.
- Build a **beat grid**: allowed cut times, ranked (downbeat > beat > off-beat) and section starts flagged as strong.
- Detect unreliable beat tracking (tempo unstable, low confidence) and either fall back to non-synced mode or ask for a manual tempo/grid.
- Allow a user-provided beat/section file to override.

**5b. Selection problem (global optimisation)**
Formulate as constrained optimisation:
- **Objective:** maximise the sum of candidate scores, plus bonuses for coverage and diversity, minus penalties for repetition, poor cut quality, pacing violations, and speed changes.
- **Hard constraints:** total duration within tolerance of the target; at most one candidate from each mutually exclusive group; each clip's use count under a configurable cap; each segment within `[min, max]` duration.
- **Soft constraints / story structure:**
  - **Chronological order by default** (the map story is a race timeline). Allow "flashback" only when explicitly configured.
  - **Coverage** across the course, in equal slices of distance or time (so the middle 40 km is represented), with a configurable weight for special zones (start, aid stations, finish, dramatic moments).
  - **Pace:** a shot length distribution (e.g. faster cutting toward the finish, longer holds at scenic moments), and alternation of roles (avoid four scenery shots in a row).
  - **Transitions:** avoid jump cuts between visually near-identical consecutive shots (visual similarity from the captions or embeddings); prefer natural time gaps.
- **Solver:** start with dynamic programming or a greedy-with-repair algorithm over the time-ordered sequence, and consider an ILP/CP-SAT solver if constraints grow. The problem is small (hundreds of candidates), so an exact solver is feasible and preferable, because it is auditable.
- **LLM role in the master step:** *advisory only.* The LLM receives the compact list (description, role, score, race position) and can propose a narrative arc, tag must-have and must-drop candidates, and review the chosen list for storytelling holes. Its output is turned into weights/pins for the solver. It never bypasses the constraints.

**5c. Exact trim and beat alignment**
Once the set is chosen (or jointly with it, for a second pass):
- Each selected candidate has a window: `in` may move within `[min_in, core_in]`, `out` within `[core_out, max_out]`, and the duration must stay within `[min_dur, max_dur]`.
- **Beat mode:** choose in/out points among the candidate's ranked `cut_points` so that each **cut lands on a beat** (downbeats preferred at section changes). Since cut points only exist where a cut is visually safe, the beat grid and the cut points must intersect within the tolerance; the solver picks the best combined score.
- Cumulative rounding: total duration of the segments must match the music segment plan (or the target), so accumulate exact times, never per-clip rounded ones.
- **Speed fine-tuning (optional, off by default):** a small speed adjustment (within ±5–10%) may close remaining gaps to the beat grid, only for roles where it isn't visible (scenery). Must be recorded in the EDL for timestamp mapping.
- **Fallbacks:** if a segment cannot land on a beat within tolerance, choose the nearest half-beat, or extend or shorten the *neighbouring* segment. If the whole track can't be filled, report by how much and suggest options (allow more clips, lower the target, choose another track).
- **Audio policy:** natural audio ducked under the music, speech clips duck the music; loudness normalisation across segments; crossfades for audio even when the video cuts.
- **Ending:** the final shot aligns to the music ending or fades. The music start offset is configurable.

**5c-2. Framing feasibility (soft, no camera decisions yet)**
- Score each candidate trim by how much good framing exists inside it: prefer in/out points and durations for which a high-scoring look option (especially one following the protagonist) is valid over the whole segment, and avoid trimming into a protagonist gap or a quality-zone-only interval.
- Use option windows to prefer *variety* between neighbouring shots (avoid two consecutive shots that could only be framed identically).
- Record, per selected segment, the top look options that fit its final length. This is a **hint** for Phase 6, and not binding.
- **Feedback loop:** if Phase 6 reports that a segment has no acceptable framing, Phase 5 re-runs with that trim banned or penalised (limited to a few iterations), swapping to an alternative candidate or another trim.

**5c-3. Audio mix plan (implemented in `spike/audio.py: mix_plan / render_mix`, tests in `spike/test_audio.py`)**
Inputs: the music track (its envelope), per-segment audio labels from `audio.json` mapped to output time through the EDL, the conditioned stems.
- **Music bed** plays throughout at its own loudness. It is **ducked under wearer speech** (default −12 dB, fast attack 50 ms, release 0.4 s) and **less under crowd/excitement** (−6 dB), so a crowd at a start or finish adds energy without burying the music.
- **Ambience swells during silence in the music.** The ambience stem sits at its bed level under the music; when the music is quiet (default below −45 dBFS) for longer than a hold time (0.3 s, so short rests do not pump it) the ambience fades up by 12 dB over 0.5 s, and drops within 0.15 s when the music returns so it never fights it. Measured on a synthetic score: +11 dB or more inside a 2 s gap, back below +6 dB 0.3 s after the music returns, no reaction to a 0.2 s rest.
- **Crowd stems** are mixed in where the labels say excitement (start, finish, aid stations), normalised, peak-safe, at a level relative to the speech.
- **Wearer speech** is normalised to about −18 LUFS and is the priority signal.
- **Programme bus:** loudness set to a target (default −16 LUFS, configurable, −14 for online) and a true-peak limiter (default −1 dBTP); the render reports loudness and true peak and fails if anything clips.
- Cut decisions use the audio labels: never cut mid-word (transcript word times), and prefer to start or end a segment in a pause.

**5d. Review artefacts**
- `edl.json` plus a human-readable table (`edl.md`/CSV): order, clip, in/out, duration, role, score, race position (km, elapsed time), reason.
- An "alternatives" report: for each segment, the next-best replacement candidates so the user can swap one easily.
- A low-res assembled **preview** render with a burned-in timecode and a UTC clock for checking.
- A summary of stats: coverage by race section, shot length histogram, the fraction of cuts on beat, and constraint slack.

**Test cases**
- P5-01: Target 90 s with a fixture of 40 candidates returns a total within tolerance, with no constraint violations.
- P5-02: Mutually exclusive candidates are never selected together.
- P5-03: Default output order is chronological by UTC (verified by asserting monotonic source UTC across segments).
- P5-04: Coverage: with clips evenly spread over the race, the selection has representation in every configured slice (test with a fixture where a naive top-score pick would ignore a slice).
- P5-05: Repetition: two near-identical high-score candidates are not both chosen unless the budget requires it.
- P5-06: Beat-sync: with a constant 120 BPM synthetic track and flexible candidates, 100% of cuts land within a small tolerance (e.g. 30 ms) of a beat.
- P5-07: With rigid candidates (min = max, no cut points), the solver reports infeasible-to-beat-match and follows the configured fallback rather than silently misaligning.
- P5-08: Downbeat preference: with a fixture where a section change is at a downbeat, the section-change cut lands on it.
- P5-09: Total video length equals the music plan length to within one frame, across 50 segments (no cumulative rounding drift).
- P5-10: Variable-tempo/unreliable-beat track triggers the fallback mode and a warning.
- P5-11: Speed adjustment is disabled by default; when enabled it never exceeds its limit and is recorded so the timemap is correct.
- P5-12: Pins and bans (user or LLM) are always honoured; a pin that makes the problem infeasible produces an explicit conflict report.
- P5-13: Determinism: the same inputs and seed produce the same EDL; tie-breaks are defined.
- P5-14: A single-clip edge case and a 100-clip case both run within the performance budget (seconds, not minutes).
- P5-15: Infeasible target (not enough footage) yields a clear error with a suggestion, not a broken EDL.
- P5-16: Ducking metadata: segments with speech get music-duck markers; segments with muted audio don't.
- P5-17: LLM advisory output that names a nonexistent candidate is ignored with a warning.
- P5-18: The alternatives report contains valid, non-conflicting replacements for each segment.
- P5-20: Framing feasibility: with two candidates of equal score, the one whose valid look option covers its whole trim is preferred; a trim that lies entirely in a protagonist gap is penalised when protagonist focus is on.
- P5-21: Feedback loop: a stub Phase 6 that rejects a segment causes Phase 5 to replace or re-trim it, within the iteration cap, and the final EDL contains no rejected trim; if the cap is hit, the best-effort EDL is returned with a warning.
- P5-22: A `timed` EDL (before Phase 6) already passes the timemap and handoff checks, and adding framing does not change any in/out time.
- P5-23: Audio mix: ambience gain rises by at least 11 dB in a 2 s music gap and not for a 0.2 s rest (implemented); music ducks by at least 11 dB within 0.2 s of speech starting and recovers to within 1 dB inside 1.5 s of it ending, and ducks 5–7 dB for crowd (implemented); the final mix has no clipped samples, true peak at or below −0.9 dBFS and integrated loudness within 0.6 LU of the target (implemented).
- P5-19: The music offset or fade-out produces an ending on a beat (or an intentional fade) as configured.

---

### Phase 6: Framing solve (per selected segment)

*Status (M0): the path machinery this phase generates output for (keyframed paths, heading-follow, path limits, the JSON format in §5.4b) is implemented and tested in `spike/camera.py` and `spike/test_camera.py` (10 tests: shortest-way yaw across the seam, no overshoot, easing behaviour, arm-swing rejection, heading unwrapping, no spin when the reference axis is vertical, limits report, extra smoothing, mixed-easing warning). The solver that chooses options and builds paths from the attention map is not started.*

**Purpose:** now that every shot has its exact in/out, duration, neighbours and place on the beat grid, choose the virtual camera's behaviour (centring, zoom, pan, perspective) and turn it into a smooth, watchable path. This is where the deferred decisions are made.

**Inputs:** the `timed` EDL, all attention maps, the music beat grid (if any), the style configuration, and the user's identity profile.

**Behaviour**
1. **Choose an option per segment** from the attention map, given the exact length. Score = option score × fit to duration (a reveal pan needs at least a minimum length; a very short shot should hold) × protagonist preference × neighbour variety. Long segments can chain two options (for example follow the protagonist, then a slow pull-back to reveal the view).
2. **Neighbour rules** (soft): vary shot scale between neighbours (alternate tight and wide), avoid near-identical framing on consecutive cuts, and prefer an entry direction different from the previous exit direction unless intentionally matching, so that cuts read as edits and not as jump cuts.
3. **Protagonist policy:** default is to centre or place "me" on a rule-of-thirds line, with headroom in the direction of travel. Show more of the space ahead. If "me" leaves the frame or the identity is uncertain, hold or ease to the fallback per configuration (never snap). Time in frame of the protagonist is measured and reported per segment.
4. **Sparse targets, dense path:** convert the chosen options to a few look targets (yaw, pitch, fov at specific times), then a deterministic solver produces the dense path: bounded angular velocity and acceleration, eased transitions, dead-zone hysteresis so small movements don't cause jitter, pitch clamped, roll zero after horizon lock, seam and obstruction avoidance, and an FOV policy (wide about 100°, tight about 70–85°, no extreme distortion), with a configurable **soft minimum FOV** derived from effective resolution: because a 4K frame at 90° is already about 2× upsampled from the source, very tight zooms look soft, so they are penalised in scoring (default threshold about 55°) but allowed (an optional hard limit can be set), and the framing report lists each shot's effective resolution. Raw LLM keyframes or raw detections never drive the render directly.
5. **Duration-aware moves:** scale pan and zoom speed to the segment length, so a reveal that takes 6 s at a natural pace is either slowed within limits or replaced by a hold if the segment is only 3 s.
6. **Music-aware moves (when music is supplied):** start and end pans and zooms on beats or bar lines, and land a move's peak on a downbeat where the option allows it.
7. **Verification loop (optional, costs LLM calls):** render a few low-res preview frames along the path, and ask the vision model whether the intended subject is in frame and well composed. Apply a limited number of corrections, then accept or report the segment as a framing failure to Phase 5 (§5c-2).
8. **Outputs:** the framing plan (§5.4a) with ranked alternatives per segment, a framing report (protagonist-in-frame percentage, max angular speed, options chosen and rejected), and a quick low-res preview video of the whole edit.
9. **Human overrides:** the user can pin an option, force a target, set a manual look direction and zoom for a segment in an override file. Overrides are honoured on re-runs.

**Test cases**
- P6-01: Synthetic marker moving in yaw at a known rate is followed with mean angular error under a set number of degrees.
- P6-02: Paths never exceed the configured max angular velocity and acceleration (checked over all frames).
- P6-03: Tracked subject crossing the ±180° seam yields a path that takes the short way, not a 360° spin.
- P6-04: Jittery detection input (noise added to a straight track) yields output path jitter (measured by jerk) reduced by at least a set factor.
- P6-05: Pitch never exceeds clamps; roll is zero after horizon lock.
- P6-06: Every EDL segment gets a path covering exactly its final `[in, out]` with no gaps, including after a trim change.
- P6-07: Subject leaves the scene mid-segment: the path holds, then eases to a fallback (forward heading) instead of snapping.
- P6-08: Path avoids the stitching seam and obstructed regions when an alternative view exists.
- P6-09: Protagonist policy: on a fixture where "me" is present, "me" is in frame for at least the configured fraction of the segment (measured on rendered frames), and is placed on the intended third line.
- P6-10: Duration awareness: the same option set on a 3 s and an 8 s segment yields a hold for the 3 s and a full reveal pan for the 8 s, and neither exceeds motion limits.
- P6-11: Neighbour variety: across a fixture sequence, no two adjacent segments share the same option, direction and scale when an alternative exists.
- P6-12: Music-aware moves: with a constant-tempo track, the start and end times of pans fall on beats within tolerance.
- P6-13: Verification loop terminates within its cap and improves, or leaves unchanged, the in-frame subject score on a fixture where the initial target is wrong.
- P6-14: A segment with no acceptable option is reported to Phase 5 as a framing failure (not silently framed badly).
- P6-15: Overrides (manual direction, forced target, pinned option) are honoured and survive a re-run.
- P6-16: Determinism: the same inputs give the same paths (no flicker between runs).
- P6-17: Changing the EDL length of one segment re-solves only that segment (and its neighbours' variety rules), and the other segments' paths are cached.
- P6-18: Uncertain protagonist identity in a segment yields a wider, lower-commitment framing (fixture) and a flagged report entry.
- P6-20: Soft minimum FOV: with all else equal, the solver prefers the option at or above the threshold; a path tighter than the threshold is chosen only when it is clearly better (or forced by an override), the report flags it, and with the optional hard limit enabled no path goes tighter.
- P6-21: Selfie-stick options: on a pole-held fixture, the solver offers and can choose both a wide "selfie" framing (protagonist plus surroundings) and a forward look along the heading, and switching between them respects motion limits.
- P6-19: Rendered preview of the synthetic test has the marker within a tolerance of frame centre.

---

### Phase 7: Render

**Purpose:** execute the EDL deterministically to produce the final flat video and the timecode map.

**Behaviour**
- Build the render graph per segment: from the equirect master, apply the per-frame yaw/pitch/roll/fov path (from the framing plan) with a rectilinear projection (`v360`-style with per-frame parameter changes), scale to the output resolution, and apply speed, transition, and audio processing. Consider rendering each segment to an intermediate file (robust, resumable, cacheable by segment hash) and then concatenating, rather than one giant filter graph.
- **H.265/HEVC in MP4 for everything** (see §8.8). Default encoder is VideoToolbox HEVC for speed on Apple Silicon, with a software x265 option for quality. The per-frame yaw/pitch/roll/fov comes from the Phase 6 framing plan, not from the EDL. **Output is 4K UHD (3840×2160) at the input frame rate.** Per-segment files keep their **source clip's own frame rate exactly** (as a rational, e.g. the DJI's nominal 50 fps), so there is no retiming and timestamps stay exact. For the **final combined film**, one frame rate is needed: `output_fps: match_source` picks the most common source rate in the EDL (by duration), and any segment with a different rate is converted with a documented method (frame drop/duplicate by default, optional frame blending), with a warning listing which segments were converted. If most footage is 50 fps and some old Insta360 clips are 30 fps, the film is 50 fps and the older segments are duplicated frames. The user can force a fixed fps instead.
- Audio: mix the conditioned stems and music per the audio mix plan (§5c-3), loudness normalise to a configurable target (e.g. -14 LUFS for online), and prevent clipping. (Today the renderer copies the camera's audio or cuts it exactly for a segment; the mix is not wired in yet.)
- Output is 16:9 only (v1).
- Optional overlays: none by default (the map/GPX overlay happens in Phase 8).
- Write `timemap.json`/CSV (§6.3) **in the same step**, from the EDL, so the render and the map can't disagree.
- Produce a QA report: per-segment durations vs plan, dropped frames, encoding errors.
- Fast draft mode: proxy inputs, low resolution, for previewing an EDL quickly.

**Test cases**
- P7-01: A synthetic marker at known yaw/pitch, framed by a static path, appears at the frame centre in the output (pixel tolerance).
- P7-02: A moving path produces a marker trajectory consistent with the path, to within a tolerance.
- P7-03: Output duration equals the EDL duration within one frame; audio and video streams are within 20 ms of each other.
- P7-04: A cut boundary in the rendered file falls on the frame corresponding to the planned time (check via frame-difference detection at the cut).
- P7-05: Source with dropped frames (the DJI's nominal 50 fps with 60 ms gaps) rendered at its own nominal rate: gaps are filled by frame duplication so the output is constant frame rate, frame timestamps are exact rational multiples with no drift over a 5-minute test, source time still maps correctly to UTC across the gaps, and A/V stays within 20 ms.
- P7-17: Output is 3840×2160 for every segment and the final film (ffprobe), at the source fps for segment files; the final film uses the most common source fps and lists converted segments in the QA report.
- P7-18: Mixed-fps EDL (a 50 fps and a 30 fps segment): the film's fps is the duration-weighted majority, the minority segment is converted with the configured method, the timemap and per-segment UTC times are unaffected, and a warning names the converted segment.
- P7-19: Effective-resolution report: for a shot at 90° FOV the reported source-pixels-per-output-pixel is about 0.5; a tighter FOV reports proportionally less, and a shot below the configured threshold is flagged (information only; the render is still 3840×2160).
- P7-22: Segment range: `--start S --end E` renders exactly the source frames in the range (frame count and first-frame time match the plan within one frame; the per-segment UTC start equals `clip.start_utc + first frame t_s`), including a range that contains a dropped-frame gap. (Verified manually on the sample: 1.0 s to 3.0 s gives 101 frames, 2.02 s.)
- P7-23: Audio: the muxed audio of a segment is sample-exact against the source (cross-correlation lag 0 samples, correlation at least 0.999), and the audio and video durations agree within one audio frame (verified on the sample: lag 0, correlation 1.0000, 2.02 s each). A whole-clip render copies the AAC stream bit-exactly.
- P7-24: Camera-path warnings: a path with peak acceleration or speed above the configured limits, or abrupt velocity changes at keyframes, prints a warning naming the cause (implemented, `path_warnings`).
- P7-21: The render is sampled from the full-resolution master (a fixture with a fine test pattern shows detail beyond what the proxy can carry), and a 4K render never passes through a lower-resolution intermediate (checked from the render log and a frequency-content test).
- P7-20: 4K render speed benchmark on the target Mac is recorded and stays within a documented budget (see the renderer risk in §11).
- P7-06: Speed 1.05 segment: duration scales correctly and the timemap slope is 1.05.
- P7-07: Resumability: killing the render mid-way and re-running re-renders only unfinished segments; the final output is identical to an uninterrupted run (bitwise for software encode with fixed settings, perceptually for hardware).
- P7-08: Output dimensions and aspect are exactly the configured 16:9 size.
- P7-09: Loudness of the final mix is within ±1 LU of the target; true peak below the ceiling.
- P7-10: Music ducking is audible: RMS of music drops by the configured amount under speech segments (measured).
- P7-11: `timemap` from a render of a synthetic clip with a burned-in UTC clock matches the on-screen clock at 10 sampled points within one frame.
- P7-12: Crossfade transition: the mapped time follows the midpoint rule in §6.3 and the total duration accounts for the overlap.
- P7-13: Missing master file: fail before any rendering starts, with a helpful message.
- P7-14: Draft mode is at least 5× faster than the full render and produces the same timeline (durations, cuts).
- P7-15: Hardware and software encoders both produce a playable HEVC MP4 with the `hvc1` tag (plays in QuickTime/Safari), the configured profile (Main or Main 10), and pixel format; ffprobe checks codec name, tag and bit depth.
- P7-16: Every video file the pipeline writes (masters, proxies, per-segment files, final film) is HEVC in MP4 (a scan of the working directory finds no other video codec).

---

### Phase 8: GPX / map handoff

**Purpose:** give the existing moving-map renderer everything it needs. The map renderer is out of scope, so this phase defines the interface and validates it.

**Behaviour**
- **Confirmed (30 Sep):** the map renderer is `gopro-dashboard-overlay` (fork `github.com/jburnhams/gopro-dashboard-overlay`, cloned at `../gopro-dashboard-overlay`). Its branch **`support-mp4-creation-datetime`** adds `--video-time-start mp4-created`: with `--use-gpx-only --gpx RACE.gpx` it reads the MP4 `creation_time` tag (whole seconds, ISO from ffprobe `format.tags`) and the duration, places the file on the GPX and renders the overlay for that span (it refuses when video and GPX do not overlap in time). So the assumption below is right: **one MP4 per segment, `creation_time` = true UTC of its first frame.** The renderer writes it (`--start-utc`, added to `strata360.render.flat`), rounded to the nearest second, and stores the exact value in the `comment` tag and in `<file>.utc.json`. Notes: the tool needs Python 3.11+ to parse a trailing `Z`; creation_time must be UTC (it compares against the GPX in UTC); the fork's `mp4-created` needs the branch merged into main or checked out; a possible small fork change is to prefer the exact `comment` value for sub-second placement. The tool needs pycairo (system cairo: `brew install cairo pkg-config`).
- **Verified end to end (30 Sep, synthetic GPX):** a 1080p segment rendered with `--start-utc` went through `scripts/overlay/overlay_segment.sh` and came out with the map, coordinates, altitude and clock at the right time. Findings: (1) the tool's default output is 8-bit H.264 veryfast, so use the supplied profile `hevc10` (`scripts/overlay/ffmpeg-profiles.json`: overlay then 10-bit HEVC at 150 Mbps, BT.709 tags kept); (2) on the local fork branch `mp4-exact-start` (one commit on top of `support-mp4-creation-datetime`, not pushed) the exact start from the `comment` tag is used, so the clock read 14:00:09.8 for 12:00:09.86 UTC instead of being off by up to 0.5 s; (3) the on-screen clock uses the machine's timezone, not the race's; (4) the overlay is generated at 10 Hz and composited onto any frame rate; (5) map tiles are fetched from the internet and cached in `.cache/gdo`; (6) setup: `brew install cairo pkg-config`, `.venv-overlay` with the fork's requirements unpinned and `setuptools<81` (pkg_resources), and `--font` given explicitly.
- **Earlier assumption:** MP4 files; the mechanism for how it learns each clip's time was unconfirmed (see open question 1). The design supports both plausible options, and the assumption is that the map renderer reads the standard MP4 `creation_time` tag (and duration) of each input file.
  - **Option A, per-segment MP4s (assumed default):** the render writes each selected segment as its own MP4 with `creation_time` set to the segment's **true UTC start** (`clip.start_utc + clock_offset + src_in_s`), and a filename that encodes order. The renderer places each file on the GPX by its `creation_time` and duration. Requires: no speed changes (speed 1.0, so the file's duration equals real elapsed time; a 1.05× segment would make the map run 5% fast, so speed adjustment stays off unless the renderer supports it), and hard cuts inside a segment boundary (no overlapping crossfades between files). The final combined film is also produced, but with its own `creation_time` set to the first segment's UTC so a renderer that reads only one file is not badly off.
  - **Option B, timemap file:** `timemap.csv` (columns: output_time_s, utc, segment_index, clip_id, speed, is_transition), sampled per frame or at 0.1 s, plus the piecewise-linear segment table. For a renderer that takes the combined film.
- **Position jumps: teleport.** When consecutive segments come from different points on the course, the map marker simply jumps at the cut. No "fly" animation, no hold. This needs no data from us beyond the correct times, but we still emit a **discontinuity list** (each cut where UTC jumps by more than a threshold, with the gap length) for review and the report.
- **Consistency checks:** every segment's UTC must fall within the GPX time range (warn and name the segment otherwise); segment times must be strictly increasing when chronological order is on; and the `creation_time` read back from each written MP4 (with ffprobe) must equal the plan to the millisecond.
- **Timestamp precision:** MP4 `creation_time` normally stores whole seconds. If sub-second accuracy matters to the renderer, the exact start is also stored in a sidecar JSON next to each MP4, and the segment's start is rounded to a whole second only if the renderer needs it (record the rounding error, up to 0.5 s). Decision: cut points are free to be on any frame, so the sidecar is the source of truth.

**Test cases**
- P8-00: Every rendered segment MP4 has a sidecar JSON (§5.8) whose `utc_start`/`utc_end` equal `clip.start_utc + src_in/out` exactly, and `film.json` lists all segments in order.
- P8-01: For a fixture EDL of 5 segments, every segment MP4's `creation_time` (read back via ffprobe) equals clip start + clock offset + in-point, within 1 s (the container's precision), and the sidecar JSON has the exact value.
- P8-02: A segment's MP4 duration equals its planned duration within one frame, so `creation_time + duration` equals the true UTC end.
- P8-03: A cut between two segments from different points on the course appears in the discontinuity list with the correct UTC gap.
- P8-04: A segment whose UTC is outside the GPX time range triggers a warning naming the segment.
- P8-05: Segments are ordered by increasing UTC when chronological mode is on, and the filenames sort in the same order.
- P8-06: With speed adjustment enabled, Option A output is refused (or warns) because durations would no longer equal real elapsed time; Option B's `timemap.csv` shows the correct slope.
- P8-07: The map renderer accepts the generated MP4s and places them correctly (contract test to be written once we have the renderer's sample input).
- P8-08: End-to-end: synthetic segments with a burned-in clock and a synthetic GPX moving at a known speed yield a map position at each segment start matching the expected position within a tolerance.
- P8-09: Timemap transition frames follow the midpoint rule of §6.3 in both the render and `timemap.csv` (Option B only).

---

### Phase 9: MCP / conversational interface (optional, after the batch pipeline works)

**Purpose:** let a user work with Claude interactively over the pipeline's artefacts, e.g. "swap the fourth segment for something with more people", "make the aid-station section longer", or "why did you pick this?".

**Proposed tools** (thin wrappers over library functions; none contain business logic):
- Catalogue: `list_clips`, `get_clip_summary(clip_id)`.
- Inspect: `get_frames(clip_id, t, yaw, pitch, fov)` returns a still for the LLM to view, `get_transcript`, `get_candidates`.
- Edit plan: `get_edl`, `pin_candidate`, `ban_candidate`, `swap_segment`, `set_target_duration`, `set_music`, `solve` (re-run phase 5 with the changes), `explain_segment`.
- Render: `render_draft`, `render_final`, `export_timemap`.

**Guidelines:** long-running jobs return a job ID and a status tool rather than blocking; all mutation goes through the same override files as the CLI so the state is always inspectable and versionable; tools return small text/JSON plus optional images (no giant payloads); safe by default (no deleting raw or master files).

**Test cases**
- P9-01: Each tool has a schema, and invalid arguments are rejected with clear errors.
- P9-02: `pin_candidate` followed by `solve` yields an EDL containing the pin, and the override file on disk reflects it.
- P9-03: `get_frames` returns an image with the requested projection (verified on the synthetic marker).
- P9-04: Long-running `render_final` returns a job ID; status reports progress and completion; a cancelled job leaves no partial output marked complete.
- P9-05: Tool calls are idempotent where documented (repeating `ban_candidate` doesn't corrupt the state).
- P9-06: No tool can read or write outside the race working directory (path traversal test).
- P9-07: Concurrent calls (two solves) are serialised or rejected safely.

---

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
- Cost tracking and per-race budget caps (§P2-11).
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

## 9. Handoff contract to the existing map renderer (summary)

- Input to the renderer is MP4. Assumed: it reads each file's `creation_time` and duration and places it on the GPX. We therefore write per-segment MP4s with true-UTC `creation_time`, keep speed at 1.0, and use hard cuts (Phase 8, Option A; the segment sidecar JSONs of §5.8 are the authoritative time record). A `timemap.csv` (Option B) is also produced.
- Jumps between clips are teleports. Nothing extra is required from us.
- **Open item:** confirm how the renderer really obtains timestamps (the `creation_time` tag, filename, or a sidecar) and its precision, then write contract test P8-07.

---

## 10. Milestones (suggested order)

1. **M0: Stitch spike.** Convert the sample OSV to equirect with ffmpeg; compare to the LRF; decide the stitching approach and stabilisation route; benchmark a 4K flat render from the master (ffmpeg `v360` on the CPU versus a GPU path). Gate for everything else. (P1 acceptance criteria.)
2. **M1: Time and timemap skeleton.** Phase 0 plus a minimal EDL → render → timemap path with hand-written EDLs and the synthetic test clips. Proves timestamp preservation and framing maths before any AI is involved.
3. **M2: Analysis.** Phase 2 (shots, audio, speech, subjects, quality) with the vision captions behind a cache and a budget cap.
4. **M3: Proposals and attention map.** Phases 3 and 4 (including protagonist identification and its review sheet), with overlay previews and human override files.
5. **M4: Master assembly and framing without music.** Phase 5 (selection, coverage, chronological order, target duration) and Phase 6 (framing solve). Handoff to the map renderer (Phase 8), first real end-to-end race film.
6. **M5: Beat sync.** Music analysis and cut alignment, the flexible-length logic.
7. **M6: Second camera and polish.** Insta360 adapter, MCP interface, face blur, HTML race report.

---

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| DJI dual-fisheye stitching quality with ffmpeg is insufficient (seams, parallax, calibration unknown) | Blocks everything | M0 spike first; fall back to vendor SDK/desktop export as a scripted step; use the LRF as a reference. |
| Camera clock wrong (no GPS available to check it) | Map overlay misaligned | Trust the clock, but run the consistency checks and offer the config offset and manual anchors (§6.2); check the Insta360 clock separately. |
| LLM picks the wrong subject or a boring moment | Poor edits | Deterministic candidate generation + scoring; the LLM only ranks; verification loop; human overrides; alternatives report. |
| Wrong person identified as "me" (look-alikes, hats, night, back views) | Film focuses on the wrong runner | Multi-cue identity (face, bib, appearance, track continuity), calibrated thresholds, `uncertain` state, one-time review sheet with corrections, tests P2-16 to P2-24. |
| Deferring framing makes Phase 5 choose trims that can't be framed well | Bad shots | Framing-feasibility scoring in Phase 5, guaranteed `defaults`, and the Phase 6 → Phase 5 feedback loop (P5-20/21, P6-14). |
| ffmpeg `v360` is CPU-bound, so 4K at 50 fps with per-frame camera parameters may render slowly | Long renders | Benchmark early (M0/M1); fall back to a GPU (Metal) or OpenCV-remap renderer behind the same interface; render per segment in parallel; draft mode uses proxies. |
| 4K flat frames upsample about 2× from the source at 90° FOV | Soft-looking shots | Accepted (4K is for the overlay detail). Render from the full-resolution master with a high-quality scaler, soft-minimum-FOV preference, effective-resolution reporting. |
| Jittery or nauseating camera paths | Unwatchable | Deterministic smoothing with velocity/accel limits; horizon lock; tests P6-02/04. |
| Beat sync infeasible with rigid clips | No sync | Handles and cut points designed up front; fallbacks; optional micro speed change. |
| Vision-model cost blows up | Budget | Prefilter, sparse sampling, batching, caching, budget caps. |
| Huge intermediate files | Disk full | Preflight checks, configurable master resolution, cleanup option. |
| Insta360 format differences (`.insv` pairs, proprietary gyro trailer) | Delay | Adapter interface; get real sample files early; may need a third-party parser or the vendor SDK. |
| Fractional-fps and VFR timing errors | A/V drift, timemap errors | Rational timebase everywhere; drift tests P1-05, P7-05. |
| Audio in wind and heavy breathing dominates | Bad audio | Wind detection, a mute/duck policy, music-forward mixing. |

---

## 12. Open questions and decisions

**Decided**
- The camera is held on a short selfie stick by the user, so the user is normally the closest, persistent person at a constant bearing.
- "Me" is identified by the user selecting their track on a sheet once. The profile is saved and reused (reference photos optional).
- Output is 4K UHD (3840×2160), at the input frame rate. Mixed-fps films use the majority rate.
- Output is 16:9 only.
- The map renderer takes MP4; position jumps between clips are simple teleports.
- The camera has no GPS in the clip metadata, and the camera clock is trusted (container `CreateDate` is UTC).

**Still open**
1. How exactly the map renderer reads time from each MP4 (the `creation_time` tag, filename, or sidecar), and to what precision. This decides between Option A and Option B in Phase 8.
2. Are the Insta360 clocks correct and in which timezone? The cameras may differ.
3. Typical clip length (still unknown; the sample is under 5 s).
5. Music source and licensing, and whether the tracks are constant-tempo.
6. Is chronological order strictly required, or are occasional flashbacks or intro teasers allowed?
7. Face-blur requirements for other runners and spectators (identity recognition of the user is local-only, see §8.6).
8. Whether you want to add reference photos on top of the "which one is me?" selection (optional).
9. Which LLM/vision provider and monthly budget?
10. Any Insta360 sample files available to test the second adapter early?

---

## 13. Definition of done (v1)

- Point the tool at a race folder plus a GPX, and receive: `edl.json`, a review report, a draft preview, and the final flat 16:9 video with its `timemap.csv`. No manual export from vendor software in the normal path.
- Every output segment carries the right UTC start (verified by reading the MP4 tags back) and no timing change breaks the map overlay.
- All test cases above are automated (except those marked as needing real footage or the live LLM suite, which run on demand).
- A re-run with no changes does no expensive work.
- Any decision can be overridden by a file edit and reflected in the next run.

---

## 14. Future work (flagged, not yet built)

Items known from the M0 spike (`progress.md`), roughly in priority order. None blocks the v1 pipeline; each is a quality or convenience improvement.

### 14.1 Stitching quality: OpenOSV stages not yet ported
Our stitch (calibration-based, linear-light, occlusion-aware, 16-bit) matches DJI's raw export closely (correlation 0.97–0.98) but only applies OpenOSV's *basic* blend. The stages below exist in [OpenOSV](https://github.com/Kemerd/OpenOSV) (Apache-2.0) and are the main remaining differences. They matter most for a selfie-stick clip, where the user's hand and body sit right at the seam.

| Stage (OpenOSV) | Purpose | Expected benefit here | Notes |
|---|---|---|---|
| **Parallax warp** (DIS optical flow, `ParallaxWarp`) | 2-D correction of parallax in the seam band | **Highest**: the hand and arm next to the lens show ghosting or doubling at the seam | GPU friendly; biggest single piece of work |
| **Seam disparity search** + 1-D seam shift (`searchSeam`) | Align the lenses for close objects, per column and per bucket | High, and a prerequisite for the warp | Per bucket of 8 frames |
| **Carved seam** (dynamic-programming seam carving, `SeamCarve`) | Choose where the two lenses meet, avoiding faces, hands and edges | High for shots framed across the seam | Rendering only |
| **Photometric seam field** (`PhotoSeam`) | Rim-aware weights plus a 2-D log-gain field, SSIM-gated | Medium/high: the proper fix for lens gain mismatch, which the simple exposure match cannot do on wet-lens, near-object clips | Would replace the (currently disabled) exposure-match gain |
| **Lens shading correction** (`LensShading`) | Adds back missing veiling glare near the rim, per lens | Medium | Measured from each lens's own sky |
| **Flare removal** (`Flare`) | Sun ghosts | Low for this clip | Optional |
| **Two-band seam smoothing** (`SeamTools`) | Glide the low-frequency difference across a wide band | Cosmetic | Optional |
| **Clip-steady mode** (`ClipSteady`) | One correction per clip instead of per bucket | Not applicable to a hand-held stick (near objects move) | Useful for rigid mounts |
| **D-Log M / HLG decoding and the DJI Rec.709 look** | Non-Normal colour modes | Only if footage is shot in D-Log M | Curves and LUTs are published in OpenOSV (`luts/`) |

Alternative for all of the above: build OpenOSV (Metal backend, community-tested on Apple Silicon) and use its stitch, then reframe from its equirect output. The cost is a large build (vcpkg compiles ffmpeg and about eight libraries), the loss of the single-resample fisheye renderer for the stitched part, and its CLI cannot do animated reframing. Decision deferred until we know how much the seam quality matters for the final film.

### 14.2 Stabilisation and camera behaviour
- **Heading-follow stabilisation: implemented (v1), `spike/camera.py`, `render4k.py --mode heading`.** Definition: keep the horizon level (remove roll and pitch shake, as world-lock does) but let the view's left–right direction follow where the runner is heading, smoothed so it turns gently through bends and ignores arm swing and wrist twist. The two extremes it sits between: *body-locked* (fixed to the camera, shakes and turns with the stick) and *world-locked* (fixed in the world, points the wrong way once you turn). v1: the heading is the horizontal direction of a chosen body axis (default the front lens, i.e. away from the user on a selfie stick, so it works even when the camera is tilted down about 57° as in the sample), smoothed with a zero-phase Gaussian (default σ 2 s) on the unwrapped angle (offline, no lag); frames where the axis is nearly vertical are filled from their neighbours (never spun); the ends of the clip use a trend-preserving extension. Measured: arm swing (8° at 1.8 Hz) leaks 0.05° in the interior and 0.6° at the clip ends. Still to do: automatic choice of the heading axis; a heading from motion cues (GPS-free velocity, or the GPX when the clip is aligned) instead of the camera axis; a causal version for live previews; a maximum turn rate; a lock-to-target mode (keep the user or another subject centred) once identity tracks exist.
- **Keyframed camera paths: implemented (v1)**, JSON with yaw, pitch, roll, field of view and easing per keyframe, relative to the world, the smoothed heading, or the camera body (format in `spike/camera.py`, example `spike/example_path.json`). Interpolation: monotone cubic spline (default, continuous velocity), smoothstep or linear; yaw takes the short way round the ±180° seam; optional extra smoothing; a limits report (peak speed, acceleration, field-of-view rate) and warnings, which caught abrupt velocity changes from mixing easing types at a key. Still to do: the framing solver (Phase 6) that generates these paths from the attention map, per-path speed and acceleration limits enforced automatically, and a subject-aware zoom.
- **Rolling shutter and sub-frame interpolation**: attitude is used per frame; the 20 higher-rate quaternions per frame (`FrameMeta.3`) could correct rolling-shutter skew and fast rotations.

### 14.3 Rendering
- **Audio: implemented (v1).** A whole-clip render copies the OSV's AAC bit-exactly; a sub-range (segment) is cut accurately and re-encoded as AAC 256 kbit/s. Verified sample-exact against the source (lag 0 samples, correlation 1.0000) and the output length matches the video. Still to do: music mixing and ducking, crossfades between segments, loudness normalisation, and 4-microphone/spatial audio handling.
- **Performance:** about 10 fps at 4K looking at the user, about 5 fps for a stabilised view across the seam, on an M4 in Python/OpenCV. Options: a Metal port of the per-pixel kernel (as OpenOSV does), cutting the 16-bit read (88 MB per lens frame) by decoding YUV directly and converting on the GPU, and skipping the second lens when the view is inside one lens.
- **Resampling quality:** bicubic is used; Lanczos is 5× slower. Compare sharpness against DJI at full resolution.
- **HDR and log:** the pipeline is SDR BT.709 (Normal mode). D-Log M and HLG inputs need the transfer functions above.

### 14.4 Colour and exposure
- **Auto gain / exposure matching in the final render**, driven by `exposure.json` (§5.9): per-shot exposure and tone adjustment, temporal smoothing, consistency across neighbouring shots, highlight protection. OpenOSV-style lens-to-lens gain is implemented (`spike/photo.py: estimate_gain`) but disabled because it is unreliable on this footage until the photometric seam field exists.
- **A "match DJI look" option** is not planned: DJI Studio's export applies an undocumented, scene-adaptive lift (measured 5–13% in linear light), which is not a good absolute reference.
- **10-bit end to end:** the encode is 10-bit Main 10 from a 16-bit render. If a future step needs more range, keep floating point in the render.

### 14.5 Data and analysis
- **Detector benchmark to finalise the proxy settings.** The proxy defaults (3840×1920, 12.5 fps, about 80–100 Mbit/s) are provisional: the sample clip contains too few people and faces (3 and 3 in 24 frames) to measure detection recall against resolution and bitrate. Once real detectors and the identity model exist, run them on lossless renders versus each candidate proxy on several race clips, then fix resolution, fps and bitrate.
- **On-demand frame and crop API** (`recrop(clip, source_frame, yaw, pitch, fov, size)`), rendering straight from the source lens frames, for identity, vision-model stills and the framing verification loop.
- **Use the camera's `.LRF` only as a fast triage source.** It is frame-synchronous with the OSV (correlation 0.998–0.999 at zero frame offset), tiny and instantly decodable, but soft (about half the detail of our render at 3840×1920) and H.264 8-bit, so it suits cheap jobs (exposure statistics, shot and motion detection, cut proposals) and never detection or recognition. It is dual-fisheye and needs our own projection anyway; other cameras' proxies differ.
- Per-clip export of **view-level** statistics from the actual render (every frame) to complement the sphere-level `exposure.json`.
- **Exposure metadata semantics:** `FrameMeta.2.15` (values such as 10.75, 181.65, 1.114 ×3, 8.04, 2.0) and the accelerometer block are undecoded; they may hold digital gains or white balance.
- Verify the IMU-offset matrices (`osmo360_imu_offsets.npy`) on a second clip and on the Insta360 (different camera, different conventions).

### 14.6 Audio: what is left
Implemented (v1): analysis and labelling (§5.10), the three conditioning chains, loudness and true-peak measurement, the mix planner, a recogniser and two neural enhancers installed and evaluated, multilingual transcription with per-segment language identification, English translation and hallucination flags (§5.11). Still to do:
- **Choose enhancement per segment.** Enhancers helped only against wind and hurt in babble, so the chain should pick per segment from the labels (§5.10): wind-dominant speech gets DeepFilterNet3 (or MossFormer2) for the *mix*, babble and ambience are left alone, and recognition always uses raw audio.
- **Evaluate on real speech.** The WER numbers use synthetic (text-to-speech) speech in real noise. Build a small hand-checked transcript set from the library (the English clips with the most speech, and the French clip) and measure WER on it.
- **Translation quality.** OPUS-MT is fast and reasonable but not perfect (French sentences read well; "on va faire depuis les joueurs qui sont longs" translated literally is a recognition error upstream). Options: NLLB-200, or a local LLM, for better English, especially Dutch (Flemish) which whisper handles less well. Have a native speaker check a sample.
- **Whose voice:** speaker embeddings to tell the wearer from bystanders (shares the identity profile with the face work). Today "speech" means clear close voiced speech.
- **Better classification** than the heuristics (a small audio-event model for cheers, applause, wind, breathing, footsteps), and wind detection that works on dual-mono audio (no stereo cues). The Osmo 360's own wind processing visibly gates high frequencies on and off; handle that before judging bandwidth.
- **Spatial audio:** the OSV stores a stereo AAC mix of what may be four microphones; check whether the raw microphone channels are recoverable and useful for directional voice pickup and beamforming toward the wearer.
- **Segment joins:** crossfades between clips' audio, room-tone fill, and matching the ambience across cuts.
- **Music analysis link:** feed `music.json` (beats and sections) into the mix plan so swells and ducks land on bars.
- **Speed:** large-v3-turbo on the CPU transcribes about 1× real time; a Metal-accelerated build (whisper.cpp) would be faster.

---

## 15. Analysis data: what we collect so edit points and framing can be decided later

Principle: **collect broadly and richly now, decide late.** Every decision the editor and the framing solver will make needs some measurement of the footage; each measurement is a per-clip JSON artefact written by a cached pipeline stage (section 0), so a later change of taste, target length or music never means re-analysing the video. Status as of 2026-09-30.

### 15.1 What each decision needs

| Decision | Data needed | Status | Artefact / stage |
|---|---|---|---|
| **What is in the clip, and when** (UTC, duration, dropped frames, colour mode) | Clip facts and the definitive start time | Done (clock offset **unverified** for Belgium) | `clip.json` (`ingest`) |
| **Where on the course** (coverage, ordering, map handoff) | The camera clock checked against the GPX, then time to distance and position | **Missing** (needs the GPX and a check of the clock offset) | `course.json` (future stage `course`) |
| **Where is the speech, and where can we cut it** | Transcript, language, translation, accurate word times, safe cut points | Done (English alignment only) | `transcript.json`, `alignment.json` (`transcribe`, `align`) |
| **Who is speaking** (the wearer or someone else) | Voice embeddings and clusters, wearer voice profile, mouth-motion linking to faces | **Missing** | `speakers.json` (future stage `speakers`) |
| **Sound design** (ambience, crowd, levels, clipping) | Loudness, clipping, wind/speech/crowd/ambience labels | Done (heuristic labels) | `audio.json` (`audio`) |
| **Exposure and look consistency** | Brightness statistics, camera exposure metadata | Done | `exposure.json` (`exposure`) |
| **Camera state and shake** (held on the stick, hand-held, put down; how steady; impacts; turning) | Attitude and angular speed summaries from the telemetry; heading; tilt; stationary segments | **Missing (cheap, no downloads)** | `motion.json` (future stage `motion`) |
| **Where things are on the sphere over time** (people, faces, signs, scenery) | The upright analysis proxy video, person detection and tracking, target tracks with yaw, pitch and size | **Missing** | `proxy.mp4` (`proxy`, built but not run), `targets.json` |
| **Which one is me** (the protagonist) | Face detection and recognition, the "which one is me?" selection saved as a profile, appearance and bib cues | **Missing** (needs face models; design in section 7, item 6a) | `identity` profile, `targets.json` |
| **What is happening** (aid station, view, finish, group, crowd) | Captions and tags from a vision model on labelled views of the sphere | **Missing** (needs a choice of vision model, local or API) | `scenes.json` |
| **What to avoid** (thumb over a lens, wet lens, blur, glare, the stick, the seam) | Obstruction and quality flags over time | **Missing** (the stick polygon exists; dynamic obstruction does not) | `quality.json` |
| **How interesting is each moment** | Combination of the above (speech, energy, people, scene, novelty) | **Missing** (after the inputs exist) | `interest.json` (Phase 3) |
| **Candidate ranges and framing options** | Proposals with handles and cut points; attention map with look options | **Missing** (Phases 3 and 4) | `proposals.json`, `attention.json` |
| **What the user tends to choose** (taste) | The two flat exports from 15 March, if they are finished films: which moments the user kept | **Unexplored** (needs the user to confirm what they are) | `taste.json` |
| **Music alignment** | Beat and section analysis of the chosen track | Waiting for a track | `music.json` |

### 15.2 Recommended order (each step unblocks the next)
1. **Verify the camera clock against the GPX** (needs the GPX and one known point, such as the race start or a recognisable place) and add the `course` stage. Without this, ordering, coverage and the map overlay rest on an unverified hour. Cheap.
2. **`motion` stage from the telemetry** (no downloads): shake level, angular speed, tilt, heading, holding style, stationary and moving segments, impacts and cadence. It feeds candidate scoring, stabilisation choice and "wearer talking to camera" hints.
3. **Run the `proxy` stage over the whole library** (about 1 hour of compute and about 10 GB for these 16.8 minutes at the default 3840x1920, 12.5 fps, 80 Mbit/s; settings are provisional until the detector benchmark, section 14.5). Everything visual below needs it.
4. **People: detection and tracking on the proxy, then faces and the "which one is me?" selection** (models to download: a person detector such as YOLO and a face detector and recogniser, for example SCRFD and ArcFace; InsightFace weights are non-commercial). Output `targets.json` (tracks with yaw, pitch, size, identity).
5. **`quality` stage:** thumb and hand over a lens, rain drops, blur, glare, over- and under-exposure, seam parallax risk; combined from the exposure statistics, sharpness measures on the lens frames and the calibration's stick polygon.
6. **`speakers` stage:** voice embeddings, wearer voice profile, and mouth-motion linking to the face tracks (design in section 7, item 6b).
7. **`scenes` stage:** captions and tags from a vision model on labelled rectilinear views (needs a decision: a local model for privacy or an API for quality; cost and what leaves the machine).
8. **Phases 3 and 4** (candidate proposals and the attention map) become straightforward once the inputs above exist, then the master assembly and the framing solve.

### 15.3 Data completeness check
`./strata360 status RACE --all` shows which stages have run per clip; a `coverage` report listing which of the 15.1 artefacts exist for every clip (and which decisions are therefore not yet possible) is a small addition to the CLI.

### 15.4 Questions that gate the next steps
- The **GPX file** and any known anchor for the clock (start time, a photo or phone timestamp).
- Whether the two 15 March MP4 exports are **finished films** (taste data), and whether you have other finished films from earlier races.
- **Vision model:** local (private, weaker) or an API (stills of the footage leave the machine)?
- **Face and voice models:** approval to download the person and face detectors and the speaker-embedding model.

---

## 16. Edit techniques, variety and the joint optimisation

The final edit is not a chain of independent choices. Which shot to use, how long to hold it, which technique to apply (little planet, zoom-in, spin, pan, a steady hold...) and where the cut lands on the beat all interact: some techniques work only at certain lengths, some need particular content, and the whole film must not repeat itself. So the last stage is **one optimisation** over the whole timeline, with a controlled amount of randomness so the result feels varied and can be re-rolled. This section replaces the separate "select" and "frame" steps of Phases 5 and 6 with a joint formulation (those phases keep their data contracts; the framing solve still turns the chosen technique into a smooth camera path).

### 16.1 The technique library
A technique is a named, parametrised camera-and-projection program with the properties the optimiser needs (stored as data in `techniques.json`, one record each):

| Property | Meaning |
|---|---|
| `id`, `family` | `hold`, `pan`, `push`, `spin`, `little_planet`, `tunnel`, `whip`, `follow`, `look_around`, `dialogue_hold` |
| `program` | A template for the camera path over normalised time u in [0, 1]: yaw, pitch, roll, field of view and projection (`dist`, 0 = rectilinear, 1 = stereographic), with easing and parameter ranges (spin turns, pan angle, start and end field of view). Instantiated for a shot's real duration and content by the framing solve. |
| `duration` | `min`, `ideal`, `max` seconds, and preferred beat multiples (a spin resolves on a bar; a whip pan lasts a beat). Outside the range the technique is infeasible; inside, its fit falls off from the ideal. |
| `energy` | 0 (calm) to 1 (intense), matched against the music section's energy at that point, or against the desired pacing curve. |
| `needs` | Content requirements, each with a weight and where it is measured: steady camera (`motion.json`), clear nadir or zenith (`quality.json`, no hand over the lens), open ground or canopy (`scenes.json`, exposure grid), a subject in view (`targets.json`), speech present (`audio.json`, `alignment.json`), protagonist present, low obstruction, effective resolution (source pixels per output pixel, README 8.10). |
| `transition_in/out` | How it connects: a cut, a whip, a spin match, a planet-to-view zoom; and which techniques pair (a `little_planet_zoom_out` wants a planet or spin before it). |
| `hero` | Strong effects (both little planets, tunnel, spin) are rare by design: a hero cap per film and a longer cooldown. |
| `limits` | `max_share` of runtime, `max_uses`, `cooldown` in shots, `max_consecutive`. |
| `variants` | Randomisable parameters with seeded jitter: clockwise or counter-clockwise, pan direction, start yaw offset, turns 0.5, 1 or 2, planet centre. |

**Initial set** (all implemented in the renderer as camera paths except where marked): `hold_wide` (steady rectilinear about 100 degrees, 2-8 s), `selfie_hold` (body-locked look at the user, 2-15 s), `follow_runner` (heading-follow, 3-10 s), `pan_reveal` (slow yaw pan 40-90 degrees, 3-6 s), `whip_pan` (fast pan used as a transition, 0.3-0.6 s), `push_in` and `pull_out` (field of view 100 to 65 degrees and back, 2-5 s), `look_around` (yaw sweep of 180 degrees past the scene, 3-6 s), `spin_roll` (image roll of a full turn, 1-2 s, on a beat), **two kinds of little planet:** `planet_fill` (stereographic straight down at 250-300 degrees, the planet stretched to fill the whole frame, spinning, 2-6 s) and `planet_globe` (the entire sphere shown as a round ball on a background colour or a blurred copy of the scene, which shrinks to the globe or grows from it to fill the frame, 2-5 s); their transitions `planet_fill_zoom_out` and `planet_fill_zoom_in` (planet to rectilinear and back, 1.5-3 s) and `globe_shrink` and `globe_grow` (fill to globe and back, 1-3 s); `tunnel_up` (stereographic straight up through the canopy, 2-5 s), and `dialogue_hold` (section 16.4). **The renderer already supports the projections this needs** (`dist` in the camera path, 0 to 1, and fields of view up to 360 degrees; verified with a fill-planet spin that zooms out to the horizon, `spike/example_little_planet.json`), and the globe (`disc` and `bg` in the camera path; section 16.6).

### 16.2 The optimisation
**Inputs:** the music (beat and bar grid, section boundaries and energy) or a fixed duration; the candidate pool (every clip's proposed ranges with handles and safe cut points, README 5.3); for each candidate the feasible techniques with their content-based fit; user pins and bans; the variety settings.

**Decisions:** an ordered sequence of segments, each with (candidate, trim window, technique, technique variant), such that every segment boundary is on a beat (or, in the voice-over workflow, on a line boundary, section 17), the durations sum to the target exactly, and the clip is used within its handles.

**Hard constraints:** target duration; cuts on the beat grid (with the fallbacks of README 5c); each segment's duration inside its technique's `min` to `max` and inside the candidate's handles; overlapping ranges of one clip are mutually exclusive; technique caps and cooldowns (`limits`); no cut inside a word (only at `safe` cut points, README 5.11); chronological order if configured; a technique's `needs` marked hard (no planet with a hand over the lens).

**Objective (maximised):**
1. Candidate quality: interest score, protagonist presence, speech clarity, coverage of the course sections (README 5b).
2. Technique fit: how well the content meets the technique's `needs`, and how close the duration is to its ideal.
3. Energy match: technique and shot energy against the music section (or pacing curve) at that time.
4. Beat quality: preference for cuts on downbeats and section starts, effects landing on bars.
5. **Variety:** a bonus for the entropy of technique usage, for changes of scale (wide, medium, tight), direction (pans alternating), angle and location; a penalty that grows with each recent repeat of the same technique (novelty decay), a stronger one for hero techniques, a quadratic penalty for exceeding a technique's target share, a penalty for two adjacent shots that look alike (same technique, direction and scale), and a pacing term (shot lengths should vary, faster near the climax).
6. Penalties for constraint softening (a transition partner missing, a cut on a weak beat) and a small cost for each change of the user's pins.

**Randomness, on purpose.** All tie-breaks and technique variants come from a seeded random generator; a `temperature` softens the choice among near-equal options so two seeds give visibly different edits with similar scores. The planner returns the best plan and N alternatives that must differ by a minimum amount (measured as the share of segments whose clip, technique or length differs), so the user picks or re-rolls a single section.

**Solver.** The problem is small (hundreds of candidates, tens to a few hundred beats). Plan: a beam search over beat positions whose state keeps the recent technique history and running usage counts (so variety terms are exact along the path), followed by local search (swap a technique, replace a candidate, shift a boundary by a beat, split or merge) with seeded simulated annealing on the full objective. An exact model (CP-SAT) is kept as a checker for small cases. Every plan carries an explanation per segment (why this clip, why this technique, what it replaced) and a report of the variety statistics (technique shares, longest run without a change, hero count, repeat distances, and which constraints were tight).

**User controls:** pin or ban a clip, a technique or a time range; set a technique budget (for example at most two little planets); a variety slider (scales the variety terms); a seed; a locked-sections mask so a re-roll only changes the unlocked part.

### 16.3 Data
`techniques.json` (the library, versioned); `edit_plan.json` (the chosen segments: clip, source in and out, technique and variant, instantiated camera path reference, out time, beat position, explanation, alternatives and the variety report). The plan is `timed` and then `framed` exactly as the EDL of README 5.6.

### 16.4 Dialogue: steady, decently cropped framing on the speaker
When a segment plays the original speech (a clip with dialogue), the optimiser is restricted to the `dialogue_hold` family and its rules apply. They exist because speech is what the viewer follows, and shaky or showy framing competes with it.
- **Steady:** the world-locked or heavily smoothed heading-follow stabilisation (long time constant), no spins, planets, whips or field-of-view animation; at most a very slow push-in at an emotional peak (under 5% per second).
- **Decent crop:** a tighter medium framing on the speaker's head and shoulders (typically 60 to 75 degrees horizontally, chosen so the face fills roughly a quarter to a third of the frame height), centred with a little headroom and the space they face on the leading side, with the **minimum field of view respected** so the crop is not soft (the source has about 21 px per degree, README 8.10; the effective-resolution report flags too-tight crops).
- **Who:** the framing target is the active speaker from speaker attribution (section 7, item 6b); when the wearer speaks to camera the framing is the steady `selfie_hold` on them; if two people talk, hold the current speaker and cut (or a two-shot if both fit) at pauses between their turns, never mid-word; if the speaker cannot be identified, fall back to the steady wide view of the group.
- **Timing:** the hold lasts the whole phrase; the in-point comes shortly before the first word (about 60 ms before the aligned start) and the out-point after the last word (about 120 ms), at `safe` cut points only, so the words are never clipped (README 5.11).
- **If the speaker leaves the frame or is occluded:** hold, then ease to the wide fallback; never snap.
- **Audio:** the original dialogue sits at the front of the mix; music ducks under it (README 5c-3).

### 16.6 The two little planets (rendering)
- **Fill planet:** the stereographic projection (`dist` = 1) looking straight down (or up for the tunnel) with a field of view of about 250 to 300 degrees: the ground becomes a disc at the centre and the sky and trees are stretched out to the edges, filling the frame. Animating `(fov, dist)` from (260, 1) to (95, 0) is the zoom out into a normal view. Implemented and verified.
- **Globe:** the whole sphere is mapped into a round disc (azimuthal equidistant: the radius grows with the angle from the view axis, ground at the centre, horizon halfway out, sky at the rim) of a chosen radius `disc` (in units of the frame's half-width), and everything outside the disc is filled with a background: a solid colour (`bg`: [r, g, b]) or a **blurred, darkened copy of the fill planet** (`bg`: "blur"), which is the popular look. Two more backgrounds take their colour from the ball itself: `bg`: "rim" (the average colour of the rim, solid) and `bg`: "gradient" (each rim colour spreads outwards in its own direction, so blue at the bottom and green at the top blend smoothly, then merge into the average rim colour with distance; `bg_spread` sets how far, default 1.5 half-widths; examples `spike/example_globe_gradient.json`, `example_globe_rim.json`). **Tuning the gradient** (path-file keys): `bg_band` (pixels just inside the rim that are sampled, default 40: a thin band makes the background continue the video exactly, a wide one gives a smoother average), `bg_smooth` (degrees of smoothing around the rim, default 8; thin plus small smoothing gives radial streaks at the rim that soften outwards) and `bg_spread` (distance over which it merges into the average rim colour). `bg_inset` (pixels skipped at the very edge, default 6, to avoid the dark lens-edge hairline) and `bg_pick` ("vivid", the default: saturated, bright samples in the band count more, so a strong orange edge wins over grey-brown; or "mean"). Examples: `example_globe_gradient_vivid.json`, `_mean.json`, `example_globe_gradient_thin.json` (2 px, 0.3 degrees, 1.0) and `_wide.json` (40 px, 8 degrees). For a sky-facing rim the result is mostly sky-coloured, so the effect is subtle on grey days. Animating `disc` from large (only the middle of the planet fills the frame) to small (a small ball) is the shrink to a globe, and the reverse the stretch to fill the frame. The edge of the disc is anti-aliased. Both kinds spin by animating `yaw` (or `roll`) and share the requirement of a clear nadir (no hand over the lens) and a steady camera.
- **Known gap:** a small hole remains where the selfie stick itself blocks both lenses at the nadir; it is filled black (an inpainting step is future work).

### 16.5 Tests
- P5-24: The technique library validates: every record has a duration range, energy, needs and limits; the renderer can instantiate every technique into a path that passes the path limits report.
- P5-25: Beat and length: on a synthetic score every cut is on a beat and the total is exact; no segment falls outside its technique's duration range; spins resolve on a bar.
- P5-26: Variety: over 50 seeds and a fixture of 60 candidates, no technique exceeds its `max_share`, hero techniques stay within their cap and cooldown, the longest run of one technique stays under the limit, and the mean entropy of technique usage is higher than a greedy top-score baseline by a set margin.
- P5-27: Seeds: the same seed gives the identical plan; different seeds give plans that differ in at least the configured share of segments while their objective scores stay within a set percentage of the best.
- P5-28: Hard content rules: a candidate with a hand over the lens is never given a little planet, a tunnel or a spin; a shaky candidate never gets `hold_wide`; dialogue segments only receive `dialogue_hold` techniques.
- P5-29: Dialogue framing: on a fixture with a known speaker the crop keeps the speaker's head in frame the whole phrase with no camera motion above the limit, never cuts inside a word, and respects the minimum field of view.
- P5-30: Pins and bans, budgets and locked sections are honoured, and a re-roll of an unlocked section leaves the locked sections byte-identical.
- P5-37: Planets: the globe's disc has the configured radius (within a pixel), the area outside it is exactly the background (solid colour, or the blurred fill planet), the edge is anti-aliased, and animating `disc` gives a continuous shrink with no jump in the picture between frames; the fill planet and the globe show the same scene content at the same orientation.
- P5-31: Every plan carries the explanation and variety report, and an infeasible request (target too long for the footage, technique budget impossible) yields a specific error naming the binding constraint.

---

## 17. The voice-over-driven workflow

An alternative to fitting shots to music alone: **the narration decides the timing**. The system drafts a script from the transcripts of all the footage, the user records it, and the picture is then fitted exactly to what was recorded, so there is always footage on screen and clips with dialogue play in deliberate pauses.

### 17.1 Flow
1. **Analyse everything** (section 15): transcripts with translation and accurate word times, speakers, scenes, quality.
2. **Story pass.** Choose the narrative beats and, for each, the shots and any dialogue clip that carries it; draft the script (an LLM draft from the transcripts, reviewed and edited by the user).
3. **Script output** for the user to read: numbered lines, each with an estimated duration, and the gaps marked, for example `[DIALOGUE: clip 0023, 12:31-12:38, "and then we lost the trail" (translated from French) - leave 6.4 s]`, `[MUSIC ONLY 3 s]`. Formats: Markdown and a printable or teleprompter HTML page, plus `script.json`. Timing estimates come from words per second plus pause allowances (comma 0.25 s, sentence 0.5 s, paragraph 0.9 s) using **the user's own reading rate**, measured from a short calibration reading. For reference, the spontaneous on-the-trail speech in the Belgian library measures 3.55 words/s (213 wpm; 3.9 words/s with pauses removed), median phrase 3.3 s, median pause between phrases 1.3 s, 0.9% fillers; deliberate narration is normally slower (about 2.5 words/s), so the calibration matters and the plan tolerates plus or minus 15%.
4. **Record** the voice-over (the user follows the script, leaving the marked pauses).
5. **Fit pass.** Transcribe the recording and force-align it **to the script text** (the text is known, so the alignment is much more accurate than from recognition alone; same tools as README 5.11) to get every line's start and end, the pauses between them and word times. Multiple takes: the best per line by alignment score or the user's pick. Result `vo.json`.
6. **Re-plan with the recording as fixed anchors** (the joint optimisation of section 16 with extra hard constraints): every line's recorded interval is fixed on the timeline; the picture is never empty; each narration line gets the shots assigned to it, with durations flexing to fit the line; a dialogue clip is scheduled in its pause, trimmed at safe cut points to the pause length (or, if the recorded pause is longer, extended with ambience and a steady hold); shot boundaries prefer line boundaries and pauses inside lines; techniques still obey section 16 (a hero technique on a long line, dialogue holds in pauses). Where a recorded pause is too short for its dialogue clip even after trimming, the tool reports the shortfall by name and offers to re-record only that pause.
7. **Mix.** Music ducks under the voice-over using the exact line times; dialogue clips play at their own level in their pauses; ambience swells in the gaps (README 5c-3).
8. **Iterate:** re-record a single line and only the affected part of the timeline is re-fitted.

### 17.2 Data contracts
- `script.json`: lines with `id`, `kind` (`narration`, `dialogue`, `music`, `silence`), `text`, `est_duration_s`, the rate used, `linked_shots` (candidate ids with roles) and, for `dialogue`, the clip, in and out, the original transcript and its English translation and the reserved pause length.
- `vo.json`: the audio file, takes, and per line: chosen take, `t0`, `t1`, word times, leading and trailing silence, the pauses that follow, alignment score and loudness.
- The fit pass writes a normal `edit_plan.json` (section 16.3) with the voice-over anchors marked fixed.

### 17.3 Later, optional
Use speech recognition as a **live guide while recording**: a teleprompter that follows the reader's position from streaming recognition and shows pace against the plan; automatic take selection; pace and pause coaching.

### 17.4 Tests
- P5-32: Timing estimate: the estimated duration of a script line is within 15% of its recorded duration on a set of recorded test lines once calibrated to the reader; the calibration step reports the measured rate.
- P5-33: Forced alignment of a recording to its script gives line boundaries within 50 ms of hand-marked truth on a labelled set, and a missing or repeated line is detected and reported.
- P5-34: The fitted plan has footage on screen for every instant of the voice-over (no gaps), every dialogue clip lies inside its pause and is trimmed only at safe cut points, and the total equals the voice-over plus music-only sections exactly.
- P5-35: A recorded pause shorter than its dialogue clip is reported with the exact shortfall; re-recording only that pause and re-fitting changes nothing outside the affected sections.
- P5-36: Ducking follows the recorded line times: music is at least 10 dB down within 100 ms of each line start and recovers after each line end.


## 18. Workflow shape: batch everything, propose everything, edit in a fast GUI

**Principle.** Heavy work happens once, unattended, in batch. The GUI only reads precomputed data and changes small decisions, so every interaction is instant. The system proposes a complete film automatically; the user overrides what they dislike, and only the affected parts are re-planned.

### 18.1 Three tiers
1. **Batch (hours, cached, resumable): `strata360 run RACE`.** Everything in sections 5 and 15: ingest and UTC, audio, transcript with translation and word times, alignment and safe cut points, exposure, motion, people and faces, speakers, scenes and tags, quality, plus the **GUI assets** below. Nothing here needs the user, except the one-time "which face is me" choice (§15, `./strata360 who`) and confirming the camera clock.
2. **Propose (seconds): `strata360 propose RACE --music SONG --length 90`.** Reads the batch data and writes a full `project.json`: the plan (segments with clip, in/out, technique and parameters, seed), the framing, the audio mix plan, a suggested voice-over script with timings where clips have dialogue, and alternatives for each segment. This is the optimiser of §16 run with the defaults; several complete alternatives (different seeds) are stored so the GUI can offer "another version" instantly.
3. **Edit (interactive, instant) and render (minutes).** The GUI edits `project.json`; the final render turns it into MP4 segments with true-UTC `creation_time` (Phase 8) and the mixed audio.

### 18.2 What the batch must precompute for a fast GUI
- **Preview proxies:** one low-resolution equirect proxy per clip (960x480 or 1280x640, all keyframes or short GOP so scrubbing and reverse play are instant, about 5 Mbps; a few MB per clip) plus a poster strip (one thumbnail per second) and the audio waveform. The GUI shows any technique live by mapping the proxy onto a sphere in WebGL (a virtual camera driven by the technique's keyframe path, the same maths as `render/camera.py`), so changing a technique, its length or its look direction previews in real time with no server render. The final render always goes back to the full-quality lens streams.
- **Candidate list** per clip (windows with quality, energy, needs features, speech, protagonist score, min/max length, safe cut points), so the optimiser and the GUI do not decode anything.
- **Option table** (candidate x technique x length feasibility and score parts), cached, so re-planning after an edit takes a fraction of a second: only the unlocked segments are re-searched (the optimiser already supports pins, bans, budgets and locked sections).
- **Transcript** with words, times, translation, speaker and face on screen, so writing a voice-over script and moving cuts to word boundaries is a lookup.
- **Music analysis** (beats, bars, sections, energy) computed when a song is added (seconds), stored next to it.
- **Map data:** GPX-derived position and race progress per clip (so the GUI can show where each clip is on the course and warn about UTC outside the GPX).

### 18.3 The edit model (everything is a diff on the proposal)
- `project.json` holds the auto proposal **and** the user's overrides separately: a list of locks (segment fixed), pins (must include this clip or window), bans (never use), technique overrides (change technique, length or parameters of one segment), trims, and per-technique or global preferences (fewer planets, more pans, hero cap). The proposal is a pure function of (batch data, overrides, seed), so it is reproducible and undoable, and re-proposing never destroys a manual choice.
- Typical interactions and what they cost: swap a segment's technique, or clip, or nudge its length (instant: table lookup, keep the rest); "suggest again" for one segment or a section (sub-second re-plan of the unlocked part); change the song or the target length (seconds: re-plan everything unlocked); drag an edge to a word boundary (instant: safe cut points snap).
- **Voice-over mode:** the proposal includes a script (edited transcript text, with translations for foreign speech) with timings; the user records against it (§17); the recorded takes are aligned by the same forced-alignment tool, and the picture is re-fitted around them (only the affected segments).
- **Music mode:** the song's beats/sections drive the plan; the user can add markers ("hit here on this moment") that become fixed points.

### 18.4 The GUI (proposal)
A local web app (a small Python server plus a browser page: no cloud; reads the race folder), because WebGL gives the 360 preview for free, it works on any screen, and it stays separate from the batch code. Panels: timeline (segments coloured by technique, beat grid, waveform, map strip), preview (WebGL sphere of the proxy with the virtual camera; play, scrub), inspector (candidates and alternatives ranked, technique picker, length, look direction gizmo), transcript and script (words click to cut; record voice-over; per-line timing), audio (music, ambience swell, ducking, meters), map (clip positions on the course), render queue. Keyboard-first. The GUI never runs a heavy stage: if it needs data that is not there, it says which batch stage to run.

### 18.4a Who is me (auto-suggest, confirm once)
The batch clusters all faces across the race and proposes the wearer automatically: the person nearly always straight in front of the rear lens (the selfie stick) and seen in several clips, with clusters of the same person from other head angles merged (centroid cosine 0.4 or more). On Legends 2026 it picked the same clusters (101 and 103) the user chose. If the suggestion is confident it can be saved with `who --auto`; otherwise the GUI shows the cluster sheet with the suggestion pre-selected and one click confirms or corrects it. The profile (`profiles/me.npz`) is reused for every later race, where new faces are simply scored against it.

### 18.4b Clock panel (auto-detect, then tweak)
- **Auto first:** when a race is opened the batch has already run `clock --suggest` (votes from running starts/stops, weighted towards small offsets: a Gaussian around the current estimate, 15 min wide by default) and, if one offset is clearly ahead (at least 3 votes and 70% of the weight), applied it and re-timed the clips. The panel shows the offset, its confidence, and the list of matching events.
- **Tweak:** the panel shows the GPS speed/cadence trace (from the FIT) above the timeline of any selected clip's step energy, aligned with the current offset, with the detected running starts/stops marked on both. The user can (a) click a clip and the point on its timeline where the running starts, then accept the suggested GPS match or pick another candidate (`clock --anchor CLIP:T`), (b) drag the clip's trace sideways against the GPS trace and release to set the offset, or (c) type a value or a UTC for a point. Every change re-times the clips at once (only `ingest` re-runs) and the overlay tool's map position updates in the preview. The machine-readable form for the GUI is `clock --suggest --json`.

### 18.4c Start screen and project folders (GUI-driven batch)
The first screen of the app is "choose a folder of footage". Everything after that is decided by what is on disk:
- **Convention:** results live in a subfolder next to the footage, `<footage folder>/strata360/` (race.json, one folder per clip with all the per-clip JSON, run.log, cluster sheets, later `project.json` and renders). The footage folder is never modified. Every command takes either a race name (old layout under `races/`) or a footage folder path.
- **What happens on open (`strata360 open FOLDER`; the GUI calls the same code):** no project yet -> it is created (languages and the race GPS file are asked for once); a project exists -> it is read, everything already done is kept (per-clip, per-stage caching with keys, so changed settings only redo what they affect) and the unfinished work continues, with progress. When nothing is left, the screen moves on to results / export configuration.
- **State machine (`strata360 progress FOLDER --json`, polled by the GUI):** `new` (no project), `processing` (stages still to run; per-stage done/total, seconds per clip, estimated time left, overall percent), `needs_input` (only the user can continue: `wearer_profile` = pick which face is you, `camera_clock` = confirm the offset; the panels of 18.4a and 18.4b), `complete` (go to results / export). Stages that wait for a user choice (identity waits for the wearer profile) do not block the rest.
- **Idempotent and interruptible:** closing the app or a crash loses at most the clip in progress; reopening continues. One run at a time per project (lock). New footage added to the folder is discovered and processed the same way.
- The default stage set for `open` is ingest, audio, transcribe, align, exposure, motion, people, identity, scenes; `proxy` (preview proxies for the GUI) joins it when the preview stage exists.

### 18.4e Which frames the detectors and the VLM see: stabilised, not body-fixed
Body-frame views (fixed to the camera) are rolled and swing with the stick, so people and faces arrive tilted and the VLM has no reliable up. The `people` and `scenes` stages therefore use **stabilised views** (`analysis/views.py` `StabViews`): cut from the gyro-upright world frame with the horizon level, and the view direction measured from the runner's smoothed heading (0 = ahead, 90 = right, 180 = behind, where the wearer normally is, 270 = left; four 100-degree views for people, ahead and behind for scenes). Cost is one ray projection per sample (about a second) on top of decoding, since the body-frame maps can no longer be reused. Yaws in `people.json` and `identity.json` are therefore heading-relative (180 = behind the runner). Face crops are upright, which also improves recognition. Detections are per sampled frame and do not depend on time-smoothing of the heading.

### 18.4g Wearer speech versus chatter
Most clips contain other people's voices (about half of all candidates had some speech), but only the wearer talking to the camera is dialogue worth building an edit around. The `speakers` stage gives every speech segment a voice fingerprint (SpeechBrain ECAPA, local) and level statistics; `strata360 voice RACE` clusters them across the race and suggests the wearer's voice as the one present in the most clips (the wearer talks to the camera all race; a companion or interviewee dominates only a few clips; loudness is not used, since the wearer speaks quietly). The user confirms once from example lines (`--me N`), which saves `profiles/me_voice.npz` for later races; every segment is then labelled `wearer` or `other` by similarity to that profile, which is more reliable than the clusters (on Legends 2026 the profile also matched a second cluster whose lines were clearly the wearer narrating: the same voice under different conditions). In `candidates`, wearer speech becomes dialogue (`speech` feature, dialogue-safe techniques, a transcript) and other voices become `chatter` (kept as ambience information and never treated as dialogue).

### 18.4f Candidates: the bridge from data to editing
The `candidates` stage (`analysis/candidates.py`, no video decoding) turns each clip's data into `candidates.json`: stretches that can be cut anywhere inside, each with UTC start/end, a quality and energy score, the shortest and longest sensible cut, and the feature names the technique library needs (steady, clear_nadir, open_ground, canopy, subject, speech, protagonist, low_obstruction, resolution). Rules: a 1 Hz usefulness score (steadiness 50%, exposure 20%, scenic 20%, not blocked 10%; shake above about 57 deg/s is always rejected); a stretch ends where the picture turns unusable, where speech starts or ends (dialogue gets its own stretch, minimum 3 s, with the transcript, translation and safe cut points), or where the setting or crowd changes; stretches under 1.5 s are dropped and stretches over 45 s are split. On the Legends library (data from before the stabilised re-run): 160 candidates, 866 s usable of 1,240 s, 72 with speech; feeding them to the optimiser gives a valid 90 s plan in 2 s (41 segments, 14 different techniques, 16 of 25 clips, no violations). Tests: `tests/test_candidates.py`.

### 18.4h Clip-based workspace, thumbnails, film details
- **Layout:** a clip list with thumbnails on the left (each row: local date and time, length, number of usable moments, a dot when it has a note); with nothing selected the main area is the **overview** (film details, progress, race track, notes for the whole folder); with a clip selected it is that clip's **detail view**: a large thumbnail, when and where (UTC time, length, track facts for that moment), motion and picture (steadiness, shake, cadence, turning, brightness range), what is in shot (people, how often the wearer is in view, settings, tags, lighting), usable moments with quality bars and speech markers, the transcript (translation, language, "you" or "other" once voices are labelled) and the clip's own notes.
- **Film details** (`<project>/project.json`, `pipeline/meta.py`, `GET/POST /api/meta`): title (default: the folder name without its date), date (default: the earliest capture, as a local date), and race results: starters, finishers, and whether the wearer finished (finished / did not finish / not set) with a finishing position that only applies to a finish. Validation: finishers cannot exceed starters, a position cannot exceed the finishers, a DNF has no position. They are given to the script writer with the notes.
- **Thumbnails in two passes:** `thumb` (early, needs only motion): the steadiest moment near the middle of the clip looking ahead, as a flat upright 16:9 view (stabilised, heading-relative), so the list has pictures as soon as the fast stages finish; `thumb_best` (last): the most attractive second of the best candidate (quality, subject, wearer, scenic score, steadiness), looking ahead or, when the wearer's face is clearly in view, back at them. The list uses the best one when it exists.
- **Safety:** `/api/open` refuses an allowed root itself (it is not a footage folder) and a folder with no camera files within three levels, so a stray click cannot create a project on a whole drive.

### 18.4l The shared proxy
- **One early expensive render, one file:** the `proxy` stage (right after `motion`, on by default) renders each clip once as an upright, stabilised equirect: 3840x1920 (about 10.7 pixels per degree), 25 fps, **H.264 at 16 Mbps with the clip's audio** (about 2 MB per second of footage, so roughly 2.5 GB for Legends; an archival HEVC or x265 proxy is still possible with `proxy.encoder`). H.264 plays in every browser, so **the same file serves the detectors, the thumbnails and the browser player**: there is no separate preview stage or second copy (an earlier design made a 2048x1024 preview from a 30 Mbps HEVC proxy; dropped). Measured on clip 0019 (4.8 s): 15 s to render (about 3x real time with the machine idle; it was 11x while other workers competed), 10.3 MB. The two full-resolution lens streams still have to be decoded and stitched once; nothing else needs to do that again.
- **Everything else reads it:** `people` and `scenes` cut their heading-relative flat views from the proxy (`analysis/views.py` `write_stab_views_proxy`; the same heading track as before, so yaws mean the same); thumbnails cut their view from it in 0.3 s (`render_thumb_proxy`) instead of rendering from the lens files; the player streams it (`/api/preview` serves `proxy.mp4`). Checked on clip 0019: views from the proxy agree with views from the lens streams (normalised correlation 0.94-0.95 looking ahead; 0.78-0.86 looking at the wearer at arm's length, where the proxy's proper lens blending differs from the quick hard split used before) and take about a third of the time.
- **Soft dependency (`soft_deps`):** `proxy` is not in the key of the stages that use it, so results made before the proxy existed stay valid and nothing was redone; but a *new* item of those stages waits until its clip's proxy is done, and uses it. Without a proxy (stage switched off) they fall back to the lens streams. Test: `tests/test_workers.py`.
- **Not in the proxy:** anything needing fine detail (faces of other people at a distance, bibs, kit) must still be cropped from the lens files; the final flat render always starts from the lens streams.

### 18.4k Moments with reasons, and how a thumbnail's field of view is chosen
- **Usable and unusable moments** (`candidates.json` `candidates` and `unusable`; the clip view's "Usable and unusable moments" card): the clip is cut into stretches, each labelled usable (with its score bar) or not, drawn as a timeline (green / grey) and listed. Hovering any of them explains it: for a usable one the score and its parts (steadiness with the shake in degrees per second, exposure, scenic score, lens blocked), the setting, people and speech, why it starts and why it ends; for an unusable one the reason (too shaky with the measured shake and the limit, lens blocked or fogged, badly exposed, low overall score with the numbers, or too short) plus the same details. Starts and ends are explained by what changed: the picture became usable or unusable, you started or stopped speaking, other voices started or stopped, the scene changed (from X to Y), the crowd changed, the clip began or ended, or a long stretch was split. A second is good when its score (steadiness 50%, exposure 20%, scenic 20%, lens clear 10%) is at least 0.32 and the shake is under about 57 deg/s.
- **Thumbnail field of view:** the goals are the widest view that is comfortable (a narrow field of view magnifies the source pixels; a wide one keeps the resolution and shows more), the least distortion (a rectilinear picture stretches towards its corners by 1/cos(angle)^2: 2.9x at 100 degrees, 3.2x at 105), and, when the picture is of the wearer, the whole body in frame. Rules: looking ahead uses 100 degrees; a picture of the wearer measures their angular height in that sample and uses the narrowest view (never below 80, never above 105) in which they take at most 85% of the frame height, centred on them; if the body would need more than 105 degrees it stays at 105 and aims a little higher so the head stays in. The chosen field of view, the corner stretch and the reason are stored in `thumb.json` and shown under the thumbnail. If the body height was not measured (face only) 60 degrees is assumed.

### 16.2b The chronological film plan (`edit/chrono.py`; replaces the free-order optimiser for the real film)
The film always follows the day in **time order**; the optimiser decides *how* each clip is edited, not *where* it goes. Rules (all checked by `violations`, tests in `tests/test_chrono.py`):
- **Every source clip contributes** at least one segment (a clip with no usable moment contributes its best unusable stretch, flagged `forced`, shown as a plain shot); a long clip contributes several, as many as its share of the film justifies.
- **No overlap** between segments of one clip; **several adjacent selections** from one clip are welcome (windows may touch), because each can have a different technique, view or cut. A window is at most 8 s; longer stretches are split into adjacent windows.
- **Three steps:** (1) split the beats between the clips (at least one minimum window each; then by concave value, so good and long clips get more with diminishing returns; no clip above 25% of the film unless that is the only way to fill it); (2) cut each share into non-overlapping windows inside the usable stretches (best stretches first, music-driven lengths), then make the total exactly the film length; (3) a seeded beam search picks the technique of every window in time order with the same variety rules as before (recent repeats, family and scale repeats, hero share and cooldowns, per-technique shares and caps, dialogue only with dialogue-safe techniques), beat- and bar-aligned.
- **When it cannot be done it says why:** a film too short to include every clip (e.g. "12 clips need at least 24 s"), too little usable footage, or no technique fitting a window.
- First real plan (Legends, 120 s, 24 clips with candidates): 39 segments, every clip at least twice, in shooting order; the script writer's story now follows the race.

### 18.4m Keeping the machine usable (resource limits)
Background processing must never make the computer unusable (three parallel workers running the vision model, detectors and proxy renders once froze a 16 GB Mac). Every worker, however it was started, now:
- runs at the **lowest CPU priority** (nice 19) and, on macOS, in the **background task class** (throttled CPU, disk and network), with **2 threads** per process; ffmpeg and the model processes it starts inherit this;
- checks **available memory** (free + inactive + speculative + purgeable pages) before every item against what that stage needs (scenes about 6 GB, people 4, proxy 2.5, transcribe 4, ...) plus a 2 GB reserve, and **waits** while there is not enough, or while the 1-minute load average is above 60% of the CPUs;
- lets the **heavy stages run one at a time** (scenes, people, proxy, speakers, transcribe, align, exposure, preview): parallelism is only across different stages, and two workers claiming the same heavy stage at the same instant are resolved in favour of the earlier claim;
- uses the **CPU, not the GPU**, for the detectors (`STRATA_GPU=1` to allow the GPU);
- **a second worker only starts with plenty of free memory** (at least 12 GB available per extra worker, machine not busy, at most 2 workers); the first worker is always allowed (it is low priority and waits for memory itself). The app says why "add a worker" is missing ("only 5 GB of memory is free; another worker needs at least 12 GB free").
Settings in `race.json` `resources`: `max_workers`, `extra_worker_free_gb`, `reserve_gb`, `busy_load_fraction`, `threads`. Code: `pipeline/resources.py`; tests: `tests/test_resources.py`.

### 18.4i Parallel workers and reprocessing
- **Work items and claims:** the batch is a set of items (clip, stage). Any number of workers can run at once, started from the GUI ("Start processing", then "Add a worker" up to a maximum of 3, since the vision and language stages are memory-hungry), from the command line, or both. A worker scans the items in stage order, skips what is done, blocked by an unfinished dependency, or claimed, claims one atomically (`.claims/<clip>__<stage>` created exclusively, holding its pid), processes it, releases it and scans again until nothing is left. The first worker therefore loops through the whole batch; a worker added later just takes whatever is unfinished and unclaimed. A claim held by a process that has died is stale and is taken over; closing the app or killing a worker loses only the item in progress.
- **Safe state:** each clip's `stages.json` is updated under a file lock (read, change one stage, write), so workers finishing different stages of the same clip never overwrite each other. Workers register in `.workers/`; the progress view shows how many are running and what each is doing (the `active` list).
- **Reprocess (clear status):** "redo" beside a stage, "Reprocess..." on the overview, and "reprocess..." on a clip open a dialog listing every (clip x stage) with its status (done, running, out of date, failed, not done), select all / select none, tick a whole stage column or a whole clip row, and an option to also tick the stages that depend on each tick (so redoing scenes also redoes candidates and the better thumbnail). Confirming forgets those statuses (files stay until replaced) and the workers redo them. Command line: `strata360 clear FOLDER STAGE [--clip ID,ID] [--no-cascade]`.
- **Thumbnails are stages:** `thumb` (quick, right after motion) and `thumb_best` (after candidates); a clip with no thumbnail simply has not been through its stage yet.
- Tests: `tests/test_workers.py` (six processes racing for one claim: exactly one wins; stale claims; concurrent state updates; clearing with dependents).

### 18.4j Places, and stages that need the race track
- **`places` stage** (`analysis/places.py`): the start, middle and end of each clip are matched to the race track by UTC time and looked up on OpenStreetMap: Nominatim reverse geocoding (road, hamlet/village/town, county, country) and the Overpass API (named places, peaks, water, waterways, historic sites, tourism, amenities and hiking routes within 1 km, nearest first). The clip view shows the summary, the road, the nearest features and an "open in OpenStreetMap" link; the script writer gets the summary and nearby names. **This is the only stage that sends anything off the machine** (rounded coordinates of those three points per clip); both endpoints can be replaced by self-hosted ones in `race.json` (`places`: `nominatim`, `overpass`, `radius_m`). The public services ask for at most one request per second and a User-Agent, so all workers share one rate limiter and every answer is cached on disk by rounded position (`<project>/cache/places/`). Clips outside the race track get no positions and say so. On Legends: about 40 s per clip the first time, under a second when cached.
- **Which points:** only positions that add information are looked up. The middle of the clip is the reference; the start is used only if it is more than 200 m from the middle, likewise the end (`places.min_separation_m`). If both are within 200 m of the middle but more than 200 m apart from each other, the start and end are used instead of the middle; if everything is close, only the middle. So a stationary clip costs one lookup, a moving one up to three. Test: `tests/test_places.py`.
- **`locations.json`:** the processed results of all clips in one file in the project folder (rebuilt every time a clip's places finish, atomic and safe with parallel workers): per clip in time order its start/end UTC, summary (villages, road, county, country) and looked-up points with addresses and nearby places; `route` (the villages and towns in order along the way, with the first clip and time each appears); and `places` (every named place seen, which clips it appears in, how near it came). It is the finished result, not the cache (`cache/places/` holds the raw web responses).
- **Track-dependent stages pause and reset:** a stage declared `needs_track` waits (shown paused, and "add the race track" appears in what is waiting for you) until `track.fit` / `track.gpx` exists in the project. Its key includes a signature of the track file's content and of the camera clock (offset, drift), so replacing the track, or moving the clip-to-track alignment by changing the clock (an anchor, a suggestion, a manual offset), makes every such stage out of date and it is redone (cheaply, from the cache when positions are unchanged). Test: `tests/test_workers.py`.

### 18.4d The web server (FastAPI)
`./strata360 serve --root ~/footage --root /Volumes/Expansion [--host 127.0.0.1] [--port 8360] [--token SECRET]` runs a FastAPI app (interactive API docs at `/api/docs`) on the machine that has the footage and GPU; the GUI is opened from any browser. Design rules:
- **Folder browsing is server-side and whitelisted:** the browser can only look inside the allowed roots (`--root`, repeatable, or `~/.strata360/server.json` `{"roots": [...]}`). Every path is resolved (symlinks included) and refused if it leaves a root; symlinks pointing out are not listed. It only ever writes the project folder next to the footage.
- **Network safety:** binds to 127.0.0.1 by default; on any other address a token is required (generated and printed if not given; sent as `?token=` on the first visit, then a cookie, or `Authorization: Bearer`). Put it behind HTTPS (a reverse proxy or a tunnel) before exposing it beyond a trusted network.
- **API:** `GET /api/roots`, `/api/browse?path=`, `/api/progress?folder=`, `/api/log?folder=`; `POST /api/open`, `/api/run`, `/api/stop`. Processing runs as a separate `strata360` process per project (survives a browser refresh; one at a time per project), so the server stays responsive. Later: media and preview streaming (range requests) for the WebGL preview, and the clock, who-is-me and edit endpoints.
- Tests: `tests/test_server.py`.
- **Front end: React + TypeScript + Tailwind, built with Vite** (`web/`; `cd web && npm install && npm run build` writes into `src/strata360/server/static`, which FastAPI serves; `npm run dev` gives hot reload with `/api` proxied to `./strata360 serve`). `scripts/setup_env.sh` builds it when npm is present; the build output and `node_modules` are not committed. Structure: `src/api.ts` (typed client), `usePoll.ts`, `components/FolderBrowser.tsx`, `components/ProjectProgress.tsx`, `App.tsx` (start screen: pick folder, then progress, then results). Planned additions in the same app: clock panel, who-is-me sheet, the timeline and WebGL 360 preview (three.js), transcript and voice-over, music, export.

### 18.5 What this means for the build order
1. Finish the data batch (running now): audio, transcript, alignment, exposure, motion; then people/faces, speakers, scenes, quality.
2. Add the **preview proxy and thumbnails** stage (cheap, fast) and the candidate builder that turns all per-clip data into `candidates.json`.
3. `propose` (the optimiser on real candidates, with framing solve and audio plan) and the `project.json` schema.
4. The GUI on top; the final render driver last (it mostly exists: `render/flat.py` with `--path` and `--start-utc`).
