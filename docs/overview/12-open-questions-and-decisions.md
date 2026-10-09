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
3. Typical clip length (still unknown; the sample is under 5 s).
5. Music source and licensing, and whether the tracks are constant-tempo.
6. Is chronological order strictly required, or are occasional flashbacks or intro teasers allowed?
7. Face-blur requirements for other runners and spectators (identity recognition of the user is local-only, see §8.6).
8. Whether you want to add reference photos on top of the "which one is me?" selection (optional).
9. Which LLM/vision provider and monthly budget?
10. Any Insta360 sample files available to test the second adapter early?

---
