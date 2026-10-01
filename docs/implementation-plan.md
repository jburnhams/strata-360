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
1. **No time map from the final film.** `render/final.py` joins every piece into one `film.mp4` with no UTC tags and no `timemap.json`/`.csv`, so the GPX overlay (the reason footage UTC is kept so carefully) cannot be driven from it. `flat.py --start-utc` can tag one clip; nothing does it for the film.
2. **The final sound is a rough mix.** `preview.build_audio` (used by the final render too): mono, fixed gains (0.25, or 1.0 where people speak), 10 ms fades at every cut, music at 0.5 with a sidechain duck, a limiter. No loudness target, no crossfade on dissolves, no use of the `audio_events` roles or `audio_clean`.
3. **No exposure matching between shots.** `exposure.json` is collected but not applied; adjacent shots from different times of day will jump.
4. **No real 4K film has been rendered.** The only trial was 11 s at 640x360 (280 s on a busy machine). At about a second per 4K frame, a 120 s film at 50 fps is about 1.7 hours of pure rendering at best; we do not know the real number.
5. **The voice-over does not drive the picture.** README 17 steps 5 and 6 (align the recording to the script, then re-fit the picture around it) are not built: today the recording is squeezed into windows that were planned without it, and overflow is cut and flagged.
6. **No lens-quality data.** There is no `quality` stage, so `clear_nadir` (needed before showing a planet, a tunnel or a spin) is a guess from the VLM's "lens problems".

**Debt worth paying while we are in there:** the README has grown to 210 KB with out-of-date passages (section 1 still lists "a GUI editor" as a non-goal; section numbers are out of order); the Python coverage floor is 38%.

## Decisions this plan assumes (change them and the order changes)

| # | Assumption | Why it matters |
|---|---|---|
| D1 | The first goal is **one finished Legends film with the map overlay**, not more analysis. | Puts milestones A and B before everything else. |
| D2 | The overlay is driven by **one MP4 per film segment** (creation_time = the segment's true start, exact UTC in the comment tag), the scheme the overlay fork already supports (`--video-time-start mp4-created`, branch `mp4-exact-start`), plus a `timemap.csv` for anything else. | Resolves README 12, open question 1, with what already works. The alternative (teach the overlay tool to read a time map for one joined file) is listed as A2b. |
| D3 | Delivery target: 3840x2160, the source rate (50 fps), HEVC Main 10, stereo AAC at -14 LUFS integrated, -1 dBTP. | Fixes the audio and render acceptance numbers. |
| D4 | Rendering stays on the CPU (Python/OpenCV) for this round; a Metal port is only done if B3's measurement says the film cannot render overnight. | Keeps the biggest piece of work optional. |
| D5 | Insta360, the MCP interface and face blur stay parked until the Legends film exists. | They are listed in Later. |

## Milestone A: the film is deliverable (critical path)

### A1. Finish the Legends batch on current stage versions (S, mostly machine time)
- Run every default stage to completion at its current version (proxy v6 for all 25 clips; scenes, speakers, candidates, thumb_best).
- Add `strata360 coverage FOLDER [--json]` (README 15.3): per clip, which section 15.1 artefacts exist and which decisions they unblock. Show it in the Overview's progress panel.
- **Done when:** `progress` reports `complete` for Legends; `coverage` lists nothing missing for default stages. Unit test for `coverage` on a built project (`tests/utils` builders).

### A2. Time map and per-segment export for the overlay (M)
- New `render/timemap.py`: from the plan and the pieces of `render/film.py`, write `<final>/timemap.json` and `timemap.csv`: for every output frame range, film time, clip, source time, UTC (rational), and the transition regions (where two clips overlap, record both; the overlay follows the incoming clip from the transition's midpoint).
- `final --segments`: besides `film.mp4`, write `segments/NNN_<clip>.mp4` (cut on piece boundaries without re-encoding where possible), each with `creation_time` set to its UTC start and `comment = strata360 start_utc=<exact>`, the same tags `flat.py --start-utc` writes, plus the `<out>.utc.json` sidecar (README 5.8).
- `scripts/overlay/overlay_film.sh FOLDER`: runs the overlay tool on each segment and joins the results; documented in README section 9.
- A2b (only if D2 is rejected): add time-map input to the overlay fork's `support-fulltimeseries-journey` branch instead.
- **Done when:** P7-05 style test: on the synthetic OSV, a two-window plan renders, every segment's tags read back (ffprobe) equal the plan's UTC to within one frame, and the time map is monotonic and covers every output frame exactly once. Integration test in `tests/integration/`; time-map maths unit-tested.

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
- Render the 120 s plan at 4K50 overnight with A2 to A4; measure frames per second, peak memory, disk; run the overlay on the segments.
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

## Milestone C: the edit is trustworthy (the hero shots and the voice-over)

### C1. `quality` stage (M to L)
- New stage after `proxy`: per second, hand or thumb over a lens, water drops or fog, blur (Laplacian variance per lens), glare, over and under exposure, seam risk (near objects at the seam from the parallax warp's near-object cells). From the lens frames at low resolution, the exposure grid and the stick polygon.
- Output `quality.json`; `candidates` uses it for `clear_nadir`, `low_obstruction` and the unusable reasons (replacing the VLM guess).
- **Done when:** a labelled set of about 40 seconds from Legends (hand over lens, drops, clear) is checked in as a fixture of measurements (no footage), and the detector agrees on at least 90%; P5-28 (no planet, tunnel or spin with a hand over the lens) passes on real candidates.

### C2. Voice-over fit pass (L) (README 17 steps 5 and 6)
- `audio/vo_align.py`: force-align each recorded take (and the synthetic lines) to the script text with the existing aligner (`audio/align.py`); per line `t0`, `t1`, word times, trailing pause, score; write `voiceover/vo.json` (README 17.2). Detect missing or repeated lines.
- `edit/chrono.py`: a voice-over mode in which line intervals are fixed anchors: windows flex to the lines, cuts prefer line boundaries and pauses, dialogue windows go into the pauses, the picture is never empty. Locked windows still win.
- Report shortfalls by name ("pause after line 12 is 1.8 s short for clip 0023's dialogue"), and offer to re-record only that line from the Voice-over panel.
- **Done when:** P5-33 (line boundaries within 50 ms on a synthetic recording made with the Kokoro engine from a known text), P5-34 (no gap in picture; dialogue inside pauses and cut at safe points), P5-35 (re-recording one line changes nothing outside its sections).

### C3. Script editing in the GUI (M)
- Regenerate one segment or a range (send the neighbours as context), pin a line so re-writes keep it, change the film length and re-fit plan and script together (all listed as "later in the GUI" in `notes-and-script.md`).
- Let the planner choose the in-point inside a candidate (today it assumes the start), so the script and the picture agree on what is on screen.
- **Done when:** unit tests on `edit/script.py` with the fake HTTP layer: a pinned line survives a re-write byte-identical; a regenerated range leaves other lines unchanged.

### C4. Who is speaking on screen (L, optional for v1)
- Active speaker detection from mouth motion on full-resolution face crops (README 7 item 6b), fused into `speakers.json`, so dialogue framing holds on the person speaking rather than the biggest other person.
- **Done when:** P5-29 passes on a fixture with a known speaker. Can slip to Later if dialogue framing looks acceptable in A5.

## Milestone D: editing in the GUI is fast

### D1. Timeline editing (M)
- Drag a window's edges; they snap to beats and to safe cut points (`alignment.json`).
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
- **E4.** Raise `fail_under` as each milestone adds tests (target 50% after A and C).

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
A1 ─┬─> A2 ─┐
    ├─> A3 ─┼─> A5 ─> B1 ─> B2 ─> B3
    └─> A4 ─┘      └─> C1 ─> (hero shots safe)
                   └─> C2 ─> C3
D1 can start any time after A1;  E runs alongside.
```

Suggested sequence: A1, A2, A3, A4 (A2 to A4 are independent and can go in parallel), A5, then B1 and C1 together, C2, C3, D1, B2/B3 as A5's numbers require.

## Questions for you
1. **D2:** is one MP4 per segment acceptable for the overlay, or do you want a single joined file the overlay tool reads with a time map?
2. **D3:** is 50 fps 4K right for the delivered film, or would 25 fps (half the render time) do?
3. Which matters more for the first film: the **voice-over driving the cut (C2)** or **music-driven** pacing? It decides whether C2 moves ahead of C1.
4. Are you happy for the README to be split into `docs/` (E1)?
