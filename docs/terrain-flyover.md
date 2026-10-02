# 3D terrain flyover (plan item N2): what was built and learned, 2 Oct 2026

Status: **productionised (2 Oct)**: the approved prototype camera is now `src/strata360/overlay/flyover.py` (`FlyoverClip`, the same interface as the 2D `MapClip`), a gap kind `flyover` in `edit/synthetic.py` (4K by default), `strata360 gap-clip --kind flyover`, `kind` on the gaps API and a **2D map / 3D flyover (4K)** dropdown for each gap in the Gaps panel. It enters the film as a synthetic clip exactly as the map clip does. Unit tests cover the camera maths, the style, the `mbgl-render` command line and the frames (with `mbgl-render` faked). **Run on both platforms:** macOS/Metal (the user's M4) and Linux/OpenGL (built and run in a cloud container on Mesa's software renderer, 2 Oct: real terrain frames at 720p and 4K, and a 4K H.264 clip through `MapClip.render`); Windows not yet tried; see "4K" below. The prototype script (`scripts/flyover/render.py`, presets and `--shots`) was removed: it is in git history (commit 9ca0208), and its camera is the module's `plan_camera`.

## Decision: MapLibre Native, not MapLibre GL JS in a browser

The plan (implementation-plan.md N2) said to re-check MapLibre Native, whose terrain was still being written in December 2025. It exists now: draft PR [maplibre/maplibre-native#4190](https://github.com/maplibre/maplibre-native/pull/4190), branch `feature/terrain-3d` (last commit 10 Sep 2026), with terrain for raster-dem tiles (Mapterhorn is Terrarium-encoded, Terrain-RGB also works), draping of raster, fill, line, hillshade and colour-relief layers, and exaggeration, on OpenGL, Metal, Vulkan and WebGPU. Most of its testing was Android/OpenGL; **Metal on this Mac works**.

No browser and no WebGL-in-headless question: `mbgl-render` draws one still per call, from a tile cache, and the driver pipes the frames into ffmpeg.

### Build (macOS, no Xcode needed; MapLibre compiles its shaders at run time)

```
brew install cmake ninja pkg-config glfw
git clone --depth 1 --branch feature/terrain-3d --recurse-submodules --shallow-submodules https://github.com/maplibre/maplibre-native.git ~/Code/maplibre-native-terrain
cd ~/Code/maplibre-native-terrain
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DMLN_WITH_METAL=ON -DMLN_WITH_OPENGL=OFF -DMLN_WITH_WERROR=OFF
nice -n 19 ninja -C build -j2 mbgl-render        # about 45 minutes at that priority; linker warnings about macOS 27 vs 14.3 are harmless
```

### Build (Linux, OpenGL; verified 2 Oct on Ubuntu 24.04, 4 cores, about 8 minutes)

```
sudo apt-get install -y cmake ninja-build clang pkg-config xvfb libcurl4-openssl-dev libglfw3-dev libuv1-dev libpng-dev libicu-dev libjpeg-dev libwebp-dev libegl1-mesa-dev libgl1-mesa-dri libgl1-mesa-dev libopengl-dev
git clone --depth 1 --branch feature/terrain-3d --recurse-submodules --shallow-submodules https://github.com/maplibre/maplibre-native.git ~/Code/maplibre-native-terrain
cd ~/Code/maplibre-native-terrain
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DMLN_WITH_OPENGL=ON -DMLN_WITH_WERROR=OFF -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
ninja -C build -j4 mbgl-render
```

With no display (a server, a container) run the CLI under `xvfb-run -a strata360 gap-clip ...`: the GL context needs an X display; with no GPU, Mesa's llvmpipe draws it in software (about 3 s a 4K frame with 720p-scale tiles, about 8 s with `--sharp` tiles on 4 cores; a GPU is far faster). Set `MBGL_RENDER` to the binary if it is not under `~/Code/maplibre-native-terrain/build/bin/`.

The binary is `build/bin/mbgl-render` (`MBGL_RENDER` overrides the path). Tiles are cached in `~/.strata360/flyover-cache.db`.

## Running it

```
strata360 gap-clip RACE --gap G03 --kind flyover                      # 4K (3840x2160), 30 fps, esri imagery, default length for the gap
strata360 gap-clip RACE --gap G03 --kind flyover --seconds 20 --size 1920x1080 --imagery topo --no-sharp
```

or choose *3D flyover (4K)* in the dropdown beside a gap in the race view's Gaps panel and press Generate. `mbgl-render` is found from `MBGL_RENDER`, then the PATH, then `~/Code/maplibre-native-terrain/build/bin/mbgl-render`; without it the command stops with the build pointer and the panel greys the option (`GET /api/gaps` says `flyover.available`). `STRATA_MBGL_BACKEND=metal|opengl|vulkan` overrides the backend (`hw.mbgl_backend()`: Metal on macOS, OpenGL elsewhere, **untested off the Mac**). Tiles are cached in `~/.strata360/flyover-cache.db`.

**The camera comes from the gap, not from keyframes written by hand** (`plan_shots`): film time maps linearly to race time (the speed-up), so the camera is at the runner's real distance at every second (a stop at an aid station is a pause), and zoom and pitch follow the speed across the screen (`zoom_pitch_for`: 2.5 km of route per film second gives zoom 11.5 and pitch 55, 0.4 km/s gives 13 and 45, below 0.05 km/s 14.5 and 30, smoothed over a few seconds). The camera is then planned as in the next section (`plan_camera`; about a second of numpy per 100 frames). The race overlay's clock, distance and pace are drawn on top, with the imagery and terrain credit bottom right (`IMAGERY` holds each source's credit).

Cost (measured at 1280x720 on the M4 in the prototype): about 0.4 s a frame, run at low priority, one process at a time.

## 4K

The camera is always planned for a 1280x720 picture. Sizes are 16:9 and a multiple of 640 wide (1280x720, 1920x1080, 2560x1440, 3840x2160). Two ways to draw the same view at 4K:

- **Default, `sharp`:** `-r 1` at 3840x2460 with the zoom raised by log2(3), so finer imagery and terrain tiles are used (Esri goes to zoom 19; the line widths are scaled to match). The same ground is in view with real 4K detail. Checked 2 Oct on an Alpine test route: same framing as the pixel-ratio render, visibly crisper (paths, lake edges; Laplacian variance 1.8x), and no new holes in the frame compared.
- **`--no-sharp`: pixel ratio.** `mbgl-render -r 3` draws the 1280x(820) view with 3x the pixels: the approved 720p framing and tile choice, the imagery enlarged and so softer. About 2.5x faster.

Either way each picture is rendered 820 px tall at 720p scale and the bottom 100 px cropped (the missing-tile wedge). Measured on the 4-core CPU-only container (llvmpipe): 720p about 1.8 s a frame, 4K about 3 s (`--no-sharp`) or 8 s (sharp); the M4 on Metal and a GPU will be faster (unmeasured at 4K). A 30 s clip at 30 fps (900 frames) is then about 2 hours of software rendering here. The first frames also fetch tiles. The clip is encoded at 12 Mbit/s per 1080p worth of pixels (48 Mbit/s at 4K) with the hardware H.264 encoder where there is one. The film's final render scales a generated clip to the film's size (`render/synthetic.py`).

## What the camera does, and why (each step was a user comment on a rendered clip)

1. **Imagery.** Esri World Imagery looked best (sharp, natural); OpenTopoMap is good as a map look; Sentinel-2 cloudless (EOX) is blurry and dark; OSM raster is flat. Licences were not read (the user said not to worry for now; Mapterhorn is open data). The Wallonia orthophotos are untested (my first URL was wrong).
2. **Camera height.** `mbgl-render` places the camera relative to the centre's height, so over hills the foreground was cut off. The fix is `--alt` = the track's altitude at the look-at point times the exaggeration (1.5).
3. **Pitch falls as zoom rises.** The draft does not cover tiles under the camera, so close and steep shows holes and stretched texture. Clean up to about pitch 50 at zoom 11.5 to 13, and about 35 at zoom 14.5. The presets stay inside that.
4. **Missing-tile wedge at the bottom edge.** Background colour matched to the forest (`#26381f`), and each frame is rendered 12% taller and the bottom strip cropped.
5. **Speed-dependent look.** Look-ahead and smoothing scale with `k = 2^(13.3 - zoom)`.
6. **Heading is fitted on the screen, not by angle.** For each frame the route (from just behind the runner to `1500 m x k` ahead) is projected through the camera mbgl builds (pinhole, vertical field of view 0.6435 rad, camera behind and above the look-at point at the distance that makes one tile pixel one map pixel, pitch measured from straight down, terrain height) to pixel positions. The heading is the bearing that keeps the route at least 12% of the width from the sides and bottom (not the top: the route runs off towards the horizon there), ties going to the route's own direction (`project`, `fit_bearing_screen`). A bare angle from the view centre was a poor proxy: how close the route gets to the edge depends on pitch and zoom.
7. **Rotating is worse than panning.** The heading is smoothed (4.5 s Gaussian, 5 degrees/s cap) and then passed through a **15 degree dead-band** (backlash: swings smaller than the band are ignored, so left-then-right cancels). It turns 0 to 28 degrees in total over the test clips. A containment step that made the camera catch up was tried and removed: it gave peaks of 17 degrees/s and turned back soon after.
8. **The look-at point moves instead** (`optimise_centre`): per frame, the smallest forward or sideways offset (in the camera's frame) that keeps the margin, including moving back towards the runner (the bottom edge was the limit at the worst frame in `dive`); each move starts up to 2 s early (largest offset within +-2 s) and is smoothed over 2 s so it glides.
9. **Marker.** A blue arrow with a white halo on the track at the runner's position, pointing along the average direction of the nearby track (window `+-120 m x k`), drawn as a polygon so that it drapes on the terrain (the draft's symbols are not yet placed at the right altitude). The route is a red line whose width follows the zoom.

Measured on the approved clips (closest the route gets to a side or the bottom, as a share of the width): `medium` 18.5%, `fast` 17.5%, `dive` 10.7% to 12.1% (4.4% before panning). One known tight spot: the close pass of `dive` (14 to 15 s) where the route bends sharply; less smoothing made it worse, so the remedy, if needed, is to ease the zoom out through the bend (not built).

## Limits and open items

- **Draft branch gaps** (its own list): symbols, circles and lines are not elevated correctly, 3D buildings are not started, tiles covering more than one terrain tile are not supported, `coveringTiles()` ignores terrain, performance was only tested in static mode. Our use (draped raster, a draped line and a draped polygon, static renders) avoids them, but the near-camera holes remain, hence the crop and the pitch limits.
- **Not done:** the route line fills in progressively (it is drawn whole); a persistent render process (the per-frame start-up is part of the 0.4 s); 4K timing on the M4; a run on a stretch with another shape of route (a night section, a gap with a long stop); the Wallonia orthophotos; hairpin handling in the close pass; the elevation strip of the map clip is not drawn on the flyover; an end-to-end test of the `gap-clip --kind flyover` command (the pieces are unit tested).
- **Python 3.13 under pyenv here prints `ValueError: unsupported hash type blake2b/blake2s` at start-up** (hashlib built without OpenSSL); harmless for these scripts.
- **Imagery licence:** unread for Esri World Imagery (what Komoot uses), Sentinel-2 and the Wallonia orthophotos; needed before any film that is shared.

## Status in the plan

This note's summary is in `docs/implementation-plan.md` (N2, 2 Oct): it supersedes the earlier "MapLibre GL JS in headless Chromium now, Native later" decision. Keep the build steps, camera findings and open items here; the plan holds the next steps (connect to the film as a synthetic clip, progressive route line, tests, imagery licence).
