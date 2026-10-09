## 15. Analysis data: what we collect so edit points and framing can be decided later

Principle: **collect broadly and richly now, decide late.** Every decision the editor and the framing solver will make needs some measurement of the footage; each measurement is a per-clip JSON artefact written by a cached pipeline stage (section 0), so a later change of taste, target length or music never means re-analysing the video. Status as of 2026-09-30.

### 15.1 What each decision needs

| Decision | Data needed | Status | Artefact / stage |
|---|---|---|---|
| **What is in the clip, and when** (UTC, duration, dropped frames, colour mode) | Clip facts and the definitive start time | Done (clock offset **unverified** for Belgium) | `clip.json` (`ingest`) |
| **Where on the course** (coverage, ordering, map handoff) | The camera clock checked against the GPX, then time to distance and position | **Missing** (needs the GPX and a check of the clock offset) | `course.json` (future stage `course`) |
| **Where is the speech, and where can we cut it** | Transcript, language, translation, accurate word times, safe cut points | Done (English alignment only) | `transcript.json`, `alignment.json` (`transcribe`, `align`) |
| **Who is speaking** (the wearer or someone else) | Voice embeddings and clusters, wearer voice profile, mouth-motion linking to faces | **Missing** | `speakers.json` (future stage `speakers`) |
| **Sound design** (ambience, crowd, levels, clipping) | Loudness, clipping, wind/speech/crowd/ambience labels | Done (heuristic labels) | `audio.json` (`audio`) |
| **Exposure and look consistency** | Brightness statistics, camera exposure metadata | Done | `exposure.json` (`exposure`) |
| **Camera state and shake** (held on the stick, hand-held, put down; how steady; impacts; turning) | Attitude and angular speed summaries from the telemetry; heading; tilt; stationary segments | **Missing (cheap, no downloads)** | `motion.json` (future stage `motion`) |
| **Where things are on the sphere over time** (people, faces, signs, scenery) | The upright analysis proxy video, person detection and tracking, target tracks with yaw, pitch and size | **Missing** | `proxy.mp4` (`proxy`, built but not run), `targets.json` |
| **Which one is me** (the protagonist) | Face detection and recognition, the "which one is me?" selection saved as a profile, appearance and bib cues | **Missing** (needs face models; design in section 7, item 6a) | `identity` profile, `targets.json` |
| **What is happening** (aid station, view, finish, group, crowd) | Captions and tags from a vision model on labelled views of the sphere | **Missing** (needs a choice of vision model, local or API) | `scenes.json` |
| **What to avoid** (thumb over a lens, wet lens, blur, glare, the stick, the seam) | Obstruction and quality flags over time | **Missing** (the stick polygon exists; dynamic obstruction does not) | `quality.json` |
| **How interesting is each moment** | Combination of the above (speech, energy, people, scene, novelty) | **Missing** (after the inputs exist) | `interest.json` (Phase 3) |
| **Candidate ranges and framing options** | Proposals with handles and cut points; attention map with look options | **Missing** (Phases 3 and 4) | `proposals.json`, `attention.json` |
| **What the user tends to choose** (taste) | The two flat exports from 15 March, if they are finished films: which moments the user kept | **Unexplored** (needs the user to confirm what they are) | `taste.json` |
| **Music alignment** | Beat and section analysis of the chosen track | Waiting for a track | `music.json` |

### 15.2 Recommended order (each step unblocks the next)
1. **Verify the camera clock against the GPX** (needs the GPX and one known point, such as the race start or a recognisable place) and add the `course` stage. Without this, ordering, coverage and the map overlay rest on an unverified hour. Cheap.
2. **`motion` stage from the telemetry** (no downloads): shake level, angular speed, tilt, heading, holding style, stationary and moving segments, impacts and cadence. It feeds candidate scoring, stabilisation choice and "wearer talking to camera" hints.
3. **Run the `proxy` stage over the whole library** (about 1 hour of compute and about 10 GB for these 16.8 minutes at the default 3840x1920, 12.5 fps, 80 Mbit/s; settings are provisional until the detector benchmark, section 14.5). Everything visual below needs it.
4. **People: detection and tracking on the proxy, then faces and the "which one is me?" selection** (models to download: a person detector such as YOLO and a face detector and recogniser, for example SCRFD and ArcFace; InsightFace weights are non-commercial). Output `targets.json` (tracks with yaw, pitch, size, identity).
5. **`quality` stage:** thumb and hand over a lens, rain drops, blur, glare, over- and under-exposure, seam parallax risk; combined from the exposure statistics, sharpness measures on the lens frames and the calibration's stick polygon.
6. **`speakers` stage:** voice embeddings, wearer voice profile, and mouth-motion linking to the face tracks (design in section 7, item 6b).
7. **`scenes` stage:** captions and tags from a vision model on labelled rectilinear views (needs a decision: a local model for privacy or an API for quality; cost and what leaves the machine).
8. **Phases 3 and 4** (candidate proposals and the attention map) become straightforward once the inputs above exist, then the master assembly and the framing solve.

### 15.3 Data completeness check
`./strata360 status RACE --all` shows which stages have run per clip; a `coverage` report listing which of the 15.1 artefacts exist for every clip (and which decisions are therefore not yet possible) is a small addition to the CLI.

### 15.4 Questions that gate the next steps
- The **GPX file** and any known anchor for the clock (start time, a photo or phone timestamp).
- Whether the two 15 March MP4 exports are **finished films** (taste data), and whether you have other finished films from earlier races.
- **Vision model:** local (private, weaker) or an API (stills of the footage leave the machine)?
- **Face and voice models:** approval to download the person and face detectors and the speaker-embedding model.

---
