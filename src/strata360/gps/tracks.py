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


def end_markers(rd):
    """Where the race starts and stops on the map: {start: {lat, lon, t}, end: {lat, lon, t, km, elapsed_s} (the last point of the run), finish: {lat, lon} (the end of the last route in race order; None without routes)}; None without a run."""
    cur = current_path(rd)
    if not cur: return None
    run = read(cur); ok = np.isfinite(run['lat']) & np.isfinite(run['lon']) & np.isfinite(run['t'])
    if ok.sum() < 2: return None
    lat, lon, t = run['lat'][ok], run['lon'][ok], run['t'][ok]; order, _ = route_order(rd); last = max(order, key=lambda o: o['order']) if order else None
    return dict(start=dict(lat=float(lat[0]), lon=float(lon[0]), t=float(t[0])), end=dict(lat=float(lat[-1]), lon=float(lon[-1]), t=float(t[-1]), km=round(float(_dist(lat, lon)[-1]) / 1000.0, 1), elapsed_s=round(float(t[-1] - t[0]))),
                finish=dict(lat=last['end'][0], lon=last['end'][1]) if last else None)


def finish_info(rd):
    """The finish of the routes for the Tracks list (the finish line, not where the run ended): {reached, route_m, covered_m, t, elapsed_s, km, time_s}. route_m is the length of all the routes and covered_m how much of that the run covered (the stages added up, as on the overlay).
    When the run came to the end of the last route (the At Finish stage) `reached` is True and t, elapsed_s, km (from the start of the run) and time_s (how long it stayed to the end of the run) say when; otherwise those are None. None without routes."""
    order, _ = route_order(rd); cur = current_path(rd)
    if not order or not cur: return None
    sched = stage_schedule(rd); tm = timing(rd); prog = stage_progress(rd)
    if not sched or not tm or not prog: return None
    names = [l for _, l in sched]; covered = 0.0
    for name, pr in prog.items():
        k = names.index(name) if name in names else None
        if k is None or not len(pr['t']): continue
        covered += pr['route_m'] if (k + 1 < len(names) and names[k + 1] != 'After Race') else float(pr['prog'][-1])                                   # a stage with something after it other than the end of the run was completed
    out = dict(reached=False, route_m=round(sum(p['route_m'] for p in prog.values())), covered_m=round(covered), t=None, elapsed_s=None, km=None, time_s=None)
    fin = next((a for a, l in sched if l == 'At Finish'), None)
    if fin is not None:
        run = read(cur); ok = np.isfinite(run['t']) & np.isfinite(run['lat']) & np.isfinite(run['lon']); tt = run['t'][ok]; cum = _dist(run['lat'][ok], run['lon'][ok])
        out.update(reached=True, t=float(fin), elapsed_s=round(float(fin - tm['start'])), km=round(float(np.interp(fin, tt, cum)) / 1000.0, 1), time_s=round(float(tm['end'] - fin)))
    return out


def _cutoff_text(rd): return _manifest(rd).get('cutoffs') or {}


def cutoff_contexts(rd, tz='Europe/Brussels'):
    """What a typed cut-off needs to be understood, for the checkpoints ('cp:N') and the finish ('finish'): {key: ctx} (see gps/cutoffs.py), with the time the run reached each, as time since the start."""
    from strata360.gps import cutoffs as CU
    tm = timing(rd)
    if not tm: return {}
    arr = {int(k): v['elapsed_s'] for k, v in tm['arrivals'].items()}; left = {int(k): arr[int(k)] + tm['checkpoints'][k] for k in tm['arrivals']}; n = len(tm['arrivals']); saved = _cutoff_text(rd); out = {}; prev_cut = None
    fin = finish_info(rd)
    for k in range(1, n + 1):
        prev_ref = prev_cut if prev_cut is not None else (arr.get(k - 1, 0))
        out[f'cp:{k}'] = dict(start=tm['start'], tz=tz, prev_ref_s=prev_ref, last_departure_s=left.get(k - 1, 0), arrival_s=arr[k])
        prev_cut = _cutoff_resolved(saved.get(f'cp:{k}'), out[f'cp:{k}'])
    prev_ref = prev_cut if prev_cut is not None else arr.get(n, 0)
    if fin: out['finish'] = dict(start=tm['start'], tz=tz, prev_ref_s=prev_ref, last_departure_s=left.get(n, 0), arrival_s=fin['elapsed_s'] if fin['reached'] else None)
    return out


def _cutoff_resolved(text, ctx):
    from strata360.gps import cutoffs as CU
    if not text: return None
    try: return CU.parse(text, ctx)['elapsed_s']
    except ValueError: return None


def overlay_places(rd):
    """Where the start, the finish (the end of the last route) and the checkpoints are, for the overlay maps: {start: (lat, lon), finish: (lat, lon) or None, checkpoints: [(n, lat, lon)]}; None without a run."""
    em = end_markers(rd)
    if not em: return None
    _, marks = route_order(rd)
    return dict(start=(em['start']['lat'], em['start']['lon']), finish=(em['finish']['lat'], em['finish']['lon']) if em['finish'] else None, checkpoints=[(m['n'], m['lat'], m['lon']) for m in marks])


def overlay_cutoffs(rd, tz='Europe/Brussels'):
    """The cut-offs for the overlay, as time since the start of the run: {'start': UTC seconds of the start, 'stage': {'Stage N': the cut-off at the end of that stage (its checkpoint, or the finish for the last)}, 'cp': {N: cut-off of checkpoint N}, 'finish': cut-off of the finish}; only those set and understood."""
    order, _ = route_order(rd); tm = timing(rd) if order else None
    if not tm: return {}
    c = {k: v['elapsed_s'] for k, v in cutoffs(rd, tz).items() if 'elapsed_s' in v}; n = len(order)
    stage = {f'Stage {k}': c[f'cp:{k}' if k < n else 'finish'] for k in range(1, n + 1) if (f'cp:{k}' if k < n else 'finish') in c}
    return dict(start=tm['start'], stage=stage, cp={int(k[3:]): v for k, v in c.items() if k.startswith('cp:')}, finish=c.get('finish'))


def set_cutoff(rd, key, text, tz='Europe/Brussels'):
    """Save the cut-off typed for a checkpoint ('cp:N') or the finish ('finish'); empty text clears it. Raises ValueError (with a message to show) when the text is not understood, KeyError for an unknown key."""
    from strata360.gps import cutoffs as CU
    ctx = cutoff_contexts(rd, tz).get(key)
    if ctx is None: raise KeyError(key)
    doc = _manifest(rd); cuts = doc.setdefault('cutoffs', {}); text = (text or '').strip()
    if not text: cuts.pop(key, None)
    else: CU.parse(text, ctx); cuts[key] = text
    _save(rd, doc)


def cutoffs(rd, tz='Europe/Brussels'):
    """The saved cut-offs as the app shows them: {key: {text, kind, elapsed_s, arrival_s, margin_s}} (margin: seconds to spare, negative when late; None when the run did not get there), or {text, error}."""
    from strata360.gps import cutoffs as CU
    saved = _cutoff_text(rd); ctxs = cutoff_contexts(rd, tz); out = {}
    for key, text in saved.items():
        ctx = ctxs.get(key)
        if ctx is None: continue
        try: r = CU.parse(text, ctx)
        except ValueError as e: out[key] = dict(text=text, error=str(e)); continue
        out[key] = dict(text=text, kind=r['kind'], elapsed_s=r['elapsed_s'], arrival_s=ctx['arrival_s'], margin_s=None if ctx['arrival_s'] is None else r['elapsed_s'] - ctx['arrival_s'])
    return out


def listing(rd, tz='Europe/Brussels'):
    """Everything the app shows: the tracks with their summaries and kinds, the merged run track when there is one, the points of interest of all of them, and where the race track leaves the routes (`divergences`)."""
    items = []; points = []
    try: order, marks = route_order(rd)
    except Exception: order, marks = [], []                                         # (the map is not worth failing the list over)
    info_of = {o['id']: o for o in order}
    for e in entries(rd):
        try: info = summary(e['file'])
        except Exception as ex: items.append(dict(id=e['id'], name=e['name'], kind=e['kind'], error=f'{type(ex).__name__}: {ex}')); continue
        try: p = [dict(q, track=e['id']) for q in pois(e['file'])]
        except Exception: p = []
        points += p; o = info_of.get(e['id']); items.append(dict(id=e['id'], name=e['name'], kind=e['kind'], pois=len(p), **info, **({k: o[k] for k in ('order', 'reversed', 'km_start', 'km_end')} if o else {})))
    items.sort(key=lambda x: (x['kind'] != 'run', x.get('order') is None, x.get('order') or 0))                        # runs first, then the routes in race order
    name = {x['id']: x['name'] for x in items}
    try: stops = checkpoint_stops(rd)
    except Exception: stops = {}                                                    # (the map is not worth failing the list over)
    for c in marks: points.append(dict(name=f"Checkpoint {c['n']}", lat=c['lat'], lon=c['lon'], ele=None, sym='checkpoint', desc=f"{name.get(c['before'], '')} → {name.get(c['after'], '')}" + (f" (their ends are {c['gap_m']} m apart)" if c['gap_m'] >= 20 else ''), track='checkpoint', n=c['n'], **({'stop': stops[c['n']]} if c['n'] in stops else {})))
    merged = None
    if len(runs(rd)) >= 2:
        current_path(rd)
        try: merged = json.load(open(os.path.join(rd, MERGED_INFO)))
        except (OSError, ValueError): merged = None
    try: div = divergences(rd)
    except Exception: div = []                                                     # (the map is not worth failing the list over)
    try: tm = timing(rd)
    except Exception: tm = {}
    try: mk = end_markers(rd)
    except Exception: mk = None
    try: fi = finish_info(rd)
    except Exception: fi = None
    try: cuts = cutoffs(rd, tz)
    except Exception: cuts = {}
    for x in items:
        if x['id'] in tm.get('sections', {}):
            i = x['id']; x['time_s'] = tm['sections'][i]; x['ran_km'] = round(tm['ran_m'][i] / 1000.0, 1); x['ascent_m'], x['descent_m'] = tm['climb'][i]
            if tm['ran_m'][i] >= 100: x['pace_s_km'] = round(tm['sections'][i] / (tm['ran_m'][i] / 1000.0))                         # (the time between the checkpoints over the distance run in it)
    return dict(tracks=items, merged=merged, pois=points, runs=len(runs(rd)), divergences=div, timing=tm or None, markers=mk, finish=fi, cutoffs=cuts)


_DIV = {}


def _fill(p, step):
    """A polyline in metres with a point every `step` metres or less along it."""
    d = np.hypot(*np.diff(p, axis=0).T); s = np.concatenate([[0], np.cumsum(d)]); n = max(2, int(s[-1] / step) + 1); u = np.linspace(0, s[-1], n)
    return np.column_stack([np.interp(u, s, p[:, 0]), np.interp(u, s, p[:, 1])]) if s[-1] > 0 else p[:1]
WRONG_DEG = 35.0               # heading differing from the route's by more than this (as lines) is heading the wrong way
MIN_WRONG = 0.3                # a stretch off the route needs this share of it heading the wrong way, else it is only an offset alongside the route


def _heading(p, k):
    """Heading (degrees, 0-180 as a line) at each point of a polyline in metres, from the points k steps either side."""
    n = len(p); a = np.clip(np.arange(n) - k, 0, n - 1); b = np.clip(np.arange(n) + k, 0, n - 1)
    return np.degrees(np.arctan2(p[b, 0] - p[a, 0], p[b, 1] - p[a, 1])) % 180.0


def _apart(h1, h2):
    """Angle between two headings taken as lines, 0-90 degrees."""
    return np.abs(((h1 - h2 + 90.0) % 180.0) - 90.0)


def divergences(rd, threshold_m=50.0, top=10, step_m=10.0, join_m=150.0):
    """Where the race track leaves the routes by more than `threshold_m` (the distance to the nearest route of any: routes can be sections of the course). The race track is taken every `step_m` metres and each route is filled in to the same spacing, so the distance is within step_m / 2; stretches off the routes
    less than `join_m` apart along the run are one divergence. A stretch that only keeps level with a route, offset from it (less than MIN_WRONG of it heading more than WRONG_DEG away from the route's direction), is left out. Returns the `top` by score (peak distance times the share heading the wrong way), biggest first: [{lat, lon, peak_m, wrong, score, length_m, km, t, line}] (lat, lon: the farthest point; km: along the race track; line: the stretch, thinned)."""
    rts = [e for e in entries(rd) if e['kind'] == 'route']; cur = current_path(rd)
    if not rts or not cur: return []
    key = (cur, os.path.getmtime(cur), tuple((e['file'], os.path.getmtime(e['file'])) for e in rts), threshold_m, top)
    if key in _DIV: return _DIV[key]
    from scipy.spatial import cKDTree
    run = read(cur); ok = np.isfinite(run['lat']) & np.isfinite(run['lon']) & np.isfinite(run['t']); lat, lon, t = run['lat'][ok], run['lon'][ok], run['t'][ok]
    if len(lat) < 2: return []
    lat0 = float(np.median(lat)); kx = 111320.0 * np.cos(np.radians(lat0)); ky = 110540.0
    xy = lambda la, lo: np.column_stack([(lo - 5.0) * kx, (la - lat0) * ky])
    pts = []; hdg = []
    for e in rts:
        r = read(e['file']); g = np.isfinite(r['lat']) & np.isfinite(r['lon'])
        if g.sum() >= 2:
            f = _fill(xy(r['lat'][g], r['lon'][g]), step_m); pts.append(f); hdg.append(_heading(f, 2))
    if not pts: return []
    tree = cKDTree(np.vstack(pts)); rh = np.concatenate(hdg)
    P = xy(lat, lon); s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))]); u = np.arange(0, s[-1], step_m)           # the race track every step_m along its own length
    if len(u) < 2: return []
    Q = np.column_stack([np.interp(u, s, P[:, 0]), np.interp(u, s, P[:, 1])]); tt = np.interp(u, s, t); d, nn = tree.query(Q); off = d > threshold_m; turn = _apart(_heading(Q, 3), rh[nn]) > WRONG_DEG       # (heading of the run against the heading of the route where it is nearest, as lines: the way along it does not matter)
    out = []; i = 0; n = len(u)
    while i < n:
        if not off[i]: i += 1; continue
        j = i
        while True:                                                                   # extend over short returns to the route
            k = j + 1
            while k < n and not off[k]: k += 1
            if k < n and (k - j) * step_m < join_m: j = k
            else: break
        a, b = i, j; share = float(turn[a:b + 1][off[a:b + 1]].mean())
        if share < MIN_WRONG: i = j + 1; continue                                  # keeps level with the route, only offset: not a wrong turn
        m = a + int(np.argmax(d[a:b + 1])); idx = np.unique(np.linspace(a, b, min(60, b - a + 1)).astype(int))
        unxy = lambda q: (float(q[1] / ky + lat0), float(q[0] / kx + 5.0))
        pk = unxy(Q[m]); out.append(dict(lat=round(pk[0], 6), lon=round(pk[1], 6), peak_m=round(float(d[m])), wrong=round(share, 2), score=round(float(d[m]) * share), length_m=round((b - a + 1) * step_m), km=round(float(u[m]) / 1000.0, 1), t=float(tt[m]), line=[[round(unxy(Q[q])[0], 6), round(unxy(Q[q])[1], 6)] for q in idx]))
        i = j + 1
    out = sorted(out, key=lambda x: -x['score'])[:top]; _DIV.clear(); _DIV[key] = out; return out


_ORDER = {}


def route_order(rd, step_m=10.0, reach_m=150.0):
    """The routes in the order the race runs them, from the race track. A route is run in one stretch of the race track about as long as itself, which starts near one of the places the race track passes the route's first point (a loop or a start and finish together make several) and goes on
    or back from there; every such start and direction is tried and the stretch whose points lie nearest the route's is taken. The routes are then put in the order of their stretches, each turned the way the race ran it. Returns
    [{id, order (1 = first), reversed, km_start, km_end (along the race track), start: [lat, lon], end: [lat, lon]}] and, between each route and the next, the checkpoints [{n, lat, lon, gap_m, before, after}]: halfway between the end of one route and the start of the next, which need not meet exactly.
    The start of the first route and the end of the last are not checkpoints. Empty without a race track."""
    rts = [e for e in entries(rd) if e['kind'] == 'route']; cur = current_path(rd)
    if not rts or not cur: return [], []
    key = (cur, os.path.getmtime(cur), tuple((e['file'], os.path.getmtime(e['file'])) for e in rts), step_m)
    if key in _ORDER: return _ORDER[key]
    from scipy.spatial import cKDTree
    run = read(cur); ok = np.isfinite(run['lat']) & np.isfinite(run['lon']); lat, lon = run['lat'][ok], run['lon'][ok]
    if len(lat) < 2: return [], []
    lat0 = float(np.median(lat)); kx = 111320.0 * np.cos(np.radians(lat0)); ky = 110540.0
    xy = lambda la, lo: np.column_stack([(lo - 5.0) * kx, (la - lat0) * ky]); ll = lambda q: [float(q[1] / ky + lat0), float(q[0] / kx + 5.0)]
    P = xy(lat, lon); s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))]); u = np.arange(0, s[-1], step_m)
    if len(u) < 2: return [], []
    Q = np.column_stack([np.interp(u, s, P[:, 0]), np.interp(u, s, P[:, 1])]); tree = cKDTree(Q); found = []
    for e in rts:
        r = read(e['file']); g = np.isfinite(r['lat']) & np.isfinite(r['lon'])
        if g.sum() < 2: continue
        R = xy(r['lat'][g], r['lon'][g]); L = float(np.hypot(*np.diff(R, axis=0).T).sum()); S = _fill(R, 50.0); span = int(1.25 * L / step_m) + 1
        near = np.sort(np.array(tree.query_ball_point(R[0], reach_m), int)); starts = []
        if len(near):
            for grp in np.split(near, np.flatnonzero(np.diff(near) > 50) + 1): starts.append(int(grp[np.argmin(np.hypot(*(Q[grp] - R[0]).T))]))      # the nearest point of each pass
        best = None
        for c in starts:
            for sign in (1, -1):
                lo, hi = (c, min(len(Q), c + span)) if sign > 0 else (max(0, c - span), c + 1)
                if hi - lo < 2: continue
                dd, ix = cKDTree(Q[lo:hi]).query(S); cost = float(np.mean(np.minimum(dd, 300.0)))
                if best is None or cost < best[0]: best = (cost, lo, ix, sign)
        if best is None: continue
        _, lo, ix, sign = best; first, last = float(u[lo + ix[0]]), float(u[lo + ix[-1]])
        found.append(dict(id=e['id'], key=(first + last) / 2, reversed=sign < 0, km_start=round(min(first, last) / 1000.0, 1), km_end=round(max(first, last) / 1000.0, 1), a=R[-1] if sign < 0 else R[0], b=R[0] if sign < 0 else R[-1]))
    found.sort(key=lambda x: x['key']); order = []; marks = []
    for n, f in enumerate(found, 1):
        order.append(dict(id=f['id'], order=n, reversed=f['reversed'], km_start=f['km_start'], km_end=f['km_end'], start=ll(f['a']), end=ll(f['b'])))
        if n > 1:
            p = found[n - 2]['b']; la, lo_ = ll((p + f['a']) / 2)
            marks.append(dict(n=n - 1, lat=round(la, 6), lon=round(lo_, 6), gap_m=round(float(np.hypot(*(f['a'] - p)))), before=found[n - 2]['id'], after=f['id']))
    _ORDER.clear(); _ORDER[key] = (order, marks); return order, marks


STOP_MS = 0.7                  # slower than this (m/s, over half a minute either side) is standing still
ZONE_M = 300.0                 # a checkpoint's zone: the race track inside it is the visit
VISIT_GAP_S = 120.0            # out of the zone (with samples there) for longer than this and coming back is another visit (shorter is the track wobbling at the edge)


def checkpoint_stops(rd, radius_m=ZONE_M, window_s=15.0):
    """How long the run spent at each checkpoint: {checkpoint n: {arrived, left, stopped_s, radius_m}} (times are UTC epoch seconds; checkpoints the run did not reach are left out).
    The visit is ONE pass of the race track through the zone (radius_m round the checkpoint): the one nearest to where the routes join along the race (the race can pass the same place again later; a return after more than VISIT_GAP_S outside is another visit and is not counted). The zone is large because the stop is often not exactly at the point,
    and time spent still moving on the way in or out is not counted: `arrived` is the first sample in the visit that is slower than STOP_MS and `left` the last one of the visit (speed over 2 x window_s round it, so a gap in the recording while the watch was paused counts as standing still), `stopped_s` the time between them, 0 when the run never slowed (`passed` is then when it went by: the sample nearest the checkpoint)."""
    order, marks = route_order(rd); cur = current_path(rd)
    if not marks or not cur: return {}
    from scipy.spatial import cKDTree
    run = read(cur); ok = np.isfinite(run['lat']) & np.isfinite(run['lon']) & np.isfinite(run['t']); lat, lon, t = run['lat'][ok], run['lon'][ok], run['t'][ok]
    if len(t) < 2: return {}
    lat0 = float(np.median(lat)); kx = 111320.0 * np.cos(np.radians(lat0)); ky = 110540.0
    P = np.column_stack([(lon - 5.0) * kx, (lat - lat0) * ky]); cum = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))]); tree = cKDTree(P); km = {o['id']: o for o in order}; out = {}
    for c in marks:
        cp = np.array([(c['lon'] - 5.0) * kx, (c['lat'] - lat0) * ky]); idx = np.sort(np.array(tree.query_ball_point(cp, radius_m), int))
        if not len(idx): continue
        visits = np.split(idx, np.flatnonzero((np.diff(idx) > 1) & (np.diff(t[idx]) > VISIT_GAP_S)) + 1); want = (km[c['before']]['km_end'] + km[c['after']]['km_start']) * 500.0       # (half the sum of two km, as metres); a gap of more than VISIT_GAP_S needs samples outside the zone between to be another visit: a gap with no samples at all is the watch paused, still the same visit
        v = min(visits, key=lambda g: abs(float(cum[g[len(g) // 2]]) - want)); tv = t[v]
        a = np.interp(tv - window_s, t, P[:, 0]), np.interp(tv - window_s, t, P[:, 1]); b = np.interp(tv + window_s, t, P[:, 0]), np.interp(tv + window_s, t, P[:, 1])
        speed = np.hypot(b[0] - a[0], b[1] - a[1]) / (2 * window_s); slow = np.flatnonzero(speed < STOP_MS)
        arrived, left = (float(tv[slow[0]]), float(tv[slow[-1]])) if len(slow) else (None, None)
        out[c['n']] = dict(passed=float(tv[int(np.argmin(np.hypot(*(P[v] - cp).T)))]), arrived=arrived, left=left, stopped_s=round(left - arrived) if arrived is not None else 0, radius_m=round(radius_m))
    return out


def timing(rd):
    """The time of the run split between the checkpoints and the routes: {total_s, start, end, checkpoints: {n: seconds}, sections: {route id: seconds}, ran_m: {route id: metres actually run in it}, climb: {route id: [ascent, descent] in metres}, arrivals: {n: {t (UTC), elapsed_s, km}} (arrival at each checkpoint, from the start of the run), ascent_m, descent_m (the whole run), consistent}. The run, from its first sample to its last, is cut at each checkpoint's arrival and departure (a checkpoint the run never slowed at is a moment, 0 s):
    section k is from the departure from checkpoint k - 1 (the start of the run for the first) to the arrival at checkpoint k (the end of the run for the last one reached), so the checkpoint times and the section times add up to `total_s` exactly. Routes beyond the last checkpoint the run reached have no time. `consistent` is False if the
    checkpoints came out of order along the run (a section would be negative)."""
    order, marks = route_order(rd); cur = current_path(rd)
    if not order or not cur: return {}
    stops = checkpoint_stops(rd); run = read(cur); ok = np.isfinite(run['t']) & np.isfinite(run['lat']) & np.isfinite(run['lon']); t = run['t'][ok]
    if len(t) < 2: return {}
    from strata360.gps.overview import ascent_descent
    alt = run['alt'][ok]; cum = _dist(run['lat'][ok], run['lon'][ok]); metres = lambda a, b: float(np.interp(b, t, cum) - np.interp(a, t, cum)); up_down = lambda a, b: ascent_descent(alt[(t >= a) & (t <= b)])                  # distance actually covered between two times
    t0, t1 = float(t.min()), float(t.max()); ids = [o['id'] for o in sorted(order, key=lambda o: o['order'])]; secs = {}; cps = {}; dist = {}; climb = {}; arrivals = {}; prev = t0; consistent = True
    for k, rid in enumerate(ids, 1):
        c = stops.get(k) if k < len(ids) else None
        if c is None:
            secs[rid] = t1 - prev; dist[rid] = metres(prev, t1); climb[rid] = up_down(prev, t1); consistent = consistent and t1 >= prev; break                                                   # the run ended in this section (or this is the last one)
        a = c['arrived'] if c['arrived'] is not None else c['passed']; l = c['left'] if c['left'] is not None else c['passed']
        arrivals[k] = dict(t=a, elapsed_s=round(a - t0), km=round(metres(t0, a) / 1000.0, 1)); secs[rid] = a - prev; dist[rid] = metres(prev, a); climb[rid] = up_down(prev, a); cps[k] = l - a; consistent = consistent and a >= prev and l >= a; prev = l
    return dict(total_s=round(t1 - t0), start=t0, end=t1, checkpoints={k: round(v) for k, v in cps.items()}, sections={k: round(v) for k, v in secs.items()}, ran_m={k: round(v) for k, v in dist.items()}, arrivals=arrivals, climb={k: [round(v[0]), round(v[1])] for k, v in climb.items()}, ascent_m=round(ascent_descent(alt)[0]), descent_m=round(ascent_descent(alt)[1]), consistent=bool(consistent))


def stage_schedule(rd, zone_m=ZONE_M):
    """What stage of the race it is, by time: [(UTC seconds from which it holds, label)] in order, the first from minus infinity: Before Race, At Start (until the run is more than zone_m from where it began), Stage 1, Checkpoint 1 (arrival to departure), Stage 2, ... Checkpoint N, Stage N + 1,
    At Finish (from coming within zone_m of the end of the last route; only if the run got there), After Race (from the last point of the run). Without routes the stage between start and end is just `On Course`. Empty without a run."""
    tm = timing(rd) if route_order(rd)[0] else {}
    cur = current_path(rd)
    if not cur: return []
    run = read(cur); ok = np.isfinite(run['lat']) & np.isfinite(run['lon']) & np.isfinite(run['t']); lat, lon, t = run['lat'][ok], run['lon'][ok], run['t'][ok]
    if len(t) < 2: return []
    lat0 = float(np.median(lat)); kx = 111320.0 * np.cos(np.radians(lat0)); ky = 110540.0
    gone = np.flatnonzero(np.hypot((lon - lon[0]) * kx, (lat - lat[0]) * ky) > zone_m); leave = float(t[gone[0]]) if len(gone) else float(t[-1]); t0, t1 = float(t[0]), float(t[-1])
    marks = end_markers(rd) or {}; seq = [(-np.inf, 'Before Race'), (t0, 'At Start')]
    if not tm:
        seq += [(leave, 'On Course')]
    else:
        n = len(tm['sections']); seq += [(leave, 'Stage 1')]
        for k in range(1, n):
            a = tm['arrivals'].get(k)
            if a is None: break
            seq += [(a['t'], f'Checkpoint {k}'), (a['t'] + tm['checkpoints'][k], f'Stage {k + 1}')]
        fin = marks.get('finish')
        if fin and len(seq) >= 3 and len(tm['arrivals']) == n - 1:                                                          # the run reached the last stage: did it get to the finish line?
            near = np.flatnonzero((np.hypot((lon - fin['lon']) * kx, (lat - fin['lat']) * ky) <= zone_m) & (t > seq[-1][0]))
            if len(near): seq += [(float(t[near[0]]), 'At Finish')]
    seq.append((t1, 'After Race')); times = np.maximum.accumulate(np.array([s[0] for s in seq])); return [(float(a), s[1]) for a, s in zip(times, seq)]


def stage_progress(rd, on_route_m=50.0, every_s=5.0):
    """How far along its route the run was at each moment of each stage: {'Stage N': {route_m, t (UTC seconds), prog (metres along the route)}} (t and prog are empty for a stage the run did not get to). The progress is the place on the route nearest to the run while the run is within `on_route_m` of it, and stays at the last such place while the run is off the route, so it is
    what the route says has been covered, to set beside the distance actually run (they differ when the run went off course or missed a loop). Sampled every `every_s` seconds over the stage."""
    order, _ = route_order(rd); cur = current_path(rd); sched = stage_schedule(rd)
    if not order or not cur or not sched: return {}
    from scipy.spatial import cKDTree
    run = read(cur); ok = np.isfinite(run['lat']) & np.isfinite(run['lon']) & np.isfinite(run['t']); lat, lon, t = run['lat'][ok], run['lon'][ok], run['t'][ok]
    lat0 = float(np.median(lat)); kx = 111320.0 * np.cos(np.radians(lat0)); ky = 110540.0; P = np.column_stack([(lon - 5.0) * kx, (lat - lat0) * ky]); files = {e['id']: e['file'] for e in entries(rd)}
    times = [a for a, _ in sched]; out = {}
    for o in order:
        name = f"Stage {o['order']}"; k = next((j for j, (_, l) in enumerate(sched) if l == name), None)
        if o['id'] not in files: continue
        r = read(files[o['id']]); g = np.isfinite(r['lat']) & np.isfinite(r['lon']); rl, ro = r['lat'][g], r['lon'][g]
        if o['reversed']: rl, ro = rl[::-1], ro[::-1]
        R = np.column_stack([(ro - 5.0) * kx, (rl - lat0) * ky]); s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(R, axis=0).T))]); u = np.arange(0, s[-1], 10.0); F = np.column_stack([np.interp(u, s, R[:, 0]), np.interp(u, s, R[:, 1])])
        sel = np.flatnonzero((t >= times[k]) & (t <= times[k + 1])) if k is not None and k + 1 < len(sched) else []
        if len(sel) < 2: out[name] = dict(route_m=float(s[-1]), t=np.array([]), prog=np.array([])); continue                  # a stage the run never got to still has its length (for the total of the routes)
        sel = sel[::max(1, int(every_s / max(1e-9, float(np.median(np.diff(t[sel]))) or 1.0)))]; d, nn = cKDTree(F).query(P[sel]); prog = np.where(d <= on_route_m, u[nn], np.nan)
        last = 0.0; prog = prog.copy()
        for j in range(len(prog)):                                                                  # holds at the last place on the route while off it
            if np.isfinite(prog[j]): last = prog[j]
            else: prog[j] = last
        out[name] = dict(route_m=float(s[-1]), t=t[sel], prog=prog)
    return out
