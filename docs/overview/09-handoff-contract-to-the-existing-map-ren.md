## 9. Handoff contract to the existing map renderer (summary)

- Input to the renderer is MP4. Assumed: it reads each file's `creation_time` and duration and places it on the GPX. We therefore write per-segment MP4s with true-UTC `creation_time`, keep speed at 1.0, and use hard cuts (Phase 8, Option A; the segment sidecar JSONs of §5.8 are the authoritative time record). A `timemap.csv` (Option B) is also produced.
- Jumps between clips are teleports. Nothing extra is required from us.
- **Open item:** confirm how the renderer really obtains timestamps (the `creation_time` tag, filename, or a sidecar) and its precision, then write contract test P8-07.

---
