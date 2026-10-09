## 17. The voice-over-driven workflow

An alternative to fitting shots to music alone: **the narration decides the timing**. The system drafts a script from the transcripts of all the footage, the user records it, and the picture is then fitted exactly to what was recorded, so there is always footage on screen and clips with dialogue play in deliberate pauses.

### 17.1 Flow
1. **Analyse everything** (section 15): transcripts with translation and accurate word times, speakers, scenes, quality.
2. **Story pass.** Choose the narrative beats and, for each, the shots and any dialogue clip that carries it; draft the script (an LLM draft from the transcripts, reviewed and edited by the user).
3. **Script output** for the user to read: numbered lines, each with an estimated duration, and the gaps marked, for example `[DIALOGUE: clip 0023, 12:31-12:38, "and then we lost the trail" (translated from French) - leave 6.4 s]`, `[MUSIC ONLY 3 s]`. Formats: Markdown and a printable or teleprompter HTML page, plus `script.json`. Timing estimates come from words per second plus pause allowances (comma 0.25 s, sentence 0.5 s, paragraph 0.9 s) using **the user's own reading rate**, measured from a short calibration reading. For reference, the spontaneous on-the-trail speech in the Belgian library measures 3.55 words/s (213 wpm; 3.9 words/s with pauses removed), median phrase 3.3 s, median pause between phrases 1.3 s, 0.9% fillers; deliberate narration is normally slower (about 2.5 words/s), so the calibration matters and the plan tolerates plus or minus 15%.
4. **Record** the voice-over (the user follows the script, leaving the marked pauses).
5. **Fit pass.** Transcribe the recording and force-align it **to the script text** (the text is known, so the alignment is much more accurate than from recognition alone; same tools as section 5.11) to get every line's start and end, the pauses between them and word times. Multiple takes: the best per line by alignment score or the user's pick. Result `vo.json`.
6. **Re-plan with the recording as fixed anchors** (the joint optimisation of section 16 with extra hard constraints): every line's recorded interval is fixed on the timeline; the picture is never empty; each narration line gets the shots assigned to it, with durations flexing to fit the line; a dialogue clip is scheduled in its pause, trimmed at safe cut points to the pause length (or, if the recorded pause is longer, extended with ambience and a steady hold); shot boundaries prefer line boundaries and pauses inside lines; techniques still obey section 16 (a hero technique on a long line, dialogue holds in pauses). Where a recorded pause is too short for its dialogue clip even after trimming, the tool reports the shortfall by name and offers to re-record only that pause.
7. **Mix.** Music ducks under the voice-over using the exact line times; dialogue clips play at their own level in their pauses; ambience swells in the gaps (section 5c-3).
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
