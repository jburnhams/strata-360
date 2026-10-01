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

**Status and work plan (2 Oct 2026, after the first long session on branch `main`, nothing committed yet: about 40 changed files; 487 Python unit tests pass).**

*Running or queued on the machine (one low-priority worker at a time; a second needs 7 GB free and a load under 8):*
1. **A1, the proxy worker** (started 1 Oct 23:19, about 5 hours left at the time of writing): proxies for 22 clips at stage v6 (the first real v6 proxies, clips 0001 to 0003, look clean: no stick, clean seams), then candidates and the thumbnails. The older v3 proxies are replaced; people, scenes and speakers keep their results (the proxy is only a soft dependency of those stages).
2. **`audio_background` for all 25 clips**, queued to start by itself when the proxy worker exits (opt-in stage, TIGER-DnR effects model, about 1.2 GB; run so the film's mix can play the speech-free sound; about 100 minutes on the CPU).
3. After both: **K1, scenes v2** (scenery-only graded prompt with clarity, about 40 minutes), then the quality grid stage (K2).

*Code work that needs no machine (in this order):*
1. **V2c steps 3 to 5** (the marking design is agreed): a `script-draft` command and `/api/script2` (draft, revise, warnings, last three drafts), the transcript panel's selection and red / green / white toggle, the script panel with the same selection, narration edits becoming pins, the diff, and the warnings. Steps 1 and 2 are built (below).
2. **Wire the script into V1 to V4:** the script's clip items become the must-carry dialogue and per-clip seconds (V1 stops allocating from the speech candidates), V3 measures the narration, V4 fits it.
3. **K2 `view_quality`**, **K3 the camera and tracking engine** (with the scenery camera), **K4 the section chooser**, **K5 = V5, the multicam cutter on the beat.**
4. **A2 (frame rate, time map, overlay settings), A3 (mix), A4 (grade).** A3 has a new rule (below).

*Built since 1 Oct (all unit tested):* the Music panel and `music.json` (`edit/music.py`); `strata360 plan-blocks` (V1 wired as a command); the proxy renderer fix (`_dirs` and the parallax warp in `EquirectRenderer.maps`); the overlap tolerance in `chrono.violations`; `edit/quality_scale.py` (the self-calibrating 0 to 10 scale); film details gained the **official race distance**; the whole-race script writer's pieces: `edit/script_pack.py` (context pack, lines split wherever the user's marks change), `edit/script_pins.py` (MUST INCLUDE / DO NOT USE lines, three narration anchors, never-say phrases, pins from the notes), `edit/script_ground.py` (advisory grounding checks), `analysis/transcript_marks.py` (per-word marks beside the corrections), the narration MUST INCLUDE fields in `notes.json` (`vo_must`), `/api/transcript/mark` and the `kind: "vo"` notes endpoint, and `scripts/script_exp/` (prompts v1 to v4, runner, checker). Also the experiments in `scripts/` (quality grid, view picking, VLM prompts).

*Decisions since 1 Oct:* D8 and D9 stand. **The writer decides what the film says** (V2b); the film's clip items drive the dialogue, not a speech budget. **Quality is always a soft score**: nothing is marked unusable (ultra footage is often foggy); droplet detection is dropped. **Cameras are signals plus an optimiser with seeded randomness** (Milestone K), including a scenery tracking that avoids people. **Scores are fitted to each project's own range.** **Red, green, white (and a derived yellow)** is the one colour language for the transcript and the script (V2c); red also silences that speech in the film's own sound. **The speech track plays only where a clip item includes it; everywhere else the film's own sound is the speech-free background track** (A3).

**Debt worth paying while we are in there:** the README has grown to 210 KB with out-of-date passages (section 1 still lists "a GUI editor" as a non-goal; section numbers are out of order); the Python coverage floor was 38% (now 47%).

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
- **Built (1 Oct):** `strata360 coverage FOLDER [--json]`, `/api/coverage` and a "Data missing" line in the progress panel (`pipeline/coverage.py`, `tests/unit/test_coverage.py`). **Still to do:** the batch run on Legends. **Started 1 Oct (evening):** one low-priority worker (`strata360 open`); it waits whenever the machine is busy. Left: exposure (3 clips), proxy, candidates, thumb_best, thumb_overlay.
- **Done when:** `progress` reports `complete` for Legends; `coverage` lists nothing missing for default stages.

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
- **Music upload (1 Oct, first step of wiring V1 in):** the Overview has a Music panel (upload, or player + waveform + spectrogram + bar lines + energy and a "change" link). `<race dir>/music.json` holds the file name as uploaded, the analysis (bpm, first downbeat, sections, confidence), the waveform peaks and the spectrogram file (`edit/music.py` `store`/`info`; `/api/music`, `/api/music/audio`, `/api/music/spectrogram`). The track's length is what D8 will hand to `plan_blocks` as the film target; nothing reads it that way yet.
- **Built (1 Oct):** `edit/blocks.py` (`plan_blocks`), `tests/unit/test_blocks.py`; `project.load_clips` also passes `alignment`. Not yet wired into `project.propose` or the GUI (V2 consumes it). The film target is passed in; choosing it from the music or a target length is left to the caller.
- **Wired in as a command (1 Oct):** `strata360 plan-blocks FOLDER [--target-s N] [--auto] [--json]` (`project.rough_blocks`, writes `<race dir>/blocks.json`; length guide: `--target-s`, else the music track from its first downbeat, else automatic; the saved beat plan is untouched). **First run on Legends with a 247 s track found a problem:** every `speech` candidate is treated as dialogue the block must carry in full, which on Legends is 228 s of speech in 24 clips (27% of the usable footage) and block minimums of 276 s, more than the whole film, so 14 clips were dropped. Speech has to become a ranked, budgeted selection (the best spans up to a share of the film, the rest left as b-roll without its sound) before V1's "carry all dialogue" rule makes sense; the chosen spans then become the must-carry dialogue for V2 to V5.
- **Done when:** unit tests: every clip gets a block, blocks are in shooting order, a block's minimum is at least its dialogue plus padding, the targets sum to the film target; an unusable clip is dropped and reported while a merely dull one keeps a block; automatic length grows with usable footage and is reproducible.

### V2. Script written per block (S to M)
- `edit/script.py`: the writer gets blocks instead of beat windows: per block its facts (as now), its seconds minus its dialogue, and a word budget from that; lines carry the `block` id (and an optional anchor: "before the dialogue" or "after it"). Blocks with dialogue keep a marked gap.
- Keep `check()` and the one retry; budgets are now a guide, not a hard cut, because V4 re-sizes the blocks to what is actually spoken.
- **Built (1 Oct):** `script.block_facts`, `build_block_messages`, `check_blocks`, `write_block_script` (lines carry `block` and `anchor`; the budget is soft: 1.3x plus 2 words before a retry, nothing is cut; the doc has per-block totals). Tests: `tests/unit/test_script_blocks.py` (scripted model, not HTTP). Not yet called from `strata360 script` or the app, which still use the beat-window path until V4 lands. Also fixed `words_in_window` failing when no clips folder is given.
- **Done when:** fake-HTTP unit tests: lines map to blocks, a block's dialogue gap is never written over, the totals report words per block.

### V2b. Whole-race script writer with pins (decided 1 Oct; replaces "carry all the dialogue" in V1)
The writer sees every clip at once and decides what the film says: which of the runner's lines to keep, the narration that links them, and the picture each clip gets.
- **Input (`edit/script_pack.py`):** per clip, in shooting order: the clip number, local time, GPS distance, pace, place, what the scene model saw, the runner's note and the corrected transcript as numbered LINES with exact times; plus the race facts and the user's notes. About 7,600 tokens for Legends (25 clips, 1,637 words of speech). Film details now hold the **official race distance** (`distance_km`, entered in the Film details panel): the GPS length reads longer (367 km against a 350 km race) because of detours.
- **Length guide (D7, D8):** the music's length from its first downbeat; else a target; else automatic: about 5 minutes, at least 50% of the total clip length and at most max(50%, 10 minutes) when the quality of the clips and the amount of transcribed speech justify it. **Narration speed:** the average of the normal voice-over speed (145 wpm) and the runner's own speech rate (228 wpm on Legends), at most 1.25 times the voice-over speed (about 181).
- **Output:** JSON items played one after another: `clip` (the runner's own lines, `from` and `to` line ids), `vo` (narration, with a short `basis`), `broll` (picture, seconds); plus `skipped` clips with reasons. Durations are recomputed by the checker (`scripts/script_exp/run.py check`), never taken from the model; a retry sends the problems back.
- **Iterating (the point of the design):** the first reply is a draft. The user then marks transcript lines **MUST INCLUDE** or **DO NOT USE**, and writes or keeps narration with an anchor: **inside a clip's run**, **in order but anywhere**, or **anywhere** (`edit/script_pins.py`; the tags go into the clip list and a constraints section tells the writer how much time the fixed parts already use). The writer then **revises the current draft**, keeping every item the new constraints do not touch. Fixed parts make the problem smaller: they fix how long and how many clips are left.
- **Checks:** structure drives retries (length within 3%, shooting order, one run per clip, no more picture than a clip has usable, every pin honoured). **Grounding is advisory** (`edit/script_ground.py`): a narration `basis` that is not in the material, a number that is nowhere in it, a claim that rests on a transcript line which is not placed next to it. They are shown to the user as warnings, never block a draft.
- **Prompt rules that matter (all generic, nothing about one race):** narration 20 to 30 percent of the film in short bridging pieces; give the clips with no speech a reason to be there; never invent; put each fact on the clip it belongs to; when the runner's words show a claim, put those words right next to the narration; the ending gets room and mostly the runner's own voice; the runner's recordings can describe earlier events.
- **Experiment (Gemini 3.1 Pro, paid key, 1 Oct):** one call takes 60 to 150 s with 14 to 20k tokens in and about 2.5k out (roughly 5 to 10 cents). A first draft usually lands within 3% of the target on the first or second attempt. A pinned revision satisfied every pin on the first attempt. Narration share rises from 13% to about 29% with the "20 to 30 percent" rule. Hard grounding rules cut the invented facts but also cut good narration, so v4 asks for a `basis` and only warns. Two of my early "errors" were my own: a checker that used the GPS length as the race distance, and a track pack line that made "80 hours" read as a time limit.
- **To do:** the GUI (read the draft item by item; toggle lines MUST INCLUDE or DO NOT USE; add and anchor narration; "revise" with a diff; warnings beside the items); store the script and the pins in the project; then the script's clip items become V1's must-carry dialogue and per-clip seconds (V1 stops allocating from the speech candidates), V3 measures the narration, V4 fits it. Chronology note: the music-first target then comes from the script's length.

### V2c. Marking and editing the script in the GUI (design 2 Oct)
**One colour language, two places.** Every word of the transcript, and every word of the draft script, has a state the user can set by selecting text (dragging across words, lines and clips is allowed) and pressing a toggle (three buttons; keys G, R, W):
- **red = NEVER USE / never say**, **green = MUST USE / must say**, **white = don't care**.
- **yellow is not stored**: it is a transcript word that is white but used by the current draft (so white = could use but isn't, yellow = could use and is). It is worked out from the draft's clip items.
Where the states live:
- *Transcript:* `transcript_marks.json` beside `transcript_edits.json`, per word, with the same `segment:word` keys, so marks survive re-runs the way corrections do. The marks reach the writer by **splitting the lines at every change of state** (`0023.27` becomes `0023.27.1`, `.2`, ...), so the writer still only chooses whole lines and `script_pins` only needs line ids; word-level cuts come from the split.
- *Narration (the script's own words):* a green selection becomes a pin (the selected text, word for word, anchored to the clip it sits in; the user can loosen it to "in order" or "anywhere"); a red selection becomes a "never say" phrase that the checker looks for. Pins are stored as text, not offsets, so they survive a rewrite. **A manual edit of any narration word turns the edited words green.**
- *The transcript inside the script:* the clip items in the script view show the same words with the same colours, and a toggle or an edit there is the same operation as in the transcript panel: it writes `transcript_marks.json` or `transcript_edits.json` (an edited word is also marked green), as if done in situ.
**Notes get a narration field.** Next to the notes at both levels (the whole folder, and each clip) a "Voice-over MUST INCLUDE" text area, one piece of narration per line: at clip level each line is anchored inside that clip's run; at folder level each line is "anywhere", with a "keep in the order written" switch.
**Clash to avoid:** the transcript panel already uses amber and blue backgrounds for corrected words. The four colours above take the background; corrections move to a small marker (a dotted underline: amber for Gemini, blue for the user; the hover text stays).
**Open questions (defaults in brackets):** does red also silence that speech in the film's own sound wherever a window of that clip plays (yes: the sound ducks out, the picture stays)? Do green words force a skipped clip back into the film (yes)? Is the draft kept with each save so a revise can show a diff (yes, last three)?
- **Build order:** (1) `transcript_marks` and the narration fields in the notes (backend, tests); (2) split lines in `script_pack`, pins from marks and notes in `script_pins`; (3) `strata360 script-draft` and `/api/script2` (draft, revise, warnings); (4) the transcript panel's selection and toggle; (5) the script panel with the same selection, edits to pins, the diff and the warnings.

### V3. Measure the spoken voice-over (M)
- `edit/voiceover.py` stops squeezing: each line is spoken (Kokoro) or recorded at its natural length (no tempo change, no cut), and its real duration is measured; for recordings, leading and trailing silence are trimmed by energy and the words are force-aligned to the line's text with the existing aligner (`audio/align.py`) to get word times and to catch a missing or repeated line.
- Output `voiceover/vo.json` (overview 17.2): per line, take, natural duration, speech start and end inside the file, word times, alignment score, loudness. Recording a new take re-measures only that line.
- **Built (1 Oct):** `edit/vo_measure.py`: `measure_take` (one file per line), `measure_recording` (one recording of several lines, split by aligning all words at once, with the pauses between), `measure_script` (speaks or takes the recording of each line of a block script at natural length, writes `voiceover/vo.json`, reuses unchanged lines so a new take re-measures only its line). Line statuses: `ok`, `short` (words missing), `long` (extra or repeated), `mismatch`, `silent`, `missing`. The aligner is injected (default wav2vec2). Tests: `tests/unit/test_vo_measure.py` (tone "speech" and scripted aligners), one integration test with the fake engine. The old squeeze path in `voiceover.build` stays until V4/V6 replace it. **Not yet checked:** the real aligner and Kokoro on a real recording (P5-33 by hand: loudness is RMS dBFS, not LUFS; the status limits assume about 150 wpm).
- **Done when:** P5-33 on a synthetic recording (Kokoro reading a known text with inserted silences): line boundaries within 50 ms, a missing line reported.

### V4. Re-size blocks to the voice-over (M)
- New `edit/vo_fit.py`: each block's length = its lines' measured durations + the pauses between lines (default 0.4 s, after a paragraph 0.9 s) + its dialogue (padded) + lead-in and lead-out (default 0.5 s each, so a line never starts on a cut), never less than the block's minimum and never more than its usable footage (if it would be, the overflow is reported: "line 7 needs 9.2 s; clip 0012 has 6.5 s usable", with the choices to shorten the line, borrow from the next block, or allow a hold on the last frame).
- **Film length (D7).** The sum of the blocks is the voice-over timeline V; the music's length is M (from its first downbeat, or from where the user starts it). Hard rule: L >= V. Target: L = M. Settings (defaults to confirm): `fade_max_s` (how much of the music may be lost to an early fade-out, 8 s), `lead_silence_max_s` (silence before the music starts, 4 s), `tail_silence_max_s` (silence after it ends, 6 s).
  - **Music longer (M > V):** the extra M - V is spread over the blocks: longer holds and pauses inside each block's usable footage, extra windows from preferred content, and a music-only intro and outro (picture with no narration, up to a few bars each). If the footage cannot fill all of it, L = V + what can be filled and the music fades out over its last bar or at a section end; if more than `fade_max_s` of the music would be lost, the shortfall is reported (with which clips ran out of footage).
  - **Voice-over longer (M < V):** L = V. The music is placed inside the film with silence (or the clips' own sound) before and/or after it, split between start and end as the sync allows, each within its limit; beyond the limits the shortfall is reported with the options to pick a longer track, loop a section of the track at a bar line, or shorten the script (C2's per-block re-write, which this pulls forward). The script writer (V2) is given the music's length as its target, so this is the exception.
  - **Music position is free within the flexibility.** The music's start in the film (an offset, possibly negative: starting part-way into the track) is chosen in V5 together with the cuts, so downbeats fall on the cuts that matter (block boundaries, the first dialogue, the last cut); the film may grow by a beat or two for this, never shrink below V.
  - **No music:** L = V, plus a short lead-in and lead-out; with a target length the extra or missing time is handled as for music (spread over the blocks, or reported), but more loosely, since there is no beat to land.
- Lines get provisional start times in film time.
- **Speed as a last resort (decided 1 Oct):** before a block's overflow is reported, its **synthetic** lines are played faster, one factor for the block, at most 1.25x as before (recordings are never changed). The line is spoken again at `rate x tempo` words a minute, not time-stretched, and measured; its `vo.json` entry gets `tempo_applied`, which counts against the limit on the next fit.
- **Built (1 Oct):** `edit/vo_fit.py`: `fit` (blocks, lines, film length, music placement, problems with choices), `respeak`, `fit_project` (measure, fit, re-speak the sped lines, fit again). Tests: `tests/unit/test_vo_fit.py`, one integration test with a voice whose pace follows the rate. Not yet wired into `strata360 script`, the project file or the app. The music-only intro and outro are folded into the first and last block's lead-in and lead-out; V5 cuts the real windows. The dialogue is one gap of its total padded length per block (V5 places the real spans). `paragraph_after` on a script line gives the longer pause; nothing sets it yet.
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
- `tiles.py`: Web Mercator, tiles fetched once into `~/.strata360/tiles/<style>/` and shared by every race (the last 256 also kept in memory), 512-pixel `@2x` tiles where the style has them; Thunderforest styles (key `THUNDERFOREST_API_KEY` from the environment or `secrets.env`, never in an error) and `osm`. The whole-route map uses a plain style (`tf-landscape`: towns, main roads, relief), the close-up a detailed one (`tf-outdoors`: contours, paths, hill shading); either can be changed per map.
- `draw.py`: Pillow for text (bundled Inter, SIL OFL), shapes drawn at 4x and reduced, OpenCV anti-aliased route lines, a soft shadow behind text and icons, digits in equal-width cells; patches laid onto 8- or 16-bit frames.
- `zoom.py`: the close-up zooms by itself within local_zoom +/- 1.5: closer where the map is busy (share of edge pixels in the map around each 200 m of route, ranked within the race), wider on straight stretches (straight-line over path distance across 800 m); worked out once per race and smoothed over 1.5 km and 30 s, so it drifts and holds still when the runner does. Checked on OpenStreetMap tiles round Houffalize: 12.5 on the open road, 14.8 in the town centre.
- `layout.py`: the reference's elements, configured in Python, not XML: date and time, distance, pace, altitude / slope / heart rate with our own vector icons (the slope icon points downhill when the slope is negative), the whole route with the marker, the moving close-up map (zoom 14) and the map credit. Written for 1920 x 1080 and scaled to the film, each element kept at its distance from its edges. race.json `overlay`: `enabled`, `style`, `elements`, `layout` (per-element overrides), `scale`, `map_opacity`, `local_zoom`, `font`, `label_font`; the race `timezone` sets the clock.
- `render/final.py`: `FinalSource` draws the overlay on each frame (so a dissolve cross-fades the two windows' overlays like the picture); the film's cache key includes the overlay settings and the track file. A missing map key stops the render at the start, not hours in.
- Nothing is stored per frame: the overlay is drawn onto each frame as it is rendered; what does not change is drawn once and reused (each distinct text, the whole-route map, the close-up while standing still). The close-up is resampled from a larger cached map at the exact position and zoom each frame, so it pans and zooms by fractions of a pixel.
- `thumb_overlay` stage (after `thumb_best`, needs the track): the clip's thumbnail with the overlay at the thumbnail's own moment (`thumb_overlay.jpg`; without a map key, the numbers only); a new thumbnail removes it so it is redone. The app has an "Overlay on thumbnails" switch above the clip list (remembered in the browser); `/api/thumb?overlay=1` sends that version when it is up to date, else the plain one.
- Cost: about 5 ms a frame at 1080 and 22 ms at 4K (the render itself is about 1 s a frame); the first frame of a new place fetches its tiles.
- Unit tests: `tests/unit/test_overlay_{series,tiles,draw,layout,zoom}.py`, `test_thumbs.py` (fake tile service, no network); web: `thumbOverlay` unit and integration tests.

**Still to do:**
- **Source frame rate (D3).** `render/final.py` takes the rate from the clips (`clip.json` `video.nominal_fps`, as a rational), not the fixed 50; a `half_rate` setting (Final film panel: "Half frame rate (faster)") renders every other source frame. The preview, the time map, the overlay and the audio all use the same rate. Mixed rates: the majority rate, others resampled by nearest source frame.
- **Time map.** New `render/timemap.py`: from the plan and the pieces of `render/film.py`, write `<final>/timemap.json` and `timemap.csv`: per window, film in/out frame, clip, source in/out time, UTC in/out (rational), and the transition regions with both clips' UTC.
- **Settings in the app.** Overlay on/off, elements, map styles and zoom in the Final film panel (writes race.json `overlay`); a field to store the map key in `secrets.env` (like `set-key`); `doctor` reports whether a key is set and how many tiles are cached. Optionally the overlay on the preview too (it is cheap).
- **Done when:** integration test on the synthetic OSV with a synthetic track and the fake tile service: a two-window plan with a dissolve renders one file in which each window shows its own clip's UTC to within one frame (read back from the drawn clock, or from a test element that encodes the time in pixels), the dissolve blends both, and the frame rate equals the source's (and half of it with `half_rate`). Time-map maths unit-tested (monotonic, every output frame covered once). One real check on Legends: the overlay's position marker matches the place seen on screen at three known points (the start line, an aid station, a village sign); the clock matches the camera clock check.

The reference (kept in `scripts/overlay/`: `layout.xml` and the command line used before) is what the look was matched against; `overlay_segment.sh` stays for anyone who still wants to run the fork on one segment.

### A3. Final sound mix (M)
- **Voice only when asked for (decided 2 Oct).** The clip's own speech (`audio_clean.flac`, the voice track) plays only inside a script `clip` item (and a window the user marks to keep its sound); everywhere else a window's own sound is the speech-free background (`audio_background.flac`, which needs the stage run for every clip; queued). Words marked red (NEVER USE) are never audible: the sound ducks out over them even inside a window of that clip. Today's mix (`render/preview.py build_audio`) still plays every window's own sound at 0.25 gain, so the voice is faintly there under b-roll: that changes.
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

## Milestone K: virtual cameras, quality signals and the optimiser (design 1 Oct; feeds V1's preferred content and V5's cuts)

The idea: for each clip, a list of **virtual cameras** in order of quality. A camera has a start and an end time (it need not cover the clip) and is either a **tracking** or a **free** camera:
- **Trackings** (full clip length by default, shortened at either end where the picture is bad there; each with its own field-of-view rules): **heading** (where the runner goes), **you** (the wearer: the head and body rules we have), **person** (another person), and **scenery** (below). Heading and the others may favour an ultra-wide view and zoom in to avoid artefacts at the edge.
- **Free cameras**: a fixed pose and field of view, or a start pose and an end pose with a pan or zoom between them; far more flexible; about one per 15 s of clip, at most 12.
Then the film is chosen in two steps: first **which part of each clip** (transcript spans decide it where there is a transcript, extended if the film needs the time; otherwise the best-quality stretches of the best cameras, optimised against the time the script and music need), then **which camera at each moment** (cuts follow the music's energy; favour you or person where there is a transcript). This is an optimisation over several signals, with **seeded randomness** for variety (same seed, same film).

**Scenery tracking (added 1 Oct): a tracking view that avoids every person and takes the best-quality scenery available.**
- *Avoid people:* the view may not contain a person box (from `people.json`, inflated by a margin; the wearer and the pole count) above a small share of its area, and the rear direction where the wearer sits is a no-go unless the camera looks elsewhere.
- *Best quality:* a scenery-only score. Direction prior from the VLM's front and rear scenery scores (the prompt ignores people, since the people stage knows them), refined by the quality grid on the 15 degree cells (exposure; a heavy flat or foggy patch counts against a view only when it takes about half of it; detail only as a tie-break).
- *Movement, as for the other trackings:* either **slow and steady** (a rate limit; it moves only when another direction has been clearly better for a few seconds) or a **quick jump cut**, and **jump cuts are rationed** (a budget per minute, default 2; pans last at least a minimum time). One dynamic programme over yaw bins: pan cost grows with the angle, a jump costs a fixed amount, the budget is enforced, and a little seeded noise in the costs gives variety.
- Used for b-roll when there is no transcript (we do not favour people then) and for contrast with people shots (a people-free alternative the VLM cannot undo).

**Signals** (quality is always a **soft score**: nothing is marked unusable, as a lot of ultra footage is foggy; droplet detection was tried and dropped, see `progress.md`):
1. VLM, front and rear every 5 s: a graded 1 to 10 scenery score and a 1 to 5 clarity (scenes stage v2). Both good: the moment is usable in any direction; one much better: favour that direction; both bad: a negative score for b-roll (soft: a crowded start line may still matter for the story).
2. The quality grid from the proxy (`scripts/quality_spike.py`): exposure, flat share, detail, as guardrails and tie-breaks, never to rank (they punish open, beautiful landscapes).
3. People, identity and speakers (`people.json`, `identity.json`, `speakers.json`), the transcript spans and the alignment.
4. Motion: heading and gyro speed (blur).
5. The music: energy per bar sets shot length; beats place the cuts.

- **K1. Scenes stage v2 (S, then about 40 min of machine time for Legends).** The scenery-only graded prompt with `clarity` in `analysis/scenes_vlm.py` (version bump, old fields kept), run on every clip after the proxy batch. The prompt is the scenery-only one tried on 1 Oct (`scripts/vlm_exp/run_scenery.py`: people ignored). Use the score as bad / fine / good and as a direction where front and rear differ by 2 or more, not as a fine ranking. **Self-calibrating scale (built 1 Oct, `edit/quality_scale.py`, `tests/unit/test_quality_scale.py`):** shots are ranked on 0 to 10 fitted to this project's own range (10th to 95th percentile of all its scores, widened to at least 2 raw points so a uniformly grey race is not stretched into noise), because a winter ultra scores 5 and 6 nearly everywhere while a sunny race would reach 8 and 9; the raw score is kept for absolute judgements. Not yet called by anything; the fit is to be stored with the project (all clips together) when K1 runs. **Done when:** on the 33-moment test set the black frames score 1 or 2 and the foggy view scores below the clear one.
- **K2. Quality grid and `view_quality` (M).** A `quality` stage writing the 15 degree grid at 2 Hz (promoted from `scripts/quality_spike.py`), and `edit/view_quality.py`: score a view (yaw, pitch, fov, aspect) from the grid with the guardrails. **Done when:** unit tests on synthetic grids (a flat half-view is penalised, an open bright landscape is not; a black view scores near zero).
- **K3. Camera generator and the tracking engine (M to L).** The four trackings and free cameras, with the DP above. **Done when:** unit tests: the scenery camera never contains a person box; jump cuts stay within the budget; pans stay within the rate limit; it avoids a foggy direction when a clear one exists; the same seed gives the same cameras and another seed differs.
- **K4. Section chooser (M).** Replaces the `candidates`-based preferred content in V1 (`edit/blocks.py`): transcript spans first, else quality under the time budget.
- **K5. The multicam cutter (L)** is V5 using the camera list: cuts between cameras on the beat, shot length from the music's energy, runs from one clip with continuous source time (the sound never cut), see V5.

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
- **E4.** Raise `fail_under` as each milestone adds tests (target 50% after V and A). 1 Oct: 39 to 47 after A1 and V1 to V4 (measured 50%).

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
