"""A point camera (README 16, milestone K): a virtual camera that keeps one place in frame while a clip or a street view section moves past it.

You click a point on the map near the path of a clip or a street view section; the camera looks at that point from wherever the runner (or the street view car) is, panning round as the path goes by and zooming with the distance (wide when close, where the
view swings fast, tighter when far). The stretch it covers is `before_m` metres of path before the closest approach and `after_m` after it. It is a generated shot of its own (edit/synthetic.py kind `pointcam`, label C1, C2 ...): a preview is rendered on demand
(`render_preview`), and a camera marked possible or must include is offered to the planner like a photo or a street view section (script_pack.camera_clips, edit/pointcam_clip.py).

  <race>/pointcams.json   {cams: [{id, label, source: {kind: 'clip', clip} | {kind: 'streetview', key}, lat, lon, height_m, before_m, after_m, fov_near, fov_far, smooth_s, use: '' | 'possible' | 'must', t_pass, created}], next}

The geometry is plain: a path is `poly = dict(lat, lon, t)` (arrays; t in epoch seconds), the camera's position at a moment is the smoothed path there, `samples(poly, cam)` gives per output step the distance and compass bearing to the point, the pitch
and the field of view, and `keyframes` turns that into a camera path for the renderer (a clip: yaw relative to the clip's own heading, calibrated against the GPS course; a street view section uses the compass bearing directly)."""
import datetime as dt, json, math, os

import numpy as np
from scipy.ndimage import gaussian_filter1d

FILE = 'pointcams.json'
EARTH = 111320.0                  # metres per degree of latitude
CAM_H = 2.2                       # the camera's height above the ground: a pole held by a runner (street view cars are a little higher: close enough)
STEP_S = 0.2                      # the path is worked out every 0.2 s (the renderer interpolates)
DEFAULTS = dict(height_m=0.0, before_m=40.0, after_m=40.0, fov_near=95.0, fov_far=55.0, smooth_s=0.8, use='')
LIMITS = dict(height_m=(0.0, 300.0), before_m=(5.0, 400.0), after_m=(5.0, 400.0), fov_near=(30.0, 130.0), fov_far=(20.0, 130.0), smooth_s=(0.0, 4.0))
MAX_OFF_PATH_M = 400.0            # a click further than this from the path is not "near the path"
MIN_S, MAX_S = 2.0, 60.0          # the shortest and longest a point camera shot is (a window shorter than MIN_S is widened, one longer than MAX_S trimmed round the closest approach)
POS_SMOOTH_S = 1.5                # the GPS positions are smoothed this much (seconds) before the camera looks from them: the fixes jitter by a few metres, which is a swing of the view when the point is close
PAN_WARN_DEG_S = 45.0             # a pan faster than this is flagged on the page: the point is passed too close for a smooth shot (move the point further out, or smooth more)


def _iso(t): return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def wrap(a): return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


# ---- the records -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _path(rd): return os.path.join(rd, FILE)


def load(rd):
    try: d = json.load(open(_path(rd)))
    except (OSError, ValueError): d = {}
    d.setdefault('cams', []); d['next'] = int(d.get('next') or 1 + max([int(c['label'][1:]) for c in d['cams']] + [0])); return d


def save(rd, doc):
    os.makedirs(rd, exist_ok=True); p = _path(rd); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(doc, open(tmp, 'w'), indent=1); os.replace(tmp, p); return doc


def get(rd, cid):
    cid = str(cid).upper(); return next((c for c in load(rd)['cams'] if c['id'] == cid), None)


def label_of(cid): return str(cid).upper()
def is_camera_label(label): return str(label).upper().startswith('C') and str(label)[1:].isdigit()


def create(rd, source, lat, lon, t_pass, **fields):
    """A new point camera at (lat, lon) for `source` ({kind: 'clip', clip: id} or {kind: 'streetview', key}); `t_pass` is the moment (epoch s) the path comes closest. Returns it."""
    doc = load(rd); n = doc['next']; cid = f'C{n}'
    cam = dict(DEFAULTS, id=cid, label=cid, source=dict(source), lat=round(float(lat), 6), lon=round(float(lon), 6), t_pass=round(float(t_pass), 2), created=_iso(__import__('time').time()))
    cam.update(check(fields)); doc['cams'].append(cam); doc['next'] = n + 1; save(rd, doc); return cam


def check(fields):
    """The settings in `fields` that are allowed, each held to its limits; ValueError for a value that is not a number or an unknown name."""
    out = {}
    for k, v in fields.items():
        if k == 'use':
            if v not in ('', 'possible', 'must', None): raise ValueError("use: '', 'possible' or 'must'")
            out[k] = v or ''
        elif k in LIMITS:
            try: x = float(v)
            except (TypeError, ValueError): raise ValueError(f'{k}: a number')
            lo, hi = LIMITS[k]; out[k] = round(min(max(x, lo), hi), 2)
        elif k in ('lat', 'lon'): out[k] = round(float(v), 6)
        elif k in ('seconds', 'name'): out[k] = None if v in (None, '') else (round(float(v), 2) if k == 'seconds' else str(v)[:80])
        else: raise ValueError(f'unknown setting {k}')
    return out


def update(rd, cid, **fields):
    doc = load(rd); cam = next((c for c in doc['cams'] if c['id'] == str(cid).upper()), None)
    if cam is None: raise KeyError(cid)
    cam.update(check(fields)); save(rd, doc); return cam


def delete(rd, cid):
    doc = load(rd); n = len(doc['cams']); doc['cams'] = [c for c in doc['cams'] if c['id'] != str(cid).upper()]; save(rd, doc); return len(doc['cams']) < n


# ---- paths ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def poly(lat, lon, t):
    """The path as dict(lat, lon, t) of float arrays in time order, keeping the fixes that have all three."""
    lat, lon, t = (np.asarray(x, float) for x in (lat, lon, t)); ok = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(t); lat, lon, t = lat[ok], lon[ok], t[ok]; o = np.argsort(t, kind='stable'); return dict(lat=lat[o], lon=lon[o], t=t[o])


def to_xy(lat, lon, lat0, lon0):
    """East and north metres of (lat, lon) from (lat0, lon0)."""
    return (np.asarray(lon, float) - lon0) * math.cos(math.radians(lat0)) * EARTH, (np.asarray(lat, float) - lat0) * EARTH


def along(p):
    """Metres along the path at each fix."""
    x, y = to_xy(p['lat'], p['lon'], p['lat'][0], p['lon'][0]); return np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])


def closest(p, lat, lon, t_lo=None, t_hi=None):
    """Where the path comes closest to (lat, lon): dict(t, dist_m, along_m), the nearest point of the line (between the fixes), optionally only within [t_lo, t_hi]. None for a path with fewer than two fixes."""
    if len(p['t']) < 2: return None
    x, y = to_xy(p['lat'], p['lon'], lat, lon); s = along(p); best = None
    for i in range(len(x) - 1):
        if t_lo is not None and p['t'][i + 1] < t_lo: continue
        if t_hi is not None and p['t'][i] > t_hi: continue
        ax, ay, bx, by = x[i], y[i], x[i + 1], y[i + 1]; dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
        dt_ = float(p['t'][i + 1] - p['t'][i]); u_lo = 0.0 if t_lo is None or dt_ <= 0 else min(max((t_lo - p['t'][i]) / dt_, 0.0), 1.0); u_hi = 1.0 if t_hi is None or dt_ <= 0 else min(max((t_hi - p['t'][i]) / dt_, 0.0), 1.0)          # (only the part of the segment inside the time range)
        u = u_lo if L2 <= 1e-9 else min(max(-(ax * dx + ay * dy) / L2, u_lo), u_hi); px, py = ax + u * dx, ay + u * dy; d = math.hypot(px, py)
        if best is None or d < best['dist_m']: best = dict(dist_m=d, t=float(p['t'][i] + u * (p['t'][i + 1] - p['t'][i])), along_m=float(s[i] + u * (s[i + 1] - s[i])))
    return best


def window(p, t_pass, before_m, after_m, t_lo=None, t_hi=None):
    """(t0, t1): the times the path is `before_m` metres before and `after_m` metres after the moment `t_pass`, held to [t_lo, t_hi] (the stretch the clip or section covers) and to MIN_S..MAX_S seconds (a window that is too short is widened round
    the pass, one too long trimmed round it)."""
    s = along(p); sp = float(np.interp(t_pass, p['t'], s)); t0 = float(np.interp(max(sp - before_m, 0.0), s, p['t'])) if len(s) > 1 else float(t_pass); t1 = float(np.interp(min(sp + after_m, s[-1]), s, p['t'])) if len(s) > 1 else float(t_pass)
    lo = p['t'][0] if t_lo is None else max(t_lo, p['t'][0]); hi = p['t'][-1] if t_hi is None else min(t_hi, p['t'][-1]); t0, t1 = max(t0, lo), min(t1, hi)
    if t1 - t0 < MIN_S: m = (t0 + t1) / 2; t0, t1 = max(lo, m - MIN_S / 2), min(hi, m + MIN_S / 2)
    if t1 - t0 > MAX_S: t0, t1 = max(t0, t_pass - MAX_S * (t_pass - t0) / max(t1 - t0, 1e-9)), min(t1, t_pass + MAX_S * (t1 - t_pass) / max(t1 - t0, 1e-9))
    return float(t0), float(t1)


def shrink(p, cam, t0, t1, seconds):
    """The window of a shot of `seconds` (shorter than the whole window): trimmed on both sides in proportion round the closest approach, so the point is always in it."""
    n = t1 - t0
    if seconds >= n - 1e-6 or n <= 0: return t0, t1
    k = max(seconds, MIN_S) / n; tp = min(max(cam['t_pass'], t0), t1); return tp - (tp - t0) * k, tp + (t1 - tp) * k


# ---- the camera ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def positions(p, times):
    """The camera's east/north (metres from the path's first fix) and its course (compass degrees of its motion) at `times`: the fixes smoothed (POS_SMOOTH_S) so a jittering GPS does not swing the view."""
    lat0, lon0 = float(p['lat'][0]), float(p['lon'][0]); x, y = to_xy(p['lat'], p['lon'], lat0, lon0); dt_ = max(float(np.median(np.diff(p['t']))) if len(p['t']) > 1 else 1.0, 0.05)
    sig = POS_SMOOTH_S / dt_; xs, ys = (gaussian_filter1d(a, sig, mode='nearest') if sig > 0.3 and len(a) > 3 else a for a in (x, y)); tx, ty = np.interp(times, p['t'], xs), np.interp(times, p['t'], ys)
    h = 1.0; vx, vy = np.interp(times + h, p['t'], xs) - np.interp(times - h, p['t'], xs), np.interp(times + h, p['t'], ys) - np.interp(times - h, p['t'], ys)
    sp = np.hypot(vx, vy) / (2 * h); course = np.degrees(np.arctan2(vx, vy)); ok = sp > 0.4
    if ok.any() and not ok.all(): course = np.degrees(np.interp(np.arange(len(course)), np.flatnonzero(ok), np.unwrap(np.radians(course[ok]))))     # standing still: the course is whatever it was a moment ago
    return dict(x=tx, y=ty, lat0=lat0, lon0=lon0, course=course % 360.0, speed=sp)


def samples(p, cam, t0, t1, step=STEP_S):
    """The camera over [t0, t1] every `step` seconds: t (epoch), dist (metres to the point), bearing (compass degrees from the camera to the point), rel (the bearing from the direction of travel, -180..180, smoothed), pitch, fov (degrees),
    and course (the camera's direction of travel). The zoom follows the distance: `fov_near` at the closest approach, `fov_far` from twice that distance on, between by distance."""
    n = max(int(round((t1 - t0) / step)), 1) + 1; times = np.linspace(t0, t1, n); pos = positions(p, times); px, py = to_xy(cam['lat'], cam['lon'], pos['lat0'], pos['lon0'])
    dx, dy = px - pos['x'], py - pos['y']; dist = np.hypot(dx, dy); bearing = np.degrees(np.arctan2(dx, dy)) % 360.0
    sig = max(float(cam.get('smooth_s', DEFAULTS['smooth_s'])), 0.0) / ((t1 - t0) / (n - 1) if n > 1 else 1.0)
    rel = np.degrees(np.unwrap(np.radians(wrap(bearing - pos['course'])))) if n > 1 else wrap(bearing - pos['course']); rel = gaussian_filter1d(rel, sig, mode='nearest') if sig > 0.3 and n > 3 else rel
    d_use = np.maximum(dist, 1.0); pitch = np.degrees(np.arctan2(float(cam.get('height_m', 0.0)) - CAM_H, d_use)); pitch = gaussian_filter1d(pitch, sig, mode='nearest') if sig > 0.3 and n > 3 else pitch; pitch = np.clip(pitch, -50.0, 60.0)
    lo = max(float(dist.min()), 1.0); s = np.clip((dist - lo) / lo, 0.0, 1.0)                                       # (tight from twice the closest distance on: a window that never gets much further than its closest point barely zooms)
    fov = np.clip(float(cam['fov_near']) + s * (float(cam['fov_far']) - float(cam['fov_near'])), 20.0, 130.0); fov = gaussian_filter1d(fov, sig, mode='nearest') if sig > 0.3 and n > 3 else fov
    return dict(t=times, dist=dist, bearing=bearing, rel=rel, pitch=pitch, fov=fov, course=pos['course'], speed=pos['speed'])


def at_times(sm, times):
    """The camera of `samples` at other moments `times` (epoch s): dict(bearing, pitch, fov, dist, inside), the bearing continuous (unwrapped) between the samples, `inside` false for a moment outside the stretch the samples cover."""
    t = sm['t']; b = np.degrees(np.unwrap(np.radians(sm['bearing']))); times = np.asarray(times, float)
    return dict(bearing=np.interp(times, t, b) % 360.0, pitch=np.interp(times, t, sm['pitch']), fov=np.interp(times, t, sm['fov']), dist=np.interp(times, t, sm['dist']), inside=(times >= t[0] - 1e-6) & (times <= t[-1] + 1e-6))


def facts(sm, p=None):
    """What the page shows about a camera path: its length in seconds, the closest and furthest the point is, the fastest pan and the field of view range, with warnings."""
    t = sm['t']; secs = float(t[-1] - t[0]); rate = np.abs(np.gradient(sm['rel'], t)) if len(t) > 2 else np.zeros(1); warn = []
    out = dict(seconds=round(secs, 1), min_dist_m=round(float(sm['dist'].min()), 1), max_dist_m=round(float(sm['dist'].max()), 1), max_pan_deg_s=round(float(rate.max()), 1), swing_deg=round(float(np.ptp(sm['rel'])), 0), fov_min=round(float(sm['fov'].min()), 0), fov_max=round(float(sm['fov'].max()), 0))
    if out['max_pan_deg_s'] > PAN_WARN_DEG_S: warn.append(f"the view swings up to {out['max_pan_deg_s']:.0f} degrees a second where the path passes {out['min_dist_m']:.0f} m from the point: raise the smoothing, or pick a point further from the path")
    if out['min_dist_m'] < 4.0: warn.append('the path goes within 4 m of the point: the view cannot stay on it as it passes')
    out['warnings'] = warn; return out


def keyframes(sm, t0, north_offset=0.0, heading=None):
    """The renderer's camera path for a CLIP: keyframes {t (seconds from t0), yaw, pitch, fov} in the world frame. The clip's own heading is the runner's direction in that frame (`heading(clip_t)`, degrees) and the compass bearing of the point is
    turned into it by the calibration `north_offset` (the circular mean of the GPS course minus that heading: how far the frame's zero is from north); without a heading the view stays relative to the runner (`rel`, for heading-follow paths)."""
    ts = sm['t'] - t0; yaw = np.degrees(np.unwrap(np.radians(sm['bearing'] - north_offset)))
    return [dict(t=round(float(t), 3), yaw=round(float(y), 2), pitch=round(float(pp), 2), fov=round(float(f), 1), ease='linear') for t, y, pp, f in zip(ts, yaw, sm['pitch'], sm['fov'])]


def north_offset(course_deg, heading_deg):
    """The calibration between the compass and a clip's frame: the circular mean of (the GPS course - the clip's heading) over moments with both, degrees. 0 when there are none."""
    a = np.radians(np.asarray(course_deg, float) - np.asarray(heading_deg, float)); a = a[np.isfinite(a)]
    return 0.0 if not len(a) else float(np.degrees(np.arctan2(np.sin(a).mean(), np.cos(a).mean())))
