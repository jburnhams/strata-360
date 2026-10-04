"""Gaps in the footage (implementation plan N1): the stretches of the race with no clip, where narration is wanted and picture is missing.

find_gaps(spans, tr) -> [{id, t0, t1, duration_s, before, after, km_start, km_end, distance_km, moving_s, moving_share, ascent_m, descent_m, daylight_start, daylight_end, local_start, local_end, ...}]
A gap is the time between two consecutive clips (overlapping clips are one stretch of footage) that lies on the race track and lasts at least `min_s`. Time before the first clip is not a gap (the film starts with footage); time after the last, to the end of the track, is the final gap (`final`) when it lasts `FINAL_MIN_S` or more, standing in for a finish clip. `spans` are the clips' [{id, t0, t1}] in epoch seconds (`load_spans` reads them from a project)."""
import hashlib, json, os
import numpy as np

from strata360.gps import series

MIN_GAP_S = 20 * 60.0           # uncovered time shorter than this is not a gap: a photo or street view section used in the film covers its own time, so a gap is only made between footage at least this far apart
FINAL_MIN_S = 120.0             # the race ends with a gap when the track runs this long past the last footage: with no finish clip it stands in for one
MOVING_MS = 0.5                 # faster than this is moving (as gps/overview.py)


def used_spans(folder):
    """The photos ticked to use in the film (a moment each, P1...) and the street view sections chosen for it (the time the runner took over them, V1...) as [{id, t0, t1}], in time order: they sit among the clips like clips, and no gap is made where they are.
    Anything that cannot be read (no photos, no street view, no track) is left out."""
    from strata360 import photos as PH
    from strata360.pipeline import config
    out = []
    try: out += [dict(id=PH.label_of(e), t0=float(e['taken_utc']), t1=float(e['taken_utc'])) for e in PH.load(config.race_dir(folder))['photos'] if PH.is_used(e)]
    except (OSError, ValueError, KeyError, TypeError): pass
    try:
        from strata360 import streetview as SV
        from strata360.gps import track
        rd = config.race_dir(folder); tp = config.track_path(folder, config.load(folder)); docs = {p: SV.load(rd, p) for p in SV.PROVIDERS}
        if tp and any(docs.values()):
            tr = track.load(tp)
            for sec in SV.chosen(rd, docs): a, b = SV.passed(sec, tr); out.append(dict(id=sec['label'], t0=a, t1=b))
    except (OSError, ValueError, KeyError, TypeError, ImportError): pass
    return sorted(out, key=lambda x: x['t0'])


def load_spans(folder, used=True):
    """The footage of a project as [{id, t0, t1}] in epoch seconds, in time order: the clips, and (unless `used` is False) the photos and street view sections ticked to use, which count as footage when gaps are found."""
    spans = series.load_spans(folder)
    return sorted(spans + used_spans(folder), key=lambda x: x['t0']) if used else spans


def merged(spans):
    """Overlapping or touching clips as one stretch each: [{t0, t1, first, last}] where `first` and `last` are the ids of the clip that starts it and the one that ends it."""
    out = []
    for s in sorted(spans, key=lambda s: s['t0']):
        if out and s['t0'] <= out[-1]['t1']:
            if s['t1'] > out[-1]['t1']: out[-1]['t1'] = s['t1']; out[-1]['last'] = s['id']
        else: out.append(dict(t0=s['t0'], t1=s['t1'], first=s['id'], last=s['id']))
    return out


def _at(tr, key, t):
    v = tr[key]; ok = np.isfinite(v)
    return float(np.interp(t, tr['t'][ok], v[ok])) if ok.any() else None


def facts(tr, t0, t1, tz='Europe/Brussels'):
    """What the track says about [t0, t1]: distance travelled and where, time spent moving, climb, daylight at both ends, local times."""
    from strata360.gps import context as X
    from strata360.gps.overview import ascent_descent
    T = tr['t']; i = np.flatnonzero((T >= t0) & (T <= t1)); d0, d1 = _at(tr, 'dist', t0), _at(tr, 'dist', t1)
    dts = np.diff(T); sp = tr['speed'][i[:-1]] if len(i) > 1 else np.array([]); mv = np.isfinite(sp) & (sp > MOVING_MS); step = dts[i[:-1]] if len(i) > 1 else np.array([])
    moving_s = float(step[mv].sum()) if len(step) else 0.0; alt = tr['alt'][i] if len(i) else np.array([]); up, down = ascent_descent(alt) if len(alt) > 1 else (0.0, 0.0)
    out = dict(km_start=None if d0 is None else round(d0 / 1000, 1), km_end=None if d1 is None else round(d1 / 1000, 1), distance_km=None if d0 is None else round((d1 - d0) / 1000, 1),
               moving_s=round(moving_s), moving_share=round(moving_s / max(t1 - t0, 1.0), 2), ascent_m=round(up), descent_m=round(down))
    for name, t in (('start', t0), ('end', t1)):
        lat, lon = _at(tr, 'lat', t), _at(tr, 'lon', t)
        out['daylight_' + name] = X.daylight(X.sun_elevation_deg(lat, lon, t)) if lat is not None and lon is not None else None
        out['local_' + name] = X._local(t, tz).strftime('%a %d %b %H:%M')
    return out


STOP_PAD_MIN_S, STOP_PAD_MAX_S, STOP_PAD_SHARE = 180.0, 600.0, 0.25          # a stop in the film shows a little of the arriving and the leaving: this much either side (a quarter of the stop, at least 3 and at most 10 minutes)


def stop_window(s):
    """(t0, t1) of the clip for a stop that was added: the stop and a little either side, so the arriving and the leaving show."""
    pad = min(max(STOP_PAD_SHARE * (s['left'] - s['arrived']), STOP_PAD_MIN_S), STOP_PAD_MAX_S); return s['arrived'] - pad, s['left'] + pad


def stops_path(folder):
    from strata360.pipeline import config
    return os.path.join(config.race_dir(folder), 'stops.json')


def added_stops(folder):
    """The stops added to the video (stops.json): [{key, arrived, left, lat, lon, km, stopped_s, radius_m}] in time order."""
    try: return sorted(json.load(open(stops_path(folder)))['added'], key=lambda s: s['arrived'])
    except (OSError, ValueError, KeyError): return []


def stop_key(s): return hashlib.sha1(f"stop:{round(s['arrived'])}".encode()).hexdigest()[:10]


def set_stop(folder, stop, on):
    """Add a stop (as listed by gps/tracks.py `other_stops`) to the video, or take it out. Returns whether it is in."""
    cur = [s for s in added_stops(folder) if s['key'] != stop['key']]
    if on: cur.append({k: stop[k] for k in ('key', 'arrived', 'left', 'lat', 'lon', 'km', 'stopped_s', 'radius_m')})
    os.makedirs(os.path.dirname(stops_path(folder)), exist_ok=True); tmp = stops_path(folder) + '.tmp'; json.dump(dict(added=cur), open(tmp, 'w'), indent=1); os.replace(tmp, stops_path(folder)); return bool(on)


def project_gaps(folder, tr, min_s=MIN_GAP_S, tz='Europe/Brussels', used=True):
    """The gaps of a project: between its footage (the clips, and with `used` the photos and street view sections ticked), with the stops added to the video as gaps of their own (see `find_gaps`)."""
    stops = added_stops(folder)
    return find_gaps(load_spans(folder) if used else load_spans(folder, used=False), tr, min_s, tz, **({'stops': stops} if stops else {}))


def find_gaps(spans, tr, min_s=MIN_GAP_S, tz='Europe/Brussels', stops=()):
    """The gaps between clips that lie on the track, in time order, numbered G01, G02, ... in that order. A stop added to the video (`stops`: see added_stops) inside a gap is a gap of its own, with `stop` facts: the stop and a little either side
    (stop_window), even when that is shorter than `min_s`; what is left of the gap before and after it is a gap of its own when it is `min_s` or more. A stop partly covered by footage is a gap for the part outside the footage only (`covered_before` / `covered_after` say which end the footage cut off); one the footage covers entirely makes no gap."""
    T = tr['t']; start, end = float(T[0]), float(T[-1]); out = []; runs = merged(spans); raw = []
    for a, b in zip(runs, runs[1:]): raw.append((max(a['t1'], start), min(b['t0'], end), a['last'], b['first'], False))
    if runs: raw.append((max(runs[-1]['t1'], start), end, runs[-1]['last'], 'finish', True))
    def add(g0, g1, before, after, final=False, stop=None):
        g = dict(t0=g0, t1=g1, duration_s=round(g1 - g0, 1), before=before, after=after, **({'final': True} if final else {}), **({'stop': stop} if stop else {}), **facts(tr, g0, g1, tz))
        g['key'] = hashlib.sha1(f'{round(g0)}:{round(g1)}'.encode()).hexdigest()[:10]; out.append(g)
    for g0, g1, before, after, final in raw:
        if g1 <= g0: continue
        mine = []
        for s in sorted(stops or [], key=lambda x: x['arrived']):
            f0, f1 = stop_window(s); w0, w1 = max(f0, g0), min(f1, g1)                                          # (only the time outside the footage: what a clip already covers is not drawn again)
            if w1 - w0 >= 60.0 and (not mine or w0 >= mine[-1][1]): mine.append((w0, w1, s, w0 > f0 + 1.0, w1 < f1 - 1.0))
        if not mine:
            if g1 - g0 >= (FINAL_MIN_S if final else min_s): add(g0, g1, before, after, final=final)
            continue
        cur, prev = g0, before
        for w0, w1, s, cut0, cut1 in mine:
            if w0 - cur >= min_s: add(cur, w0, prev, 'stop'); prev = 'stop'
            add(w0, w1, prev, 'stop', stop=dict(s, pad_s=round(s['arrived'] - stop_window(s)[0]), covered_before=cut0, covered_after=cut1)); cur, prev = w1, 'stop'
        if g1 - cur >= (FINAL_MIN_S if final else min_s): add(cur, g1, prev, after, final=final)
    for n, g in enumerate(out, 1): g['id'] = f'G{n:02d}'
    return out
