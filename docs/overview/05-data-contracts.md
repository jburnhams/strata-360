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
