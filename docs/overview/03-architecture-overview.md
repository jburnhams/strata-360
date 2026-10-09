## 3. Architecture overview

```
 raw files ──► P0 Ingest/Catalog ──► P1 Normalize (stitch, stabilise, proxy)
                                              │
                                              ▼
                                   P2 Analyse (per clip, cached)
                                              │
                                              ▼
                              P3 Propose candidate ranges (per clip, LLM-assisted)
                                              │
                                              ▼
                              P4 Attention map (per clip: where to look, when,
                                 and where "me" is; options, not paths)
                                              │
        music track ─► P5a Music analysis     │
                                   ▼          ▼
                            P5 Master assembly: choose shots + exact in/out
                                              │        ▲
                                              ▼        │ (re-trim / swap if no good framing)
                            P6 Framing solve: choose zoom/pan/centring per shot
                                              │
                                              ▼
                                  P7 Render (H.265 MP4s + timecode map)
                                              │
                                              ▼
                        P8 Handoff to GPX/map renderer (existing)
```

Principles:
1. **The LLM never edits video. It reads text and stills and emits structured JSON.** Everything else is deterministic code. Results are reproducible, cheap to re-run, and reviewable.
2. **Every phase reads and writes files in a defined schema.** No hidden state. Phases can be re-run individually.
3. **Everything is cached by content hash plus parameters.** Re-running the pipeline after tweaking phase 5 must not redo phase 1.
4. **Two-tier resolution.** Analysis works on a proxy. Only the final render touches full-resolution masters.
5. **Defer decisions; emit options with valid ranges.** Early phases record what is *possible* (time ranges with handles, look targets with the times they exist), never a single committed choice. Decisions are made as late as the information allows: shot lengths in Phase 5, camera moves in Phase 6.
6. **Time is sacred.** A single canonical timeline (UTC, in rational or nanosecond units) is used everywhere. See §6.

---
