## 12. Open questions and decisions

**Decided**
- The camera is held on a short selfie stick by the user, so the user is normally the closest, persistent person at a constant bearing.
- "Me" is identified by the user selecting their track on a sheet once. The profile is saved and reused (reference photos optional).
- Output is 4K UHD (3840×2160), at the input frame rate. Mixed-fps films use the majority rate.
- Output is 16:9 only.
- The map renderer takes MP4; position jumps between clips are simple teleports.
- The camera has no GPS in the clip metadata, and the camera clock is trusted (container `CreateDate` is UTC).

**Still open**
1. How exactly the map renderer reads time from each MP4 (the `creation_time` tag, filename, or sidecar), and to what precision. This decides between Option A and Option B in Phase 8.
2. Are the Insta360 clocks correct and in which timezone? The cameras may differ.
3. Typical clip length. *Answered (20 Oct 2026), measured on the owner's whole library: 881 Insta360 X3 clips (14.1 h, 2022 to 2026) have a median of 31 s (10th to 90th percentile 12 to 107 s; 54 under 10 s, 196 over a minute, 14 over 5 minutes, the longest 29 min); 127 DJI Osmo 360 clips (1.4 h) a median of 24 s (10 to 93 s, the longest 5 min).*
5. Music source and licensing, and whether the tracks are constant-tempo.
6. Is chronological order strictly required, or are occasional flashbacks or intro teasers allowed? *Partly answered (19 Oct 2026): one intro teaser is built, the cold open (`edit/cold_open.py`, [plan](../plan/cold-open.md)): the race's best moment plays before the opening title, then the story runs in order. It is on when `strata360 coldopen` has chosen one, and off with `--pick none` or `STRATA_COLD_OPEN=0`. Flashbacks inside the story are still not allowed.*
7. Face-blur requirements for other runners and spectators (identity recognition of the user is local-only, see §8.6).
8. Whether you want to add reference photos on top of the "which one is me?" selection (optional).
9. Which LLM/vision provider and monthly budget?
10. Any Insta360 sample files available to test the second adapter early?

---
