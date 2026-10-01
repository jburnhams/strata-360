# Implementation plan (from 1 Oct 2026)

This turns the README's ideas (sections 10 to 18) and the open items in `progress.md` into an ordered list of work. Each item has a goal, the code it touches, what "done" means (with a test), and a rough size (S: under a day, M: 1 to 3 days, L: about a week). The README stays the reference for how things work; this file only says what to build next and in what order.

## Where we are

**Built and working on real footage (Legends 2026, 25 clips, 1,240 s):**
- The batch: 20 cached, resumable stages run by parallel workers under resource limits (ingest through candidates and thumbnails), driven from the web app.
- Stitching and rendering from the lens files: calibration, gyro stabilisation, heading-follow, carved seam, parallax warp, stick mask fix, little planets and globe.
- The analysis data: transcripts with translation, alignment and corrections, wearer face and voice profiles, people tracks, scenes (local VLM), places (OpenStreetMap), camera clock against the FIT.
- The edit: the chronological planner (`edit/chrono.py`) with overrides saved in `project.json`, framing per window, transitions, music tempo and energy, the script writer (Gemini 3.1 Pro), voice-over (Kokoro or your own recordings), the streaming preview and the resumable final render.
- The web app: clips, moments, transcript, timeline, script, voice-over, music, clock, who-is-me, film preview, final render.

**Gaps that stop us delivering the film the README promises (goal 4, section 13):**
1. **No map overlay on the final film.** `render/final.py` joins every piece into one `film.mp4` with no per-clip UTC and no `timemap.json`/`.csv`, so the GPX overlay (the reason footage UTC is kept so carefully) cannot be driven from it. `flat.py --start-utc` can tag one clip; nothing does it for the pieces of the film. Its frame rate is also a fixed default (`fps=50.0`) rather than the source's.
2. **The final sound is a rough mix.** `preview.build_audio` (used by the final render too): mono, fixed gains (0.25, or 1.0 where people speak), 10 ms fades at every cut, music at 0.5 with a sidechain duck, a limiter. No loudness target, no crossfade on dissolves, no use of the `audio_events` roles or `audio_clean`.
3. **No exposure matching between shots.** `exposure.json` is collected but not applied; adjacent shots from different times of day will jump.
4. **No real 4K film has been rendered.** The only trial was 11 s at 640x360 (280 s on a busy machine). At about a second per 4K frame, a 120 s film at the source's 50 fps is about 1.7 hours of pure rendering at best; we do not know the real number.
5. **The voice-over does not drive the picture.** Today the order is plan, then script, then voice: the planner (`edit/chrono.py`) fixes every window in whole beats of a constant-tempo grid, the script is written into those windows, and `edit/voiceover.py` squeezes each spoken line into its window (synthetic lines sped up to 1.25x, recordings cut and flagged `over`). README 17 steps 5 and 6 (measure the recording, then fit the picture around it) are not built, and cuts can only fall on a constant grid (`edit/music.py` assumes a fixed tempo), not on the music's actual beats to the millisecond.
6. **No lens-quality data.** There is no `quality` stage, so `clear_nadir` (needed before showing a planet, a tunnel or a spin) is a guess from the VLM's "lens problems".

**Debt worth paying while we are in there:** the README has grown to 210 KB with out-of-date passages (section 1 still lists "a GUI editor" as a non-goal; section numbers are out of order); the Python coverage floor is 38%.

## Decisions this plan assumes (change them and the order changes)

| # | Assumption | Why it matters |
|---|---|---|
| D1 | The first goal is **one finished Legends film with the map overlay**, not more analysis. | Puts the deliverable film (A, V) before more analysis. |
| D2 | **Decided (1 Oct):** the delivered film is **one file**, but the map overlay is made **per input clip**: each window of the film is overlaid from its own clip's UTC span (the scheme the overlay fork already supports: `creation_time` = true start, exact UTC in the comment tag, `--video-time-start mp4-created`, branch `mp4-exact-start`), and the overlaid windows are joined into the film. A `timemap.csv` is written too, for checking and for anything else. | Resolves README 12, open question 1. Shapes A2. |
| D3 | **Decided (1 Oct):** the output frame rate **matches the source**, whatever it is (50 or 60 for the Osmo 360; 59.94 kept as the exact rational), with a GUI option to **halve it** (25 / 30) for a faster render. If clips in one film differ, the majority rate is used (README 12) and the others are resampled. Delivery: 3840x2160, HEVC Main 10, stereo AAC at -14 LUFS integrated, -1 dBTP. | Fixes the render and audio acceptance numbers. |
| D4 | Rendering stays on the CPU (Python/OpenCV) for this round; a Metal port is only done if B3's measurement says the film cannot render overnight. | Keeps the biggest piece of work optional. |
| D5 | Insta360, the MCP interface and face blur stay parked until the Legends film exists. | They are listed in Later. |
| D6 | **Decided (1 Oct):** the first cut is **voice-over driven**. The spoken voice-over sets the rough length of each clip's part of the film (with each clip's usable and preferred content); the music then sets the **precise cut moments** (to the millisecond, then the nearest frame) on its beats, without ever cutting a clip's own speech short. | Puts milestone V on the critical path straight after A1, ahead of the rest of A. |

## Milestone A: the film is deliverable (critical path)

### A1. Finish the Legends batch on current stage versions (S, mostly machine time)
- Run every default stage to completion at its current version (proxy v6 for all 25 clips; scenes, speakers, candidates, thumb_best).
- Add `strata360 coverage FOLDER [--json]` (README 15.3): per clip, which section 15.1 artefacts exist and which decisions they unblock. Show it in the Overview's progress panel.
- **Done when:** `progress` reports `complete` for Legends; `coverage` lists nothing missing for default stages. Unit test for `coverage` on a built project (`tests/utils` builders).

## Milestone V: the voice-over cut (first cut; critical path after A1)

The new order of operations, replacing plan, then script, then squeeze:

```
rough plan (clip blocks)  ->  script per block  ->  voice-over spoken / recorded and measured
      ->  re-size blocks to the measured voice-over  ->  windows inside blocks  ->  cuts snapped to the music's beats  ->  final audio placement
```

Terms: a **block** is one clip's continuous part of the film (the film stays chronological, so blocks are in shooting order); a block holds one or more **windows** (the existing plan segments: one view and technique each). Narration **lines** belong to blocks. A clip's **dialogue** (the wearer speaking on camera, the `speech` windows) is played in a gap between lines.

### V1. Rough plan: clip blocks and preferred content (M)
- `edit/chrono.py` step 1 (`allocate`) already splits the film between clips; expose it as a planning level of its own, in seconds rather than beats: per clip a block with a target length, the usable stretches it may use, its **preferred content** (best candidates by kind and priority: `speech`, `you`, `person`, `scene`, `best`) and any dialogue it must carry (with its exact speech span from `alignment.json`, padded 60 ms before and 120 ms after, README 16.4).
- Locks, bans and per-clip weights (the existing overrides) apply at this level unchanged.
- **Done when:** unit tests: every clip gets a block, blocks are in shooting order, a block's minimum is at least its dialogue plus padding, and the targets sum to the requested length.

### V2. Script written per block (S to M)
- `edit/script.py`: the writer gets blocks instead of beat windows: per block its facts (as now), its seconds minus its dialogue, and a word budget from that; lines carry the `block` id (and an optional anchor: "before the dialogue" or "after it"). Blocks with dialogue keep a marked gap.
- Keep `check()` and the one retry; budgets are now a guide, not a hard cut, because V4 re-sizes the blocks to what is actually spoken.
- **Done when:** fake-HTTP unit tests: lines map to blocks, a block's dialogue gap is never written over, the totals report words per block.

### V3. Measure the spoken voice-over (M)
- `edit/voiceover.py` stops squeezing: each line is spoken (Kokoro) or recorded at its natural length (no tempo change, no cut), and its real duration is measured; for recordings, leading and trailing silence are trimmed by energy and the words are force-aligned to the line's text with the existing aligner (`audio/align.py`) to get word times and to catch a missing or repeated line.
- Output `voiceover/vo.json` (README 17.2): per line, take, natural duration, speech start and end inside the file, word times, alignment score, loudness. Recording a new take re-measures only that line.
- **Done when:** P5-33 on a synthetic recording (Kokoro reading a known text with inserted silences): line boundaries within 50 ms, a missing line reported.

### V4. Re-size blocks to the voice-over (M)
- New `edit/vo_fit.py`: each block's length = its lines' measured durations + the pauses between lines (default 0.4 s, after a paragraph 0.9 s) + its dialogue (padded) + lead-in and lead-out (default 0.5 s each, so a line never starts on a cut), never less than the block's minimum and never more than its usable footage (if it would be, the overflow is reported: "line 7 needs 9.2 s; clip 0012 has 6.5 s usable", with the choices to shorten the line, borrow from the next block, or allow a hold on the last frame).
- The film length is now the sum of the blocks: the requested length becomes a target the script aims for, not a constraint. Lines get provisional start times in film time.
- **Done when:** unit tests: every line lies inside its own block; no line overlaps a dialogue span; the film has picture for every instant of the voice-over (P5-34); a reported overflow names the line and the clip.

### V5. Windows inside blocks, then cuts on the beat (L, the heart of it)
- **Windows.** Inside each block, cut windows from the preferred content as `cut_windows` does now (non-overlapping, 2 to 8 s, techniques by the existing beam search), but in seconds, not beats.
- **Beat times, precisely.** `edit/music.py` gains a beat tracker that returns the actual time of every beat and downbeat (dynamic programming over the onset envelope, starting from today's constant-tempo estimate, allowed to drift), refined to the onset peak, so a beat is known to within a few milliseconds even where the tempo wanders. `music.json` stores the beat list.
- **Snapping.** Every cut (between windows and between blocks) moves to a nearby beat, preferring downbeats and bar lines, within a tolerance (default: half a beat either way). Hard rules:
  1. a dialogue window always contains its whole speech span plus padding: a cut next to speech may only move **outwards** (earlier before it, later after it), never into it;
  2. a cut never falls inside a voice-over word, and a line keeps its lead-in (a cut under a line between its words is fine);
  3. each window stays inside its technique's duration range and its clip's usable footage; total length changes only by what snapping adds or removes, and lines are re-timed with their block.
  If no beat satisfies the rules, the cut stays at the nearest safe point off the beat and is reported in the plan ("cut 14 is 120 ms off the beat: the dialogue in clip 0023 ends there").
- **Milliseconds to frames.** The cut time is kept exact in the plan; the picture cuts on the nearest frame (within 10 ms at 50 fps, 8 ms at 60), the sound at the exact sample.
- **Without music:** the same pass with no beat list, so cuts land on the voice-over's pauses and the safe cut points only.
- **Done when:** unit tests on a synthetic beat list with a drifting tempo and a fixture with dialogue: every cut not reported as off-beat is within one frame of a beat; no dialogue span is shortened by a single sample; no cut inside a voice-over word; the reported off-beat cuts are exactly those the rules force; the same seed gives the same plan.

### V6. Place the sound and show it (M)
- Voice-over lines are placed at their fitted times without tempo change; music ducks under lines and dialogue (shared with A3); the preview (`render/preview.py`) and final use the new plan unchanged (it is still a list of windows).
- Timeline: blocks as bands over the windows, lines drawn above with their measured lengths, beat ticks, off-beat cuts marked with their reason; record or re-record a line from there, after which only its block and its neighbours' cuts are re-fitted (P5-35).
- **Done when:** web integration test (msw) for the block, line and beat display; Python test that re-recording one line leaves every window outside its block and its two neighbouring cuts unchanged.

## Milestone A (continued)

### A2. Map overlay per input clip, joined into one film (M to L)
How it works: every window of the plan comes from one input clip, so its UTC span is known exactly. The overlay is rendered for each window separately against the route, and the windows are then joined (with their transitions) into the single delivered file.
- **Source frame rate (D3).** `render/final.py` takes the rate from the clips (`clip.json` `video.nominal_fps`, as a rational), not the fixed 50; a `half_rate` setting (Final film panel: "Half frame rate (faster)") renders every other source frame. The preview, the time map, the overlay and the audio all use the same rate. Mixed rates: the majority rate, others resampled by nearest source frame (the renderer already maps output times to source frames).
- **Time map.** New `render/timemap.py`: from the plan and the pieces of `render/film.py`, write `<final>/timemap.json` and `timemap.csv`: per window, film in/out frame, clip, source in/out time, UTC in/out (rational), and the transition regions with both clips' UTC.
- **Overlay layer per window.** For each window (plus its transition handles, so a dissolve has overlay on both sides), run the overlay tool against the race track over that window's UTC span and produce an **overlay-only layer with alpha** at the film's size and rate. To check first: whether the fork can render an overlay-only output with transparency (its overlay-only generate mode with an alpha codec such as ProRes 4444 or PNG-in-MOV); if not, add that to the fork. Fallback if alpha is not possible: render each window's picture piece as a tagged MP4 (`creation_time` + exact UTC comment, as `flat.py --start-utc` does), overlay onto it directly, and join those (costs one extra encode of the picture).
- **Composite and join.** `render/final.py` composites each window's layer onto its picture piece before encoding (one encode, no extra generation loss), cross-fading the two layers inside a dissolve or dip just like the picture, then joins the pieces into `film.mp4` as today. The overlay layers are cached per window (key: UTC span, size, rate, overlay layout, track file signature), so re-planning only redoes changed windows.
- **Settings.** Overlay layout (the overlay tool's layout file), on/off, and position, in `race.json` `overlay` and the Final film panel; the overlay tool's location in `~/.strata360/server.json` (it lives in its own virtual environment, `.venv-overlay`). `doctor` checks it.
- **Done when:** integration test on the synthetic OSV with a synthetic GPX and a stub overlay command (writes a layer whose pixels encode the UTC it was asked for): a two-window plan with a dissolve renders one file in which each window shows its own clip's UTC to within one frame, the dissolve blends both, and the frame rate equals the source's (and half of it with `half_rate`). Time-map maths unit-tested (monotonic, every output frame covered once). One real check on Legends: the overlay's position marker matches the place seen on screen at three known points (the start line, an aid station, a village sign).

### A3. Final sound mix (M)
- Move the mix out of `render/preview.py` into `audio/mix.py` (shared by preview and final; the preview keeps a fast path).
- Per window: use `audio_clean.flac`, with the level and role from `audio_events` (`window_mix` already suggests them) instead of the fixed 0.25 / 1.0.
- Crossfade the clips' sound across dissolves and dips (equal-power, the transition's length); 30 ms crossfade on hard cuts instead of fade-out/fade-in, so cuts do not dip.
- Stereo out (the clips' own stereo where it exists, voice-over and dialogue centred).
- Loudness: two-pass `loudnorm` (or `pyloudnorm`) on the final mix to D3's target; report the measured values in the final's `status.json`.
- Duck the music to bars (`music.json`) under dialogue as well as under the voice-over (README 17.1 step 7).
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

## Milestone B: rendering is fast enough to iterate (M to L, depends on A5's numbers)

### B1. Parallel pieces (S)
- `render/final.py` pieces are independent; let up to `resources.max_workers` processes take pieces using the same claim files as the batch (`pipeline/runner.py`), at low priority.
- **Done when:** two workers on the synthetic OSV produce byte-identical pieces to one worker; resource limits respected (`tests/unit/test_resources.py` pattern).

### B2. Cheaper frames (M)
- Skip the second lens when the view lies inside one lens (most `dialogue_hold` and `selfie_hold` windows).
- Decode only the needed range of each lens stream; YUV in, convert after the remap.
- **Done when:** a benchmark script (`scripts/bench_render.py`) reports frames per second for hold, pan, planet on clip 0019; a measured gain is recorded; output differs from before by less than 1 code value at 10-bit outside the skipped lens.

### B3. Decide on a GPU port (decision, S)
- If A5 plus B1 and B2 still put a 120 s film over about 8 hours, plan a Metal (or wgpu) kernel for the per-pixel remap as a separate milestone; otherwise park it.

## Milestone C: the edit is trustworthy

### C1. `quality` stage (M to L)
- New stage after `proxy`: per second, hand or thumb over a lens, water drops or fog, blur (Laplacian variance per lens), glare, over and under exposure, seam risk (near objects at the seam from the parallax warp's near-object cells). From the lens frames at low resolution, the exposure grid and the stick polygon.
- Output `quality.json`; `candidates` uses it for `clear_nadir`, `low_obstruction` and the unusable reasons (replacing the VLM guess).
- **Done when:** a labelled set of about 40 seconds from Legends (hand over lens, drops, clear) is checked in as a fixture of measurements (no footage), and the detector agrees on at least 90%; P5-28 (no planet, tunnel or spin with a hand over the lens) passes on real candidates.

### C2. Script editing in the GUI (M)
- Regenerate one block's lines or a range (send the neighbours as context), pin a line so re-writes keep it, change the target length and re-plan blocks and script together (listed as "later in the GUI" in `notes-and-script.md`). Builds on V2 to V4.
- **Done when:** unit tests on `edit/script.py` with the fake HTTP layer: a pinned line survives a re-write byte-identical; a regenerated range leaves other lines unchanged.

### C3. Who is speaking on screen (L, optional for v1)
- Active speaker detection from mouth motion on full-resolution face crops (README 7 item 6b), fused into `speakers.json`, so dialogue framing holds on the person speaking rather than the biggest other person.
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
- **E1.** Split the README: keep sections 0 to 3 and a short "how it works" in the README; move phase specs, data contracts and design sections into `docs/` (one file per area: capture and time, stitching and render, analysis, edit, audio, GUI and server); remove passages contradicted by later work (non-goals, the two-proxy design, the free-order optimiser as the main path).
- **E2.** Trim `progress.md` to findings and decisions; the build narrative is in git history.
- **E3.** Move the three `PROMPT_*.md` files from the repo root into `docs/prompts/`.
- **E4.** Raise `fail_under` as each milestone adds tests (target 50% after V and A).

## Later (parked until the film exists)
- Insta360 adapter (needs sample `.insv` files; README 12 questions 2 and 10).
- MCP / conversational interface (Phase 9).
- Face blur for other runners and spectators (README 12 question 7).
- OpenOSV's remaining stages: photometric seam field, lens shading, flare (README 14.1); nadir inpainting; rolling-shutter correction from the 20 per-frame quaternions.
- D-Log M and HLG input.
- Taste learning from the user's earlier finished films (README 15.1, `taste.json`).
- Speech enhancement chosen per segment (README 14.6) beyond what `audio_clean` does.

## Order and dependencies

```
A1 ─> V1 ─> V2 ─> V3 ─> V4 ─> V5 ─> V6 ─┐
A2, A3, A4 (independent, alongside V) ───┼─> A5 ─> B1 ─> B2 ─> B3
                                          └─> C1 ─> (hero shots safe)
C2 after V4;  D1 after V5;  E runs alongside.
```

Suggested sequence: A1, then the V milestone in order (V5 is the largest piece), with A2 to A4 in parallel; then A5 (the first real film: voice-over driven, cut on the beat, with overlay); then B1 and C1, C2, D1, and B2/B3 as A5's numbers require.

## Questions for you
(D2, D3 and D6 answered on 1 Oct.)
1. Defaults in V4 and V5 to confirm: pause between lines 0.4 s, lead-in and lead-out 0.5 s per block, snapping tolerance half a beat, and when no beat fits, cut off the beat (reported) rather than hold the last frame.
2. Should the film length stay a hard target (shorten or drop lines to fit) or follow the voice-over (V4 as written)?
3. Are you happy for the README to be split into `docs/` (E1)?
