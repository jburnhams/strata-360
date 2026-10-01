"""Overview of the race track for the GUI: a simplified polyline for a map, and the main statistics."""
import datetime as dt, os
import numpy as np
from strata360.gps import track


def _iso(t): return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def ascent_descent(alt, hysteresis=4.0):
    """Total climb and descent (m) of an altitude series, ignoring wiggles smaller than `hysteresis` metres."""
    a = alt[np.isfinite(alt)]
    if len(a) < 2: return 0.0, 0.0
    up = down = 0.0; ref = a[0]
    for v in a[1:]:
        if v - ref >= hysteresis: up += v - ref; ref = v
        elif ref - v >= hysteresis: down += ref - v; ref = v
    return up, down


def overview(path, points=400):
    tr = track.load(path); ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon']); T = tr['t']
    if not ok.any(): return dict(present=True, error='the file has no positions')
    lat, lon = tr['lat'][ok], tr['lon'][ok]; idx = np.unique(np.linspace(0, len(lat) - 1, points).astype(int))
    up, down = ascent_descent(tr['alt']); sp = tr['speed']; mv = np.isfinite(sp) & (sp > 0.5); dist = float(np.nanmax(tr['dist'])) if np.isfinite(tr['dist']).any() else None
    dt_ = np.diff(T); gaps = int((dt_ > 10).sum()); hr = tr['hr'][np.isfinite(tr['hr'])]
    return dict(present=True, file=os.path.basename(path), samples=int(len(T)), start_utc=_iso(T[0]), end_utc=_iso(T[-1]), duration_h=round(float((T[-1] - T[0]) / 3600.0), 2),
                moving_h=round(float(mv.sum() / 3600.0), 2), distance_km=None if dist is None else round(dist / 1000.0, 1), ascent_m=round(up), descent_m=round(down),
                avg_speed_kmh=None if not mv.any() else round(float(np.mean(sp[mv])) * 3.6, 1), avg_pace_min_km=None if not mv.any() else round(1000.0 / float(np.mean(sp[mv])) / 60.0, 2),
                max_altitude_m=None if not np.isfinite(tr['alt']).any() else round(float(np.nanmax(tr['alt']))), min_altitude_m=None if not np.isfinite(tr['alt']).any() else round(float(np.nanmin(tr['alt']))),
                avg_hr=None if not len(hr) else round(float(np.mean(hr))), max_hr=None if not len(hr) else round(float(np.max(hr))), gaps_over_10s=gaps,
                bbox=[float(lat.min()), float(lon.min()), float(lat.max()), float(lon.max())], line=[[round(float(lat[i]), 5), round(float(lon[i]), 5)] for i in idx])
