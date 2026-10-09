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
