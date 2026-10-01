# Implementation plan (from 1 Oct 2026)

This turns the README's ideas (sections 10 to 18) and the open items in `progress.md` into an ordered list of work. Each item has a goal, the code it touches, what "done" means (with a test), and a rough size (S: under a day, M: 1 to 3 days, L: about a week). The overview (`overview.md`, formerly the README) stays the reference for how things work; this file only says what to build next and in what order.

## Where we are

**Built and working on real footage (Legends 2026, 25 clips, 1,240 s):**
- The batch: 20 cached, resumable stages run by parallel workers under resource limits (ingest through candidates and thumbnails), driven from the web app.
- Stitching and rendering from the lens files: calibration, gyro stabilisation, heading-follow, carved seam, parallax warp, stick mask fix, little planets and globe.
- The analysis data: transcripts with translation, alignment and corrections, wearer face and voice profiles, people tracks, scenes (local VLM), places (OpenStreetMap), camera clock against the FIT.
- The edit: the chronological planner (`edit/chrono.py`) with overrides saved in `project.json`, framing per window, transitions, music tempo and energy, the script writer (Gemini 3.1 Pro), voice-over (Kokoro or your own recordings), the streaming preview and the resumable final render.
- The web app: clips, moments, transcript, timeline, script, voice-over, music, clock, who-is-me, film preview, final render.

**Gaps that stop us delivering the film the README promises (goal 4, section 13):**
1. **The map overlay is drawn but not yet checked end to end.** Since 1 Oct the final render draws the overlay (`src/strata360/overlay/`) on every frame at that frame's UTC; there is still no `timemap.json`/`.csv`, no integration test on a rendered film and no check on Legends. Its frame rate is also a fixed default (`fps=50.0`) rather than the source's (A2).
2. **The final sound is a rough mix.** `preview.build_audio` (used by the final render too): mono, fixed gains (0.25, or 1.0 where people speak), 10 ms fades at every cut, music at 0.5 with a sidechain duck, a limiter. No loudness target, no crossfade on dissolves, no use of the `audio_events` roles or `audio_clean`.
3. **No exposure matching between shots.** `exposure.json` is collected but not applied; adjacent shots from different times of day will jump.
4. **No real 4K film has been rendered.** The only trial was 11 s at 640x360 (280 s on a busy machine). At about a second per 4K frame, a 120 s film at the source's 50 fps is about 1.7 hours of pure rendering at best; we do not know the real number.
5. **The voice-over does not drive the picture.** Today the order is plan, then script, then voice: the planner (`edit/chrono.py`) fixes every window in whole beats of a constant-tempo grid, the script is written into those windows, and `edit/voiceover.py` squeezes each spoken line into its window (synthetic lines sped up to 1.25x, recordings cut and flagged `over`). overview 17 steps 5 and 6 (measure the recording, then fit the picture around it) are not built, and cuts can only fall on a constant grid (`edit/music.py` assumes a fixed tempo), not on the music's actual beats to the millisecond.
6. **No lens-quality data.** There is no `quality` stage, so `clear_nadir` (needed before showing a planet, a tunnel or a spin) is a guess from the VLM's "lens problems".

**Debt worth paying while we are in there:** the README has grown to 210 KB with out-of-date passages (section 1 still lists "a GUI editor" as a non-goal; section numbers are out of order); the Python coverage floor is 38%.

## Decisions this plan assumes (change them and the order changes)

| # | Assumption | Why it matters |
|---|---|---|
| D1 | The first goal is **one finished Legends film with the map overlay**, not more analysis. | Puts the deliverable film (A, V) before more analysis. |
| D2 | **Decided (1 Oct, revised the same day):** the delivered film is **one file**, and the map overlay follows **each window's own clip UTC**, frame by frame. It is drawn by our own code (`src/strata360/overlay/`), not by the gopro-dashboard-overlay fork: the fork was used only as a guide to what to show. A `timemap.csv` is written too, for checking and for anything else. | Resolves overview 12, open question 1. Shapes A2. |
| D3 | **Decided (1 Oct):** the output frame rate **matches the source**, whatever it is (50 or 60 for the Osmo 360; 59.94 kept as the exact rational), with a GUI option to **halve it** (25 / 30) for a faster render. If clips in one film differ, the majority rate is used (overview 12) and the others are resampled. Delivery: 3840x2160, HEVC Main 10, stereo AAC at -14 LUFS integrated, -1 dBTP. | Fixes the render and audio acceptance numbers. |
| D4 | **Decided (1 Oct):** the **GPU is always preferred** for rendering (and the heavy per-pixel work in the proxy); the CPU path is kept only where its quality is noticeably better, which is measured, not assumed. | Makes the GPU renderer (B3) a planned milestone, not an option. |
| D5 | Insta360, the MCP interface and face blur stay parked until the Legends film exists. | They are listed in Later. |
| D6 | **Decided (1 Oct):** the first cut is **voice-over driven**. The spoken voice-over sets the rough length of each clip's part of the film (with each clip's usable and preferred content); the music then sets the **precise cut moments** (to the millisecond, then the nearest frame) on its beats, without ever cutting a clip's own speech short. | Puts milestone V on the critical path straight after A1, ahead of the rest of A. |
| D7 | **Decided (1 Oct, revised):** the film is **never shorter than the voice-over**, and **ideally as long as the music**, with a little flexibility. The voice-over length is the fitted voice-over timeline (lines, the pauses between them, the clips' dialogue gaps, lead-in and lead-out: V4's sum). Film length L >= voice-over; the target is the music's length. Where they differ: the music can be faded out early, start after the film begins or end before it does (a short silence at the start or end of the film), and its start can be shifted against the picture so beats line up with the cuts. | Sets the film target for V1 to V5 and makes the music's position a variable of the fit. |
| D8 | **Decided (1 Oct):** the film's length guide is **one of**: a single music track, a target length, or **neither**, in which case it is **automatic**: worked out from the usable footage and from how long the generated script runs, including the clips' own speech (transcript portions) it uses. Whichever it is, it is a guide; D7's flexibility applies. | Adds the auto-length rule to V1 and V2. |
| D9 | **Decided (1 Oct):** a clip is **dropped only if it must be**: first because it has no usable footage; otherwise every clip gets at least some b-roll, using the framing variety (field of view, pans, little planets and other techniques) to make the most of it. Only if the film cannot hold every clip's minimum are clips dropped, unusable ones first, then the lowest-value ones, each reported. | Changes V1's allocation (today an unusable clip contributes a forced stretch). |

## Milestone A: the film is deliverable (critical path)

### A1. Finish the Legends batch on current stage versions (S, mostly machine time)
- Run every default stage to completion at its current version (proxy v6 for all 25 clips; scenes, speakers, candidates, thumb_best).
- Add `strata360 coverage FOLDER [--json]` (overview 15.3): per clip, which section 15.1 artefacts exist and which decisions they unblock. Show it in the Overview's progress panel.
- **Done when:** `progress` reports `complete` for Legends; `coverage` lists nothing missing for default stages. Unit test for `coverage` on a built project (`tests/utils` builders).

## Milestone V: the voice-over cut (first cut; critical path after A1)

The new order of operations, replacing plan, then script, then squeeze:

```
rough plan (clip blocks)  ->  script per block  ->  voice-over spoken / recorded and measured
      ->  re-size blocks to the measured voice-over  ->  windows inside blocks  ->  cuts snapped to the music's beats  ->  final audio placement
```

Terms: a **block** is one clip's continuous part of the film (the film stays chronological, so blocks are in shooting order); a block holds one or more **windows** (the existing plan segments: one view and technique each). Narration **lines** belong to blocks. A clip's **dialogue** (the wearer speaking on camera, the `speech` windows) is played in a gap between lines.

### V1. Rough plan: clip blocks and preferred content (M)
- `edit/chrono.py` step 1 (`allocate`) already splits the film between clips; expose it as a planning level of its own, in seconds rather than beats: per clip a block with a target length (the film target, D8: the music's length when a track is chosen, else the target length when one is given, else automatic, below), the usable stretches it may use, its **preferred content** (best candidates by kind and priority: `speech`, `you`, `person`, `scene`, `best`) and any dialogue it must carry (with its exact speech span from `alignment.json`, padded 60 ms before and 120 ms after, overview 16.4).
- **Which clips (D9):** a clip with no usable footage is dropped (and listed); every other clip gets a block of at least its minimum b-roll (one minimum window, 2 s, plus its dialogue if it has any). Only if the target cannot hold all the minimums are more clips dropped, lowest value first, each reported with the reason. This replaces today's "forced" unusable stretch in `edit/chrono.py`.
- **Automatic length (D8, no music and no target):** each clip's block gets a natural length from its usable footage with diminishing returns (for example 2 s + 1.5 x sqrt(usable seconds), capped at its usable footage) plus its dialogue; the sum is the first guide for the script, and the script's measured length then sets the film (V4).
- Locks, bans and per-clip weights (the existing overrides) apply at this level unchanged.
- **Done when:** unit tests: every clip gets a block, blocks are in shooting order, a block's minimum is at least its dialogue plus padding, the targets sum to the film target; an unusable clip is dropped and reported while a merely dull one keeps a block; automatic length grows with usable footage and is reproducible.

### V2. Script written per block (S to M)
- `edit/script.py`: the writer gets blocks instead of beat windows: per block its facts (as now), its seconds minus its dialogue, and a word budget from that; lines carry the `block` id (and an optional anchor: "before the dialogue" or "after it"). Blocks with dialogue keep a marked gap.
- Keep `check()` and the one retry; budgets are now a guide, not a hard cut, because V4 re-sizes the blocks to what is actually spoken.
- **Done when:** fake-HTTP unit tests: lines map to blocks, a block's dialogue gap is never written over, the totals report words per block.

### V3. Measure the spoken voice-over (M)
- `edit/voiceover.py` stops squeezing: each line is spoken (Kokoro) or recorded at its natural length (no tempo change, no cut), and its real duration is measured; for recordings, leading and trailing silence are trimmed by energy and the words are force-aligned to the line's text with the existing aligner (`audio/align.py`) to get word times and to catch a missing or repeated line.
- Output `voiceover/vo.json` (overview 17.2): per line, take, natural duration, speech start and end inside the file, word times, alignment score, loudness. Recording a new take re-measures only that line.
- **Done when:** P5-33 on a synthetic recording (Kokoro reading a known text with inserted silences): line boundaries within 50 ms, a missing line reported.

### V4. Re-size blocks to the voice-over (M)
- New `edit/vo_fit.py`: each block's length = its lines' measured durations + the pauses between lines (default 0.4 s, after a paragraph 0.9 s) + its dialogue (padded) + lead-in and lead-out (default 0.5 s each, so a line never starts on a cut), never less than the block's minimum and never more than its usable footage (if it would be, the overflow is reported: "line 7 needs 9.2 s; clip 0012 has 6.5 s usable", with the choices to shorten the line, borrow from the next block, or allow a hold on the last frame).
- **Film length (D7).** The sum of the blocks is the voice-over timeline V; the music's length is M (from its first downbeat, or from where the user starts it). Hard rule: L >= V. Target: L = M. Settings (defaults to confirm): `fade_max_s` (how much of the music may be lost to an early fade-out, 8 s), `lead_silence_max_s` (silence before the music starts, 4 s), `tail_silence_max_s` (silence after it ends, 6 s).
  - **Music longer (M > V):** the extra M - V is spread over the blocks: longer holds and pauses inside each block's usable footage, extra windows from preferred content, and a music-only intro and outro (picture with no narration, up to a few bars each). If the footage cannot fill all of it, L = V + what can be filled and the music fades out over its last bar or at a section end; if more than `fade_max_s` of the music would be lost, the shortfall is reported (with which clips ran out of footage).
  - **Voice-over longer (M < V):** L = V. The music is placed inside the film with silence (or the clips' own sound) before and/or after it, split between start and end as the sync allows, each within its limit; beyond the limits the shortfall is reported with the options to pick a longer track, loop a section of the track at a bar line, or shorten the script (C2's per-block re-write, which this pulls forward). The script writer (V2) is given the music's length as its target, so this is the exception.
  - **Music position is free within the flexibility.** The music's start in the film (an offset, possibly negative: starting part-way into the track) is chosen in V5 together with the cuts, so downbeats fall on the cuts that matter (block boundaries, the first dialogue, the last cut); the film may grow by a beat or two for this, never shrink below V.
  - **No music:** L = V, plus a short lead-in and lead-out; with a target length the extra or missing time is handled as for music (spread over the blocks, or reported), but more loosely, since there is no beat to land.
- Lines get provisional start times in film time.
- **Done when:** unit tests: every line lies inside its own block; no line overlaps a dialogue span; the film has picture for every instant of the voice-over (P5-34); a reported overflow names the line and the clip; L is never below V; with a 90 s track and 60 s of voice-over and enough footage, L is 90 s (within a beat) and every block grew; with too little footage the music fades and the fade is within `fade_max_s` or reported; with a 60 s track and a 64 s voice-over, L is 64 s and the music's silence at start plus end is 4 s, each within its limit.

### V5. Windows inside blocks, then cuts on the beat (L, the heart of it)
- **Windows.** Inside each block, cut windows from the preferred content as `cut_windows` does now (non-overlapping, 2 to 8 s, techniques by the existing beam search), but in seconds, not beats.
- **Beat times, precisely.** `edit/music.py` gains a beat tracker that returns the actual time of every beat and downbeat (dynamic programming over the onset envelope, starting from today's constant-tempo estimate, allowed to drift), refined to the onset peak, so a beat is known to within a few milliseconds even where the tempo wanders. `music.json` stores the beat list.
- **Music offset.** Before snapping, choose the music's start in the film (within D7's limits) that puts the most important cuts (block boundaries, dialogue starts, the last cut) nearest to downbeats; a small search over offsets in steps of a few milliseconds, scored by the total snap distance.
- **Snapping.** Every cut (between windows and between blocks) moves to a nearby beat, preferring downbeats and bar lines, within a tolerance (default: half a beat either way). Hard rules:
  1. a dialogue window always contains its whole speech span plus padding: a cut next to speech may only move **outwards** (earlier before it, later after it), never into it;
  2. a cut never falls inside a voice-over word, and a line keeps its lead-in (a cut under a line between its words is fine);
  3. each window stays inside its technique's duration range and its clip's usable footage; snapping may lengthen the film by a beat or two but never makes it shorter than the voice-over (D7); lines are re-timed with their block.
  If no beat satisfies the rules, the cut stays at the nearest safe point off the beat and is reported in the plan ("cut 14 is 120 ms off the beat: the dialogue in clip 0023 ends there").
- **Milliseconds to frames.** The cut time is kept exact in the plan; the picture cuts on the nearest frame (within 10 ms at 50 fps, 8 ms at 60), the sound at the exact sample.
- **Without music:** the same pass with no beat list, so cuts land on the voice-over's pauses and the safe cut points only.
- **Done when:** unit tests on a synthetic beat list with a drifting tempo and a fixture with dialogue: every cut not reported as off-beat is within one frame of a beat; no dialogue span is shortened by a single sample; no cut inside a voice-over word; the reported off-beat cuts are exactly those the rules force; the same seed gives the same plan.

### V6. Place the sound and show it (M)
- Voice-over lines are placed at their fitted times without tempo change; music ducks under lines and dialogue (shared with A3); the preview (`render/preview.py`) and final use the new plan unchanged (it is still a list of windows).
- Timeline: blocks as bands over the windows, lines drawn above with their measured lengths, beat ticks, off-beat cuts marked with their reason; record or re-record a line from there, after which only its block and its neighbours' cuts are re-fitted (P5-35).
- **Done when:** web integration test (msw) for the block, line and beat display; Python test that re-recording one line leaves every window outside its block and its two neighbouring cuts unchanged.

## Milestone A (continued)

### A2. Map overlay per window, joined into one film (M to L; overlay drawing done 1 Oct)
How it works: every window of the plan comes from one input clip, so its UTC span is known exactly (`utc_start` in the plan). The overlay is drawn onto each frame at that frame's own UTC, inside the final renderer, before transitions are blended; the windows are then joined into the single delivered file as before.

**Decided (1 Oct): our own overlay, not the fork.** The fork (gopro-dashboard-overlay, GPL-3, used before through `scripts/overlay/`) was read and used as a guide only; no code was taken from it. Driving it would have meant a second environment with cairo, a stand-in MP4 per window to carry its start time (whole seconds in `creation_time`, hence the unpublished `mp4-exact-start` branch), a picture every 0.1 s rather than every frame, speed and slope recomputed from each window's few seconds (wrong at every window start), the whole-route map rebuilt for every window, and a 1080 layout enlarged to 4K.

**Built (1 Oct), `src/strata360/overlay/`:**
- `series.py`: distance (the FIT's own, or measured along the path for a GPX), pace, slope (over 60 m of distance), altitude and heart rate, smoothed once over the whole race on a 1 s grid and read at the exact time of each frame; NaN (shown as a dash) outside the track, in long gaps and when stopped.
- `tiles.py`: Web Mercator, tiles fetched once into `~/.strata360/tiles/<style>/` and shared by every race, 512-pixel `@2x` tiles where the style has them; Thunderforest styles (`tf-outdoors` default, key `THUNDERFOREST_API_KEY` from the environment or `secrets.env`, never in an error) and `osm`.
- `draw.py`: Pillow for text (bundled Inter, SIL OFL), shapes drawn at 4x and reduced, OpenCV anti-aliased route lines, a soft shadow behind text and icons, digits in equal-width cells; patches laid onto 8- or 16-bit frames.
- `layout.py`: the reference's elements, configured in Python, not XML: date and time, distance, pace, altitude / slope / heart rate with our own vector icons (the slope icon points downhill when the slope is negative), the whole route with the marker, the moving close-up map (zoom 14) and the map credit. Written for 1920 x 1080 and scaled to the film, each element kept at its distance from its edges. race.json `overlay`: `enabled`, `style`, `elements`, `layout` (per-element overrides), `scale`, `map_opacity`, `local_zoom`, `font`, `label_font`; the race `timezone` sets the clock.
- `render/final.py`: `FinalSource` draws the overlay on each frame (so a dissolve cross-fades the two windows' overlays like the picture); the film's cache key includes the overlay settings and the track file. A missing map key stops the render at the start, not hours in.
- Cost: about 5 ms a frame at 1080 and 22 ms at 4K (the render itself is about 1 s a frame); the first frame of a new place fetches its tiles.
- Unit tests: `tests/unit/test_overlay_{series,tiles,draw,layout}.py` (fake tile service, no network).

**Still to do:**
- **Source frame rate (D3).** `render/final.py` takes the rate from the clips (`clip.json` `video.nominal_fps`, as a rational), not the fixed 50; a `half_rate` setting (Final film panel: "Half frame rate (faster)") renders every other source frame. The preview, the time map, the overlay and the audio all use the same rate. Mixed rates: the majority rate, others resampled by nearest source frame.
- **Time map.** New `render/timemap.py`: from the plan and the pieces of `render/film.py`, write `<final>/timemap.json` and `timemap.csv`: per window, film in/out frame, clip, source in/out time, UTC in/out (rational), and the transition regions with both clips' UTC.
- **Settings in the app.** Overlay on/off, elements, map style in the Final film panel (writes race.json `overlay`); a field to store the map key in `secrets.env` (like `set-key`); `doctor` reports whether a key is set and how many tiles are cached. Optionally the overlay on the preview too (it is cheap).
- **Done when:** integration test on the synthetic OSV with a synthetic track and the fake tile service: a two-window plan with a dissolve renders one file in which each window shows its own clip's UTC to within one frame (read back from the drawn clock, or from a test element that encodes the time in pixels), the dissolve blends both, and the frame rate equals the source's (and half of it with `half_rate`). Time-map maths unit-tested (monotonic, every output frame covered once). One real check on Legends: the overlay's position marker matches the place seen on screen at three known points (the start line, an aid station, a village sign); the clock matches the camera clock check.

The reference (kept in `scripts/overlay/`: `layout.xml` and the command line used before) is what the look was matched against; `overlay_segment.sh` stays for anyone who still wants to run the fork on one segment.

### A3. Final sound mix (M)
- Move the mix out of `render/preview.py` into `audio/mix.py` (shared by preview and final; the preview keeps a fast path).
- Per window: use `audio_clean.flac`, with the level and role from `audio_events` (`window_mix` already suggests them) instead of the fixed 0.25 / 1.0.
- Crossfade the clips' sound across dissolves and dips (equal-power, the transition's length); 30 ms crossfade on hard cuts instead of fade-out/fade-in, so cuts do not dip.
- Stereo out (the clips' own stereo where it exists, voice-over and dialogue centred).
- Loudness: two-pass `loudnorm` (or `pyloudnorm`) on the final mix to D3's target; report the measured values in the final's `status.json`.
- Duck the music to bars (`music.json`) under dialogue as well as under the voice-over (overview 17.1 step 7).
- **Done when:** unit tests on synthetic tones: the integrated loudness of the output is -14 +/-0.5 LUFS and true peak at most -1 dBTP; no level dip of more than 1 dB at a hard cut between two equal tones; music at least 10 dB down within 100 ms of each voice-over line start (P5-36).

### A4. Exposure match between shots (M)
- `render/grade.py`: per window, a gain (and optional gentle tone curve) towards a target brightness from `exposure.json`, smoothed across a window and eased across cuts so neighbouring shots do not jump; highlight protection; never applied to night shots beyond a cap (keep night dark).
- Applied in `render/flat.py` before encoding (linear light, so it is the same maths in preview and final).
- Grade overridable per window in the Timeline (a brightness nudge).
- **Done when:** unit test: two synthetic windows at 0.5x and 1.5x brightness come out within 10% of each other with no clipping added; a night window keeps its relative darkness. Visual check on three real cuts noted in `progress.md`.

### A5. A real end-to-end Legends render (S, plus machine time)
- Render the 120 s plan at 4K and the source frame rate overnight with A2 to A4 (overlay included); measure frames per second, peak memory, disk; also time the half-rate option.
- Record what looks wrong (seams, grade, framing, sound) as issues; they feed milestone C.
- **Done when:** a finished film with overlay exists, and `progress.md` has the timings and the list of defects.

## Milestone B: rendering is fast enough to iterate (GPU first)

### B1. Parallel pieces (S)
- `render/final.py` pieces are independent; let up to `resources.max_workers` processes take pieces using the same claim files as the batch (`pipeline/runner.py`), at low priority.
- **Done when:** two workers on the synthetic OSV produce byte-identical pieces to one worker; resource limits respected (`tests/unit/test_resources.py` pattern).

### B2. Cheaper frames (M; the savings apply to the GPU path too)
- Skip the second lens when the view lies inside one lens (most `dialogue_hold` and `selfie_hold` windows).
- Decode only the needed range of each lens stream; YUV in, convert after the remap.
- **Done when:** a benchmark script (`scripts/bench_render.py`) reports frames per second for hold, pan, planet on clip 0019; a measured gain is recorded; output differs from before by less than 1 code value at 10-bit outside the skipped lens.

### B3. GPU renderer (L)
- The per-pixel work (fisheye remap of both lenses, seam blend, parallax warp, globe compositing, overlay compositing, colour conversion) moves to the GPU, with the GPU chosen like the video hardware in `src/strata360/hw.py`: Apple GPU on macOS, CUDA on Windows/Linux when present, CPU otherwise. Start with PyTorch (`grid_sample`, already in `.venv-vision` with MPS and CUDA) for the remap and blends, so one code path serves both; a hand-written Metal kernel only if that is too slow.
- Decode straight to GPU memory where the platform allows; keep 16-bit (or float) through the render.
- **Quality gate (D4):** a comparison script renders the same frames on CPU and GPU (hold, pan, planet, globe, a seam with a hand near it) and reports the difference (max and mean in 10-bit code values, PSNR, and a sharpness measure). GPU is the default; a technique stays on the CPU only if the GPU result is noticeably worse, and the reason is recorded in `progress.md`.
- **Done when:** the comparison passes on the synthetic OSV in CI (CPU-only runners compare the torch-on-CPU path with the OpenCV path), and on the Mac the GPU render of the A5 film is measured against the CPU one.

## Milestone C: the edit is trustworthy

### C1. `quality` stage (M to L)
- New stage after `proxy`: per second, hand or thumb over a lens, water drops or fog, blur (Laplacian variance per lens), glare, over and under exposure, seam risk (near objects at the seam from the parallax warp's near-object cells). From the lens frames at low resolution, the exposure grid and the stick polygon.
- Output `quality.json`; `candidates` uses it for `clear_nadir`, `low_obstruction` and the unusable reasons (replacing the VLM guess).
- **Done when:** a labelled set of about 40 seconds from Legends (hand over lens, drops, clear) is checked in as a fixture of measurements (no footage), and the detector agrees on at least 90%; P5-28 (no planet, tunnel or spin with a hand over the lens) passes on real candidates.

### C2. Script editing in the GUI (M)
- Regenerate one block's lines or a range (send the neighbours as context), pin a line so re-writes keep it, change the target length and re-plan blocks and script together (listed as "later in the GUI" in `notes-and-script.md`). Builds on V2 to V4.
- **Done when:** unit tests on `edit/script.py` with the fake HTTP layer: a pinned line survives a re-write byte-identical; a regenerated range leaves other lines unchanged.

### C3. Who is speaking on screen (L, optional for v1)
- Active speaker detection from mouth motion on full-resolution face crops (overview 7 item 6b), fused into `speakers.json`, so dialogue framing holds on the person speaking rather than the biggest other person.
- **Done when:** P5-29 passes on a fixture with a known speaker. Can slip to Later if dialogue framing looks acceptable in A5.

## Milestone D: editing in the GUI is fast

### D1. Timeline editing (M)
- Drag a window's edges; they snap to beats and to safe cut points with the V5 rules (never into dialogue).
- "Suggest again" for one window or a selected range (re-plan only the unlocked part with a new seed); keep the last three versions to step back.
- A map strip under the timeline (positions from `gps/context.py`).
- **Done when:** web integration tests (msw) for drag-snap and suggest-again; Python unit tests for the partial re-plan leaving locked windows identical (P5-30).

### D2. Live technique preview (L, optional)
- The WebGL player already projects the proxy; drive it from a window's camera path (`render/camera.py` maths in TypeScript), so changing a technique previews instantly without the HLS render.
- **Done when:** a unit test compares the TypeScript path evaluation with the Python one on the example paths in `spike/` (same yaw, pitch, fov to 0.01 degrees).

## Milestone E: documentation and test debt (S each, alongside the others)
- **E1.** Done 1 Oct: the README became `docs/overview.md`, the other Markdown files moved into `docs/`, and the README is now a short page of links. Still to do: remove passages in the overview contradicted by later work (section 1 non-goals, the two-proxy design, the free-order optimiser as the main path) and, if it keeps growing, split it into one file per area.
- **E2.** Trim `progress.md` to findings and decisions; the build narrative is in git history.
- **E3.** Done 1 Oct: the three `PROMPT_*.md` files are in `docs/prompts/`.
- **E4.** Raise `fail_under` as each milestone adds tests (target 50% after V and A).

## Later (parked until the film exists)
- A generated (AI) backing track made to fit the finished cut: the film's length, its block boundaries as section changes, its energy curve, and beats placed on the cuts (the reverse of V5: the music fits the picture).
- Insta360 adapter (needs sample `.insv` files; overview 12 questions 2 and 10).
- MCP / conversational interface (Phase 9).
- Face blur for other runners and spectators (overview 12 question 7).
- OpenOSV's remaining stages: photometric seam field, lens shading, flare (overview 14.1); nadir inpainting; rolling-shutter correction from the 20 per-frame quaternions.
- D-Log M and HLG input.
- Taste learning from the user's earlier finished films (overview 15.1, `taste.json`).
- Speech enhancement chosen per segment (overview 14.6) beyond what `audio_clean` does.

## Order and dependencies

```
A1 ─> V1 ─> V2 ─> V3 ─> V4 ─> V5 ─> V6 ─┐
A2, A3, A4 (independent, alongside V) ───┼─> A5 ─> B1 ─> B3 (GPU) ─> B2
                                          └─> C1 ─> (hero shots safe)
C2 after V4;  D1 after V5;  E runs alongside.
```

Suggested sequence: A1, then the V milestone in order (V5 is the largest piece), with A2 to A4 in parallel; then A5 (the first real film: voice-over driven, cut on the beat, with overlay); then B1 and C1, C2, D1, with the GPU renderer (B3) straight after B1 (A5's CPU render is the quality reference it is compared against), then B2.

## Questions for you
Answered on 1 Oct: D2, D3, D6, D7, the docs move, and the V4/V5/D7 defaults (0.4 s between lines, 0.5 s lead-in and lead-out, snapping up to half a beat, off-beat cut reported when no beat fits, up to 8 s of music lost to a fade, up to 4 s of silence before the music and 6 s after).

Answered on 1 Oct as well: a reference overlay (layout and command line) to work from, now drawn by our own code rather than the fork (A2); clips are dropped only if they must be (D9); one track, a target length, or automatic length (D8); GPU preferred (D4).

Still open:
None; the overlay configuration arrived on 1 Oct (A2).
