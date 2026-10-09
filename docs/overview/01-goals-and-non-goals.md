## 1. Goals and non-goals

### Goals
1. **Fully automated export** of raw 360 files (DJI `.OSV`, Insta360 `.INSV`/`.MP4`) into a common, well-understood intermediate format. No manual use of vendor GUIs in the normal path.
2. **Per-clip analysis and rich options, not decisions.** For each clip, produce (a) several ranked candidate time ranges with flexible trim handles and (b) an *attention map*: a description of everything worth looking at on the sphere over time, including where **the user** is. No camera move (zoom, pan, perspective, centring) is chosen at this stage, because the right choice depends on the final length of the shot, its neighbours and the music.
3. **Master assembly.** Given all clips' candidates, a target total duration, and optionally a music track, choose which candidates to use and their exact in/out points. Output one edit decision list (EDL). Then, once each shot's exact length is known, a separate **framing solve** picks the camera moves for it.
4. **Timestamp preservation.** Every second of output video maps back to a known wall-clock UTC time, so the map/GPX overlay can be driven from it.
5. **Optional beat sync.** Cut points and clip lengths flex slightly so cuts land on musical beats.
6. **Human-in-the-loop by default.** Every stage writes inspectable files. The user can override any decision before the final render.

### Non-goals (for now)
- A GUI editor. The interface is CLI, files, and later an MCP server.
- Colour grading, titles, or audio mixing beyond music ducking/normalisation.
- Rendering the GPX map. That already exists. This project only supplies it the timing map (see §9).
- Live/real-time processing.

### Scale assumptions
- 20–100 clips per race, each roughly 5 s to a few minutes (the sample is 4.8 s). Assume total raw footage is under about 2 hours per race.
- The DJI sample is 3840×3840 HEVC 10-bit ×2 lenses at about 50 fps, roughly 170 Mbit/s. A race's raw footage can be tens of GB.
- Output: 4K UHD, at the source frame rate.
- Target hardware: Apple Silicon Mac, Python 3.11+, ffmpeg, exiftool available via Homebrew.

---
