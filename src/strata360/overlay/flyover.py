"""A 3D terrain flyover clip for a stretch of the race with no footage (implementation plan N2): the camera flies along the route over satellite imagery draped on terrain, with the race overlay's numbers on top.

  clip = FlyoverClip(series, t0, t1, seconds, fps=30, size=(3840, 2160), imagery='esri', tz='Europe/Brussels')
  clip.frames -> number of frames;  clip.time(k) -> the race time (UTC seconds) frame k shows;  clip.frame(k) -> RGB uint8 picture;  mapclip.render(clip, path) -> an MP4

The same interface as overlay/mapclip.py's `MapClip`, so the render, the film and the GUI treat both alike. Frame k shows the race at `t0 + k * speedup / fps`. Each picture is one still of MapLibre Native
(`mbgl-render`, the terrain branch: build steps in docs/terrain-flyover.md), run once per frame from a shared tile cache. The camera is planned first, in pure numpy (docs/terrain-flyover.md, "What the camera does"):
keyframes over film time (route km, zoom, pitch: zoom in and tilt up when the runner is slow on the screen, wide and steep when fast), the heading fitted so that the route stays on the screen, little turning
(smoothed and dead-banded) and the look-at point moving instead. The camera is worked out for a 1280 x 720 picture and rendered at any 16:9 size that is a multiple of 640 wide (4K = 3840 x 2160): the
same view, drawn with 3x the pixels. `sharp` (the default) asks for finer map tiles at larger sizes (zoom raised by log2 of the scale) instead of enlarging the 720p tiles (`sharp=False`: the look of the approved 720p clips, softer at 4K)."""
import json, math, os, shutil, subprocess, sys, tempfile

import numpy as np, cv2
from scipy.interpolate import PchipInterpolator

from strata360 import hw
from strata360.overlay.gapoverlay import GapOverlay
from strata360.overlay.mapclip import frame_count

BASE_W, BASE_H = 1280, 720    # the picture the camera is planned for
RENDER_H = 820                # rendered this tall at BASE_W, and the bottom cropped: the draft branch leaves a wedge of missing tiles along the bottom edge
EXAGGERATION = 1.5
BACKGROUND = '#26381f'        # what shows where a tile is missing: matches the forest
CACHE = os.path.join(os.path.expanduser('~'), '.strata360', 'flyover-cache.db')
MBGL_DEFAULT = os.path.join(os.path.expanduser('~'), 'Code', 'maplibre-native-terrain', 'build', 'bin', 'mbgl-render')
FOV = 0.6435011               # mbgl's default vertical field of view (radians)

IMAGERY = {                   # name -> (tiles url, tile size, max zoom, credit)
    'esri': ('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 256, 19, 'Imagery © Esri, Maxar, Earthstar Geographics'),
    'eox': ('https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg', 256, 14, 'Sentinel-2 cloudless © EOX IT Services (contains Copernicus data)'),
    'osm': ('https://tile.openstreetmap.org/{z}/{x}/{y}.png', 256, 19, '© OpenStreetMap contributors'),
    'topo': ('https://tile.opentopomap.org/{z}/{x}/{y}.png', 256, 17, 'Map © OpenTopoMap (CC-BY-SA), data © OpenStreetMap contributors'),
}
DEFAULT_IMAGERY = 'esri'
TERRAIN_CREDIT = 'Terrain © Mapterhorn'
# camera by speed across the screen (km of route per second of film): zoom and pitch fall together as it slows (the draft branch shows holes when close and steep)
ZOOM_RANGE = (11.5, 14.5); PITCH_AT_ZOOM = ([11.5, 13.0, 14.5], [55.0, 45.0, 30.0]); SPEED_AT_13 = 0.375; OCTAVES_PER_ZOOM = 1.9


class FlyoverError(RuntimeError): pass


def find_mbgl():
    """Path of the `mbgl-render` built from MapLibre Native's terrain branch: $MBGL_RENDER, then the PATH, then where docs/terrain-flyover.md builds it."""
    for p in (os.environ.get('MBGL_RENDER'), shutil.which('mbgl-render'), MBGL_DEFAULT):
        if p and os.path.isfile(p): return p
    raise FlyoverError('mbgl-render (MapLibre Native, terrain branch) is not installed: build it as in docs/terrain-flyover.md and put its path in MBGL_RENDER')


# ---- the route and the camera plan (pure functions of arrays) ----

def route_from_series(series, step_m=10.0):
    """The route on an even grid of distance: (metres along, lat, lon, altitude) arrays, from the overlay's series (so the distance is the one the overlay shows)."""
    v = series.at(series._pt); d, lat, lon, alt = v['dist_m'], series.route_lat, series.route_lon, v['alt_m']
    ok = np.isfinite(d) & np.isfinite(alt); d, lat, lon, alt = d[ok], lat[ok], lon[ok], alt[ok]; keep = np.r_[True, np.diff(d) > 0]; d, lat, lon, alt = d[keep], lat[keep], lon[keep], alt[keep]
    if len(d) < 2: raise ValueError('the track has no distance or altitude to fly over')
    g = np.arange(d[0], d[-1], step_m); return g, np.interp(g, d, lat), np.interp(g, d, lon), np.interp(g, d, alt)


def gauss(x, fps, sigma_s):
    """Gaussian low-pass over time (edges held), so back-and-forth moves cancel instead of being followed."""
    k = np.arange(-int(3 * sigma_s * fps), int(3 * sigma_s * fps) + 1) / (sigma_s * fps); w = np.exp(-0.5 * k ** 2); w /= w.sum(); pad = len(w) // 2
    return np.convolve(np.r_[[x[0]] * pad, x, [x[-1]] * pad], w, 'valid')


def zoom_pitch_for(speed_kms):
    """Zoom and pitch for a camera moving `speed_kms` km of route per second of film: overview at 2.5 km/s (zoom 11.5, pitch 55), working pace at 0.4 km/s (13, 45), a close pass below 0.05 km/s (14.5, 30)."""
    s = np.maximum(np.asarray(speed_kms, float), 1e-3); z = np.clip(13.0 - np.log2(s / SPEED_AT_13) / OCTAVES_PER_ZOOM, *ZOOM_RANGE); return z, np.interp(z, *PITCH_AT_ZOOM)


def plan_shots(series, t0, t1, seconds, step_s=1.0):
    """Camera keyframes [{t, km, zoom, pitch}] for the stretch shown in `seconds` of film: the runner's real position at every `step_s`, so a stop at an aid station is a pause, with zoom and pitch from
    the speed across the screen (smoothed over a few seconds, so the camera eases in and out of a fast section instead of jumping)."""
    n = max(3, int(round(seconds / step_s)) + 1); t = np.linspace(0.0, float(seconds), n); km = series.at(t0 + t * (t1 - t0) / seconds)['dist_m'] / 1000.0
    if not np.all(np.isfinite(km)): raise ValueError('the stretch has no distance on the track')
    km = np.maximum.accumulate(km); speed = gauss(np.gradient(km, t), 1.0 / (t[1] - t[0]), 3.0); z, p = zoom_pitch_for(speed)
    return [dict(t=float(a), km=float(b), zoom=float(c), pitch=float(d)) for a, b, c, d in zip(t, km, z, p)]


def chord_bearing(g, lat, lon, c, back_m, ahead_m):
    """Bearing of the straight line from `back_m` behind `c` to `ahead_m` ahead (metres along the route)."""
    a, b = np.interp([c - back_m, c + ahead_m], g, lat), np.interp([c - back_m, c + ahead_m], g, lon)
    return np.degrees(np.arctan2((b[1] - b[0]) * 111320 * np.cos(np.radians(a.mean())), (a[1] - a[0]) * 111320))


def fit_bearing(g, lat, lon, c, reach_m, cone=50.0):
    """The route's own direction: the mode of the bearings (seen from the runner) of route points up to `reach_m` ahead, nearer points counting more, each scoring by how far inside a +-`cone` degree view it falls."""
    d = np.linspace(reach_m * 0.1, reach_m, 24)
    la, lo = np.interp(c + d, g, lat), np.interp(c + d, g, lon); la0, lo0 = np.interp(c, g, lat), np.interp(c, g, lon)
    pts = np.degrees(np.arctan2((lo - lo0) * np.cos(np.radians(la0)), la - la0)); w = np.exp(-d / (0.6 * reach_m)); cand = np.arange(0, 360, 3.0)
    diff = (pts[None, :] - cand[:, None] + 180) % 360 - 180
    return cand[int(np.argmax((w[None, :] * np.clip(1 - (diff / cone) ** 2, 0, None)).sum(1)))]


def smooth_bearings(b, fps, sigma_s=3.0, max_dps=6.0):
    """Gaussian smoothing of the (unwrapped) heading over time, then a turn-rate limit, so the camera swings slowly."""
    u = np.degrees(np.unwrap(np.radians(b))); k = np.arange(-int(4 * sigma_s * fps), int(4 * sigma_s * fps) + 1) / (sigma_s * fps)
    w = np.exp(-0.5 * k ** 2); w /= w.sum(); pad = len(w) // 2; sm = np.convolve(np.r_[[u[0]] * pad, u, [u[-1]] * pad], w, 'valid'); out = [sm[0]]
    for x in sm[1:]: out.append(out[-1] + np.clip(x - out[-1], -max_dps / fps, max_dps / fps))
    return np.array(out) % 360


def deadband(b, width):
    """Backlash: the output holds still while the input stays within +-`width` degrees of it, and is only pushed when the input goes past that. Swings smaller than the band are ignored."""
    u = np.degrees(np.unwrap(np.radians(b))); out = np.empty_like(u); cur = u[0]
    for i, x in enumerate(u): cur = min(max(cur, x - width), x + width); out[i] = cur
    return out % 360


def travel(b):
    """Total degrees the heading turns, and the number of times it reverses direction (by more than 1 degree)."""
    d = np.diff(np.degrees(np.unwrap(np.radians(b)))); d = d[np.abs(d) > 1e-3]; sign = np.sign(d); return float(np.abs(d).sum()), int((np.diff(sign[sign != 0]) != 0).sum())


def project(g, lat, lon, alt, route_m, centre, bearing, zoom, pitch, size, exag):
    """Where points of the route (metres along it) fall on the screen (pixels), through the camera mbgl builds from centre / zoom / bearing / pitch: a pinhole `FOV` camera looking at `centre` = (lat, lon, height)
    from behind and above (at the distance that makes one tile pixel one map pixel), pitch measured from straight down. `size` = (width, height) of the rendered picture before the bottom crop.
    Returns x, y, and whether the point is in front of the camera."""
    la0, lo0, h0 = centre; W, H = size; b, p = np.radians(bearing), np.radians(pitch)
    mpp = 40075016.686 * np.cos(np.radians(la0)) / (512 * 2 ** zoom); F = 0.5 * H / np.tan(FOV / 2); dist = F * mpp
    e = (np.interp(route_m, g, lon) - lo0) * 111320 * np.cos(np.radians(la0)); n = (np.interp(route_m, g, lat) - la0) * 111320; u = np.interp(route_m, g, alt) * exag - h0
    f = np.array([np.sin(b) * np.sin(p), np.cos(b) * np.sin(p), -np.cos(p)]); r = np.array([np.cos(b), -np.sin(b), 0.0]); up = np.cross(r, f)
    v = np.stack([e, n, u], 1) - (-f * dist); depth = v @ f
    with np.errstate(divide='ignore', invalid='ignore'): x = W / 2 + F * (v @ r) / depth; y = H / 2 - F * (v @ up) / depth
    return x, y, depth > 0


def edge_margin(x, y, ok, W, H_visible):
    """Distance of each point to the nearest side or the bottom of the visible picture, as a fraction of the width (negative: outside); points behind the camera count as outside.
    Not the top edge: the route runs off towards the horizon there, which is natural."""
    return np.where(ok, np.minimum.reduce([x, W - x, H_visible - y]) / W, -1.0)


def fit_bearing_screen(g, lat, lon, alt, runner, centre, zoom, pitch, k, size, exag, visible_h, reach, margin=0.07):
    """The bearing (tried every 3 degrees) that keeps the most of the route, from just behind the runner to `reach * k` metres ahead, inside the picture with a `margin` (fraction of the width) to spare, nearer
    route counting more; among those that do (nearly) as well as the best, the one nearest the route's own direction."""
    d = np.linspace(-60 * k, reach * k, 28); w = np.exp(-np.clip(d, 0, None) / (0.6 * reach * k)); cand = np.arange(0, 360, 3.0); score = np.empty(len(cand))
    for i, c in enumerate(cand):
        x, y, ok = project(g, lat, lon, alt, runner + d, centre, c, zoom, pitch, size, exag); score[i] = (w * (edge_margin(x, y, ok, size[0], visible_h) > margin)).sum()
    good = cand[score >= 0.97 * score.max()]; pref = fit_bearing(g, lat, lon, runner, reach * k)
    return good[np.argmin(np.abs((good - pref + 180) % 360 - 180))]


def optimise_centre(g, lat, lon, alt, runner, centres, brgs, ks, zs, ps, size, exag, visible_h, reach, margin, fps, sigma_s, lead_s=2.0):
    """Move the look-at point, not the heading, to give the route room: per frame, among forward / sideways offsets of the nominal centre (in the camera's own frame) the smallest one that keeps the route from just
    behind the runner to `reach * k` ahead at least `margin` (fraction of the width) from the sides and bottom, or the roomiest if none does. Each move starts up to `lead_s` early and the offsets are smoothed
    over `sigma_s` seconds, so the camera glides."""
    fwd_opts, lat_opts = np.array([-400, -300, -200, -100, 0, 150, 300, 500, 700]), np.array([0, -150, 150, -300, 300, -500, 500])  # metres at zoom 13.3, times k
    offs = np.zeros((len(runner), 2))
    for i, (r, c, b, k, z, p) in enumerate(zip(runner, centres, brgs, ks, zs, ps)):
        d = np.linspace(-60 * k, reach * k, 40); th = np.radians(b); f = np.array([np.sin(th), np.cos(th)]); rt = np.array([np.cos(th), -np.sin(th)]); best, best_m, best_cost = (0.0, 0.0), -9.0, None
        for fo in fwd_opts:
            for la_ in lat_opts:
                e, n = (fo * f + la_ * rt) * k; cc = (c[0] + n / 111320, c[1] + e / (111320 * np.cos(np.radians(c[0]))), c[2])
                x, y, ok = project(g, lat, lon, alt, r + d, cc, b, z, p, size, exag); m = edge_margin(x, y, ok, size[0], visible_h).min(); cost = abs(fo) + 1.5 * abs(la_)
                if m >= margin and (best_cost is None or cost < best_cost): best, best_m, best_cost = (fo * k, la_ * k), m, cost
                elif best_cost is None and m > best_m: best, best_m = (fo * k, la_ * k), m
        offs[i] = best
    w = int(lead_s * fps); wide = lambda x: np.array([x[max(0, i - w): i + w + 1][np.argmax(np.abs(x[max(0, i - w): i + w + 1]))] for i in range(len(x))])
    offs = np.stack([gauss(wide(offs[:, 0]), fps, sigma_s), gauss(wide(offs[:, 1]), fps, sigma_s)], 1); out = []
    for (c, b, o) in zip(centres, brgs, offs):
        th = np.radians(b); e, n = o[0] * np.array([np.sin(th), np.cos(th)]) + o[1] * np.array([np.cos(th), -np.sin(th)]); out.append((c[0] + n / 111320, c[1] + e / (111320 * np.cos(np.radians(c[0]))), c[2]))
    return out


def screen_stats(g, lat, lon, alt, runner, centres, ks, zs, ps, brgs, size, exag, visible_h, reach):
    """Per frame, the smallest edge margin (fraction of the width) over the route from just behind the runner to `reach * k` ahead."""
    out = []
    for r, c, k, z, p, b in zip(runner, centres, ks, zs, ps, brgs):
        d = np.linspace(-60 * k, reach * k, 40); x, y, ok = project(g, lat, lon, alt, r + d, c, b, z, p, size, exag); out.append(edge_margin(x, y, ok, size[0], visible_h).min())
    return np.array(out)


def plan_camera(route, shots, fps, frames, exag=EXAGGERATION, margin=0.12, reach=1500.0, sigma=4.5, rate=5.0, dead=15.0, pan_sigma=2.0, pan=True):
    """The camera of every frame from keyframes `shots` ([{t, km, zoom, pitch}], eased with a monotone cubic so it never runs backwards): dict of arrays zoom, pitch, k (scale of the look-ahead, 2^(13.3 - zoom)),
    runner (metres along the route), lat / lon / alt (the look-at point, altitude already exaggerated), bearing, margin (closest the route gets to a side or the bottom, share of the width) and turned (degrees)."""
    g, lat, lon, alt = route; t = np.array([s['t'] for s in shots], float)
    curve = lambda key: PchipInterpolator(t, [s[key] for s in shots]); km_at, zoom_at, pitch_at = curve('km'), curve('zoom'), curve('pitch')
    ts = np.arange(frames) / fps; zs = np.array(zoom_at(ts), float); ps = np.array(pitch_at(ts), float); ks = 2 ** (13.3 - zs); runner = np.array(km_at(ts), float) * 1000
    cs = runner + 250 * ks                                                                                       # the look-at point: ahead by an amount that follows the zoom, smoothed over time
    mean_at = lambda arr, c, k: np.interp(np.linspace(c - 150 * k, c + 150 * k, 9), g, arr).mean()
    clat = gauss(np.array([mean_at(lat, c, k) for c, k in zip(cs, ks)]), fps, 2.0); clon = gauss(np.array([mean_at(lon, c, k) for c, k in zip(cs, ks)]), fps, 2.0); cel = gauss(np.interp(cs, g, alt) * exag, fps, 2.0)
    centres = list(zip(clat, clon, cel)); size = (BASE_W, RENDER_H); vis = BASE_H
    raw = np.array([fit_bearing_screen(g, lat, lon, alt, r, c, z, p, k, size, exag, vis, reach, margin) for r, c, z, p, k in zip(runner, centres, zs, ps, ks)])
    smooth = smooth_bearings(raw, fps, sigma, rate); brgs = smooth_bearings(deadband(smooth, dead), fps, sigma / 3, rate) if dead else smooth
    if pan: centres = optimise_centre(g, lat, lon, alt, runner, centres, brgs, ks, zs, ps, size, exag, vis, reach, margin, fps, pan_sigma)
    mg = screen_stats(g, lat, lon, alt, runner, centres, ks, zs, ps, brgs, size, exag, vis, reach)
    return dict(zoom=zs, pitch=ps, k=ks, runner=runner, lat=np.array([c[0] for c in centres]), lon=np.array([c[1] for c in centres]), alt=np.array([c[2] for c in centres]), bearing=brgs, margin=mg, turned=travel(brgs)[0])


# ---- the picture ----

def marker(lat0, lon0, brg, size_m, fid):
    """Arrow polygon (tip ahead, notched tail) at a point, `size_m` long, as a GeoJSON feature: it lies on the ground, so it drapes on the terrain."""
    th = np.radians(brg); f = np.array([np.sin(th), np.cos(th)]); r = np.array([np.cos(th), -np.sin(th)]); shape = [(1.0, 0), (-0.7, 0.6), (-0.35, 0), (-0.7, -0.6)]   # (forward, right) in units of size_m / 2
    ring = [(lon0 + (size_m / 2) * (x * f[0] + y * r[0]) / (111320 * np.cos(np.radians(lat0))), lat0 + (size_m / 2) * (x * f[1] + y * r[1]) / 111320) for x, y in shape]
    return {'type': 'Feature', 'id': fid, 'geometry': {'type': 'Polygon', 'coordinates': [ring + [ring[0]]]}}


def make_style(imagery, exag, lon, lat, scale=1.0, dz=0.0, hillshade=True):
    """The MapLibre style: the imagery draped over Mapterhorn terrain, the route (`lon`, `lat`: its coordinates) as a white-edged red line, and an empty source `me` for the marker. `scale` and `dz` widen the lines
    and shift their zoom stops when the picture is rendered at a higher zoom for the same view (sharp tiles), so they look the same."""
    if imagery not in IMAGERY: raise ValueError(f'imagery: one of {", ".join(IMAGERY)}')
    url, tile, maxz, _ = IMAGERY[imagery]; width = lambda a, b: ['interpolate', ['exponential', 2], ['zoom'], 10 + dz, a * scale, 15 + dz, b * scale]
    layers = [{'id': 'bg', 'type': 'background', 'paint': {'background-color': BACKGROUND}}, {'id': 'img', 'type': 'raster', 'source': 'img'}]
    if hillshade: layers.append({'id': 'hs', 'type': 'hillshade', 'source': 'dem', 'paint': {'hillshade-exaggeration': 0.25, 'hillshade-shadow-color': '#000000'}})
    layers += [{'id': 'route-casing', 'type': 'line', 'source': 'route', 'paint': {'line-color': '#fff', 'line-width': width(5, 12)}}, {'id': 'route', 'type': 'line', 'source': 'route', 'paint': {'line-color': '#ff3b1f', 'line-width': width(3, 7)}},
               {'id': 'me-halo', 'type': 'fill', 'source': 'me', 'filter': ['==', ['id'], 0], 'paint': {'fill-color': '#ffffff', 'fill-opacity': 1}}, {'id': 'me', 'type': 'fill', 'source': 'me', 'filter': ['==', ['id'], 1], 'paint': {'fill-color': '#1e6bff', 'fill-opacity': 1}}]
    return {'version': 8, 'sources': {'img': {'type': 'raster', 'tiles': [url], 'tileSize': tile, 'maxzoom': maxz}, 'dem': {'type': 'raster-dem', 'url': 'https://tiles.mapterhorn.com/tilejson.json'},
            'route': {'type': 'geojson', 'data': {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': np.c_[lon, lat].tolist()}}}, 'me': {'type': 'geojson', 'data': {'type': 'FeatureCollection', 'features': []}}},
            'terrain': {'source': 'dem', 'exaggeration': exag}, 'layers': layers}


def check_size(size):
    W, H = size
    if W % 640 or H * 16 != W * 9: raise ValueError(f'flyover size {W}x{H}: 16:9 and a multiple of 640 wide (1280x720, 1920x1080, 2560x1440, 3840x2160)')


class FlyoverClip:
    def __init__(self, series, t0, t1, seconds, fps=30.0, size=(3840, 2160), imagery=DEFAULT_IMAGERY, tz='Europe/Brussels', st=None, exag=EXAGGERATION, sharp=True, mbgl=None, cache=CACHE, camera=None, tiles=None, info=None):
        if not t1 > t0: raise ValueError('the stretch has no length')
        check_size(size)
        if imagery not in IMAGERY: raise ValueError(f'imagery: one of {", ".join(IMAGERY)}')
        self.series, self.fps, self.size, self.imagery, self.exag, self.sharp = series, float(fps), tuple(size), imagery, exag, sharp; self.W, self.H = self.size; self.cache = cache
        self.frames = frame_count(seconds, fps); self.t0, self.t1 = float(t0), float(t1); self.speedup = (self.t1 - self.t0) / (self.frames / self.fps); self.mbgl = mbgl
        self.scale = self.W / BASE_W; self.dz = math.log2(self.scale) if sharp else 0.0; self.render_h = self.H * RENDER_H // BASE_H
        self.route = route_from_series(series); self.shots = plan_shots(series, self.t0, self.t1, self.frames / self.fps); self.cam = camera or plan_camera(self.route, self.shots, self.fps, self.frames, exag)
        g, lat, lon, _ = self.route; i0, i1 = np.searchsorted(g, [self.cam['runner'].min() - 500, self.cam['runner'].max() + 3000]); sl = slice(i0, max(i1, i0 + 2))
        self.style = make_style(imagery, exag, lon[sl], lat[sl], self.scale if sharp else 1.0, self.dz)
        self.gap = GapOverlay(series, size, self.t0, self.t1, tz, tiles, st, credit=[IMAGERY[imagery][3] + ' · ' + TERRAIN_CREDIT], info=info); self.overlay = self.gap.overlay
        self._tmp = None

    def time(self, k): return self.t0 + k * self.speedup / self.fps

    def times(self): return self.t0 + np.arange(self.frames) * self.speedup / self.fps

    def args(self, k, style_path, png):
        """The `mbgl-render` command line for frame k."""
        c = self.cam; r = 1.0 if self.sharp else self.scale; w, h = (self.W, self.render_h) if self.sharp else (BASE_W, RENDER_H)
        return [self.mbgl or find_mbgl(), f'--backend={hw.mbgl_backend()}', '-s', style_path, '-c', self.cache, '-o', png, '-x', f'{c["lon"][k]:.6f}', '-y', f'{c["lat"][k]:.6f}', '-A', f'{c["alt"][k]:.1f}',
                '-z', f'{c["zoom"][k] + self.dz:.3f}', '-b', f'{c["bearing"][k]:.2f}', '-p', f'{c["pitch"][k]:.2f}', '-r', f'{r:g}', '-w', str(w), '-h', str(h)]

    def still(self, k):
        """The terrain picture of frame k, RGB at the frame size (no overlay)."""
        g, lat, lon, _ = self.route; c = self.cam; r, kk = float(c['runner'][k]), float(c['k'][k]); la, lo = float(np.interp(r, g, lat)), float(np.interp(r, g, lon)); brg = chord_bearing(g, lat, lon, r, 120 * kk, 120 * kk)
        self.style['sources']['me']['data'] = {'type': 'FeatureCollection', 'features': [marker(la, lo, brg, 190 * kk * 1.25, 0), marker(la, lo, brg, 190 * kk, 1)]}
        if self._tmp is None: self._tmp = tempfile.mkdtemp(prefix='strata-flyover-'); os.makedirs(os.path.dirname(self.cache), exist_ok=True)
        sp, png = os.path.join(self._tmp, 'style.json'), os.path.join(self._tmp, 'frame.png')
        with open(sp, 'w') as f: json.dump(self.style, f)
        res = subprocess.run(self.args(k, sp, png), capture_output=True, text=True)
        if res.returncode or not os.path.exists(png): raise FlyoverError(f'mbgl-render failed on frame {k}: {(res.stderr or res.stdout).strip()[-400:]}')
        img = cv2.imread(png, cv2.IMREAD_COLOR); os.remove(png)
        if img is None: raise FlyoverError(f'mbgl-render wrote no picture for frame {k}')
        if img.shape[0] < self.H or img.shape[1] != self.W: raise FlyoverError(f'mbgl-render drew {img.shape[1]}x{img.shape[0]}, expected {self.W}x{self.render_h}: does this build support -r / -h as used?')
        return np.ascontiguousarray(img[:self.H, :, ::-1])             # the bottom strip (missing tiles) cropped, BGR -> RGB

    def frame(self, k):
        """The picture of frame k as RGB uint8: the terrain with the race overlay on top (overlay/gapoverlay.py)."""
        return self.gap.apply(self.still(k), self.time(k))

    def close(self):
        if self._tmp: shutil.rmtree(self._tmp, ignore_errors=True); self._tmp = None
