# Generated music (plan item G): options and plan, 5 Oct 2026

Status (6 Oct): **G0, G1 and a Music studio screen are built; G2 to G5 are not.** Built: the precise beat tracker, key and bar similarity (`edit/music.py`), re-sequencing to any length (`edit/remix.py`), stems with Demucs, per-bar layer gains and vocal windows (`edit/stems.py`, `edit/layers.py`), the build (`edit/music_build.py`, `strata360 music-build`), the intensity curve from the footage signals (`edit/intensity.py`, `edit/intensity_signals.py`) and the screen (`web/src/components/MusicStudio.tsx`, `edit/music_studio.py`, endpoints under `/api/music/studio`). All tested on synthetic audio only: **nothing has been heard on a real track, and Demucs has not run** (needs the PC). What is left of G1: the `scenes` energy, the director's marked moments, the real voice-over timeline, the curve under the Overview waveform. The step list is in section 5; `docs/implementation-plan.md` (Milestone G) has the details of each piece and what is not yet done. Decided with the user on 5 Oct:
- the film is **personal**;
- everything is made **locally** (a few Gemini Pro calls, like the script writer's, are fine);
- **mostly instrumental**, so the film's own sound is never obscured;
- **no lyrics of our own**: the only singing is portions of the uploaded track's own vocals;
- the whole project, generation included, runs on the **Windows PC** (RTX 5070 Ti 16 GB, 64 GB RAM), like every other stage: no special handling for another machine.

The landscape in section 3 was researched on 5 Oct 2026. The field changes monthly (several of the models below shipped in September 2026), so re-check it before building G3 or G4.

## 1. The idea

Music made for the film instead of only fitting the film to a track:
- **Elements of both** the uploaded track (`music.json`) and the clips' own background sound (`audio_background.flac`, the speech-free TIGER-DnR effects track).
- **Any length**: the film's length, not the track's.
- **Mostly instrumental**, with **a few sung phrases from the uploaded track** placed in quiet moments, where there is no voice-over and no clip speech.
- **Intensity follows the action**: sparser on the long grind, fuller at the start, the finish, the crowds and the hard climbs.

## 2. What changes from today

Today the uploaded track is fixed. It sets the film's length (D7), `edit/music.py` finds its beats and energy for the planner, and `edit/lyrics.py` finds where it is sung so narration avoids it (V7). The new design changes three of those:

1. **The picture sets the music's length** (the old "Later" item: the reverse of V5). The voice-over-driven cut (V4) gives the length, and the music is built to it.
2. **The beat grid is the uploaded track's, planned before any audio is made.** The tempo, metre and key are the original's. They have to be, because its own vocal phrases and sections are reused. V5 snaps cuts to that grid, and the built track is checked against it afterwards (G5). There is no generate, cut, generate-again loop.
3. **Vocals are placed, not avoided.** The original's vocals are removed everywhere (its instrumental stem is used) except in a few chosen moments. In those, a sung phrase from the original plays at its own place in the bar. `lyrics.py` already finds the phrases and their times.

**The key design point:** the result is an ordinary music track plus a score sidecar. `music.json` records it (with `source: built` and the score key), so V5's beat snapping, the rough mix, the A3 ducking and the GUI's waveform work unchanged.

**A consequence:** G0, below, delivers most of the idea **with no generative model at all** (it is the top of the fidelity slider, 4.5): the original's instrumental stem re-sequenced to any length, layers following the intensity, and its vocals let through only in the chosen moments. Generation (G3) adds what re-sequencing cannot: new material in the original's style where the original has nothing at the needed intensity (a sparse night section, a long build to the finish), and smooth bridges between distant parts of the track.

## 3. The landscape (5 Oct 2026)

### Hosted services (for reference only: not planned, decision G-D2)

Ranks are from the Artificial Analysis vocal music arena (blind pairwise votes, Elo).

| Service | Elo | Notes |
|---|---|---|
| Suno v6 (9 Sep 2026) | 1142 (1st) | Best quality. No official API (a partner API was being "explored" in July). Screens uploaded audio for unauthorised use. |
| Mureka V9.5 (Aug 2026) | 1103 (3rd) | Reference tracks, melody IDs; REST via resellers. |
| Google Lyria 3.5 (Gemini API, 4 Sep 2026) | 1052 (5th) | Soft section timestamps in the prompt; **no audio input**; about $0.08 a song. |
| ElevenLabs Music v2.5 (11 Sep 2026) | 1012 (7th) | Hard per-section durations (composition plans), inpainting on uploaded audio, word timestamps. Will not release a track that references another artist's work. |
| MiniMax Music 2.6 / 3.0 (Aug 2026) | 987 to 1001 | Cover model takes reference audio. |
| Stable Audio 3 Large (May 2026) | instrumental | API only; the smaller sizes are open (below). |
| Udio | n/a | No API, downloads disabled since its UMG settlement. |

### Open weights (run locally)

| Model | Licence | Fits the 5070 Ti (16 GB)? | For us |
|---|---|---|---|
| **ACE-Step 1.5** (Jan 2026; **1.5 XL**, 4B, Apr 2026) | **MIT** | Base: yes, easily (under 6 GB without its planner LM, 12 GB with). XL: yes with offload (12 GB; 20 GB without), and the 64 GB of RAM takes the offload. (The base also runs on a Mac via MLX.) | **First choice.** BPM, key and time signature as inputs; 10 s to 10 min; **instrumental** generation; **reference audio** (the original's instrumental stem); **repaint** a time range; **Complete** and **Lego** (generate an accompaniment for, or add a layer to, existing audio); **Extract** (stems); extend. Its own audio analysis can describe the uploaded track (genre, instruments). REST server or Python API. |
| **Stable Audio 3 Medium** (1.4B; Small 459M) (May 2026) | Stability community licence (free for personal use) | yes | **Second choice, for the bake-off.** Instrumental only, which is now what we want, and trained on licensed data. Up to 6:20; **audio-to-audio** from the original; **inpainting** and **continuation**. Good for bridges, risers and extending a section. |
| MiniMax Music 3.0 (Aug 2026) | community licence | no: about 11B parameters in all | A songs-with-lyrics model, too large for 16 GB. Not needed now. |
| YuE2-3B (Sep 2026), HeartMuLa-oss-3B (Feb 2026), LeVo 2 | CC BY-NC / Apache-2.0 / unclear | YuE2 wants 24 GB; the others are borderline | Song-with-lyrics models. Not needed now that we write no lyrics. |

**Stem separation:** Demucs (`htdemucs_ft`, MIT; vocals, drums, bass, other; fast on CUDA) by default, with ACE-Step's Extract as an alternative to compare by ear.

**The Windows PC:** the 5070 Ti is a Blackwell card, so it needs a PyTorch build for CUDA 12.8 or later. `hw.gpu_device()` already returns `cuda` there. `requirements.txt` pins torch 2.9.1, which has CUDA 12.8 wheels. The music models live in their own environment, like `.venv-vision`, because ACE-Step pins its own dependencies.

## 4. Design

```
footage signals ──► intensity curve (G1) ──┐
voice-over timeline (V4) ──► quiet windows ┼──► score plan (G2) ──► build: original stems + generated sections (G0, G3, G4) ──► fit, check, repair (G5) ──► music track + score ──► V5 cuts, A3 mix
uploaded track ──► grid, key, stems, sung phrases (lyrics.py) ──┤
background sound ──► swells, footsteps ────┘
```

### 4.1 Intensity curve (`edit/intensity.py`, `intensity.json`)

A value from 0 to 1 per bar of film time, from signals we already have, each mapped through the plan into film time:
- `audio_events` energy categories (cheering, shouting, crowd, applause);
- motion and camera shake (`analysis/motion.py`);
- pace, slope and heart rate from the track (`overlay/series.py`);
- the `scenes` stage's `energy` (0 to 1) and `mood` every 5 s, where that stage has run (its Qwen runner is MLX, so on the PC it is present only for clips analysed on a Mac); the curve works without it;
- the technique energy of each window (overview 18);
- story weight: the start, the finish, and moments the director marks;
- the voice-over and dialogue: the music is sparser under speech anyway.

The curve is smoothed, quantised to bars, and given hysteresis so the level does not flicker. Changes land on phrase boundaries [4 bars].

### 4.2 Score plan (`edit/score.py`, `score.json`)

Pure Python, the heart of the feature, and unit-testable without audio.
- **Grid:** the uploaded track's tempo, metre and first downbeat (`music.json`), plus its key (a chroma estimate to add to `music.py`). Bars = the film's length over the bar length, rounded; the remainder goes to the ending's fade or a stretch of 3% at most.
- **Sections:** cut where the intensity level changes. Each section has its bars, its film times and a level. Its **source** is one of:
  - `original`: a stretch of the uploaded track, chosen by matching its own section energy to the level;
  - `generated`: new instrumental material in the original's style, key and tempo;
  - `bridge`: a few bars that join two sources.

  Each section also has its **layers**: which stems play and at what gain per bar.
- **Sung moments: chosen by the director (decided 5 Oct).** The director (V7, Gemini Pro, the call it already makes) lays out the film as a sequence of items and already decides where narration and clip speech go, so it also decides where the original's singing is heard, with a new item kind (4.2a). No new call is needed. The planner then builds the music around those moments: the phrase is fixed, and the music bends to it.
- **Without a director run** (a plan made by hand, or the planner alone): the rules pick the best-confidence phrases for the highest-intensity stretches with no narration or clip speech that are long enough, and report it when there are none.

### 4.2a The `sing` item in the director's draft

**What the director is given:** when the music is built (not fixed), the pack (`script_pack.music_facts`) lists the original's sung phrases as a **library**, not at fixed film times, because the built music can put a phrase anywhere. Each phrase has:
- an id (`P01`, ...);
- the words heard, flagged as rough (the recogniser mishears; your corrections in `lyrics_edits.json` apply);
- its length in seconds and in bars;
- a confidence, with doubtful and deleted phrases left out;
- whether its words repeat in the track (a repeated line is probably the hook).

**What it returns:** `{"type": "sing", "phrase": "P07", "clip": "0023", "why": "the hook as the runner crosses the line"}`. The `clip` is the picture under the singing, played like b-roll (a `gap` clip such as `G04` works too). There is no narration and no clip speech inside a `sing` item, so the item *is* the quiet window. Its length is the phrase's length rounded up to whole bars, plus [one bar] of lead-in and lead-out; the director does not set it. The usual optional `anchor` applies ("land this on the finish").

**The prompt:** mostly instrumental, so sung moments are rare and earned [at most 4 in a film; often none in the first third]; use them where the words or the energy fit what is on screen and nothing needs saying; never the same phrase twice unless it is the hook and the moments are far apart.

**`check` (`script_draft`)** rejects and returns for a retry: an unknown or doubtful phrase, more `sing` items than allowed, two sung moments closer than [30 s], and a `sing` item with no picture. `director_notes` advises: a phrase over a busy stretch of the intensity curve, and a hook used before the halfway point.

**What the planner does with it (G2):** it puts the phrase's first sung beat on the same beat of a bar as in the original, moving the item by at most half a bar and taking the difference from the neighbouring b-roll, as V5 does. It marks the bars around it as sung for the score, so the sources and form (4.3) for those bars follow from the fidelity setting (4.5). Everywhere else the original's vocals stay off.

**With the original track fixed (no built music, as today):** a phrase is heard only where the track sings it, so a `sing` item there means "keep narration and clip speech clear while the track sings P07", and it must be anchored at that phrase's film time. It is the same item with a stricter check, and it replaces today's advisory note about narration over singing.

### 4.3 How a sung moment sounds

Two ways, both to try by ear on Legends:
- **(a) The original's own bars** [default]: the full mix of the original around the phrase (its accompaniment and all), crossfaded on bar lines into what comes before and after. It sounds exactly like the record, but the intensity is whatever the original has there.
- **(b) The phrase's vocal stem over the film's own accompaniment**: either the original's instrumental stem from elsewhere, or a generated one (ACE-Step Complete: an accompaniment for a given vocal). This is more flexible, but separated vocals carry faint artefacts, so it needs a careful listen.

Everywhere else the original's **vocal stem is off**, and a G5 check makes sure no singing leaks through: separating vocals from a generated take catches a choir or hum the generator added.

### 4.4 Using both sources

1. **Re-sequencing the original** (G0, no generative model): bar-level jumps between self-similar bars (chroma and timbre per bar), so a section can be repeated, shortened or reordered without an audible join; the original's own ending kept as the film's ending.
2. **Stem layering** (G0): drums, bass and other faded in and out per bar to follow the intensity curve, the way adaptive game music works. This gives finer and more predictable control than any generator.
3. **Generated sections in the original's style** (G3): ACE-Step with the original's BPM, key and metre, the original's instrumental stem as reference audio, and a caption for the level. Or repaint and extend from a real stretch of the original, so the new bars grow out of it.
4. **The background sound as an instrument:** crowd swells timed to the start, finish and aid stations; found-sound intros and outros that blend into the music; the existing ambience swell when the music is quiet (overview 5c-3). Generators handle field recordings poorly, so these are mixed in on the beat, not generated from.

### 4.5 True to the track, or in its style: the fidelity setting

One setting, a slider in the Music panel from 0 to 1 [default 0.75], decides how much of what you hear is the uploaded track's own audio and how much is new material in its style. It is film-wide, and any section can be pinned either way ("keep the original here", "generate here"). The slider has five named stops; values between them interpolate.

| Fidelity | Name | What is built |
|---|---|---|
| **1.0** | **The record** | Only the original's audio: re-sequenced, layered, extended by repeating its own bars (G0). No generative model. Following the intensity is limited to what the original's own sections and stems can do. |
| **0.75** | **Extended** | Original sections wherever one matches the level; generated audio only for bridges and for levels the original never reaches (a sparse night, a long build). Generated bars grow out of the neighbouring original bars (repaint or continuation), with strong reference to the original. |
| **0.5** | **Remix** | About half the bars are original. Generated sections are free to follow the intensity, still with the original's stems as reference audio and its key and tempo. |
| **0.25** | **Inspired by** | Mostly generated, with the original's instrumental stem as reference audio at low strength. The original's own audio is heard only at sung moments, and at the start and end if pinned. |
| **0.0** | **In its style** | Everything generated from a description of the original (genre, instruments, tempo, key, metre) with no reference audio. Sung moments, if any, are the original's vocal stem over a generated accompaniment (4.3 form b). |

What the setting changes, so the planner can be tested without audio (`score.py`):
- **The share of original bars.** For each section the planner compares the best-matching original stretch (energy against the level, plus how well its bars join) with "generate". The tolerance for accepting an original stretch widens as fidelity rises, so the share of original bars never falls as the slider goes up. At 1.0, generation is not allowed (a level the original cannot reach is reported, and layering does what it can). At 0.0, original audio is not allowed outside the sung moments.
- **Reference strength** for generated sections: ACE-Step's reference-audio and cover strength, or Stable Audio 3's audio-to-audio strength. Strong near the top of the slider, weak near the bottom, and none at 0.0. The exact parameter names are to be confirmed against each model's API when G3 and G4 are built.
- **Where generated bars come from:** at 0.75 and above they are repainted or continued from the neighbouring original bars, so they start from the record's own sound. Below that they are generated fresh and joined on bar lines.
- **The sung moments:** at 0.5 and above, form a (the original's own bars); below 0.5, form b (its vocal stem over the film's accompaniment). Each moment can be overridden.
- **Layering:** at high fidelity the original's arrangement is mostly kept, and the curve only mutes or lifts whole stems at phrase boundaries. At low fidelity the generated material is already written to the level, and layering only trims it.

The fidelity value is part of each section's key, so moving the slider rebuilds only the sections whose source or reference strength changed, and takes made at an earlier setting stay cached for comparison. The rough mix (V6) previews any setting within a minute when the takes exist.

### 4.6 Building the take (`audio/music_gen/`)

One interface: `render(section, backend, seed) -> audio`. Each take is stored under `<race dir>/music_gen/<key>/`, where the key covers the section's spec, the backend, the model version, the seed and the settings, so nothing is computed twice. A section that changes is the only one built again. Several takes per generated section [3]; the user picks one in the Music panel.
- **Stems** (G0): Demucs on the uploaded track, once, kept next to `music.json`.
- **ACE-Step** (G3): generated sections and bridges; repaint for repairs.
- **Stable Audio 3 Medium** (G4): the same section specs, for the bake-off; continuation and inpainting for bridges.
- **Captions:** a template from the level and the original's description (from ACE-Step's analysis or written once by hand) ["sparse", "steady", "driving", "full"]. The project's Qwen3.5-9B could write richer ones from the scene labels, but its runner is MLX (Apple only), so on the PC it would need a CUDA runner first. The template is the default; Qwen is a later option.

### 4.7 Fit, check and repair (`edit/music_fit.py`)

- **Grid:** `music.analyse` on each generated section. A uniform tempo error of up to 3% is fixed with a time-stretch (rubberband). Drift, or a downbeat out by more than [40 ms], means the section is repainted or regenerated.
- **Joins:** every join between sources is on a downbeat, with an equal-power crossfade [one beat].
- **No stray singing:** the vocal stem of the whole built track is near silent outside the chosen moments.
- **Length:** equals the film to within one frame; the ending lands on the last bar or the planned fade.
- When the cut changes later, only the sections whose bars changed are stale.

### 4.8 Mix

A3, with the built track as "the music", plus the per-bar stem gains and the background-sound layers on the beat. Because the music is mostly instrumental and sparse under speech, the ducking can be gentler than with a sung track.

## 5. Steps

| Step | What | Size |
|---|---|---|
| **G0** | **(built 5 Oct, untried on real audio)** **Stems, re-sequencing and layering, no generative model.** Demucs stems of the uploaded track; bar-level re-sequencing to any length ending on its own ending; per-bar layer gains from a given curve; vocals only in given windows. | M |
| **G1** | **(built 6 Oct apart from the items listed in the status)** **Intensity curve** from the signals in 4.1; drawn under the music waveform. | S to M |
| **G2** | **Score plan**: `score.py`, key estimation in `music.py`, quiet windows, the director's `sing` items (4.2a: the phrase library in the pack, the item in the prompt, `check` and `director_notes`, a prompt version bump) and the rules for a plan with no director run, sources and layers per section, and the **fidelity setting** (4.5) with per-section pins. | M |
| **G3** | **ACE-Step**: the backend interface, generated and bridge sections in the original's style, repaint for repairs. | M |
| **G4** | **Stable Audio 3 Medium** as the second backend; a **bake-off on Legends** (the same score, both backends, plus G0 alone, judged by ear, like `docs/bakeoff`). | S to M |
| **G5** | **Fit, check, repair**, and the Music panel: the **fidelity slider** with its five stops, takes, the score's sections (original or generated) and sung moments drawn on the waveform, pin or rebuild a section. | M to L |

Dependencies: G1 and G2 need V4 (the voice-over timeline) and the plan. V5 cuts on the original's grid, so it does not wait for any of this. **G0 can start now**, and G0 with G1 and G2 is already a usable result.

**Done when:**
- **G0:** the Legends track built to 60, 247 and 400 s, each ending on its own ending, with no audible jump (by ear) and every bar boundary within 10 ms of the grid; layer gains follow a given curve per bar; no singing outside the given windows (vocal stem check).
- **G1:** unit tests on synthetic signals: the level changes only on phrase boundaries, a single loud window does not change it, and the start and finish get the top level when marked.
- **G2:** unit tests: a draft's `sing` item becomes a stretch with no narration or clip speech, as long as its phrase rounded up to bars plus the lead-in and lead-out; the phrase starts on its original beat in the bar; a doubtful phrase, too many `sing` items, or two too close are sent back; with the track fixed, an unanchored `sing` item is sent back; bars times bar length equals the film's length within one frame; at fidelity 1.0 no bar is generated, and at 0.0 no original audio plays outside the sung moments; the share of original bars never falls as fidelity rises; a pinned section ignores the slider; moving the slider changes the keys of only the sections whose source or strength changed; no sung phrase overlaps a voice-over line or clip speech; a phrase starts on its original beat in the bar; a phrase with no window that fits is reported, not squeezed in.
- **G3 and G4:** backends behind fakes in the unit suite (`tests/utils` fakes); one real build per backend run by hand on the PC's GPU (like the other model-dependent checks, overview section 0) and logged in `progress.md` with its time and peak GPU memory.
- **G5:** on Legends, a built track whose downbeats are all within 40 ms of the grid after fitting, with no singing outside the chosen moments, and a film of the right length that plays through the rough mix.

## 5a. Ready to start (5 Oct; G0a, G0b and G1 since built, see the status above)

Every decision is taken except the fidelity default, and 0.75 is enough to start. What G needs from the rest of the plan is built: the music record and analysis (`music.py`), the lyrics and their phrases (`lyrics.py`), the voice-over fit (V4, `vo_fit.py`), the director with items and anchors (V7, L1 to L4), and the background track and sound events.

**Four things to settle inside the work, not before it:**
1. **Precise beats.** `music.py` assumes a constant tempo. Re-sequencing bars (G0) needs every beat and downbeat to within a few milliseconds, allowing drift. That beat tracker is already planned for V5 ("Beat times, precisely"). Build it once, as G0's first step, and V5 reuses it.
2. **Demucs with torchaudio 2.9.** Recent torchaudio removed the audio file loading Demucs relies on (the project already patches DeepFilterNet for the same thing). Call Demucs's model API on samples decoded by ffmpeg, as `music.decode` does, and write the stems with ffmpeg. Pin the version.
3. **Film length with built music (V4).** V4 fits the voice-over against a fixed music length M. With built music, M follows the film: V4 runs as "no music" for the length (L = V plus lead-in and lead-out, or the target length), and the score is built to L. That is a small mode switch in `vo_fit`, done in G2.
4. **ACE-Step on Windows with the 5070 Ti** (G3 step 0): install it in its own environment, generate one 30 s instrumental at a given BPM and key, repaint 8 s of it, and note the actual parameter names (reference strength, cover strength) and the time and peak GPU memory, in `progress.md`. Do the same for Stable Audio 3 Medium before G4.

**First piece of work (G0a), all unit-testable with synthetic audio** (`tests/unit`: clicks at a known tempo, a drifting tempo, a tone sequence with known self-similar bars):
- the precise beat and downbeat tracker in `music.py` (V5's, shared);
- a key estimate in `music.py` (chroma against key profiles);
- bar features (chroma and timbre per bar) and the bar-to-bar similarity used for jump points;
- `edit/remix.py`: a re-sequencing to a target number of bars that ends on the track's own ending, with every join on a downbeat between similar bars; output as a bar list (pure), then rendered with ffmpeg and short crossfades.

Then **G0b**: Demucs stems (stored next to `music.json`, keyed by the file's signature), per-bar layer gains, and vocals only inside given windows. After G0b, a built track can already be heard in the rough mix. G1 (the intensity curve) can run alongside.

## 6. Decisions

| | Question | Answer or [default] |
|---|---|---|
| G-D1 | Personal or commercial? | **Decided 5 Oct: personal.** The uploaded track's audio is reused locally. |
| G-D2 | Hosted generation or local? | **Decided 5 Oct: local only**; a few Gemini Pro calls are fine. |
| G-D3 | Lyrics? | **Decided 5 Oct: none of our own.** Mostly instrumental; the only singing is portions of the uploaded track's vocals. |
| G-D4 | Tempo and key? | **Follows from G-D3: the original's.** |
| G-D5 | Where does generation run? | **Decided 5 Oct: the Windows PC** (RTX 5070 Ti 16 GB, 64 GB RAM), where the whole project runs. |
| G-D6 | How many sung moments, and which form (4.3 a or b)? | **Decided 5 Oct: the director chooses the moments** (4.2a), within a limit [at most 4, 30 s apart]; the form follows the fidelity setting (4.5) and can be overridden per moment. |
| G-D7 | How does the project reach the generator? | **Decided 5 Oct: no question.** The whole project runs on the PC, like every other stage. |
| G-D8 | The fidelity default (4.5). | [0.75, "extended"]: enough to start; to be tuned by ear in G4's bake-off. |

## 7. Risks

- **Licensing:** settled for now by G-D1 (personal, local). If the film is ever published, a remix or extension of the uploaded track is a derivative work.
- **Quality cannot be unit-tested.** The plan, the grid, the fit and the checks can; how it sounds needs the user's ears on each new backend or model.
- **Separated vocals** (form b) can sound thin or carry the drums' ghost; form a avoids that.
- **Generated material against the original:** new sections may not sound like the same band. The reference audio, the original's key and tempo, and joins on bar lines are the defences; the bake-off with G0 alone shows whether generation earns its place.
- **The Blackwell GPU and Windows:** ACE-Step and Stable Audio 3 are developed mostly on Linux and Apple. A first-hour check on the PC (G3 step 0) confirms they install and run before anything is built on them.
- **Churn:** the backend interface keeps any one model replaceable; re-check section 3 before G3 and G4.

## Sources (5 Oct 2026)

- Artificial Analysis vocal music leaderboard: https://artificialanalysis.ai/music/leaderboard/vocals
- ACE-Step 1.5: https://github.com/ace-step/ACE-Step-1.5 ; paper: https://arxiv.org/abs/2602.00744 ; 1.5 XL: https://gigazine.net/gsc_news/en/20260409-ace-step-1-5-xl/
- Stable Audio 3: https://the-decoder.com/stability-ai-launches-stable-audio-3-0-with-up-to-six-minute-tracks-and-open-weights/
- MiniMax Music 3: https://kie.ai/blog/minimax-music-3-release
- YuE2: https://mer.vin/news/yue2-3b-claims-it-beats-suno-v6-on-open-music-generation/ ; HeartMuLa: https://github.com/HeartMuLa/heartlib ; LeVo 2: https://huggingface.co/tencent/SongGeneration
- Suno v6: https://datanorth.ai/news/suno-launches-v6-v6-wild-and-v6-mini ; Lyria 3.5: https://ai.google.dev/gemini-api/docs/interactions/music-generation ; ElevenLabs composition plans: https://elevenlabs.io/docs/eleven-api/guides/how-to/music/composition-plans ; Udio: https://undetectr.com/blog/udio-download
