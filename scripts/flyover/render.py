"""Prototype terrain flyover of the race track with MapLibre Native (`mbgl-render`, branch feature/terrain-3d).

One mbgl-render call per frame (static mode, tiles from a shared cache db), frames piped to ffmpeg. The camera is a set of keyframes over film
time: route position (km), zoom and pitch, eased between keyframes, so a fast overview can slow down and drop in for a voice-over and back out.
The camera looks at a point ahead on the route; look-ahead and the heading smoothing scale with the current zoom (about 300 m / 400 m at zoom 13.3,
doubling per zoom level out). Closer and steeper shows holes near the camera (the draft branch does not yet cover tiles under the camera), so the
pitch should fall as the zoom rises: see PRESETS.

  python scripts/flyover/render.py FIT --preset fast --start-km 20 --out out.mp4
  python scripts/flyover/render.py FIT --shots shots.json --out out.mp4     # [{"t":0,"km":20,"zoom":11.5,"pitch":55}, ...]
"""
import argparse, json, os, subprocess, sys, tempfile
import numpy as np
from scipy.interpolate import PchipInterpolator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
from strata360.gps import track  # noqa: E402
from styles import style  # noqa: E402

MBGL = os.environ.get('MBGL_RENDER', os.path.expanduser('~/Code/maplibre-native-terrain/build/bin/mbgl-render'))
CACHE = os.path.expanduser('~/.strata360/flyover-cache.db')

# film seconds, km travelled, zoom, pitch for a start at `km0`: overview (about 2.5 km/s), working pace, and a slow close pass
PRESETS = {
    'fast': lambda km0: [dict(t=0, km=km0, zoom=11.5, pitch=55), dict(t=20, km=km0 + 50, zoom=11.5, pitch=55)],
    'medium': lambda km0: [dict(t=0, km=km0, zoom=13, pitch=45), dict(t=8, km=km0 + 3, zoom=13, pitch=45)],
    'slow': lambda km0: [dict(t=0, km=km0, zoom=14.5, pitch=30), dict(t=10, km=km0 + 0.5, zoom=14.5, pitch=30)],
    # slow down from overview into a close pass, then back out: zoom and pitch fall together
    'dive': lambda km0: [dict(t=0, km=km0, zoom=11.5, pitch=55), dict(t=4, km=km0 + 6, zoom=11.5, pitch=55),
                         dict(t=8, km=km0 + 6.6, zoom=14.5, pitch=30), dict(t=14, km=km0 + 7.1, zoom=14.5, pitch=30),
                         dict(t=18, km=km0 + 12, zoom=11.5, pitch=55)],
}


def load_route(tr, step_m=10):
    ok = np.isfinite(tr['lat']) & np.isfinite(tr['dist']) & np.isfinite(tr['alt'])
    d = tr['dist'][ok]; keep = np.r_[True, np.diff(d) > 0]
    d, lat, lon, alt = d[keep], tr['lat'][ok][keep], tr['lon'][ok][keep], tr['alt'][ok][keep]
    g = np.arange(d[0], d[-1], step_m)
    return g, np.interp(g, d, lat), np.interp(g, d, lon), np.interp(g, d, alt)


def chord_bearing(g, lat, lon, c, back_m, ahead_m):
    """Bearing of the straight line from `back_m` behind `c` to `ahead_m` ahead (metres along the route)."""
    a, b = np.interp([c - back_m, c + ahead_m], g, lat), np.interp([c - back_m, c + ahead_m], g, lon)
    return np.degrees(np.arctan2((b[1] - b[0]) * 111320 * np.cos(np.radians(a.mean())), (a[1] - a[0]) * 111320))


def fit_bearing(g, lat, lon, c, reach_m, cone=50.0):
    """The bearing that keeps most of the coming route in view: the mode of the bearings (seen from the runner) of route points up to `reach_m`
    ahead, nearer points counting more, each point scoring by how far inside a +-`cone` degree view it falls. Hairpins pull it only as far as they weigh."""
    d = np.linspace(reach_m * 0.1, reach_m, 24)
    la, lo = np.interp(c + d, g, lat), np.interp(c + d, g, lon); la0, lo0 = np.interp(c, g, lat), np.interp(c, g, lon)
    pts = np.degrees(np.arctan2((lo - lo0) * np.cos(np.radians(la0)), la - la0))
    w = np.exp(-d / (0.6 * reach_m))
    cand = np.arange(0, 360, 3.0)
    diff = (pts[None, :] - cand[:, None] + 180) % 360 - 180
    score = (w[None, :] * np.clip(1 - (diff / cone) ** 2, 0, None)).sum(1)
    return cand[int(np.argmax(score))]


def smooth_bearings(b, fps, sigma_s=3.0, max_dps=6.0):  # (used with --sigma / --rate: see main)
    """Gaussian smoothing of the (unwrapped) heading over time, then a turn-rate limit, so the camera swings slowly."""
    u = np.unwrap(np.radians(b)); u = np.degrees(u)
    k = np.arange(-int(4 * sigma_s * fps), int(4 * sigma_s * fps) + 1) / (sigma_s * fps)
    w = np.exp(-0.5 * k ** 2); w /= w.sum(); pad = len(w) // 2
    sm = np.convolve(np.r_[[u[0]] * pad, u, [u[-1]] * pad], w, 'valid')
    out = [sm[0]]
    for x in sm[1:]: out.append(out[-1] + np.clip(x - out[-1], -max_dps / fps, max_dps / fps))
    return np.array(out) % 360


def offsets(g, lat, lon, runner, ks, brgs, reach=300.0):
    """Largest angle (degrees) between the camera heading and any route point from the runner to `reach * k` metres ahead, per frame: how close
    the coming route gets to the side of the view."""
    out = []
    for r, k, b in zip(runner, ks, brgs):
        d = np.linspace(40 * k, reach * k, 20); la0, lo0 = np.interp(r, g, lat), np.interp(r, g, lon)
        pts = np.degrees(np.arctan2((np.interp(r + d, g, lon) - lo0) * np.cos(np.radians(la0)), np.interp(r + d, g, lat) - la0))
        out.append(np.abs((pts - b + 180) % 360 - 180).max())
    return np.array(out)


def contain(brgs, targets, limit=22.0):
    """Pull the smoothed heading back to within `limit` degrees of the (lightly smoothed) fitted target where it has fallen behind a sustained
    turn: the camera stays calm in wiggles, and only a real change of direction is allowed to move it faster than the rate limit."""
    return (targets + np.clip((brgs - targets + 180) % 360 - 180, -limit, limit)) % 360


FOV = 0.6435011  # mbgl's default vertical field of view (radians)


def project(g, lat, lon, alt, route_m, centre, bearing, zoom, pitch, size, exag):
    """Where points of the route (metres along it) fall on the screen (pixels), through the camera mbgl builds from centre / zoom / bearing / pitch:
    a pinhole `FOV` camera looking at `centre` = (lat, lon, height) from behind and above (at the distance that makes one tile pixel one map pixel),
    pitch measured from straight down. `size` = (width, height) of the rendered picture before the bottom crop. Returns x, y, and whether the
    point is in front of the camera."""
    la0, lo0, h0 = centre; W, H = size; b, p = np.radians(bearing), np.radians(pitch)
    mpp = 40075016.686 * np.cos(np.radians(la0)) / (512 * 2 ** zoom)  # ground metres per pixel
    F = 0.5 * H / np.tan(FOV / 2); dist = F * mpp
    e = (np.interp(route_m, g, lon) - lo0) * 111320 * np.cos(np.radians(la0)); n = (np.interp(route_m, g, lat) - la0) * 111320
    u = np.interp(route_m, g, alt) * exag - h0
    f = np.array([np.sin(b) * np.sin(p), np.cos(b) * np.sin(p), -np.cos(p)]); r = np.array([np.cos(b), -np.sin(b), 0.0]); up = np.cross(r, f)
    v = np.stack([e, n, u], 1) - (-f * dist)  # from the camera (which is `dist` behind the centre along the view direction)
    depth = v @ f
    with np.errstate(divide='ignore', invalid='ignore'):
        x = W / 2 + F * (v @ r) / depth; y = H / 2 - F * (v @ up) / depth
    return x, y, depth > 0


def edge_margin(x, y, ok, W, H_visible):
    """Distance of each visible-region point to the nearest side or the bottom of the picture, as a fraction of the width (negative: outside); points behind the camera
    count as outside."""
    m = np.minimum.reduce([x, W - x, H_visible - y]) / W  # not the top edge: the route runs off towards the horizon there, which is natural
    return np.where(ok, m, -1.0)


def fit_bearing_screen(g, lat, lon, alt, runner, centre, zoom, pitch, k, size, exag, visible_h, reach, margin=0.07):
    """The bearing (tried every 3 degrees) that keeps the most of the route, from just behind the runner to `reach * k` metres ahead, inside the
    picture with a `margin` (fraction of the width) to spare, nearer route counting more."""
    d = np.linspace(-60 * k, reach * k, 28); w = np.exp(-np.clip(d, 0, None) / (0.6 * reach * k))
    cand = np.arange(0, 360, 3.0); score = np.empty(len(cand))
    for i, c in enumerate(cand):
        x, y, ok = project(g, lat, lon, alt, runner + d, centre, c, zoom, pitch, size, exag)
        score[i] = (w * (edge_margin(x, y, ok, size[0], visible_h) > margin)).sum()
    # among bearings that keep (nearly) as much of the route on the picture as the best, the one nearest the route's own direction
    good = cand[score >= 0.97 * score.max()]; pref = fit_bearing(g, lat, lon, runner, reach * k)
    return good[np.argmin(np.abs((good - pref + 180) % 360 - 180))]


def optimise_centre(g, lat, lon, alt, runner, centres, brgs, ks, zs, ps, size, exag, visible_h, reach, margin, fps, sigma_s, lead_s=2.0):
    """Move the look-at point, not the heading, to give the route room: per frame, among forward / sideways offsets of the nominal centre (in the
    camera's own frame) the smallest one that keeps the route from just behind the runner to `reach * k` ahead at least `margin` (fraction of the
    width) from the sides and bottom, or the roomiest if none does. The offsets are then smoothed over `sigma_s` seconds, so the camera glides."""
    fwd_opts, lat_opts = np.array([-400, -300, -200, -100, 0, 150, 300, 500, 700]), np.array([0, -150, 150, -300, 300, -500, 500])  # metres at zoom 13.3, times k
    offs = np.zeros((len(runner), 2))
    for i, (r, c, b, k, z, p) in enumerate(zip(runner, centres, brgs, ks, zs, ps)):
        d = np.linspace(-60 * k, reach * k, 40); th = np.radians(b); f = np.array([np.sin(th), np.cos(th)]); rt = np.array([np.cos(th), -np.sin(th)])
        best, best_m, best_cost = (0.0, 0.0), -9.0, None
        for fo in fwd_opts:
            for la_ in lat_opts:
                e, n = (fo * f + la_ * rt) * k
                cc = (c[0] + n / 111320, c[1] + e / (111320 * np.cos(np.radians(c[0]))), c[2])
                x, y, ok = project(g, lat, lon, alt, r + d, cc, b, z, p, size, exag)
                m = edge_margin(x, y, ok, size[0], visible_h).min(); cost = abs(fo) + 1.5 * abs(la_)
                if m >= margin and (best_cost is None or cost < best_cost): best, best_m, best_cost = (fo * k, la_ * k), m, cost
                elif best_cost is None and m > best_m: best, best_m = (fo * k, la_ * k), m
        offs[i] = best
    w = int(lead_s * fps)  # start each move early: the largest offset asked for within +-lead_s seconds, then smoothed
    wide = lambda x: np.array([x[max(0, i - w): i + w + 1][np.argmax(np.abs(x[max(0, i - w): i + w + 1]))] for i in range(len(x))])
    offs = np.stack([gauss(wide(offs[:, 0]), fps, sigma_s), gauss(wide(offs[:, 1]), fps, sigma_s)], 1)
    out = []
    for (c, b, o) in zip(centres, brgs, offs):
        th = np.radians(b); e, n = o[0] * np.array([np.sin(th), np.cos(th)]) + o[1] * np.array([np.cos(th), -np.sin(th)])
        out.append((c[0] + n / 111320, c[1] + e / (111320 * np.cos(np.radians(c[0]))), c[2]))
    return out, offs


def screen_stats(g, lat, lon, alt, runner, centres, ks, zs, ps, brgs, size, exag, visible_h, reach):
    """Per frame, the smallest edge margin (fraction of the width) over the route from just behind the runner to `reach * k` ahead."""
    out = []
    for r, c, k, z, p, b in zip(runner, centres, ks, zs, ps, brgs):
        d = np.linspace(-60 * k, reach * k, 40); x, y, ok = project(g, lat, lon, alt, r + d, c, b, z, p, size, exag)
        out.append(edge_margin(x, y, ok, size[0], visible_h).min())
    return np.array(out)


def deadband(b, width):
    """Backlash: the output holds still while the input stays within +-`width` degrees of it, and is only pushed when the input goes past that.
    Swings smaller than the band (a heading that goes left, then right again) are ignored; a real change of direction moves it, a band's width behind."""
    u = np.degrees(np.unwrap(np.radians(b))); out = np.empty_like(u); cur = u[0]
    for i, x in enumerate(u):
        cur = min(max(cur, x - width), x + width); out[i] = cur
    return out % 360


def travel(b):
    """Total degrees the heading turns, and the number of times it reverses direction (by more than 1 degree)."""
    d = np.diff(np.degrees(np.unwrap(np.radians(b)))); d = d[np.abs(d) > 1e-3]
    sign = np.sign(d); return float(np.abs(d).sum()), int((np.diff(sign[sign != 0]) != 0).sum())


def gauss(x, fps, sigma_s):
    """Gaussian low-pass over time (edges held), so back-and-forth moves cancel instead of being followed."""
    k = np.arange(-int(3 * sigma_s * fps), int(3 * sigma_s * fps) + 1) / (sigma_s * fps); w = np.exp(-0.5 * k ** 2); w /= w.sum(); pad = len(w) // 2
    return np.convolve(np.r_[[x[0]] * pad, x, [x[-1]] * pad], w, 'valid')


def marker(lat0, lon0, brg, size_m, fid):
    """Arrow polygon (tip ahead, notched tail) at a point, `size_m` long, as lon/lat: lies on the ground so it drapes on the terrain."""
    th = np.radians(brg); f = np.array([np.sin(th), np.cos(th)]); r = np.array([np.cos(th), -np.sin(th)])  # (east, north) unit vectors: forward, right
    shape = [(1.0, 0), (-0.7, 0.6), (-0.35, 0), (-0.7, -0.6)]  # (forward, right) in units of size_m / 2
    ring = [(lon0 + (size_m / 2) * (x * f[0] + y * r[0]) / (111320 * np.cos(np.radians(lat0))), lat0 + (size_m / 2) * (x * f[1] + y * r[1]) / 111320) for x, y in shape]
    return {'type': 'Feature', 'id': fid, 'geometry': {'type': 'Polygon', 'coordinates': [ring + [ring[0]]]}}


def camera_curves(shots):
    t = np.array([s['t'] for s in shots], float)
    f = lambda key: PchipInterpolator(t, [s[key] for s in shots])  # monotone: no overshoot, so the camera never runs backwards
    return t[-1], f('km'), f('zoom'), f('pitch')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('fit'); ap.add_argument('--preset', choices=PRESETS); ap.add_argument('--shots', help='JSON list of keyframes {t, km, zoom, pitch}')
    ap.add_argument('--start-km', type=float, default=20); ap.add_argument('--fps', type=float, default=25)
    ap.add_argument('--imagery', default='esri'); ap.add_argument('--exaggeration', type=float, default=1.5)
    ap.add_argument('--width', type=int, default=1280); ap.add_argument('--height', type=int, default=720)
    ap.add_argument('--max-seconds', type=float, help='render only the first seconds (a quick look)')
    ap.add_argument('--dry-run', action='store_true', help='work out the camera and print its statistics, render nothing'); ap.add_argument('--fit-mode', choices=['screen', 'cone'], default='screen'); ap.add_argument('--margin', type=float, default=0.12, help='fit: edge margin, fraction of width'); ap.add_argument('--reach', type=float, default=1500, help='metres x k ahead the fit and the check look'); ap.add_argument('--cone', type=float, default=50); ap.add_argument('--sigma', type=float, default=4.5, help='heading smoothing, seconds'); ap.add_argument('--rate', type=float, default=5.0, help='max turn, degrees/s'); ap.add_argument('--dead', type=float, default=15.0, help='dead-band, degrees: swings smaller than this are ignored'); ap.add_argument('--no-pan', dest='pan', action='store_false', help='do not move the look-at point (forward / sideways) to give the route room'); ap.add_argument('--pan-sigma', type=float, default=2.0, help='smoothing of that movement, seconds'); ap.add_argument('--verbose', action='store_true'); ap.add_argument('--no-route', action='store_true'); ap.add_argument('--out', default='flyover.mp4')
    a = ap.parse_args()
    shots = json.load(open(a.shots)) if a.shots else PRESETS[a.preset or 'medium'](a.start_km)
    dur, km_at, zoom_at, pitch_at = camera_curves(shots)
    if a.max_seconds: dur = min(dur, a.max_seconds)
    g, lat, lon, alt = load_route(track.load(a.fit))
    km = lambda t: float(km_at(t)) * 1000
    lo_m, hi_m = km(0), km(dur)
    st = style(a.imagery, a.exaggeration)
    if not a.no_route:
        i0, i1 = np.searchsorted(g, [lo_m - 500, hi_m + 3000]); sl = slice(i0, i1)
        st['sources']['route'] = {'type': 'geojson', 'data': {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': np.c_[lon[sl], lat[sl]].tolist()}}}
        st['layers'].append({'id': 'route-casing', 'type': 'line', 'source': 'route', 'paint': {'line-color': '#fff', 'line-width': ['interpolate', ['exponential', 2], ['zoom'], 10, 5, 15, 12]}})
        st['layers'].append({'id': 'route', 'type': 'line', 'source': 'route', 'paint': {'line-color': '#ff3b1f', 'line-width': ['interpolate', ['exponential', 2], ['zoom'], 10, 3, 15, 7]}})
    st['sources']['me'] = {'type': 'geojson', 'data': {'type': 'FeatureCollection', 'features': []}}
    st['layers'] += [{'id': 'me-halo', 'type': 'fill', 'source': 'me', 'filter': ['==', ['id'], 0], 'paint': {'fill-color': '#ffffff', 'fill-opacity': 1}},
                     {'id': 'me', 'type': 'fill', 'source': 'me', 'filter': ['==', ['id'], 1], 'paint': {'fill-color': '#1e6bff', 'fill-opacity': 1}}]
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    n = int(dur * a.fps)
    ff = None if a.dry_run else subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(a.fps), '-i', '-', '-vf', f'crop={a.width}:{a.height}:0:0', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', a.out],
                          stdin=subprocess.PIPE)
    ts = np.arange(n) / a.fps; zs = np.array([float(zoom_at(t)) for t in ts]); ks = 2 ** (13.3 - zs); ps = np.array([float(pitch_at(t)) for t in ts])
    runner = np.array([km(t) for t in ts])
    cs = runner + 250 * ks  # look-at point per frame, ahead by an amount that follows the zoom; its position is smoothed over time
    clat = gauss(np.array([np.interp(np.linspace(c - 150 * k, c + 150 * k, 9), g, lat).mean() for c, k in zip(cs, ks)]), a.fps, 2.0)
    clon = gauss(np.array([np.interp(np.linspace(c - 150 * k, c + 150 * k, 9), g, lon).mean() for c, k in zip(cs, ks)]), a.fps, 2.0)
    cel = gauss(np.interp(cs, g, alt) * a.exaggeration, a.fps, 2.0)
    centres = list(zip(clat, clon, cel)); size = (a.width, a.height / 0.88)
    # heading: the bearing that keeps the coming route on the picture (through the real camera), then smoothed in time
    if a.fit_mode == 'screen':
        raw = np.array([fit_bearing_screen(g, lat, lon, alt, r, c, z, p, k, size, a.exaggeration, a.height, a.reach, a.margin) for r, c, z, p, k in zip(runner, centres, zs, ps, ks)])
    else:
        raw = np.array([fit_bearing(g, lat, lon, r, a.reach * k, a.cone) for r, k in zip(runner, ks)])
    smooth = smooth_bearings(raw, a.fps, a.sigma, a.rate)
    brgs = smooth_bearings(deadband(smooth, a.dead), a.fps, a.sigma / 3, a.rate) if a.dead else smooth
    mg0 = screen_stats(g, lat, lon, alt, runner, centres, ks, zs, ps, brgs, size, a.exaggeration, a.height, a.reach)
    if a.pan:
        centres, offs = optimise_centre(g, lat, lon, alt, runner, centres, brgs, ks, zs, ps, size, a.exaggeration, a.height, a.reach, a.margin, a.fps, a.pan_sigma)
        clat, clon, cel = (np.array([c[j] for c in centres]) for j in range(3))
    mg = screen_stats(g, lat, lon, alt, runner, centres, ks, zs, ps, brgs, size, a.exaggeration, a.height, a.reach)
    tv, rev = travel(brgs)
    if a.pan: print(f'before moving the centre: closest to an edge {np.percentile(mg0, 5):+.1%} (5th percentile), worst {mg0.min():+.1%}')
    if a.dry_run and a.verbose:
        i = int(np.argmin(mg)); d = np.linspace(-60 * ks[i], a.reach * ks[i], 40); x, y, ok = project(g, lat, lon, alt, runner[i] + d, centres[i], brgs[i], zs[i], ps[i], size, a.exaggeration)
        print(f'worst frame {i} (t={ts[i]:.1f}s zoom {zs[i]:.1f} pitch {ps[i]:.0f} bearing {brgs[i]:.0f}): route points x={np.round(x[::4])}, y={np.round(y[::4])} in a {size[0]:.0f}x{a.height:.0f} picture')
        print('margin by second:', [f'{ts[i]:.0f}s z{zs[i]:.1f} p{ps[i]:.0f} b{brgs[i]:.0f} m{mg[i]:+.0%}' for i in range(0, n, int(a.fps))])
    print(f'heading: turns {tv:.0f} deg in {rev} reversals, peak {np.abs(np.diff(np.unwrap(np.radians(brgs)))).max() * a.fps * 57.3:.1f} deg/s; '
          f'route (from just behind the runner to {a.reach:.0f} m x k ahead) on the picture: closest to an edge {np.percentile(mg, 5):+.1%} of the width (5th percentile), '
          f'worst {mg.min():+.1%}; within 5% of an edge or off it in {np.mean(mg < 0.05):.0%} of frames, off the picture in {np.mean(mg < 0):.0%}')
    if a.dry_run: return
    with tempfile.TemporaryDirectory() as tmp:
        sp = os.path.join(tmp, 'style.json'); png = os.path.join(tmp, 'f.png')
        for i in range(n):
            z, p, k, r, brg = zs[i], float(pitch_at(ts[i])), ks[i], runner[i], brgs[i]
            la, lo, ce = clat[i], clon[i], cel[i]  # camera is placed relative to the centre height
            st['sources']['me']['data'] = {'type': 'FeatureCollection', 'features': [
                marker(np.interp(r, g, lat), np.interp(r, g, lon), chord_bearing(g, lat, lon, r, 120 * k, 120 * k), 190 * k * 1.25, 0),
                marker(np.interp(r, g, lat), np.interp(r, g, lon), chord_bearing(g, lat, lon, r, 120 * k, 120 * k), 190 * k, 1)]}
            json.dump(st, open(sp, 'w'))
            res = subprocess.run(['nice', '-n', '19', MBGL, '--backend=metal', '-s', sp, '-c', CACHE, '-o', png, '-x', f'{lo:.6f}', '-y', f'{la:.6f}',
                                  '-A', f'{ce:.1f}', '-z', f'{z:.3f}', '-b', f'{brg:.2f}', '-p', f'{p:.2f}', '-w', str(a.width), '-h', str(int(a.height / 0.88))],
                                 capture_output=True, text=True)
            if res.returncode: sys.exit(res.stderr)
            ff.stdin.write(open(png, 'rb').read()); print(f'\rframe {i + 1}/{n}', end='', flush=True)
    ff.stdin.close(); ff.wait(); print('\n', a.out)


if __name__ == '__main__':
    main()
