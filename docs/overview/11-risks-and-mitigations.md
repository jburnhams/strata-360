## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| DJI dual-fisheye stitching quality with ffmpeg is insufficient (seams, parallax, calibration unknown) | Blocks everything | M0 spike first; fall back to vendor SDK/desktop export as a scripted step; use the LRF as a reference. |
| Camera clock wrong (no GPS available to check it) | Map overlay misaligned | Trust the clock, but run the consistency checks and offer the config offset and manual anchors (§6.2); check the Insta360 clock separately. |
| LLM picks the wrong subject or a boring moment | Poor edits | Deterministic candidate generation + scoring; the LLM only ranks; verification loop; human overrides; alternatives report. |
| Wrong person identified as "me" (look-alikes, hats, night, back views) | Film focuses on the wrong runner | Multi-cue identity (face, bib, appearance, track continuity), calibrated thresholds, `uncertain` state, one-time review sheet with corrections, tests P2-16 to P2-24. |
| Deferring framing makes Phase 5 choose trims that can't be framed well | Bad shots | Framing-feasibility scoring in Phase 5, guaranteed `defaults`, and the Phase 6 → Phase 5 feedback loop (P5-20/21, P6-14). |
| ffmpeg `v360` is CPU-bound, so 4K at 50 fps with per-frame camera parameters may render slowly | Long renders | Benchmark early (M0/M1); fall back to a GPU (Metal) or OpenCV-remap renderer behind the same interface; render per segment in parallel; draft mode uses proxies. |
| 4K flat frames upsample about 2× from the source at 90° FOV | Soft-looking shots | Accepted (4K is for the overlay detail). Render from the full-resolution master with a high-quality scaler, soft-minimum-FOV preference, effective-resolution reporting. |
| Jittery or nauseating camera paths | Unwatchable | Deterministic smoothing with velocity/accel limits; horizon lock; tests P6-02/04. |
| Beat sync infeasible with rigid clips | No sync | Handles and cut points designed up front; fallbacks; optional micro speed change. |
| Vision-model cost blows up | Budget | Prefilter, sparse sampling, batching, caching, budget caps. |
| Huge intermediate files | Disk full | Preflight checks, configurable master resolution, cleanup option. |
| Insta360 format differences (`.insv` pairs, proprietary gyro trailer) | Delay | Adapter interface; get real sample files early; may need a third-party parser or the vendor SDK. |
| Fractional-fps and VFR timing errors | A/V drift, timemap errors | Rational timebase everywhere; drift tests P1-05, P7-05. |
| Audio in wind and heavy breathing dominates | Bad audio | Wind detection, a mute/duck policy, music-forward mixing. |

---
