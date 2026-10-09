## 10. Milestones (suggested order)

1. **M0: Stitch spike.** Convert the sample OSV to equirect with ffmpeg; compare to the LRF; decide the stitching approach and stabilisation route; benchmark a 4K flat render from the master (ffmpeg `v360` on the CPU versus a GPU path). Gate for everything else. (P1 acceptance criteria.)
2. **M1: Time and timemap skeleton.** Phase 0 plus a minimal EDL → render → timemap path with hand-written EDLs and the synthetic test clips. Proves timestamp preservation and framing maths before any AI is involved.
3. **M2: Analysis.** Phase 2 (shots, audio, speech, subjects, quality) with the vision captions behind a cache and a budget cap.
4. **M3: Proposals and attention map.** Phases 3 and 4 (including protagonist identification and its review sheet), with overlay previews and human override files.
5. **M4: Master assembly and framing without music.** Phase 5 (selection, coverage, chronological order, target duration) and Phase 6 (framing solve). Handoff to the map renderer (Phase 8), first real end-to-end race film.
6. **M5: Beat sync.** Music analysis and cut alignment, the flexible-length logic.
7. **M6: Second camera and polish.** Insta360 adapter, MCP interface, face blur, HTML race report.

---
