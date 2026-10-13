# Insta360 seam evaluation (scratch tools, Oct 2026)

Used to find and fix the X3's lens alignment (see `docs/progress/2026-10-insta360.md`). Paths are hard-coded to the sample folder and a scratch directory; run from a folder holding `corpus/`.

1. `scan3.py` scores 3 frames per clip (seam disagreement) -> `scan3.json`.
2. `mkcorpus.py` freezes the 16 worst and 16 best frames (with neighbours) as JPEGs in `corpus/`.
3. `harness.py` scores a corpus with the real renderer's lens maps: 1 - correlation of high-passed lens pictures around the 12-direction seam ring (glare and exposure differences drop out). Lower is better.
4. `fitdelta.py` fits the front-lens rotation from SIFT matches; `refine.py` refines it against the metric with a held-out half; `stitchview.py` renders the real blend at the seams and straight down the stick.
`mei.py` is the unified-camera (Mei) projection used to unproject matches.
5. `carve.py` (feather against seam carving + parallax), `gain.py` (adds the exposure-match gain), `mband.py` (prototype two-band blend: low frequencies over a wide transition, detail over the narrow seam).
