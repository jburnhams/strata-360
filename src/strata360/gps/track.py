"""The race GPS track (Garmin FIT or GPX) as arrays, cached as `.npz` next to the source, plus GPX export.

The arrays drive our own analysis (clock verification, position per clip, race progress) and the overlay on the final film (overlay/series.py); `to_gpx` writes a GPX
where another tool needs one. Times are UTC seconds since the epoch. Semicircles (FIT) are converted to degrees."""
import os
import numpy as np

SEMI = 180.0 / 2 ** 31
FIELDS = ('t', 'lat', 'lon', 'alt', 'speed', 'hr', 'cadence', 'dist', 'temp', 'power')


def load_fit(path):
    import fitdecode
    rows = []
    with fitdecode.FitReader(path) as ff:
        for f in ff:
            if f.frame_type != fitdecode.FIT_FRAME_DATA or f.name != 'record': continue
            d = {x.name: x.value for x in f.fields}
            if d.get('timestamp') is None: continue
            lat, lon = d.get('position_lat'), d.get('position_long')
            rows.append((d['timestamp'].timestamp(), np.nan if lat is None else lat * SEMI, np.nan if lon is None else lon * SEMI,
                         _f(d.get('enhanced_altitude', d.get('altitude'))), _f(d.get('enhanced_speed', d.get('speed'))), _f(d.get('heart_rate')), _f(d.get('cadence')),
                         _f(d.get('distance')), _f(d.get('temperature')), _f(d.get('power'))))
    return dict(zip(FIELDS, np.array(rows, float).T))


def _f(v): return np.nan if v is None else float(v)


def load_gpx(path):
    import gpxpy
    g = gpxpy.parse(open(path)); rows = []
    for tr in g.tracks:
        for sg in tr.segments:
            for p in sg.points: rows.append((p.time.timestamp(), p.latitude, p.longitude, p.elevation if p.elevation is not None else np.nan))
    a = np.array(rows, float).T; nan = np.full(a.shape[1], np.nan)
    return dict(t=a[0], lat=a[1], lon=a[2], alt=a[3], speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)


def load(path, cache=True):
    """FIT or GPX -> dict of equal-length arrays (FIELDS), sorted by time; cached in `<path>.npz`."""
    npz = path + '.npz'
    if cache and os.path.exists(npz) and os.path.getmtime(npz) >= os.path.getmtime(path):
        z = np.load(npz); return {k: z[k] for k in z.files}
    tr = load_fit(path) if path.lower().endswith('.fit') else load_gpx(path)
    o = np.argsort(tr['t']); tr = {k: v[o] for k, v in tr.items()}
    if cache: np.savez_compressed(npz, **tr)
    return tr


def at(tr, t):
    """Position (lat, lon) and speed at UTC seconds `t` (linear interpolation over samples that have a position)."""
    ok = np.isfinite(tr['lat']); t = np.asarray(t, float)
    return np.interp(t, tr['t'][ok], tr['lat'][ok]), np.interp(t, tr['t'][ok], tr['lon'][ok])


def to_gpx(tr, path, every=1):
    import datetime as dt
    ok = np.flatnonzero(np.isfinite(tr['lat']))[::every]; out = ['<?xml version="1.0"?><gpx version="1.1" creator="strata360" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>']
    for i in ok:
        e = '' if not np.isfinite(tr['alt'][i]) else f"<ele>{tr['alt'][i]:.1f}</ele>"
        out.append(f"<trkpt lat=\"{tr['lat'][i]:.6f}\" lon=\"{tr['lon'][i]:.6f}\">{e}<time>{dt.datetime.fromtimestamp(tr['t'][i], dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}</time></trkpt>")
    open(path, 'w').write(''.join(out) + '</trkseg></trk></gpx>')
