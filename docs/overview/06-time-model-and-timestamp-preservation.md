## 6. Time model and timestamp preservation

This underpins the GPX map overlay, so it gets its own section.

### 6.1 Establishing each clip's absolute start time
**The camera clock is trusted.** There is no GPS in the footage, so there is nothing to sync against per clip. Sources, in priority order (record which one won in `start_utc_source`):
1. Manual override table (CSV), for a clip or a whole camera.
2. Container `CreateDate`, treated as **UTC** (evidence in §2). The config has a `container_time_is_utc` flag, defaulting to true, in case another camera stores local time.
3. Filename timestamp, using the same UTC assumption. Used only if the container time is missing or disagrees with it by more than a second (log a warning).
4. Optional GPS time from telemetry, if a camera ever provides it.

Everything is stored as UTC. The race timezone lives in config only to display local times and to convert the GPX if the GPX is not in UTC.

### 6.2 Clock sanity check (light, optional)
Because the clock is trusted, there is no calibration step in the main path. Provide cheap safeguards instead:
- **Consistency checks:** clips must be time-ordered in the same way as their filename counters; clip start times must fall inside the GPX time range (warn if not); gaps and overlaps between consecutive clips must be plausible for the race (e.g. two clips overlapping in time by more than a second is suspicious).
- **Single global offset:** an optional `camera_clock_offset_s` per camera in config (default 0), for the case where the user notices later that the whole camera clock is off by a constant amount (for example by comparing one clip to a known point on the course).
- **Clock correction feature (`strata360 clock RACE`; `gps/anchors.py`).** Camera clocks that have been offline for a long time are wrong by a constant amount (once corrected, the clock stays in sync through the race; drift support exists but is off unless anchors hours apart disagree). Three ways to set it, all ending in one re-time of every clip (only `ingest` re-runs; nothing else is recomputed):
  1. **`--suggest`:** running starts and stops are found in the GPS/FIT (speed) and in each clip's accelerometer step rhythm (`motion.json` `steps`); every camera event votes for the offset that would match each GPS event of the same kind within 30 minutes; the offsets with the most votes are listed. `--use-suggestion N` applies one.
  2. **`--anchor CLIP:SECONDS`:** what the GUI does when the user selects a clip and clicks the point on its timeline where the running starts (or stops). The click snaps to the nearest detected step event within 8 s; the matching GPS event nearest to the current estimate is used (`--utc ISO` overrides; the result flags an ambiguous match so the GUI can ask). Anchors are stored in `race.json` (`camera_clock.anchors`).
  3. **Manual:** `camera_clock.offset_seconds` (camera minus UTC).
  **Auto-detect on the real library (30 Sep):** matching every running start/stop against the FIT alone is not decisive (the watch has about 1,700 start/stop events over four days and only about a dozen clips contain a transition), and two other cues were tried and rejected (step cadence and camera heading against GPS course: no peak at the true offset). What works is the **mass start**: the earliest clip with a crowd (people stage) in which the wearer sets off and keeps going is paired with the FIT's first running start (the watch was started at the gun). That gave +358 s against the hand-set +370 s: 12 s out, because the camera's "start" is the first shuffle and the watch's is the first speed above 1.2 m/s. So the automatic answer is right to about 15 s and is shown as a suggestion with its confidence; the GUI tweak (an anchor on the exact moment the running starts) finishes it.
  Two or more anchors at least 6 hours apart also fit a steady drift (`drift_s_per_day`), applied by ingest; a single anchor, or anchors close together, give a constant offset. Tests: `tests/unit/test_clock.py`.
- **Verified example (Legends 2026):** the camera clock was 370 s ahead of UTC, found by matching the moment the wearer starts running at the race start (clip accelerometer step energy) with the running onset in the Garmin FIT (`camera_clock.offset_seconds`; progress.md). Daylight (scene brightness vs sun elevation) bounds the offset to about 15 minutes and is a good sanity check; a sudden event gives seconds.
- **Manual anchors (optional):** "this clip, at this moment, was at this GPX time." Two or more anchors allow a linear drift correction. Not automatic, and not needed unless the clock turns out to be wrong.
- The Insta360 clock is separate and must be checked against the same anchors, because older footage may have been recorded with a different offset or timezone.

### 6.3 Preserving time through editing
For every output segment, the render writes a mapping from output time to source UTC:
`utc(out_t) = clip.start_utc + clock_offset + src_in_s + (out_t - out_start_s) × speed`

Rules:
- Speed changes and any freeze frames are represented explicitly. Never approximate.
- Transitions (crossfades) overlap two source times. The map uses the **outgoing clip until the midpoint, then the incoming clip**, and this rule is documented.
- The map is sampled to a fixed grid (e.g. every output frame or every 0.1 s) and also stored as piecewise-linear segments.
- Segments are also emitted in a form that expresses the *non-contiguity*: the race position "jumps" between clips, and the map renderer needs to know when to animate a jump versus a smooth advance (§9).

---
