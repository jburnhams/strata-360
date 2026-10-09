## Milestone C: the edit is trustworthy

### C1. `quality` stage (M to L)
- New stage after `proxy`: per second, hand or thumb over a lens, water drops or fog, blur (Laplacian variance per lens), glare, over and under exposure, seam risk (near objects at the seam from the parallax warp's near-object cells). From the lens frames at low resolution, the exposure grid and the stick polygon.
- **Built (7 Oct), first cut:** `analysis/lens_check.py` and the `lens` stage (`lens_check.json`): once a second, per lens (480 px), the largest connected patch of smooth, non-sky cells on a 12 x 12 grid, plus dark, glare and soft shares; `candidates` (v7, `lens` a soft dependency) lowers `clear_nadir` where a lens is covered. Tests: `tests/unit/test_lens_check.py` (synthetic pictures). **Limits found on real frames (clip 0001, a room):** a plain white wall is as smooth as a hand, so `cover` hits 0.44 to 0.51 indoors and it is NOT used for `blocked` or the unusable decision, only for `clear_nadir`; telling a hand from a wall needs the two lenses compared or the VLM. Droplets (`soft`) and seam risk are measured but unchecked. **Not yet:** the labelled 40 s fixture and the 90% check; the stage has not been run over the batch.
- Output `quality.json`; `candidates` uses it for `clear_nadir`, `low_obstruction` and the unusable reasons (replacing the VLM guess).
- **Done when:** a labelled set of about 40 seconds from Legends (hand over lens, drops, clear) is checked in as a fixture of measurements (no footage), and the detector agrees on at least 90%; P5-28 (no planet, tunnel or spin with a hand over the lens) passes on real candidates.

### C2. Script editing in the GUI (M)
- Regenerate one block's lines or a range (send the neighbours as context), pin a line so re-writes keep it, change the target length and re-plan blocks and script together (listed as "later in the GUI" in `notes-and-script.md`). Builds on V2 to V4.
- **Done when:** unit tests on `edit/script.py` with the fake HTTP layer: a pinned line survives a re-write byte-identical; a regenerated range leaves other lines unchanged.

### C3. Who is speaking on screen (L, optional for v1)
- Active speaker detection from mouth motion on full-resolution face crops (overview 7 item 6b), fused into `speakers.json`, so dialogue framing holds on the person speaking rather than the biggest other person.
- **Done when:** P5-29 passes on a fixture with a known speaker. Can slip to Later if dialogue framing looks acceptable in A5.
