# Video super-resolution / restoration trial on the problem close views

Question: the final film's close "you" views look painted (OSV compression). Per-frame models (RealPLKSR, SwinIR, SCUNet, Real-ESRGAN, see `docs/progress/2026-10-music-upscale.md`) clean or add texture frame by frame and can flicker; a video model sees neighbouring frames.

Test clips (made from the final film `final/af061ea030/film.mp4`, in `<race dir>/final/stills/upscale-compare/video-test/`):
- `input_1080p25_t174-180.mp4`: 6 s of the close view (clip 0023), 1920x1080 at 25 fps, what the film pipeline renders before enlarging.
- `input_crop_640x360_t175-177.mp4`: a 2 s, 640x360 crop of the face area.
- `reference_4k_direct_t174-180.mp4`: the same 6 s at 4K straight from the film (no model).

## Mac (16 GB): SeedVR2 does not fit
`mflux-upscale-seedvr2` (mlx-gen 0.38, `AbstractFramework/seedvr2-3b-4bit`, venv `~/.venvs/seedvr2`): a 1920x1080 still to 2x fails (Metal buffer 12.7 GB over the 9.5 GB limit); a 640x360 still crop to 2x runs out of memory (24 GB peak); video needs chunks of at least 29 frames, 640x352 x 33 frames runs out of memory after 4 minutes (30 GB peak) and even 320x192 exceeds the tool's own safe budget (13.9 GB against 4.7 GB). `--force-unsafe-video-memory` was refused by the session's permission check and was not used.

## Windows PC (RTX 5070 Ti 16 GB): to try
1. SeedVR2 (numz/ComfyUI-SeedVR2_VideoUpscaler, Apache-2.0): clone it, `python inference_cli.py --help` for the current flags (the README's "Run as Standalone" section), use the 3B model in an fp8 or GGUF build with BlockSwap and VAE tiling; run on `input_1080p25_t174-180.mp4` to 2160 and on the 640x360 crop to 720.
2. BasicVSR++ / RealBasicVSR through MMagic (`openmim`, `mmcv`; may be awkward on Windows).
3. Judge by eye at 100%: flicker (step through frames), invented detail on the eyes and the ground, the block patterns, against `reference_4k_direct` and per-frame SCUNet + Real-ESRGAN general.
Note down the seconds a frame and the peak GPU memory.
