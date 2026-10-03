"""`places` stage: where was each clip? Reverse-geocode the start, middle and end of a clip (positions from the race track at the clip's UTC times) and list named places nearby.

Data comes from OpenStreetMap through two public web services (the only stage that sends anything off the machine: the coordinates of the start, middle and end of each clip):
  * Nominatim reverse geocoding (address, village/town, county, country) - https://nominatim.org/release-docs/latest/api/Reverse/
  * Overpass API (named features within `radius` metres: places, peaks, water, waterways, historic sites, amenities, leisure)
Both endpoints are configurable (`places` in race.json) so a self-hosted server can replace them. The public services ask for at most one request per second and an identifying User-Agent, so
all workers share one rate limiter (a lock file in the project's cache) and every answer is cached on disk by rounded position (about 11 m), so a repeat costs nothing.
Clips outside the race track (before the start, after the finish) get no positions and say so."""
import datetime as dt, hashlib, json, math, os, time, urllib.parse, urllib.request
from strata360 import oslib
from strata360.gps import osm

OVERPASS = 'https://overpass-api.de/api/interpreter'

SCHEMA_VERSION = 1
UA = 'strata360-personal-race-film/0.1 (local tool; reverse geocoding of my own race track)'
MIN_GAP_S = 1.1


def _throttle(cache_dir):
    os.makedirs(cache_dir, exist_ok=True); p = os.path.join(cache_dir, '.last')
    with open(p, 'a+') as f, oslib.file_lock(f):
        f.seek(0); last = float(f.read().strip() or 0); wait = last + MIN_GAP_S - time.time()
        if wait > 0: time.sleep(wait)
        f.seek(0); f.truncate(); f.write(str(time.time())); f.flush()


def _get(url, cache_dir, key, data=None, timeout=40):
    """GET/POST with the disk cache and the shared rate limit. Returns parsed json (or None on failure, which is not cached)."""
    cf = os.path.join(cache_dir, hashlib.sha1(key.encode()).hexdigest()[:20] + '.json')
    if os.path.exists(cf):
        try: return json.load(open(cf))
        except ValueError: pass
    for attempt in range(3):
        _throttle(cache_dir)
        try:
            req = urllib.request.Request(url, data=data, headers={'User-Agent': UA, 'Accept-Language': 'en'})
            out = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode()); tmp = cf + f'.{os.getpid()}.tmp'; json.dump(out, open(tmp, 'w')); os.replace(tmp, cf); return out
        except Exception:
            time.sleep(2 + 3 * attempt)
    return None


def _dist(lat1, lon1, lat2, lon2):
    r = 6371000.0; p1, p2 = math.radians(lat1), math.radians(lat2); a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def reverse(lat, lon, cache_dir, url='https://nominatim.openstreetmap.org/reverse', zoom=16):
    q = urllib.parse.urlencode(dict(format='jsonv2', lat=f'{lat:.5f}', lon=f'{lon:.5f}', zoom=zoom, addressdetails=1, namedetails=0))
    r = _get(f'{url}?{q}', cache_dir, f'rev|{url}|{lat:.4f}|{lon:.4f}|{zoom}')
    if not r or 'address' not in r: return None
    a = r['address']; keep = ('road', 'hamlet', 'village', 'suburb', 'town', 'city', 'municipality', 'county', 'state', 'country')
    return dict(display_name=r.get('display_name'), **{k: a[k] for k in keep if k in a})


def nearby(lat, lon, cache_dir, url=OVERPASS, radius=1000, limit=14):
    ql = (f'[out:json][timeout:25];('
          f'nwr(around:{radius},{lat:.5f},{lon:.5f})[name][place];'
          f'nwr(around:{radius},{lat:.5f},{lon:.5f})[name][natural~"^(peak|water|spring|cave_entrance|wood|heath|wetland|cliff|rock)$"];'
          f'nwr(around:{radius},{lat:.5f},{lon:.5f})[name][waterway~"^(river|stream|waterfall|canal)$"];'
          f'nwr(around:{radius},{lat:.5f},{lon:.5f})[name][historic];nwr(around:{radius},{lat:.5f},{lon:.5f})[name][tourism~"^(viewpoint|attraction|picnic_site|camp_site|museum|information)$"];'
          f'nwr(around:{radius},{lat:.5f},{lon:.5f})[name][amenity~"^(restaurant|cafe|bar|pub|place_of_worship|drinking_water|shelter|toilets)$"];'
          f'nwr(around:{radius},{lat:.5f},{lon:.5f})[name][leisure~"^(park|nature_reserve|sports_centre|pitch)$"];'
          f'nwr(around:{radius},{lat:.5f},{lon:.5f})[name][route~"^(hiking|foot)$"];);out center 120;')
    key = f'ovp|{url}|{lat:.3f}|{lon:.3f}|{radius}'
    if url == OVERPASS: r = osm.pool(cache_dir).query(ql, key=key)                                   # the public server: spread over the mirrors (same cache files as before)
    else: r = _get(url, cache_dir, key, data=urllib.parse.urlencode({'data': ql}).encode(), timeout=60)   # a server of your own: only that one
    if not r: return None
    seen = {};
    for e in r.get('elements', []):
        t = e.get('tags', {}); name = t.get('name'); c = e.get('center') or e
        if not name or 'lat' not in c: continue
        kind = next((f'{k}={t[k]}' for k in ('place', 'natural', 'waterway', 'historic', 'tourism', 'amenity', 'leisure', 'route') if k in t), 'feature'); d = _dist(lat, lon, c['lat'], c['lon'])
        if name not in seen or d < seen[name]['distance_m']: seen[name] = dict(name=name, kind=kind, distance_m=round(d))
    return sorted(seen.values(), key=lambda x: x['distance_m'])[:limit]


def select_points(fix, minsep=200.0):
    """Which of the start, middle and end positions are worth looking up. The middle is the reference: the start is used only if it is more than `minsep` metres from the middle, likewise the end.
    If both are within `minsep` of the middle but the start and end are themselves more than `minsep` apart, the start and end are used instead of the middle; if everything is close, only the middle.
    `fix` maps 'start'/'middle'/'end' to (lat, lon); returns the labels in time order."""
    d = lambda a, b: _dist(fix[a][0], fix[a][1], fix[b][0], fix[b][1])
    far_s, far_e = d('start', 'middle') > minsep, d('end', 'middle') > minsep
    if far_s and far_e: return ['start', 'middle', 'end']
    if far_s: return ['start', 'middle']
    if far_e: return ['middle', 'end']
    return ['start', 'end'] if d('start', 'end') > minsep else ['middle']


def analyse(clip_json, track, cache_dir, cfg=None):
    """places.json body for one clip: the start, middle and end of it (positions at those UTC instants from the race track), each with an address and named places nearby."""
    import numpy as np
    cfg = (cfg or {}).get('places', {}) or {}
    nom, ovp, radius = cfg.get('nominatim', 'https://nominatim.openstreetmap.org/reverse'), cfg.get('overpass', OVERPASS), int(cfg.get('radius_m', 1000))
    t0 = dt.datetime.fromisoformat(clip_json['time']['start_utc'].replace('Z', '+00:00')).timestamp(); dur = clip_json['video']['source_frames'] / clip_json['video']['nominal_fps']
    T = track['t']; ok = np.isfinite(track['lat'])
    if t0 + dur < T[0] - 30 or t0 > T[-1] + 30: return dict(schema=SCHEMA_VERSION, covered=False, note='outside the race track (no position for this clip)', points=[], source='OpenStreetMap (Nominatim, Overpass)')
    fixes = {}
    for label, f in (('start', 0.0), ('middle', 0.5), ('end', 1.0)):
        t = t0 + f * dur; fixes[label] = (f, float(np.interp(t, T[ok], track['lat'][ok])), float(np.interp(t, T[ok], track['lon'][ok])))
    minsep = float(cfg.get('min_separation_m', 200.0)); chosen = select_points({k: (v[1], v[2]) for k, v in fixes.items()}, minsep); pts = []
    for label in chosen:
        f, lat, lon = fixes[label]
        pts.append(dict(label=label, t_s=round(f * dur, 1), lat=round(lat, 5), lon=round(lon, 5), address=reverse(lat, lon, cache_dir, nom), nearby=nearby(lat, lon, cache_dir, ovp, radius)))
    names = []
    for p in pts:
        a = p['address'] or {}; n = a.get('hamlet') or a.get('village') or a.get('suburb') or a.get('town') or a.get('city') or a.get('municipality')
        if n and n not in names: names.append(n)
    first = pts[0]['address'] or {}
    return dict(schema=SCHEMA_VERSION, covered=True, source='OpenStreetMap (Nominatim, Overpass)', radius_m=radius, min_separation_m=minsep, points=pts,
                summary=dict(places=names, road=first.get('road'), county=first.get('county'), country=first.get('country'),
                             text=(', '.join(names) or first.get('display_name') or 'unknown') + (f" ({first['county']})" if first.get('county') else '')))


def rebuild_locations(project_root):
    """Write `<project>/locations.json`: the processed place results of every clip in one file (not the raw cache), in clip time order, plus a race-wide index of the named places seen (which clips they
    appear in and how near they came) and the sequence of villages/towns along the way. Rebuilt whenever a clip's places finish; safe to call from parallel workers (atomic replace)."""
    import glob
    clips, index, route = [], {}, []
    for d in sorted(glob.glob(os.path.join(project_root, 'clips', '*', ''))):
        try: c = json.load(open(d + 'clip.json')); pl = json.load(open(d + 'places.json'))
        except (OSError, ValueError): continue
        clips.append(dict(clip=c['clip_id'], start_utc=c['time']['start_utc'], end_utc=c['time'].get('end_utc'), covered=pl.get('covered', False), note=pl.get('note'), summary=pl.get('summary'), points=pl.get('points', [])))
        for n in (pl.get('summary') or {}).get('places', []):
            if not route or route[-1]['name'] != n: route.append(dict(name=n, first_clip=c['clip_id'], first_utc=c['time']['start_utc']))
        for p in pl.get('points', []):
            for x in (p.get('nearby') or []):
                e = index.setdefault(x['name'], dict(name=x['name'], kind=x['kind'], clips=[], nearest_m=x['distance_m']))
                if c['clip_id'] not in e['clips']: e['clips'].append(c['clip_id'])
                e['nearest_m'] = min(e['nearest_m'], x['distance_m'])
    doc = dict(schema=1, generated=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), source='OpenStreetMap (Nominatim reverse geocoding, Overpass API)', clips=clips, route=route,
               places=sorted(index.values(), key=lambda e: (e['clips'][0], e['nearest_m'])))
    p = os.path.join(project_root, 'locations.json'); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(doc, open(tmp, 'w'), indent=1, ensure_ascii=False); os.replace(tmp, p); return len(clips), len(index)
