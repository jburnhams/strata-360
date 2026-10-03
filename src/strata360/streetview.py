"""Street view for the race: which parts of the run were on a road, and what street-level imagery exists along them, from three providers. Stored in `<race_dir>/streetview/`:
  roads.json       stage `roads`: the stretches of the run track on a drivable road (gps/roads.py, OpenStreetMap through the cached mirror pool), each with its line, plus the whole run thinned for the map.
  <provider>.json  one stage per provider (`mapillary`, `panoramax`, `google`): the SECTIONS of imagery on those stretches. A section is one capture run (a Mapillary / Panoramax sequence, or a run of Google panoramas) along one stretch:
                   {id, provider, stretch, kind '360' | '2d', km0, km1, length_m, frames, spacing_m, year, camera, size, angles, items: [{id, km, lat, lon, a, b, c, t, u, h}]}.
                   For a flat ('2d') camera `a` is the way the camera faced relative to the way the runner went (0 = the same way, 90 = to the right, 180 = back at the runner) and `angles` counts the frames facing forward / right / back / left;
                   a 360 camera sees every way. `b` is the runner's bearing at that frame (to aim a panorama).
Mapillary and Panoramax images are CC BY-SA (credit them); Google's terms do not allow keeping or re-using its imagery, so its pictures are only fetched for display and never kept on disk (server/app.py).
Each provider stage records the id of the roads it was made from, and is redone when that changes.
  quality.json     stage `quality`: for each plausible Mapillary / Panoramax section, a score from 0 to 100 for how good a clip of it will look (edit/streetview_cam.py `quality`: how well the pictures between two real ones can be made, and how
                   steady the view is at 25 m/s), measured on the smaller copies of its pictures; {sections: {key: {score, grade, psnr, jerk, roll, frames}}}."""
import collections, datetime as dt, hashlib, json, math, os, time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from strata360.gps import osm, roads

SCHEMA = 1
STAGES = ('roads', 'mapillary', 'panoramax', 'google', 'quality')
PROVIDERS = ('mapillary', 'panoramax', 'google')
ON_ROAD_M = 12.0                 # a frame belongs to a stretch when it was taken this near the run's line
SPLIT_M = 60.0                   # a gap in the frames bigger than this ends a section
STEP_M = 20.0
UA = 'strata360-personal-race-film/0.1 (local tool; street-level coverage along my own race track)'
GRAPH = 'https://graph.mapillary.com/images'
PANORAMAX = 'https://api.panoramax.xyz/api/search'
GOOGLE_META = 'https://maps.googleapis.com/maps/api/streetview/metadata'
FIELDS = 'id,sequence,compass_angle,is_pano,computed_geometry,geometry,captured_at,width,height,make,model'


def adir(rd): return os.path.join(rd, 'streetview')
def _path(rd, name): return os.path.join(adir(rd), name + '.json')


def load(rd, name):
    try: return json.load(open(_path(rd, name)))
    except (OSError, ValueError): return None


def _save(rd, name, doc):
    os.makedirs(adir(rd), exist_ok=True); p = _path(rd, name); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(doc, open(tmp, 'w'), separators=(',', ':')); os.replace(tmp, p)


def _bearing(a, b):
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0])); x = math.cos(math.radians(a[0])) * math.sin(math.radians(b[0])) - math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1]))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _metres(a, b): return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])))
def _rel(angle, bearing): return (angle - bearing + 180) % 360 - 180                       # -180..180, 0 = the way the runner went
def direction(rel):
    """Which way a flat camera faced, from its angle to the runner's way: forward, right, back or left."""
    r = abs(rel); return 'forward' if r <= 45 else 'back' if r >= 135 else ('right' if rel > 0 else 'left')


def roads_id(doc): return hashlib.sha1(json.dumps([[s['km0'], s['km1']] for s in doc['stretches']]).encode()).hexdigest()[:10]


# --- stage: roads ---------------------------------------------------------------------------------------------------------------------------------------------------------------
def find_roads(track, cache_dir, svc=None, log=print):
    """roads.json body: the road stretches of `track` (a dict of lat, lon, dist arrays) and the run thinned to about every 100 m for drawing."""
    lat, lon, dist = (np.asarray(track[k], float) for k in ('lat', 'lon', 'dist'))
    out = roads.stretches(lat, lon, dist, cache_dir, svc=svc); la, lo, d = roads.sample(lat, lon, dist, STEP_M); stretches = []
    for n, s in enumerate(out, 1):
        line = [[round(float(a), 5), round(float(b), 5)] for a, b in zip(la[s['i0']:s['i1']], lo[s['i0']:s['i1']])]
        stretches.append(dict(id=f'R{n}', km0=s['km0'], km1=s['km1'], length_m=s['length_m'], highways=s['highways'], names=s['names'], line=line))
    log(f'roads: {len(stretches)} stretches, {sum(s["length_m"] for s in stretches) / 1000:.1f} km of {d[-1] / 1000:.0f} km')
    run = [[round(float(a), 4), round(float(b), 4)] for a, b in zip(la[::5], lo[::5])]
    doc = dict(schema=SCHEMA, source='OpenStreetMap (Overpass)', on_road_m=8.0, min_m=300.0, total_km=round(float(d[-1]) / 1000, 2), stretches=stretches, run=run); doc['id'] = roads_id(doc); return doc


# --- the sections of imagery on a stretch ---------------------------------------------------------------------------------------------------------------------------------------
class Line:
    """A stretch's line, with the distance along it and the runner's bearing at any point near it."""
    def __init__(self, stretch):
        self.pts = [tuple(p) for p in stretch['line']]; self.km0 = stretch['km0']; self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]): self.cum.append(self.cum[-1] + _metres(a, b))
    def locate(self, p):
        """(km along the run, metres from the line, bearing of the runner there) for the nearest point on the line (projected onto its segments)."""
        best = (1e9, 0.0, 0.0)
        for i in range(len(self.pts) - 1):
            a, b = self.pts[i], self.pts[i + 1]; k = math.cos(math.radians(a[0])) * 111320; ax, ay = (p[1] - a[1]) * k, (p[0] - a[0]) * 111320; bx, by = (b[1] - a[1]) * k, (b[0] - a[0]) * 111320
            L = bx * bx + by * by; t = 0.0 if L == 0 else max(0.0, min(1.0, (ax * bx + ay * by) / L)); d = math.hypot(ax - t * bx, ay - t * by)
            if d < best[0]: best = (d, self.cum[i] + t * math.sqrt(L), _bearing(a, b))
        return self.km0 + best[1] / 1000, best[0], best[2]
    def bbox(self, pad_m=30):
        la = [p[0] for p in self.pts]; lo = [p[1] for p in self.pts]; dl = pad_m / 111320; dn = pad_m / (111320 * math.cos(math.radians(la[0])))
        return min(lo) - dn, min(la) - dl, max(lo) + dn, max(la) + dl


def sections_of(provider, stretch, frames):
    """Group frames [{seq, km, lat, lon, a (angle or None), b, t, id, u, pano, camera, size}] of one stretch into sections: one per capture run (`seq`), split where the frames leave a gap of more than SPLIT_M."""
    by = collections.defaultdict(list)
    for f in frames: by[f['seq']].append(f)
    out = []
    for seq, fs in by.items():
        fs = sorted(fs, key=lambda f: f['km']); runs = [[fs[0]]]
        for f in fs[1:]:
            if (f['km'] - runs[-1][-1]['km']) * 1000 > SPLIT_M: runs.append([])
            runs[-1].append(f)
        for r in runs:
            gaps = [(b['km'] - a['km']) * 1000 for a, b in zip(r, r[1:])]; pano = sum(1 for f in r if f['pano']) * 2 >= len(r); camera = collections.Counter(f['camera'] for f in r if f['camera']).most_common(1)
            size = collections.Counter(tuple(f['size']) for f in r if f['size']).most_common(1)
            years = sorted({dt.datetime.fromtimestamp(f['t'], dt.timezone.utc).year for f in r if f['t']})
            sec = dict(provider=provider, stretch=stretch['id'], kind='360' if pano else '2d', km0=round(r[0]['km'], 3), km1=round(r[-1]['km'], 3), length_m=int(round((r[-1]['km'] - r[0]['km']) * 1000)), frames=len(r),
                       spacing_m=round(float(np.median(gaps)), 1) if gaps else None, years=years, camera=camera[0][0] if camera else None, size=list(size[0][0]) if size else None, seq=seq,
                       angles=None if pano else dict(collections.Counter(direction(f['a']) for f in r if f['a'] is not None)),
                       items=[{k: v for k, v in dict(id=f['id'], km=round(f['km'], 3), lat=round(f['lat'], 6), lon=round(f['lon'], 6), a=None if f['a'] is None else round(f['a']), b=round(f['b']), t=f['t'], u=f.get('u'), h=f.get('h'), c=None if f.get('c') is None else round(f['c'], 1)).items() if v is not None} for f in r])
            out.append(sec)
    return out


def _number(out):
    out.sort(key=lambda s: (s['km0'], s['provider'], s['seq'])); c = collections.Counter()
    for s in out: c[s['provider']] += 1; s['id'] = f'{s["provider"][0].upper()}{c[s["provider"]]}'
    return out


def _key(name):
    from strata360.edit import llm_remote as LR
    return LR.secret(name)


def _get(url, params, tries=3):
    for k in range(tries):
        try:
            r = requests.get(url, params=params, headers={'User-Agent': UA}, timeout=60)
            if r.status_code == 200: return r.json()
            if r.status_code in (400, 401, 403): raise RuntimeError(f'{url.split("/")[2]} refused the request ({r.status_code}): {r.text[:160]}')
        except requests.RequestException: pass
        time.sleep(2 + 3 * k)
    raise RuntimeError(f'{url.split("/")[2]} did not answer')


def find_mapillary(rdoc, token, get=_get, log=print):
    out = []
    for st in rdoc['stretches']:
        line = Line(st); w, s, e, n = line.bbox(); frames = []
        for x in get(GRAPH, dict(access_token=token, bbox=f'{w},{s},{e},{n}', fields=FIELDS, limit=2000)).get('data', []):
            g = (x.get('computed_geometry') or x.get('geometry') or {}).get('coordinates')
            if not g: continue
            km, dist, b = line.locate((g[1], g[0]))
            if dist > ON_ROAD_M: continue
            pano = bool(x.get('is_pano')); ang = x.get('compass_angle')
            frames.append(dict(seq=x.get('sequence') or x['id'], km=km, lat=g[1], lon=g[0], a=None if pano or ang is None else _rel(ang, b), b=b, c=ang, t=(x.get('captured_at') or 0) / 1000 or None, id=x['id'], pano=pano,
                               camera=' '.join(v for v in (x.get('make'), x.get('model')) if v and v != 'none') or None, size=[x['width'], x['height']] if x.get('width') else None))
        out += sections_of('mapillary', st, frames)
    log(f'mapillary: {len(out)} sections'); return _number(out)


def find_panoramax(rdoc, get=_get, log=print):
    out = []
    for st in rdoc['stretches']:
        line = Line(st); w, s, e, n = line.bbox(); frames = []
        for f in get(PANORAMAX, dict(bbox=f'{w},{s},{e},{n}', limit=1000)).get('features', []):
            g = f['geometry']['coordinates']; km, dist, b = line.locate((g[1], g[0]))
            if dist > ON_ROAD_M: continue
            p = f.get('properties', {}); cam = p.get('pers:interior_orientation') or {}; size = cam.get('sensor_array_dimensions') or []; pano = cam.get('field_of_view') == 360 or (len(size) == 2 and size[0] >= 1.9 * size[1])
            t = None
            try: t = dt.datetime.fromisoformat(p['datetime'].replace('Z', '+00:00')).timestamp()
            except (KeyError, ValueError): pass
            az = p.get('view:azimuth'); assets = f.get('assets') or {}; a = assets.get('sd') or assets.get('hd') or {}
            frames.append(dict(seq=f.get('collection') or f['id'], km=km, lat=g[1], lon=g[0], a=None if pano or az is None else _rel(az, b), b=b, c=az, t=t, id=f['id'], u=a.get('href'), h=(assets.get('hd') or {}).get('href'), pano=pano,
                               camera=' '.join(v for v in (cam.get('camera_manufacturer'), cam.get('camera_model')) if v) or None, size=list(size) if len(size) == 2 else None))
        out += sections_of('panoramax', st, frames)
    log(f'panoramax: {len(out)} sections'); return _number(out)


def find_google(rdoc, key, get=_get, log=print, workers=8):
    """Google panoramas along the stretches, one metadata question (free) per sample point of the stretch every STEP_M: a pano is a frame, and a capture run is the panoramas in a row."""
    jobs = []
    for st in rdoc['stretches']:
        line = Line(st)
        for i, p in enumerate(line.pts): jobs.append((st, line, i, p))
    def ask(j):
        st, line, i, p = j; b = _bearing(line.pts[max(0, i - 1)], line.pts[min(len(line.pts) - 1, i + 1)])
        return j, get(GOOGLE_META, dict(location=f'{p[0]:.6f},{p[1]:.6f}', radius=20, source='outdoor', key=key)), b
    with ThreadPoolExecutor(workers) as ex: res = list(ex.map(ask, jobs))
    bad = [m for _, m, _ in res if m.get('status') not in ('OK', 'ZERO_RESULTS')]
    if bad: raise RuntimeError(f'Google refused the Street View lookup: {bad[0].get("status")} {bad[0].get("error_message", "")[:160]}')
    out = []
    for st in rdoc['stretches']:
        frames = []; seen = {}
        for (s2, line, i, p), m, b in res:
            if s2 is not st or m.get('status') != 'OK' or m['pano_id'] in seen: continue
            loc = m['location']; km = line.locate((loc['lat'], loc['lng']))[0]; seen[m['pano_id']] = 1
            try: t = dt.datetime.strptime(m.get('date', ''), '%Y-%m').replace(tzinfo=dt.timezone.utc).timestamp()
            except ValueError: t = None
            frames.append(dict(seq='g', km=km, lat=loc['lat'], lon=loc['lng'], a=None, b=b, t=t, id=m['pano_id'], pano=True, camera='Google Street View car', size=None))
        out += sections_of('google', st, frames)
    log(f'google: {len(out)} sections'); return _number(out)


def provider_doc(provider, sections, rdoc): return dict(schema=SCHEMA, provider=provider, roads=rdoc['id'], generated=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), sections=sections, frames=sum(s['frames'] for s in sections),
                                                        km=round(sum(s['length_m'] for s in sections) / 1000, 2))


def quality_of(rd): return (load(rd, 'quality') or {}).get('sections') or {}


def find_quality(rd, rdoc, force=False, log=print, measure=None, fetch=None):
    """Score the plausible Mapillary / Panoramax sections that have no score yet (or whose pictures changed): fetch the smaller copies of their pictures and measure (edit/streetview_cam.py `quality`). Saved after each section so a long run
    keeps what it did. Returns the keys scored. A section that cannot be measured is recorded with its error."""
    from strata360.edit import streetview_cam as CAM
    measure = measure or CAM.quality; fetch = fetch or CAM.fetch; docs = {p: load(rd, p) for p in PROVIDERS}; done = quality_of(rd) if not force else {}; roads = {x['id']: x for x in rdoc['stretches']}; made = []
    todo = [x for x in annotate(rd, docs) if x['plausible'] and x['provider'] != 'google' and (x['key'] not in done or done[x['key']].get('frames') != x['frames'])]
    for n, x in enumerate(todo, 1):
        st = roads.get(x['stretch']); road = dict(line=st['line'], km0=st['km0']) if st else None
        try:
            if x['provider'] == 'mapillary' and not _key('MAPILLARY_TOKEN'): raise RuntimeError('no MAPILLARY_TOKEN in secrets.env')
            fetch(rd, x, token=_key('MAPILLARY_TOKEN'), log=lambda *_: None, preview=True); m = measure(rd, x, road=road); m['grade'] = CAM.grade(m['score']); m['frames'] = x['frames']; done[x['key']] = m
        except Exception as e:                                                                                              # (this section only: the rest are still measured)
            done[x['key']] = dict(error=f'{type(e).__name__}: {e}'[:200], frames=x['frames'], score=None, grade=None)
        made.append(x['key']); _save(rd, 'quality', dict(schema=SCHEMA, generated=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), sections=done)); log(f"quality {n}/{len(todo)}: {x['provider']} {x['id']} " + (f"{done[x['key']]['score']} ({done[x['key']]['grade']})" if done[x['key']].get('score') is not None else 'could not be measured'))
    return made


def status(rd):
    """What exists: for each stage whether it is done, out of date (its roads changed) or not done, with counts."""
    r = load(rd, 'roads'); out = dict(roads=dict(done=bool(r), stretches=len(r['stretches']) if r else 0, km=round(sum(s['length_m'] for s in r['stretches']) / 1000, 1) if r else 0))
    q = (load(rd, 'quality') or {}).get('sections') or {}; out['quality'] = dict(done=bool(q), scored=sum(1 for v in q.values() if v.get('score') is not None), km=0)
    for p in PROVIDERS:
        d = load(rd, p); out[p] = dict(done=bool(d), stale=bool(d and r and d.get('roads') != r.get('id')), sections=len(d['sections']) if d else 0, frames=d['frames'] if d else 0, km=d['km'] if d else 0)
    return out


def run(rd, track, stages=None, force=False, log=print, svc=None, get=_get, measure=None, fetch=None):
    """Make the stages (all by default) that are missing or out of date; a provider stage needs the roads."""
    stages = [s for s in (stages or STAGES)]
    bad = [s for s in stages if s not in STAGES]
    if bad: raise ValueError(f'unknown street view stage(s) {", ".join(bad)}: one of {", ".join(STAGES)}')
    done = []
    if 'roads' in stages and (force or not load(rd, 'roads')):
        _save(rd, 'roads', find_roads(track, os.path.join(rd, 'cache', 'osm'), svc=svc, log=log)); done.append('roads')
    rdoc = load(rd, 'roads')
    for p in [s for s in stages if s in PROVIDERS]:
        if rdoc is None: raise RuntimeError('street view: run the roads stage first')
        cur = load(rd, p)
        if cur and cur.get('roads') == rdoc['id'] and not force: continue
        if p == 'mapillary':
            tok = _key('MAPILLARY_TOKEN')
            if not tok: raise RuntimeError('mapillary: no MAPILLARY_TOKEN in secrets.env (a free token from mapillary.com/developer)')
            secs = find_mapillary(rdoc, tok, get, log)
        elif p == 'panoramax': secs = find_panoramax(rdoc, get, log)
        else:
            key = _key('GOOGLE_MAPS_API_KEY')
            if not key: raise RuntimeError('google: no GOOGLE_MAPS_API_KEY in secrets.env (a Google Maps Platform key with the Street View Static API enabled)')
            secs = find_google(rdoc, key, get, log)
        _save(rd, p, provider_doc(p, secs, rdoc)); done.append(p)
    if 'quality' in stages:
        if rdoc is None: raise RuntimeError('street view: run the roads stage first')
        if find_quality(rd, rdoc, force, log, measure, fetch): done.append('quality')
    return done


# --- pictures (the page asks the server, which fetches and keeps them; the keys never reach the browser) ---------------------------------------------------------------------
def find_item(doc, item_id):
    for s in (doc or {}).get('sections', []):
        for it in s['items']:
            if it['id'] == item_id: return s, it
    return None, None


def _bytes(url, params=None):
    r = requests.get(url, params=params, headers={'User-Agent': UA}, timeout=60)
    if r.status_code != 200: raise RuntimeError(f'{url.split("/")[2]} answered {r.status_code}')
    return r.content


def image(rd, provider, doc, item_id, w=640, fetch=_bytes, get=_get):
    """JPEG bytes of one frame of a section in `doc`: Mapillary (the 256 / 1024 / 2048 px copy) and Panoramax are kept in streetview/img/; Google's is fetched each time and never kept (its terms). KeyError if the frame is not in the doc."""
    sec, it = find_item(doc, item_id)
    if it is None: raise KeyError(item_id)
    rd_img = os.path.join(adir(rd), 'img'); w = 256 if w <= 256 else 1024 if w <= 1024 else 2048
    if provider == 'google':
        key = _key('GOOGLE_MAPS_API_KEY')
        if not key: raise RuntimeError('google: no GOOGLE_MAPS_API_KEY in secrets.env')
        return fetch('https://maps.googleapis.com/maps/api/streetview', dict(size='640x400', pano=item_id, heading=it['b'], fov=90, pitch=0, key=key))
    f = os.path.join(rd_img, f'{provider[0]}-{item_id}-{w}.jpg')
    if os.path.exists(f): return open(f, 'rb').read()
    if provider == 'mapillary':
        tok = _key('MAPILLARY_TOKEN')
        if not tok: raise RuntimeError('mapillary: no MAPILLARY_TOKEN in secrets.env')
        url = get(f'https://graph.mapillary.com/{item_id}', dict(access_token=tok, fields=f'thumb_{w}_url')).get(f'thumb_{w}_url')
        if not url: raise RuntimeError('mapillary has no picture for this frame')
        data = fetch(url)
    elif provider == 'panoramax':
        if not it.get('u'): raise RuntimeError('panoramax gave no picture address for this frame')
        data = fetch(it['u'])
    else: raise KeyError(provider)
    os.makedirs(rd_img, exist_ok=True); tmp = f'{f}.{os.getpid()}.tmp'; open(tmp, 'wb').write(data); os.replace(tmp, f); return data


# --- which sections are worth showing, which overlap, and what you chose ----------------------------------------------------------------------------------------------------------
MIN_FRAMES, MIN_LENGTH_M, MAX_SPACING_M = 30, 150, 10.0       # a section is plausible when it has this many pictures (2 s of film at 15 a second), is this long and has pictures no further apart than this
PLAY_FPS = 15                                                    # how many source pictures a second the film shows
SLOWEST = 4.0                                                    # pictures a second: the slowest a section can be played and still blend smoothly (the film's frames in between are made by blending neighbours). There is no fastest: pictures are just skipped
CHOICES = ('possible', 'must')


def clip_range(s):
    """(shortest, longest) clip in seconds the section can make: as short as any clip may be (2 s: played faster, with pictures skipped) up to the slowest it can go, SLOWEST pictures a second blended up to the film's frame rate. Only the part that
    matches the run's GPS is counted (the pictures are within ON_ROAD_M of it)."""
    return 2.0, round(s['frames'] / SLOWEST, 1)


def steadying(s):
    """How well the clip's camera can be kept steady: 'exact' (a 360 camera whose true rotation Mapillary reconstructed), 'estimated' (a 360 camera levelled from the picture itself) or 'by matching only' (a flat camera: the far field of neighbouring pictures is matched, and it may still wobble)."""
    return 'by matching only' if s['kind'] != '360' else 'exact' if s['provider'] == 'mapillary' else 'estimated'


def section_key(s): return f"{s['provider']}:{s['seq']}:{s['km0']:.2f}"                  # stays the same when the stage is run again (the numbers M1.. may move)


def judge(s):
    """(plausible, why not): whether a section has enough pictures, close enough together, over enough road, to make a clip of it. Google's are never offered (its terms do not allow its pictures in a film; kept for looking at only)."""
    if s['provider'] == 'google': return False, 'Google\'s terms do not allow its pictures in a film'
    if s['frames'] < MIN_FRAMES: return False, f"only {s['frames']} pictures (needs {MIN_FRAMES})"
    if s['length_m'] < MIN_LENGTH_M: return False, f"only {s['length_m']} m long (needs {MIN_LENGTH_M} m)"
    if s['spacing_m'] is None or s['spacing_m'] > MAX_SPACING_M: return False, f"pictures {s['spacing_m']} m apart (needs {MAX_SPACING_M:g} m or less)"
    return True, ''


def overlaps(sections, share=0.3):
    """{id: [ids of the sections that cover the same road]}: two sections overlap when the stretch they share is at least `share` of the shorter one. Same road, different source or date."""
    out = {s['id']: [] for s in sections}
    for i, a in enumerate(sections):
        for b in sections[i + 1:]:
            both = min(a['km1'], b['km1']) - max(a['km0'], b['km0'])
            if both > 0 and both * 1000 >= share * min(a['length_m'], b['length_m'], 1e9): out[a['id']].append(b['id']); out[b['id']].append(a['id'])
    return out


def _state(rd):
    try: d = json.load(open(os.path.join(adir(rd), 'choices.json')))
    except (OSError, ValueError): d = {}
    return dict(choices={k: v for k, v in (d.get('choices') or {}).items() if v in CHOICES}, labels=d.get('labels') or {}, next=int(d.get('next') or 1))


def choices(rd): return _state(rd)['choices']


def set_choice(rd, key, choice):
    """Mark a section (by its key) as `possible` or `must` for the film, or clear it with 'none'. A section that is chosen gets a label V1, V2 ... for good (the script and the plan refer to it by that name). Returns the choice."""
    if choice not in (*CHOICES, 'none'): raise ValueError(f'choice is one of {", ".join(CHOICES)} or none')
    st = _state(rd)
    if choice == 'none': st['choices'].pop(key, None)
    else:
        st['choices'][key] = choice
        if key not in st['labels']: st['labels'][key] = st['next']; st['next'] += 1
    os.makedirs(adir(rd), exist_ok=True); p = os.path.join(adir(rd), 'choices.json'); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(st, open(tmp, 'w'), indent=1); os.replace(tmp, p); return choice


BRIGHT, DARK = {'day', 'golden hour'}, {'twilight', 'night'}


def light(sec, tr):
    """The light a section was filmed in against the light the runner had there: {captured, race, warning}. The warning says so when a daytime view would be shown for a stretch run in the dark (or the other way round); None when they fit or are unknown. `tr` is the race track."""
    from strata360.gps import context as X, clock as CK
    d, t = track_dist(tr); mid = sec['items'][len(sec['items']) // 2]; caps = sorted(i['t'] for i in sec['items'] if i.get('t')); cap_t = caps[len(caps) // 2] if caps else None
    race_t = float(np.interp((sec['km0'] + sec['km1']) / 2 * 1000, d, t)); day = lambda tt: X.daylight(CK.sun_elevation_deg(mid['lat'], mid['lon'], tt)) if tt else None; cap, race = day(cap_t), day(race_t); warn = None
    said = {'day': 'in daylight', 'golden hour': 'in golden-hour light', 'twilight': 'at twilight', 'night': 'at night'}
    if (cap in BRIGHT and race in DARK) or (cap in DARK and race in BRIGHT): warn = f'Filmed {said[cap]}, but the runner passes here {said[race]}: it would look wrong in the film.'
    return dict(captured=cap, race=race, warning=warn)


def annotate(rd, docs, tr=None):
    """Every section of the provider docs {provider: doc or None} (and, with the race track `tr`, the light they were filmed in against the race's there) with what the page needs: key, plausible (and why not), pictures' play time and apparent speed at PLAY_FPS, the ids it overlaps, and the choice. Sorted by km."""
    out = [dict(s) for p in PROVIDERS for s in (docs.get(p) or {}).get('sections', [])]; ov = overlaps(out); st = _state(rd); ch = st['choices']; qs = quality_of(rd)
    for s in out:
        s['key'] = section_key(s); s['plausible'], s['why_not'] = judge(s); s['play_s'] = round(s['frames'] / PLAY_FPS, 1); s['min_s'], s['max_s'] = clip_range(s); s['speed_ms'] = round(s['spacing_m'] * PLAY_FPS, 1) if s['spacing_m'] else None
        s['steadied'] = steadying(s); q = qs.get(s['key']); s['quality'] = dict(score=q.get('score'), grade=q.get('grade'), psnr=q.get('psnr'), jerk=q.get('jerk'), roll=q.get('roll'), error=q.get('error')) if q and q.get('frames') == s['frames'] else None; s['light'] = light(s, tr) if tr is not None and s['items'] else None; s['overlaps'] = ov[s['id']]; s['choice'] = ch.get(s['key']); s['label'] = f"V{st['labels'][s['key']]}" if s['key'] in st['labels'] and s['choice'] else None
    return sorted(out, key=lambda s: (s['km0'], s['provider']))


def chosen(rd, docs):
    """The sections chosen for the film (and plausible), in km order, each with its label V1..."""
    return [s for s in annotate(rd, docs) if s['choice'] and s['plausible'] and s['label']]


def track_dist(tr):
    """(dist, t) arrays of the race track, over the fixes that have a position and a time: the distance along the run in metres (the track's own, or worked out from the positions when a GPX has none)."""
    from strata360.gps import tracks as TKS
    ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon']) & np.isfinite(tr['t']); t = np.asarray(tr['t'])[ok]; d = np.asarray(tr['dist'], float)[ok] if 'dist' in tr else np.full(int(ok.sum()), np.nan)
    if not np.isfinite(d).all(): d = TKS._dist(np.asarray(tr['lat'])[ok], np.asarray(tr['lon'])[ok])
    return d, t
