"""Data for the race map and charts (implementation plan, Milestone M): the track decimated for a chart, the line for the part of the map in view, and where each clip sits on the track.

series(tr, points)      -> elapsed time, distance, altitude (with the lowest and highest of each bin, so peaks survive), pace of the moving part, share of the bin spent moving, heart rate;
line(tr, bbox, max)     -> [lat], [lon], [elapsed s] of the track inside a box (or the whole track), at most `max` points, in order;
clips(tr, spans, tz)    -> per clip: position at its middle, the stretch of track it covers, and the facts the hover card shows.
`tr` is gps.track.load's dict (t, lat, lon, alt, speed, hr, dist); times are epoch seconds, elapsed times are seconds since the first sample."""
import datetime as dt, glob, json, os
import numpy as np

MOVING_MS = 0.5            # faster than this is moving (gps/overview.py)
MIN_MOVING = 0.2           # a bin with less moving time than this share has no pace (stopped)
SMOOTH_S = 1200.0          # pace is the median over about this long (a bin of a few minutes is noisy over an 80 hour race), and a stop stays a gap


def _iso(t): return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _r(x, n): return None if x is None or not np.isfinite(x) else round(float(x), n)


def load_spans(folder):
    """The clips of a project as [{id, t0, t1}] in epoch seconds (clip.json, times already corrected by the camera clock), in time order."""
    from strata360.pipeline import config
    out = []
    for p in sorted(glob.glob(os.path.join(config.race_dir(folder), 'clips', '*', 'clip.json'))):
        try:
            c = json.load(open(p)); t0 = dt.datetime.fromisoformat(c['time']['start_utc'].replace('Z', '+00:00')).timestamp(); out.append(dict(id=c['clip_id'], t0=t0, t1=t0 + c['video']['source_frames'] / c['video']['nominal_fps']))
        except (OSError, ValueError, KeyError): continue
    return sorted(out, key=lambda s: s['t0'])


def prepare(tr):
    """The track with distance and speed filled in when the file has none (a GPX has positions and times only): distance along the path, speed over about 10 s. A FIT's own values are kept."""
    out = dict(tr); T = tr['t']; ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon'])
    if np.isfinite(tr['dist']).any() and np.isfinite(tr['speed']).any(): return out
    la, lo = np.radians(tr['lat'][ok]), np.radians(tr['lon'][ok]); step = np.zeros(len(la))
    if len(la) > 1: a = np.sin(np.diff(la) / 2) ** 2 + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(np.diff(lo) / 2) ** 2; step[1:] = 2 * 6371000.0 * np.arcsin(np.sqrt(a))
    d = np.cumsum(step)
    if not np.isfinite(tr['dist']).any(): full = np.full(len(T), np.nan); full[ok] = d; out['dist'] = np.interp(T, T[ok], d) if ok.any() else full
    if not np.isfinite(tr['speed']).any() and ok.any():
        dist = out['dist']; k = max(int(round(10.0 / max(float(np.median(np.diff(T))), 1e-3))), 1); lag = np.arange(len(T)) - k; lag[lag < 0] = 0
        dt_ = np.maximum(T - T[lag], 1e-3); out['speed'] = np.where(T - T[lag] > 0, (dist - dist[lag]) / dt_, np.nan)
    return out


def smooth(values, width):
    """Rolling median over `width` bins (odd) that ignores gaps (None) and leaves a gap where the value was a gap."""
    if width <= 1: return list(values)
    h = width // 2; out = []
    for i, v in enumerate(values):
        w = [x for x in values[max(i - h, 0):i + h + 1] if x is not None]
        out.append(None if v is None or not w else float(np.median(w)))
    return out


def series(tr, points=2000, smooth_s=SMOOTH_S):
    T = tr['t']; n = len(T); k = int(max(min(points, n), 1)); edges = np.linspace(0, n, k + 1).astype(int); out = {key: [] for key in ('t', 'km', 'alt', 'alt_lo', 'alt_hi', 'pace', 'moving', 'hr')}
    ok_d = np.isfinite(tr['dist'])
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a: b = min(a + 1, n)
        sl = slice(a, b); out['t'].append(_r(float(np.mean(T[sl]) - T[0]), 1))
        d = tr['dist'][sl]; d = d[np.isfinite(d)]; out['km'].append(_r(float(d[-1]) / 1000.0, 3) if len(d) else None)
        alt = tr['alt'][sl]; alt = alt[np.isfinite(alt)]
        out['alt'].append(_r(float(alt.mean()), 1) if len(alt) else None); out['alt_lo'].append(_r(float(alt.min()), 1) if len(alt) else None); out['alt_hi'].append(_r(float(alt.max()), 1) if len(alt) else None)
        sp = tr['speed'][sl]; mv = np.isfinite(sp) & (sp > MOVING_MS); share = float(mv.mean()) if len(sp) else 0.0; out['moving'].append(round(share, 2))
        out['pace'].append(_r(float(np.median(1000.0 / sp[mv]) / 60.0), 2) if share >= MIN_MOVING and mv.any() else None)
        hr = tr['hr'][sl]; hr = hr[np.isfinite(hr)]; out['hr'].append(_r(float(hr.mean()), 0) if len(hr) else None)
    del ok_d
    bin_s = float(T[-1] - T[0]) / max(k, 1); width = int(round(smooth_s / max(bin_s, 1e-9))) | 1
    out['pace'] = [None if v is None else round(v, 2) for v in smooth(out['pace'], width if width > 1 else 1)]
    return dict(points=k, start_utc=_iso(T[0]), end_utc=_iso(T[-1]), duration_s=round(float(T[-1] - T[0])), distance_km=_r(float(np.nanmax(tr['dist'])) / 1000.0, 1) if np.isfinite(tr['dist']).any() else None, **out)


def line(tr, bbox=None, max_points=3000):
    """The track inside `bbox` = (lat0, lon0, lat1, lon1), or all of it, as at most `max_points` points. A point whose neighbour is inside is kept, so the line leaves and enters the box without a gap."""
    ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon'])
    if bbox is not None:
        la0, lo0, la1, lo1 = bbox; inside = ok & (tr['lat'] >= la0) & (tr['lat'] <= la1) & (tr['lon'] >= lo0) & (tr['lon'] <= lo1); near = inside.copy(); near[1:] |= inside[:-1]; near[:-1] |= inside[1:]; ok = ok & near
    idx = np.flatnonzero(ok)
    if len(idx) > max_points: idx = idx[np.unique(np.linspace(0, len(idx) - 1, max_points).astype(int))]
    return dict(lat=[round(float(x), 5) for x in tr['lat'][idx]], lon=[round(float(x), 5) for x in tr['lon'][idx]], t=[round(float(x - tr['t'][0]), 1) for x in tr['t'][idx]])


def _interp(tr, key, t):
    v = tr[key]; ok = np.isfinite(v)
    return float(np.interp(t, tr['t'][ok], v[ok])) if ok.any() else None


def clips(tr, spans, tz='Europe/Brussels', stretch_points=60, sun_of=None):
    """Where each clip is on the track. `covered` is False for a clip with no track under it (before the start, after the finish). `sun_of(clip id)` gives the clip's stored sun field (gps/sun.py, the `sun` stage) or None;
    when it does, the clip's daylight and sun elevation are that field, not worked out again."""
    from strata360.gps import context as X
    T = tr['t']; out = []
    for s in spans:
        mid = 0.5 * (s['t0'] + s['t1']); ctx = X.context_at(tr, s['t0'], s['t1'], tz); sun = sun_of(s['id']) if sun_of else None
        if ctx.get('covered') and sun and sun.get('covered'): ctx = dict(ctx, daylight=sun['daylight'], sun_elevation_deg=sun['elevation_deg'])
        item = dict(id=s['id'], start_utc=_iso(s['t0']), end_utc=_iso(s['t1']), duration_s=round(s['t1'] - s['t0'], 1), covered=bool(ctx.get('covered')))
        if item['covered'] and T[0] <= mid <= T[-1]:
            i = np.flatnonzero((T >= s['t0']) & (T <= s['t1'])); i = i[np.isfinite(tr['lat'][i]) & np.isfinite(tr['lon'][i])]
            if len(i) > stretch_points: i = i[np.unique(np.linspace(0, len(i) - 1, stretch_points).astype(int))]
            pts = [[round(float(tr['lat'][j]), 5), round(float(tr['lon'][j]), 5)] for j in i]
            if len(pts) < 2: p0 = [round(_interp(tr, 'lat', mid), 5), round(_interp(tr, 'lon', mid), 5)]; pts = [p0, p0]
            item.update(t_mid=round(mid - float(T[0]), 1), t0=round(s['t0'] - float(T[0]), 1), t1=round(s['t1'] - float(T[0]), 1), lat=round(_interp(tr, 'lat', mid), 5), lon=round(_interp(tr, 'lon', mid), 5), stretch=pts,
                        facts=dict(local=f"{ctx['local_date']} {ctx['local_time']}", daylight=ctx.get('daylight'), elapsed_h=ctx.get('elapsed_h'), distance_km=ctx.get('distance_km'), percent=ctx.get('percent_of_distance'), pace_min_km=ctx.get('pace_min_per_km') if ctx.get('moving') else None,
                                   gradient_pct=ctx.get('gradient_pct'), altitude_m=ctx.get('altitude_m'), heart_rate=ctx.get('heart_rate'), text=X.describe(ctx)))
        out.append(item)
    return out
