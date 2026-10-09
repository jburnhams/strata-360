## Milestone B: rendering is fast enough to iterate (GPU first)

### B1. Parallel pieces (S)
- `render/final.py` pieces are independent; let up to `resources.max_workers` processes take pieces using the same claim files as the batch (`pipeline/runner.py`), at low priority.
- **Done when:** two workers on the synthetic OSV produce byte-identical pieces to one worker; resource limits respected (`tests/unit/test_resources.py` pattern).

### B2. Cheaper frames (M; the savings apply to the GPU path too)
- Skip the second lens when the view lies inside one lens (most `dialogue_hold` and `selfie_hold` windows).
- Decode only the needed range of each lens stream; YUV in, convert after the remap.
- **Done when:** a benchmark script (`scripts/bench_render.py`) reports frames per second for hold, pan, planet on clip 0019; a measured gain is recorded; output differs from before by less than 1 code value at 10-bit outside the skipped lens.

### B3. GPU renderer (L)
- The per-pixel work (fisheye remap of both lenses, seam blend, parallax warp, globe compositing, overlay compositing, colour conversion) moves to the GPU, with the GPU chosen like the video hardware in `src/strata360/hw.py`: Apple GPU on macOS, CUDA on Windows/Linux when present, CPU otherwise. Start with PyTorch (`grid_sample`, already in `.venv-vision` with MPS and CUDA) for the remap and blends, so one code path serves both; a hand-written Metal kernel only if that is too slow.
- Decode straight to GPU memory where the platform allows; keep 16-bit (or float) through the render.
- **Quality gate (D4):** a comparison script renders the same frames on CPU and GPU (hold, pan, planet, globe, a seam with a hand near it) and reports the difference (max and mean in 10-bit code values, PSNR, and a sharpness measure). GPU is the default; a technique stays on the CPU only if the GPU result is noticeably worse, and the reason is recorded in `progress.md`.
- **Done when:** the comparison passes on the synthetic OSV in CI (CPU-only runners compare the torch-on-CPU path with the OpenCV path), and on the Mac the GPU render of the A5 film is measured against the CPU one.
