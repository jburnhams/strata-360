"""The project's GPS tracks: any number of uploaded FIT / GPX files, each marked a RUN (the recording of the race, with times) or a ROUTE (the planned or official course, for planning: shown on the map, not used by the film).

  <project>/tracks.json            the manifest: the tracks (id, name, file, kind) and the kind of the older single file
  <project>/tracks/<id>-<name>     the uploaded files (a file that is replaced or removed is moved aside, never deleted)
  <project>/track.fit | track.gpx  the older single track: it counts as the first run (id `main`)
  <project>/track.merged.npz       the runs merged into one (when there are two or more), what the rest of the program reads through `config.track_path`

Merging runs (`merge`): the runs are taken in priority order (the older single file, then the uploads in order); a lower run keeps only the samples outside the stretches that a higher run recorded without a break (more than 30 s without a sample is a break), so two devices recording the same hours do not double the
track, while a run that fills the gap left by another (a flat battery, a second watch) joins on. Samples are then in time order and the distance is worked out again along the merged line. Points of interest: waypoints of a GPX, course points of a FIT (`pois`)."""
import datetime as dt, json, os, re

import numpy as np

from strata360.gps import track as TR

MANIFEST, MERGED, MERGED_INFO = 'tracks.json', 'track.merged.npz', 'track.merged.json'
LEGACY = ('track.fit', 'track.gpx')
KINDS = ('run', 'route')
BREAK_S = 30.0                 # no sample for this long inside a run is a break in its recording
MAX_BYTES = 200 * 1024 * 1024


def _iso(t): return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def dir_of(rd): return os.path.join(rd, 'tracks')


def _manifest(rd):
    try: doc = json.load(open(os.path.join(rd, MANIFEST)))
    except (OSError, ValueError): doc = {}
    doc.setdefault('tracks', []); doc.setdefault('main_kind', 'run'); doc.setdefault('next', 1); return doc


def _save(rd, doc):
    os.makedirs(rd, exist_ok=True); p = os.path.join(rd, MANIFEST); tmp = p + '.tmp'
    with open(tmp, 'w') as f: json.dump(doc, f, indent=1)
    os.replace(tmp, p)


def entries(rd):
    """Every track of the project in priority order: [{id, name, file (full path), kind}]; the older single file first, as `main`."""
    doc = _manifest(rd); out = []
    legacy = next((n for n in LEGACY if os.path.exists(os.path.join(rd, n))), None)
    if legacy: out.append(dict(id='main', name=legacy, file=os.path.join(rd, legacy), kind=doc['main_kind']))
    for t in doc['tracks']:
        p = os.path.join(dir_of(rd), t['file'])
        if os.path.exists(p): out.append(dict(t, file=p))
    return out


def runs(rd): return [e for e in entries(rd) if e['kind'] == 'run']


def read(path):
    """The samples of a track file (gps/track.py `load`)."""
    return TR.load(path)


def _dist(lat, lon):
    la, lo = np.radians(lat), np.radians(lon); a = np.sin(np.diff(la) / 2) ** 2 + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(np.diff(lo) / 2) ** 2
    return np.concatenate([[0.0], np.cumsum(2 * 6371000.0 * np.arcsin(np.sqrt(a)))])


def summary(path, points=400):
    """What the app shows about one track file: samples, bounding box, length, times (None for a route without times), and a line of at most `points` points."""
    tr = read(path); ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon'])
    if not ok.any(): raise ValueError('the file has no positions')
    lat, lon, t = tr['lat'][ok], tr['lon'][ok], tr['t'][ok]; idx = np.unique(np.linspace(0, len(lat) - 1, points).astype(int)); timed = bool(np.isfinite(t).all())
    return dict(samples=int(len(lat)), timed=timed, start_utc=_iso(t[0]) if timed else None, end_utc=_iso(t[-1]) if timed else None, distance_km=round(float(_dist(lat, lon)[-1]) / 1000.0, 1),
                bbox=[float(lat.min()), float(lon.min()), float(lat.max()), float(lon.max())], line=[[round(float(lat[i]), 5), round(float(lon[i]), 5)] for i in idx])


def merge(trs):
    """One track from several runs (`trs`: sample dicts in priority order, highest first): see the module notes. Returns a dict of the FIELDS arrays, sorted by time, with `dist` worked out along the merged line."""
    kept = []; covered = []
    for tr in trs:
        t = np.asarray(tr['t'], float); ok = np.isfinite(t) & np.isfinite(tr['lat']) & np.isfinite(tr['lon'])
        if not ok.any(): continue
        idx = np.flatnonzero(ok); keep = np.ones(len(idx), bool)
        for a, b in covered: keep &= ~((t[idx] >= a) & (t[idx] <= b))
        kept.append({k: np.asarray(v)[idx[keep]] for k, v in tr.items()})
        ti = t[idx]; cut = np.flatnonzero(np.diff(ti) > BREAK_S); starts = np.r_[0, cut + 1]; ends = np.r_[cut, len(ti) - 1]; covered += [(float(ti[a]), float(ti[b])) for a, b in zip(starts, ends)]       # the stretches it recorded without a break
    if not kept: raise ValueError('no run has positions with times')
    out = {k: np.concatenate([d[k] for d in kept]) for k in TR.FIELDS}; o = np.argsort(out['t'], kind='stable'); out = {k: v[o] for k, v in out.items()}
    out['dist'] = _dist(out['lat'], out['lon']); return out


def _merged_sources(rd): return [e for e in runs(rd)]


def update_merged(rd):
    """Make `track.merged.npz` match the runs: written when there are two or more, removed when there are not."""
    mp, ip = os.path.join(rd, MERGED), os.path.join(rd, MERGED_INFO); rs = runs(rd)
    if len(rs) < 2:
        for p in (mp, ip):
            if os.path.exists(p): os.remove(p)
        return None
    tr = merge([read(e['file']) for e in rs]); tmp = mp + '.tmp.npz'; np.savez_compressed(tmp, **tr); os.replace(tmp, mp)
    info = dict(runs=[e['id'] for e in rs], samples=int(len(tr['t'])), start_utc=_iso(tr['t'][0]), end_utc=_iso(tr['t'][-1]), distance_km=round(float(tr['dist'][-1]) / 1000.0, 1)); json.dump(info, open(ip, 'w')); return info


def current_path(rd):
    """The file `config.track_path` hands to the rest of the program: the merged run track when there are two or more runs (made again when a source is newer), the one run's own file when there is one, else None."""
    rs = runs(rd)
    if not rs: return None
    if len(rs) == 1: return rs[0]['file']
    mp = os.path.join(rd, MERGED)
    if not os.path.exists(mp) or any(os.path.getmtime(e['file']) > os.path.getmtime(mp) for e in rs) or _stale_sources(rd, rs): update_merged(rd)
    return mp


def _stale_sources(rd, rs):
    try: return json.load(open(os.path.join(rd, MERGED_INFO))).get('runs') != [e['id'] for e in rs]
    except (OSError, ValueError): return True


def _safe(name): return re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(name))[:80] or 'track'


def add(rd, filename, data, kind=None):
    """Save an uploaded file as a new track and return its entry (with `summary`). The first run defaults to `run`, later uploads to `route`. Raises ValueError when the file cannot be read, or is marked a run without times."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.fit', '.gpx'): raise ValueError('a .fit or .gpx file, please')
    if len(data) < 100 or len(data) > MAX_BYTES: raise ValueError('the file is empty or too large')
    if kind is not None and kind not in KINDS: raise ValueError(f'kind: one of {", ".join(KINDS)}')
    doc = _manifest(rd); kind = kind or ('run' if not runs(rd) else 'route'); tid = f"t{doc['next']}"; os.makedirs(dir_of(rd), exist_ok=True); dest = os.path.join(dir_of(rd), f'{tid}-{_safe(filename)}')
    with open(dest, 'wb') as f: f.write(data)
    try:
        info = summary(dest)
        if kind == 'run' and not info['timed']: raise ValueError('a run needs times on its points (this file has none: mark it a route)')
    except Exception as e:
        os.replace(dest, dest + '.bad')
        if isinstance(e, ValueError): raise
        raise ValueError(f'could not read that file: {type(e).__name__}: {e}')
    doc['tracks'].append(dict(id=tid, name=os.path.basename(filename), file=os.path.basename(dest), kind=kind, added=_iso(dt.datetime.now(dt.timezone.utc).timestamp()))); doc['next'] += 1; _save(rd, doc); update_merged(rd)
    return dict(id=tid, name=os.path.basename(filename), kind=kind, **info)


def set_kind(rd, tid, kind):
    if kind not in KINDS: raise ValueError(f'kind: one of {", ".join(KINDS)}')
    doc = _manifest(rd); e = next((x for x in entries(rd) if x['id'] == tid), None)
    if e is None: raise KeyError(tid)
    if kind == 'run' and not summary(e['file'])['timed']: raise ValueError('a run needs times on its points (this file has none)')
    if tid == 'main': doc['main_kind'] = kind
    else:
        for t in doc['tracks']:
            if t['id'] == tid: t['kind'] = kind
    _save(rd, doc); update_merged(rd)


def remove(rd, tid):
    """Take a track out of the project: its file is moved to `tracks/removed/` (never deleted)."""
    doc = _manifest(rd); e = next((x for x in entries(rd) if x['id'] == tid), None)
    if e is None: raise KeyError(tid)
    gone = os.path.join(dir_of(rd), 'removed'); os.makedirs(gone, exist_ok=True)
    if tid == 'main':
        for n in LEGACY:
            for suffix in ('', '.npz', '.pois.json'):
                p = os.path.join(rd, n + suffix)
                if os.path.exists(p): os.replace(p, os.path.join(gone, n + suffix + '.removed'))
    else:
        for suffix in ('', '.npz', '.pois.json'):
            p = e['file'] + suffix
            if os.path.exists(p): os.replace(p, os.path.join(gone, os.path.basename(p)))
        doc['tracks'] = [t for t in doc['tracks'] if t['id'] != tid]; _save(rd, doc)
    update_merged(rd)


def pois(path):
    """Points of interest of one file: [{name, lat, lon, ele, sym, desc}] from a GPX's waypoints (and the named points of its routes) or a FIT's course points; kept in `<file>.pois.json` until the file changes."""
    cache = path + '.pois.json'
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
        try: return json.load(open(cache))
        except ValueError: pass
    out = []
    if path.lower().endswith('.gpx'):
        trk, rte, wpt = TR.gpx_parts(path)
        for w in wpt: out.append(dict(name=w['name'], lat=w['lat'], lon=w['lon'], ele=w['ele'], sym=w['sym'], desc=w['desc']))
        for q in rte + trk:
            if q['name']: out.append(dict(name=q['name'], lat=q['lat'], lon=q['lon'], ele=q['ele'], sym=q['sym'], desc=q['desc']))
    else:
        import fitdecode
        with fitdecode.FitReader(path) as ff:
            for f in ff:
                if f.frame_type != fitdecode.FIT_FRAME_DATA or f.name != 'course_point': continue
                d = {x.name: x.value for x in f.fields}
                if d.get('position_lat') is None or d.get('position_long') is None: continue
                out.append(dict(name=str(d.get('name') or ''), lat=d['position_lat'] * TR.SEMI, lon=d['position_long'] * TR.SEMI, ele=None, sym=str(d.get('type') or ''), desc=''))
    out = [dict(p, lat=round(float(p['lat']), 6), lon=round(float(p['lon']), 6), ele=None if p['ele'] is None else round(float(p['ele']), 1)) for p in out]
    try: json.dump(out, open(cache, 'w'))
    except OSError: pass
    return out


def listing(rd):
    """Everything the app shows: the tracks with their summaries and kinds, the merged run track when there is one, and the points of interest of all of them."""
    items = []; points = []
    for e in entries(rd):
        try: info = summary(e['file'])
        except Exception as ex: items.append(dict(id=e['id'], name=e['name'], kind=e['kind'], error=f'{type(ex).__name__}: {ex}')); continue
        try: p = [dict(q, track=e['id']) for q in pois(e['file'])]
        except Exception: p = []
        points += p; items.append(dict(id=e['id'], name=e['name'], kind=e['kind'], pois=len(p), **info))
    merged = None
    if len(runs(rd)) >= 2:
        current_path(rd)
        try: merged = json.load(open(os.path.join(rd, MERGED_INFO)))
        except (OSError, ValueError): merged = None
    return dict(tracks=items, merged=merged, pois=points, runs=len(runs(rd)))
