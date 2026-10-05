# Generated music (plan item G): options and plan, 5 Oct 2026

Status: **design, nothing built.** The landscape below was researched on 5 Oct 2026. This field changes monthly (three of the models below shipped in September 2026), so re-check section 3 before building G3 or G4.

## 1. The idea (from the user, 5 Oct)

Make the film's music instead of only fitting the film to a track:
- **Elements of both** the uploaded track (`music.json`) and the clips' own background sound (`audio_background.flac`, the speech-free TIGER-DnR effects track).
- **Any length**: the film's length, not the track's.
- **Lyrics in the quiet moments**: sung lines where there is no voice-over and no clip speech.
- **Intensity follows the action**: quieter and sparser on the long grind, fuller at the start, the finish, the crowds and the hard climbs.

## 2. What changes from today

Today the uploaded track is fixed: it sets the film's length (D7), `edit/music.py` finds its beats and energy for the planner, and `edit/lyrics.py` finds where it is sung so narration avoids it (V7). Generating the music turns three of those round:

1. **The picture sets the music's length** (the old "Later" item: the reverse of V5). The voice-over-driven cut (V4) gives the length; the music is written to it.
2. **We choose the tempo and the bar count**, so the beat grid exists *before* the audio does. V5 snaps cuts to the planned grid; the generated audio is then checked against it (G5). This removes the ordering problem: we do not have to generate, cut, and then generate again.
3. **Vocals are something we place, not avoid.** The score puts sung lines into the gaps between narration and dialogue; the same `vocal_spans` check then confirms they landed there.

**The key design point:** the result is an ordinary music track plus a score sidecar. `music.json` records it (with `source: generated` and the score key), so V5's beat snapping, the rough mix, the A3 ducking and the GUI's waveform work unchanged.

## 3. The landscape (5 Oct 2026)

Quality ranks are from the Artificial Analysis vocal music arena (blind pairwise votes; Elo). No open-weight model is on that leaderboard, so open models' quality claims are their authors' own.

### Hosted services

| Service | Vocal arena Elo | Lyrics | Section timing | Audio in | API | Notes |
|---|---|---|---|---|---|---|
| **Suno v6** (9 Sep 2026; v6, v6-wild, v6-mini) | **1142 (1st)** | yes | soft (structure tags) | yes: covers, mashups, sampling, plain-language edits of a section | **no official API**; a partner API was being "explored" (July 2026). Resellers drive users' accounts, against the terms | Best quality. Trained partly on licensed catalogues (Warner, BMG, Believe); uploaded audio is screened for unauthorised use. Usable only by hand: export and drop in (G5 "bring your own take"). |
| **Mureka V9.5** (Aug 2026) | 1103 (3rd) | yes | soft | reference tracks, melody IDs, cloned vocals | REST through resellers; check for an official one before building | Strong vocals; least known to us. |
| **Google Lyria 3.5** (Gemini API since 4 Sep 2026) | 1052 (5th) | yes, with section tags | **timestamps in the prompt** (`[0:00 - 0:10] Intro: ...`), soft | **none** (text or image only) | **official**, the Gemini API we already use for the script writer; about $0.08 a song | Multi-minute songs, 44.1 kHz WAV, SynthID watermark, artist imitation and copyrighted lyrics blocked. Returns lyrics and structure, no word timings. |
| **ElevenLabs Music v2.5** (11 Sep 2026) | 1012 (7th) | yes, per section | **hard: a composition plan of up to 30 sections, each 3 to 120 s in ms, 3 s to 10 min in total** | **inpainting on uploaded audio** by song ID and ms ranges (remix, extend, stitch) | **official** | Commercial use on every plan; optional **word-level timestamps**; stem separation; video-to-music in their Studio. A track that references another artist's work cannot be downloaded. |
| MiniMax Music 2.6 and 3.0 (Aug 2026) | 987 to 1001 | yes, section tags | caption with BPM and key; length 10 to 300 s | cover model (6 s to 6 min reference) | official; $0.15 a song | 3.0 also has open weights (below). |
| Stable Audio 3 Large (May 2026) | not ranked (instrumental) | **no vocals** | length; inpainting ranges | audio-to-audio, inpainting, continuation | official (and fal) | Instrumental beds and transitions only. |
| Udio | n/a | | | | **no API; downloads disabled** since the UMG settlement (licensed walled garden) | **Not usable.** |

### Open weights (run locally)

| Model | Licence | Runs on | What matters for us |
|---|---|---|---|
| **ACE-Step 1.5** (Jan 2026; **1.5 XL**, 4B, Apr 2026) | **MIT** | **Mac (MLX)**, CUDA, ROCm, Intel, CPU. Under 6 GB in DiT-only mode, 12 GB+ with the planner LM, XL 20 GB+ (12 GB with offload) | **BPM, key and time signature as inputs**, length 10 s to 10 min, lyrics with structure tags, **repaint a time range** (new lyrics or style for that range only), cover and reference-audio guidance, **Lego** (add a track to existing audio), Extract and Complete, vocal-to-backing-track, **LRC lyric timestamps** out, LoRA training, REST server (`acestep-api`). Seconds per song on a good GPU. |
| MiniMax Music 3.0 (13 Aug 2026) | MiniMax-Music3 **Community Licence** (read the terms before any commercial use) | heavy: 8B + 0.6B LLMs, 2.4B flow model; no official VRAM figure, reported running on Apple Metal | Lyrics with section tags plus a structured caption (genre, BPM, key, emotional progression, arrangement); up to 5 min; 32 kHz. No reference audio or editing. |
| YuE2-3B (Sep 2026) | **CC BY-NC 4.0** (non-commercial output) | Linux, 24 GB NVIDIA | Claims to beat Suno v6 in a single generation (its own benchmark); zero-shot covers; outputs an editable ABC score as well as audio. Out unless the film is non-commercial and a CUDA machine is at hand. |
| HeartMuLa-oss-3B (Feb 2026) | Apache-2.0 | CUDA; no stated Mac support | Lyrics and tags, up to about 4 min; reference-audio conditioning not released yet. Ships a lyrics transcriber (HeartTranscriptor) worth trying in place of faster-whisper in `lyrics.py`. |
| LeVo 2 / SongGeneration 2 (Tencent) | unclear (Hugging Face card says Apache-2.0, repository terms are custom) | CUDA | Strong reported quality; licence to settle before use. |
| Stable Audio 3 Small and Medium (May 2026) | free below $1M annual revenue | small (459M, 1.4B) | Instrumental only; up to 6:20; inpainting and continuation. A candidate for transitions and "bridge" bars between sections. |

### What this means for us

1. **The uploaded track's audio cannot go to the hosted services freely.** Suno screens uploads, ElevenLabs will not release a track that references other artists' work, and Lyria takes no audio at all. So "elements of the uploaded track" splits in two:
   - **its features as text**: tempo, key, time signature, instrumentation, the energy shape, the sections. These work with any backend, and they are what keeps the generated music "in the family" of the original;
   - **its actual audio**: stems, sections, motifs. That needs either a local model (ACE-Step: reference audio, cover, repaint, Lego) or a track the user owns the rights to (then ElevenLabs inpainting is the hosted route).
2. **Exact timing.** Only ElevenLabs takes hard per-section durations. ACE-Step takes BPM and total length, and its repaint works on time ranges, so we can enforce sections by repainting. Lyria's timestamps are hints. Whatever the backend, G5 measures the result and repairs it.
3. **Quality against control.** The best-sounding services (Suno, Mureka) are the hardest to automate. The plan below automates the controllable ones, keeps a "bring your own take" path for the best ones, and compares takes by ear.

## 4. Design

```
footage signals ─► intensity curve (G1) ─┐
voice-over timeline (V4) ─► vocal windows ┼─► score plan (G2) ─► backend (G3/G4) ─► fit, check, repair (G5) ─► music track + score ─► V5 cuts, A3 mix
uploaded track ─► tempo, key, sections ───┤        ▲ lyrics (director, V7)
background sound ─► cadence, swells ──────┘
```

### 4.1 Intensity curve (`edit/intensity.py`, `intensity.json`)

A value from 0 to 1 per bar of film time, from signals we already have, each mapped through the plan (EDL) into film time:
- `audio_events` energy categories (cheering, shouting, crowd, applause);
- motion and camera shake (`analysis/motion.py`);
- pace, slope and **heart rate** from the track (`overlay/series.py`);
- the technique energy of each window (overview 18, `energy`);
- story weight: the start, the finish, and moments the director marks;
- the voice-over and dialogue as *negative space*: the music thins under speech anyway.

The curve is smoothed, quantised to bars, and given hysteresis so the level does not flicker. Changes land on phrase boundaries (4 or 8 bars [default 4]).

### 4.2 Score plan (`edit/score.py`, `score.json`)

Pure Python, the heart of the feature, and fully unit-testable without audio.
- **Grid:** tempo [default: the uploaded track's BPM; option: from the runner's cadence, often 160 to 180 steps a minute, or half of it], time signature and key from the uploaded track (key needs a chroma-based estimate added to `music.py`). Bars = the film length (V4) over the bar length, rounded; the remainder goes to a tail or a 1 to 3% stretch.
- **Sections:** cut where the intensity level changes; each has bars, start and end in film time, an energy level, style and instrumentation tags (from the uploaded track's description plus the level), and its **sources** (generated, a stretch of the original track, or a background sound layer).
- **Vocal windows:** stretches of at least N bars [default 4] with no voice-over line and no clip speech (V4's timeline). Each gets a syllable budget from its bar count and the tempo.
- **Lyrics:** written by the director (V7) in the same call as the script: it gets the vocal windows with their bar counts and budgets and what happens on screen there, and returns lyrics per window [default: English, first person, about the race]. Checks: syllables within budget, no artist names and no existing lyrics (Lyria refuses them; they would also be a licence problem).

### 4.3 Using both sources

From least to most dependent on the original audio:
1. **Style transfer by description** (any backend): the uploaded track's tempo, key, metre, instrumentation and energy shape written into the style tags.
2. **Stem layering** (no generative model): separate stems (Demucs, or ACE-Step Extract) and fade layers in and out per bar to follow the intensity curve, the way adaptive game music does. This gives finer control than any generator, and works on the original track as well as on a generated one.
3. **Background sound as an instrument**: footsteps set or confirm the tempo; crowd swells timed to the start, finish and aid stations; found-sound intros and outros that blend into the music; the existing ambience swell in quiet music (overview 5c-3). Generators handle field recordings poorly, so these are mixed in on the beat, not generated from.
4. **Real sections of the original**: its intro, its hook or its ending kept, with generated sections bridging and extending (ACE-Step repaint or cover locally; ElevenLabs inpainting if we own the rights).

### 4.4 Rendering backends (`audio/music_gen/`)

One interface: `render(score, backend, seed) -> audio + what it reports` (lyric timestamps when it has them). Each take is stored under `<race dir>/music_gen/<key>/`, where the key covers the score, the backend, the model version, the seed and the settings, so nothing is paid for or computed twice. Several takes per score [default 3]; the user picks one in the Music panel.
- **ACE-Step** (local, first): BPM, key and length from the grid; lyrics with structure tags; the uploaded track as reference; then repaint per section where G5 finds a section off.
- **ElevenLabs** (hosted): the score maps almost one to one onto a composition plan (section text with lyrics, `duration_ms`, positive and negative styles); word timestamps on.
- **Lyria 3.5** (hosted, cheap, same Gemini key): the score as a timestamped prompt; instrumental beds, or songs where soft timing is acceptable.
- **Bring your own take**: a file made anywhere (Suno v6, Mureka) plus the score it was made from (we print the score as a prompt to paste). G5 fits and checks it like any other take.

Over 10 minutes (every backend's limit, about 5 for some): split into movements at low-intensity bars and join on a downbeat, or extend with continuation, repaint or inpainting.

### 4.5 Fit, check and repair (`edit/music_fit.py`)

- `music.analyse` on the take: the tempo and every downbeat against the planned grid. A uniform error of up to 3% is fixed with a time-stretch (rubberband); drift or a bar out by more than [40 ms] means repairing that section (repaint or inpaint) or regenerating it.
- **Vocals:** the provider's word timestamps or ACE-Step's LRC, else `lyrics.py` on the take. Singing outside its window is repaired the same way; a window left empty is reported.
- **Length:** equals the film to within one frame; the ending lands on the last bar or the planned fade.
- When the cut changes later, only the sections whose bars changed are stale and are repainted, not the whole song.

### 4.6 Mix

A3 unchanged: the generated track is "the music". Two additions: the stem layers' per-bar gains (4.3, point 2) and the background-sound layers on the beat.

## 5. Recommendation and steps

**Local first with ACE-Step 1.5**: MIT licence, runs on the Mac, takes BPM and key directly, can repaint by time range, and is the only route that can use the uploaded track's audio without uploading it. **ElevenLabs** is the hosted backend, because its composition plan is our score. **Lyria 3.5** is a cheap second hosted option, and **Suno v6** is a manual path until it has an API. Before G3, a **G0** that needs no generative model, so "any length" and "follows the action" work early and stay as the fallback.

| Step | What | Size |
|---|---|---|
| **G0** | **Remix to length and stem layering, no generative model.** Bar-level re-sequencing of the uploaded track using self-similar jump points (chroma and timbre per bar), ending on its real ending; stems with per-bar gains from a hand-drawn or flat intensity curve. | M |
| **G1** | **Intensity curve** from the signals in 4.1, through the EDL into film time; drawn under the music waveform. | S to M |
| **G2** | **Score plan, vocal windows and lyrics**: `score.py`, key estimation in `music.py`, the director's lyrics (V7 prompt and checks). | M |
| **G3** | **Backend interface and ACE-Step** (local server, takes stored by key). | M |
| **G4** | **ElevenLabs and Lyria backends**; "bring your own take" import. | S to M |
| **G5** | **Fit, check, repair**; Music panel: takes, score lanes on the waveform, regenerate a section; a bake-off on Legends (same score, every backend, judged by ear, like `docs/bakeoff`). | M to L |

Dependencies: G1 and G2 need V4 (the voice-over timeline) and the plan. V5 cuts on the score's planned grid, so it does not wait for G3. G0, G1 and G2 can start now.

**Done when:**
- **G0:** a remix of the Legends track to 60, 247 and 400 s, each ending on the track's own ending, has no audible jump (checked by ear), and every bar boundary is within 10 ms of the grid; the layer gains follow a given curve per bar.
- **G1:** unit tests on synthetic signals: the level changes only on phrase boundaries, a single loud window does not change it, the start and finish get the highest level when marked.
- **G2:** unit tests: bars times bar length equals the film length within one frame; no vocal window overlaps a voice-over line or clip speech; lyrics over budget or naming an artist fail the check.
- **G3 and G4:** backends behind fakes in the unit suite (`tests/utils` HTTP and subprocess fakes); one real take per backend run by hand and logged in `progress.md`.
- **G5:** on Legends, a take whose downbeats are all within 40 ms of the grid after fitting, with no sung word outside a vocal window (or reported), and a film of the right length that plays through the rough mix.

## 6. Decisions (defaults in brackets await confirmation)

| | Question | Default |
|---|---|---|
| G-D1 | Is the film personal and non-commercial, or might it be published commercially? This decides whether the uploaded track's audio may be reused (4.3 point 4) and whether YuE2 or MiniMax 3's licences are acceptable. | [personal, non-commercial; still keep the uploaded track's audio local] |
| G-D2 | Spend on hosted generation, or local only? | [local first (ACE-Step); hosted for comparison, with a cost shown before each run, as for the 3D flyover] |
| G-D3 | How recognisable should the original be: real sections kept, or only "in its style"? | [in its style, plus its stems in G0] |
| G-D4 | Lyrics: whose voice, what language, about what? May sung lines ever go over clip dialogue? | [English, first person, about the race; never over dialogue or the voice-over] |
| G-D5 | Tempo from the uploaded track or from the runner's cadence? | [the uploaded track] |

## 7. Risks

- **Licensing** of the uploaded track (G-D1). A cover or a stitched remix is a derivative work whatever the tool; running it locally avoids an upload, not that question.
- **Quality cannot be unit-tested.** The plan, the grid, the fit and the checks can; how it sounds needs the user's ears on each new backend or model.
- **Vocal timing** is the least reliable part of every generator. G5's repair loop is what makes "lyrics in the quiet moments" dependable, so it is not optional.
- **Churn:** the backend interface keeps any one model replaceable; re-check this landscape before G3 and G4.

## Sources (5 Oct 2026)

- Artificial Analysis vocal music leaderboard: https://artificialanalysis.ai/music/leaderboard/vocals
- ElevenLabs composition plans: https://elevenlabs.io/docs/eleven-api/guides/how-to/music/composition-plans ; inpainting: https://elevenlabs.io/docs/eleven-api/guides/how-to/music/inpainting ; Music v2.5: https://elevenlabs.io/blog/music-v2-5-model
- Lyria 3.5 in the Gemini API: https://ai.google.dev/gemini-api/docs/interactions/music-generation
- Suno v6: https://datanorth.ai/news/suno-launches-v6-v6-wild-and-v6-mini ; API status: https://www.musicbusinessworldwide.com/suno-explores-developer-api-seeking-apps-that-unlock-experiences-generative-music-makes-possible-for-the-first-time/
- Mureka V9.5: https://useapi.net/docs/api-mureka-v1
- MiniMax Music 3: https://kie.ai/blog/minimax-music-3-release
- Udio: https://undetectr.com/blog/udio-download
- ACE-Step 1.5: https://github.com/ace-step/ACE-Step-1.5 ; paper: https://arxiv.org/abs/2602.00744
- YuE2: https://mer.vin/news/yue2-3b-claims-it-beats-suno-v6-on-open-music-generation/
- HeartMuLa: https://github.com/HeartMuLa/heartlib
- LeVo 2: https://huggingface.co/tencent/SongGeneration
- Stable Audio 3: https://the-decoder.com/stability-ai-launches-stable-audio-3-0-with-up-to-six-minute-tracks-and-open-weights/
