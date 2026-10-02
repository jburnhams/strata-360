# 3D terrain flyover (plan item N2): what was built and learned, 2 Oct 2026

Status: **a working prototype, camera approved by the user on 2 Oct** (v7 clips on Legends km 20 to 70). Not yet wired into the film: nothing turns a gap into a camera plan, and there are no tests. Code: `scripts/flyover/` (`render.py`, `styles.py`).

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

The binary is `build/bin/mbgl-render` (`MBGL_RENDER` overrides the path). Tiles are cached in `~/.strata360/flyover-cache.db`.

## Running it

```
python scripts/flyover/render.py <track.fit> --preset dive --start-km 20 --out dive.mp4
python scripts/flyover/render.py <track.fit> --shots shots.json --out clip.mp4    # [{"t":0,"km":20,"zoom":11.5,"pitch":55}, ...]
python scripts/flyover/render.py <track.fit> --preset dive --dry-run --verbose    # the camera and its statistics, no rendering
```

Presets (`PRESETS` in `render.py`): `fast` (50 km in 20 s, zoom 11.5, pitch 55), `medium` (3 km in 8 s, zoom 13, pitch 45), `slow` (0.5 km in 10 s, zoom 14.5, pitch 30), `dive` (overview, slows into a close pass, back out: 18 s). The camera is **keyframes over film time** (route km, zoom, pitch), eased with a monotone cubic (PCHIP), so zoom and pitch animate and the camera never runs backwards. Speed (zoom in for the voice-over, out for a night) is the slope of the km curve.

Cost: about 0.4 s a frame at 1280x720 on the M4 (a 30 s clip is about 5 minutes), run at `nice 19`, one process at a time.

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
- **Not done:** the route line fills in progressively (it is drawn whole); the keyframes are not connected to the film (a gap to a camera plan, a rendered clip as a synthetic source for the script pack and planner, as the plan's "How a generated clip enters the edit" describes); 1080p and 4K renders and a persistent render process (the per-frame start-up is part of the 0.4 s); a run on a different stretch than km 20 to 70 (a night section with another shape of route); the Wallonia orthophotos; the `--shots` file format has no tests; no unit tests for `project`, `fit_bearing_screen`, `deadband`, `optimise_centre` (all pure functions of arrays, so easy to test).
- **Python 3.13 under pyenv here prints `ValueError: unsupported hash type blake2b/blake2s` at start-up** (hashlib built without OpenSSL); harmless for these scripts.
- **Imagery licence:** unread for Esri World Imagery (what Komoot uses), Sentinel-2 and the Wallonia orthophotos; needed before any film that is shared.

## Status in the plan

This note's summary has been moved into `docs/implementation-plan.md` (N2, 2 Oct): it supersedes the earlier "MapLibre GL JS in headless Chromium now, Native later" decision. Keep the build steps, camera findings and open items here; the plan holds the next steps (connect to the film as a synthetic clip, progressive route line, tests, imagery licence).
