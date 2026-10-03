"""The race GPS track (Garmin FIT or GPX) as arrays, cached as `.npz` next to the source, plus GPX export.

The arrays drive our own analysis (clock verification, position per clip, race progress) and the overlay on the final film (overlay/series.py); `to_gpx` writes a GPX
where another tool needs one. Times are UTC seconds since the epoch. Semicircles (FIT) are converted to degrees."""
import datetime as dt
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


def _local(tag): return tag.rsplit('}', 1)[-1]


def _num(text):
    try: return float(text)
    except (TypeError, ValueError): return np.nan


def _stamp(text):
    """A GPX time (ISO 8601, `Z` or an offset) as epoch seconds; nan when absent."""
    if not text: return np.nan
    try: d = dt.datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
    except ValueError: return np.nan
    return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()


def gpx_parts(path):
    """The elements of a GPX file, read with the standard library: (track points, route points, waypoints), each point a dict of lat, lon, ele, time, name, sym, desc, hr, cad, temp (missing = None)."""
    import xml.etree.ElementTree as ET
    def point(e):
        d = dict(lat=float(e.get('lat')), lon=float(e.get('lon')), ele=None, time=None, name='', sym='', desc='', hr=None, cad=None, temp=None)
        for c in e.iter():
            n = _local(c.tag); v = (c.text or '').strip()
            if n == 'ele' and v: d['ele'] = _num(v)
            elif n == 'time': d['time'] = v
            elif n == 'name': d['name'] = v
            elif n == 'sym': d['sym'] = v
            elif n in ('desc', 'cmt') and v and not d['desc']: d['desc'] = v
            elif n == 'hr' and v: d['hr'] = _num(v)
            elif n == 'cad' and v: d['cad'] = _num(v)
            elif n == 'atemp' and v: d['temp'] = _num(v)
        return d
    root = ET.parse(path).getroot(); trk, rte, wpt = [], [], []
    for e in root.iter():
        n = _local(e.tag)
        if n == 'trkpt': trk.append(point(e))
        elif n == 'rtept': rte.append(point(e))
        elif n == 'wpt': wpt.append(point(e))
    return trk, rte, wpt


def load_gpx(path):
    trk, rte, _ = gpx_parts(path); pts = trk or rte                                                                       # a GPX that holds a route (<rte>) and no track: the route (a planned one has no times)
    if not pts: raise ValueError('the file has no track or route points')
    f = lambda k: np.array([np.nan if p[k] is None else p[k] for p in pts], float); nan = np.full(len(pts), np.nan)
    return dict(t=np.array([_stamp(p['time']) for p in pts]), lat=f('lat'), lon=f('lon'), alt=f('ele'), speed=nan, hr=f('hr'), cadence=f('cad'), dist=nan, temp=f('temp'), power=nan)


def load(path, cache=True):
    """FIT or GPX -> dict of equal-length arrays (FIELDS), sorted by time; cached in `<path>.npz`."""
    if path.lower().endswith('.npz'):                                                                                     # a merged track (gps/tracks.py)
        z = np.load(path); return {k: z[k] for k in z.files}
    npz = path + '.npz'
    if cache and os.path.exists(npz) and os.path.getmtime(npz) >= os.path.getmtime(path):
        z = np.load(npz); return {k: z[k] for k in z.files}
    tr = load_fit(path) if path.lower().endswith('.fit') else load_gpx(path)
    o = np.argsort(tr['t'], kind='stable') if np.isfinite(tr['t']).any() else np.arange(len(tr['t'])); tr = {k: v[o] for k, v in tr.items()}              # (a route without times keeps its order)
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
