# Implementation plan (from 1 Oct 2026)

This turns the README's ideas (sections 10 to 18) and the open items in `progress.md` into an ordered list of work. Each item has a goal, the code it touches, what "done" means (with a test), and a rough size (S: under a day, M: 1 to 3 days, L: about a week). The overview (`overview.md`, formerly the README) stays the reference for how things work; this file only says what to build next and in what order.

## Where we are

**Built and working on real footage (Legends 2026, 25 clips, 1,240 s):**
- The batch: 20 cached, resumable stages run by parallel workers under resource limits (ingest through candidates and thumbnails), driven from the web app.
- Stitching and rendering from the lens files: calibration, gyro stabilisation, heading-follow, carved seam, parallax warp, stick mask fix, little planets and globe.
- The analysis data: transcripts with translation, alignment and corrections, wearer face and voice profiles, people tracks, scenes (local VLM), places (OpenStreetMap), camera clock against the FIT.
- The edit: the chronological planner (`edit/chrono.py`) with overrides saved in `project.json`, framing per window, transitions, music tempo and energy, the script writer (Gemini 3.1 Pro), voice-over (Kokoro or your own recordings), the streaming preview and the resumable final render.
- The web app: clips, moments, transcript, timeline, script, voice-over, music, clock, who-is-me, film preview, final render.

**Gaps that stop us delivering the film the README promises (goal 4, section 13), as of 8 Oct 2026:**
1. **No real 4K film has been rendered (A5).** The only trial was 11 s at 640x360. The overlay, source frame rate, time map (A2), the mix (A3) and the exposure match (A4) are built and tested on synthetic clips, but not yet looked at on a full Legends render (position check at three known places still by eye). At about a second per 4K frame, a 120 s film at 50 fps is about 1.7 hours of pure rendering at best; the real number is unknown.
2. **The script does not yet drive V1 to V4 in the app.** The script writer, its GUI (V2c) and the director items exist; the planner builds from the script (`script_plan`, `beat_sync`), but the full loop on Legends (mark, pin, revise, then plan, voice, cut on the beat) has not been run end to end, and V3's real aligner on real recordings is unchecked.
3. **Quality and cameras are built** (K1 to K7: scenes v2 and the project's own scale, the `quality` stage and `view_quality`, the per-clip camera list, the scenery camera; K4 was superseded by the script writer and K5 is the window structure plus `beat_sync`). What is open is judging them on a real film (A5), C1's labelled lens fixture, C3 active speaker detection and D1 timeline editing.
4. **Enlarging tight shots** exists for stills and 1080p; at 4K almost every shot would need it and a frame costs 4 s or more, so it is not practical for the whole film. No enlarged film has been rendered.

**Status (8 Oct 2026, branch `claude/upscale-and-stills`).** Built since the 2 Oct status (details in the milestone sections below and in `progress.md`):
- **A2** frame rate from the footage and half-rate switch, `timemap.json/.csv`, `doctor` map key check; **A3** stereo mix with crossfaded joins, exact ducking and loudness target; **A4** exposure match between shots (`render/grade.py`).
- **V2b/V2c** whole-race script writer with pins, marks and notes in the GUI; **V4** borrowing from the next item; **V5** `edit/beat_sync.py` (cuts on the music's beats, music start searched).
- **M1 to M3** race map and charts; **N1** 2D gap map clips and **N2 the 3D terrain flyover**, both wired into the script, planner, preview and final render (the planner chooses 2D or 3D per gap; gap pages in the GUI). Windows is untried for the flyover.
- **G** generated music: stems, re-sequencing to any length, layering, lyrics, `sing` items, built mode; ACE-Step repaint experiments (not judged by ear, not in the repo).
- **K** per-clip camera list (`cameras` stage), `lens` stage first cut, **upscaling** (`edit/upscale.py`, modes off/1080p/1440p/full), stills of the final film, render progress, still gallery.
- **One pipeline for preview, still and final (8 to 9 Oct):** generated clips (gap maps, flyovers, photos, street view, street view point cameras) are rendered from their original sources at the film's own frame rate and size (`edit/synth_render.py`, kept in `synthetic/film/`); a point camera on a clip is cut from the original OSV by the final renderer; the preview is the final renderer (`FinalSource`) with preview parameters and a `--source proxy|osv` option (`strata360 film`). **A5 done once:** the first full 4K Legends render (`final/af061ea030/film.mp4`, 3.26 GB) and its defect check (`progress/2026-10-music-upscale.md`).
- **Selective enlarging (9 Oct):** RealPLKSR only, a whole shot when more than 0.5 s of it needs 2.5x or more (`--upscale full --upscale-min-zoom 2.5`; 6 Legends shots, 40 s). Enlarger comparisons (RealPLKSR, SwinIR, Real-ESRGAN, SCUNet, FBCNN, SeedVR2 does not fit the 16 GB Mac) and the zoom histogram are in the progress log; `scripts/zoom_histogram.py`, `scripts/zoom_thresholds.py`, `scripts/vsr_exp/` (Windows PC video-model trial).

*Next, in order:*
1. **A5 is done once (8 Oct): the first real 4K Legends render exists** (`final/af061ea030/film.mp4`, 3.26 GB; timings and defects in `progress/2026-10-music-upscale.md`). Next: render the enlarged version (6 shots) and compare, true peak -0.4 dBTP (target -1), overlay legibility on light maps, the preview's audio (-15.2 LUFS, peak +0.2 dBFS) and the dip transition, the video-model trial on the Windows PC, then re-render. Machine jobs waiting: render clip 0021's proxy again (dropped-frame fix), and the gap clips made before the 3 Oct route change (the maps and flyovers G11, G17, G19).
2. **Run the script loop on Legends** (V2c step 5c), then wire the chosen script through V3 (real aligner on real recordings) and V4; V6 timeline display and per-line re-recording.
3. **D1 timeline editing** (drag edges with beat snap, re-plan only the unlocked part); then C3 (optional) and C1's labelled fixture (low priority: a hand over the lens is minor). K1 to K5 and C2 are done (see Milestone K's status and V2c).
4. **Left over in finished milestones:** A2 settings in the Final film panel (map style, zoom, elements, key field); M4 (day/night shading, background tiles, zoom to a clip, clock-check use); V5 voice-over word times and cuts without music; G real runs (Demucs, `sing` items, judging repainted bars by ear); enlarging threshold decision and a diffusion upscaler (blocked by memory on the 16 GB Mac); flyover on Windows.
5. **B1 to B3** faster rendering (GPU) after A5; **E1** doc debt (out-of-date overview passages, size).

*Decisions since 1 Oct:* D8 and D9 stand. **The writer decides what the film says** (V2b). **Quality is always a soft score**; nothing is marked unusable. **Cameras are signals plus an optimiser with seeded randomness** (Milestone K). **Scores are fitted to each project's own range.** **Red, green, white (and a derived yellow)** is the one colour language for transcript and script (V2c). **The speech track plays only where a clip item includes it; elsewhere the film's own sound is the speech-free background track** (A3). **The planner chooses 2D map or 3D flyover per gap; no credits drawn on screen** (3 Oct).

**Debt worth paying while we are in there:** the overview has grown to 210 KB with out-of-date passages (section 1 still lists "a GUI editor" as a non-goal; section numbers are out of order); the Python coverage floor was 38% (now 47%).


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


## Order and dependencies

```
A1 ─> V1 ─> V2 ─> V3 ─> V4 ─> V5 ─> V6 ─┐
K1, K2 ─> K3 ─> K4 (feeds V1) and K5 (is V5) ───┤
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

## Milestones and other sections (one file each)

- [Milestone A: the film is deliverable (critical path)](plan/milestone-a-the-film-is-deliverable.md)
- [Milestone V: the voice-over cut (first cut; critical path after A1)](plan/milestone-v-the-voice-over-cut.md)
- [Milestone A (continued)](plan/milestone-a-continued.md)
- [Milestone K: virtual cameras, quality signals and the optimiser (design 1 Oct; feeds V1's preferred content and V5's cuts)](plan/milestone-k-virtual-cameras-quality-sign.md)
- [Milestone M: the race map and charts (design 2 Oct, morning; defaults in brackets await confirmation)](plan/milestone-m-the-race-map-and-charts.md)
- [Milestone N: generated clips for the gaps (idea 2 Oct; research done, decisions open)](plan/milestone-n-generated-clips-for-the-gaps.md)
- [Milestone G: generated music (design 5 Oct; options and plan in `docs/ai-music.md`)](plan/milestone-g-generated-music.md)
- [Milestone B: rendering is fast enough to iterate (GPU first)](plan/milestone-b-rendering-is-fast-enough-to.md)
- [Milestone C: the edit is trustworthy](plan/milestone-c-the-edit-is-trustworthy.md)
- [Milestone D: editing in the GUI is fast](plan/milestone-d-editing-in-the-gui-is-fast.md)
- [Milestone E: documentation and test debt (S each, alongside the others)](plan/milestone-e-documentation-and-test-debt.md)
- [Later (parked until the film exists)](plan/later.md)
- [Several tracks per project: runs and routes](plan/several-tracks-per-project-runs-and-rout.md)
