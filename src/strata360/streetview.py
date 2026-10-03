"""Street view for the race: which parts of the run were on a road, and what street-level imagery exists along them, from three providers. Stored in `<race_dir>/streetview/`:
  roads.json       stage `roads`: the stretches of the run track on a drivable road (gps/roads.py, OpenStreetMap through the cached mirror pool), each with its line, plus the whole run thinned for the map.
  <provider>.json  one stage per provider (`mapillary`, `panoramax`, `google`): the SECTIONS of imagery on those stretches. A section is one capture run (a Mapillary / Panoramax sequence, or a run of Google panoramas) along one stretch:
                   {id, provider, stretch, kind '360' | '2d', km0, km1, length_m, frames, spacing_m, year, camera, size, angles, items: [{id, km, lat, lon, a, b, c, t, u, h}]}.
                   For a flat ('2d') camera `a` is the way the camera faced relative to the way the runner went (0 = the same way, 90 = to the right, 180 = back at the runner) and `angles` counts the frames facing forward / right / back / left;
                   a 360 camera sees every way. `b` is the runner's bearing at that frame (to aim a panorama).
Mapillary and Panoramax images are CC BY-SA (credit them); Google's are credited "© Google". All three are kept in streetview/img/ and streetview/src/ once fetched (a Google view costs a request each, so it is fetched once). `manual.json` holds sections promoted from the click-the-map search (they stay when the stages are run again).
Each provider stage records the id of the roads it was made from, and is redone when that changes.
  quality.json     stage `quality`: for each plausible Mapillary / Panoramax section, a score from 0 to 100 for how good a clip of it will look (edit/streetview_cam.py `quality`: how well the pictures between two real ones can be made, and how
                   steady the view is at 25 m/s), measured on the smaller copies of its pictures; {sections: {key: {score, grade, psnr, jerk, roll, frames}}}."""
import collections, datetime as dt, hashlib, json, math, os, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

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
    out = roads.stretches(lat, lon, dist, cache_dir, on_m=ON_ROAD_M, svc=svc); la, lo, d = roads.sample(lat, lon, dist, STEP_M); stretches = []
    for n, s in enumerate(out, 1):
        line = [[round(float(a), 5), round(float(b), 5)] for a, b in zip(la[s['i0']:s['i1']], lo[s['i0']:s['i1']])]
        stretches.append(dict(id=f'R{n}', km0=s['km0'], km1=s['km1'], length_m=s['length_m'], highways=s['highways'], names=s['names'], line=line))
    log(f'roads: {len(stretches)} stretches, {sum(s["length_m"] for s in stretches) / 1000:.1f} km of {d[-1] / 1000:.0f} km')
    run = [[round(float(a), 4), round(float(b), 4)] for a, b in zip(la[::5], lo[::5])]
    doc = dict(schema=SCHEMA, source='OpenStreetMap (Overpass)', on_road_m=ON_ROAD_M, min_m=300.0, total_km=round(float(d[-1]) / 1000, 2), stretches=stretches, run=run); doc['id'] = roads_id(doc); return doc


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


def _open(url, params=None, timeout=60):
    """(status, body bytes) of a GET with the identifying User-Agent; an error status is returned, not raised (None, b'' when the server cannot be reached)."""
    if params: url = url + ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=timeout) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
    except (urllib.error.URLError, OSError, ValueError): return None, b''


def _get(url, params, tries=3):
    for k in range(tries):
        status, body = _open(url, params)
        if status == 200:
            try: return json.loads(body.decode())
            except ValueError: pass
        elif status in (400, 401, 403): raise RuntimeError(f'{url.split("/")[2]} refused the request ({status}): {body.decode(errors="replace")[:160]}')
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
    measure = measure or CAM.quality; fetch = fetch or CAM.fetch; docs = {p: load(rd, p) for p in PROVIDERS}; done = quality_of(rd) if not force else {}; made = []
    todo = [x for x in annotate(rd, docs) if x['plausible'] and (x['key'] not in done or done[x['key']].get('frames') != x['frames'])]
    for n, x in enumerate(todo, 1):
        road = road_of(rd, x)
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
def find_item(doc, item_id, extra=()):
    for s in [*(doc or {}).get('sections', []), *extra]:
        for it in s['items']:
            if it['id'] == item_id: return s, it
    return None, None


def _bytes(url, params=None):
    status, body = _open(url, params)
    if status != 200: raise RuntimeError(f'{url.split("/")[2]} answered {status}')
    return body


def image(rd, provider, doc, item_id, w=640, fetch=_bytes, get=_get):
    """JPEG bytes of one frame of a section in `doc`: Mapillary (the 256 / 1024 / 2048 px copy), Panoramax and Google (a 640 px view along the road) are kept in streetview/img/. KeyError if the frame is not in the doc."""
    sec, it = find_item(doc, item_id, [x for x in manual_sections(rd) if x['provider'] == provider])
    if it is None: raise KeyError(item_id)
    rd_img = os.path.join(adir(rd), 'img'); w = 256 if w <= 256 else 1024 if w <= 1024 else 2048
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
    elif provider == 'google':
        key = _key('GOOGLE_MAPS_API_KEY')
        if not key: raise RuntimeError('google: no GOOGLE_MAPS_API_KEY in secrets.env')
        data = fetch('https://maps.googleapis.com/maps/api/streetview', dict(size='640x400', pano=item_id, heading=it['b'], fov=90, pitch=0, key=key))
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
    """How well the clip's camera can be kept steady: 'exact' (a 360 camera whose true rotation Mapillary reconstructed, or a Google panorama, which is levelled and north-referenced), 'estimated' (a 360 camera levelled from the picture itself) or 'by matching only' (a flat camera: the far field of neighbouring pictures is matched, and it may still wobble)."""
    return 'by matching only' if s['kind'] != '360' else 'estimated' if s['provider'] == 'panoramax' else 'exact'


def section_key(s): return f"{s['provider']}:{s['seq']}:{s['km0']:.2f}"                  # stays the same when the stage is run again (the numbers M1.. may move)


def judge(s):
    """(plausible, why not): whether a section has enough pictures, close enough together, over enough road, to make a clip of it."""
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
    return dict(choices={k: v for k, v in (d.get('choices') or {}).items() if v in CHOICES}, labels=d.get('labels') or {}, next=int(d.get('next') or 1), lengths={k: float(v) for k, v in (d.get('lengths') or {}).items() if isinstance(v, (int, float))})


def choices(rd): return _state(rd)['choices']


def set_choice(rd, key, choice):
    """Mark a section (by its key) as `possible` or `must` for the film, or clear it with 'none'. A section that is chosen gets a label V1, V2 ... for good (the script and the plan refer to it by that name). Returns the choice."""
    if choice not in (*CHOICES, 'none'): raise ValueError(f'choice is one of {", ".join(CHOICES)} or none')
    st = _state(rd)
    if choice == 'none': st['choices'].pop(key, None)
    else:
        st['choices'][key] = choice
        if key not in st['labels']: st['labels'][key] = st['next']; st['next'] += 1
    _save_state(rd, st); return choice


def _save_state(rd, st):
    os.makedirs(adir(rd), exist_ok=True); p = os.path.join(adir(rd), 'choices.json'); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(st, open(tmp, 'w'), indent=1); os.replace(tmp, p)


def set_length(rd, s, seconds):
    """Fix how long the film shows a section (an annotated one), within what it can play (`min_s` to `max_s`), or leave it to the plan with None. Returns the length or None. ValueError when it is not allowed."""
    st = _state(rd)
    if seconds is None: st['lengths'].pop(s['key'], None); _save_state(rd, st); return None
    try: v = round(float(seconds), 1)
    except (TypeError, ValueError): raise ValueError('the length is a number of seconds')
    if not s['min_s'] <= v <= s['max_s']: raise ValueError(f"this section can play {s['min_s']} to {s['max_s']} seconds")
    st['lengths'][s['key']] = v; _save_state(rd, st); return v


LIT, DARK_BELOW = 0.0, -6.0       # the sun's height (degrees): at or above LIT the scene is lit by the sun; below DARK_BELOW (past civil twilight) it is dark. Between them is dusk or dawn: it fits either


def sun_phrase(e):
    """The sun's height in words: 'the sun 6° above the horizon (daylight)'."""
    return f'the sun {abs(e):.0f}° {"above" if e >= 0 else "below"} the horizon ({"daylight" if e > 6 else "golden-hour light" if e >= 0 else "dusk or dawn" if e >= DARK_BELOW else "dark"})'


def light_between(lat, lon, cap_t, race_t):
    """The light of a picture taken at `cap_t` against the light the runner had at `race_t` at the same place (epoch seconds; cap_t may be None): {captured, race, captured_sun, race_sun, warning}; see `light`."""
    from strata360.gps import context as X, clock as CK
    sun = lambda tt: float(CK.sun_elevation_deg(lat, lon, tt)) if tt else None; ce, re = sun(cap_t), sun(race_t); warn = None
    if ce is not None and ((ce >= LIT and re < DARK_BELOW) or (ce < DARK_BELOW and re >= LIT)): warn = f'Filmed with {sun_phrase(ce)}, but the runner passes here with {sun_phrase(re)}: it would look wrong in the film.'
    return dict(captured=None if ce is None else X.daylight(ce), race=X.daylight(re), captured_sun=None if ce is None else round(ce, 1), race_sun=round(re, 1), warning=warn)


def light(sec, tr):
    """The light a section was filmed in against the light the runner had there, from the sun's height at the real date, time and place of each (so the time of year counts: 19:00 in February is dark, in July broad daylight): {captured, race, captured_sun, race_sun, warning}.
    The warning says so when a view lit by the sun would be shown for a stretch run in the dark (past civil twilight), or the other way round, and gives both heights; None when they fit (dusk and dawn fit either) or are unknown. `tr` is the race track."""
    d, t = track_dist(tr); mid = sec['items'][len(sec['items']) // 2]; caps = sorted(i['t'] for i in sec['items'] if i.get('t')); cap_t = caps[len(caps) // 2] if caps else None
    return light_between(mid['lat'], mid['lon'], cap_t, float(np.interp((sec['km0'] + sec['km1']) / 2 * 1000, d, t)))


def passed(s, tr):
    """[start, end] (epoch seconds) of the time the runner took over the section, from the race track."""
    d, t = track_dist(tr); return [float(np.interp(s['km0'] * 1000, d, t)), float(np.interp(s['km1'] * 1000, d, t))]


def nearest_clips(s, clips, tr, gaps=None):
    """Where a section sits among the camera clips along the run: {before, after, overlaps, in_gap}. `before` and `after` are the nearest clip ending before the section starts and the nearest one starting after it ends, as {label, seconds, km} (the time and the distance
    along the run between them and the section: 0 would mean touching); `overlaps` are the labels of the clips that cover any of the section's time; `in_gap` is the id of the gap in the footage that holds all of it. `clips` are [{label, t0, t1}] (epoch seconds), `gaps` [{id, t0, t1}]; None without the section's pass time."""
    if s.get('passed') is None or clips is None: return None
    p0, p1 = s['passed']; d, t = track_dist(tr); at = lambda x: float(np.interp(x, t, d)); before = after = None
    for c in clips:
        if c['t1'] <= p0 and (before is None or c['t1'] > before['t']): before = dict(label=c['label'], t=c['t1'], seconds=round(p0 - c['t1']), km=round((at(p0) - at(c['t1'])) / 1000.0, 2))
        if c['t0'] >= p1 and (after is None or c['t0'] < after['t']): after = dict(label=c['label'], t=c['t0'], seconds=round(c['t0'] - p1), km=round((at(c['t0']) - at(p1)) / 1000.0, 2))
    strip = lambda x: None if x is None else {k: v for k, v in x.items() if k != 't'}
    return dict(before=strip(before), after=strip(after), overlaps=[c['label'] for c in clips if c['t0'] < p1 and c['t1'] > p0], in_gap=next((g['id'] for g in gaps or [] if g['t0'] <= p0 and p1 <= g['t1']), None))


def annotate(rd, docs, tr=None, clips=None, gaps=None):
    """Every section of the provider docs {provider: doc or None} (and, with the race track `tr`, the light they were filmed in against the race's there) with what the page needs: key, plausible (and why not), pictures' play time and apparent speed at PLAY_FPS, the ids it overlaps, and the choice. Sorted by km."""
    out = [dict(s) for p in PROVIDERS for s in (docs.get(p) or {}).get('sections', [])]; have = {section_key(s) for s in out}; out += [dict(s) for s in manual_sections(rd) if section_key(s) not in have]; ov = overlaps(out); st = _state(rd); ch = st['choices']; qs = quality_of(rd)
    for s in out:
        s['key'] = section_key(s); s['plausible'], s['why_not'] = judge(s); s['play_s'] = round(s['frames'] / PLAY_FPS, 1); s['min_s'], s['max_s'] = clip_range(s); s['speed_ms'] = round(s['spacing_m'] * PLAY_FPS, 1) if s['spacing_m'] else None
        s['steadied'] = steadying(s); q = qs.get(s['key']); s['quality'] = dict(score=q.get('score'), grade=q.get('grade'), psnr=q.get('psnr'), jerk=q.get('jerk'), roll=q.get('roll'), error=q.get('error')) if q and q.get('frames') == s['frames'] else None; caps = [i['t'] for i in s['items'] if i.get('t')]; s['filmed'] = [min(caps), max(caps)] if caps else None; s['passed'] = passed(s, tr) if tr is not None else None; s['has_video'] = os.path.exists(video_path(rd, s)); s['near'] = nearest_clips(s, clips, tr, gaps) if tr is not None else None; s['light'] = light(s, tr) if tr is not None and s['items'] else None; s['overlaps'] = ov[s['id']]; s['choice'] = ch.get(s['key']); s['seconds'] = st['lengths'].get(s['key']); s['label'] = f"V{st['labels'][s['key']]}" if s['key'] in st['labels'] and s['choice'] else None
    return sorted(out, key=lambda s: (s['km0'], s['provider']))


VIDEO_VERSION = 1                 # bumped when the camera changes so the preview videos are made again
PREVIEW_MS = 25.0                 # the road speed a preview video plays at (m/s), within the clip lengths the section can make
PREVIEW_SIZE = (960, 540)


def default_seconds(s):
    """How long the preview video of a section is: its stretch at PREVIEW_MS, held to what the section can play."""
    lo, hi = clip_range(s); return round(max(lo, min(s['length_m'] / PREVIEW_MS, hi)), 1)


def video_path(rd, s, pano=False):
    """Where the preview video of a (annotated) section is kept: named by the section and by what it is made from, so a changed section or camera gets a new one."""
    h = hashlib.sha1(json.dumps([s['key'], s['frames'], default_seconds(s), VIDEO_VERSION, 'pano' if pano else 'view'], sort_keys=True).encode()).hexdigest()[:12]; return os.path.join(adir(rd), 'video', f"{s['id']}-{h}{'-360' if pano else ''}.mp4")


def make_video(rd, s, log=print, pano=False):
    """Make the preview video of an (annotated) Mapillary or Panoramax section with the app's own camera, from the smaller copies of its pictures; kept (a finished one is not made again). Returns the path."""
    from strata360.edit import streetview_cam as CAM
    out = video_path(rd, s, pano)
    if os.path.exists(out): return out
    CAM.fetch(rd, s, token=_key('MAPILLARY_TOKEN'), log=log, preview=True); os.makedirs(os.path.dirname(out), exist_ok=True)
    if pano: CAM.render_pano(rd, s, default_seconds(s), out, road=road_of(rd, s), log=log); return out
    CAM.render(rd, s, default_seconds(s), out, road=road_of(rd, s), size=PREVIEW_SIZE, preview=True, log=log); return out


def chosen(rd, docs):
    """The sections chosen for the film, in km order, each with its label V1... Any section can be chosen, even one too short or too sparse to be a candidate: that is the user's call."""
    return [s for s in annotate(rd, docs) if s['choice'] and s['label']]


def track_dist(tr):
    """(dist, t) arrays of the race track, over the fixes that have a position and a time: the distance along the run in metres (the track's own, or worked out from the positions when a GPX has none)."""
    from strata360.gps import tracks as TKS
    ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon']) & np.isfinite(tr['t']); t = np.asarray(tr['t'])[ok]; d = np.asarray(tr['dist'], float)[ok] if 'dist' in tr else np.full(int(ok.sum()), np.nan)
    if not np.isfinite(d).all(): d = TKS._dist(np.asarray(tr['lat'])[ok], np.asarray(tr['lon'])[ok])
    return d, t


# --- what is nearest to a point you click on the map ----------------------------------------------------------------------------------------------------------------------------------------
NEAR_RADII = (100.0, 250.0, 500.0)          # metres: the search widens until enough capture runs are found
GOOGLE_RING_M = (20.0, 45.0, 80.0)


def _box(lat, lon, r):
    dl = r / 111320.0; dn = r / (111320.0 * math.cos(math.radians(lat))); return lon - dn, lat - dl, lon + dn, lat + dl


def _frames_mapillary(lat, lon, r, token, get):
    w, s, e, n = _box(lat, lon, r); out = []
    for x in get(GRAPH, dict(access_token=token, bbox=f'{w},{s},{e},{n}', fields=FIELDS, limit=2000)).get('data', []):
        g = (x.get('computed_geometry') or x.get('geometry') or {}).get('coordinates')
        if g: out.append(dict(seq=x.get('sequence') or x['id'], id=x['id'], lat=g[1], lon=g[0], compass=x.get('compass_angle'), pano=bool(x.get('is_pano')), t=(x.get('captured_at') or 0) / 1000 or None,
                              camera=' '.join(v for v in (x.get('make'), x.get('model')) if v and v != 'none') or None, size=[x['width'], x['height']] if x.get('width') else None, url=None))
    return out


def _frames_panoramax(lat, lon, r, token, get):
    w, s, e, n = _box(lat, lon, r); out = []
    for f in get(PANORAMAX, dict(bbox=f'{w},{s},{e},{n}', limit=1000)).get('features', []):
        g = f['geometry']['coordinates']; p = f.get('properties', {}); cam = p.get('pers:interior_orientation') or {}; size = cam.get('sensor_array_dimensions') or []; t = None
        try: t = dt.datetime.fromisoformat(p['datetime'].replace('Z', '+00:00')).timestamp()
        except (KeyError, ValueError): pass
        out.append(dict(seq=f.get('collection') or f['id'], id=f['id'], lat=g[1], lon=g[0], compass=p.get('view:azimuth'), pano=cam.get('field_of_view') == 360 or (len(size) == 2 and size[0] >= 1.9 * size[1]), t=t,
                        camera=' '.join(v for v in (cam.get('camera_manufacturer'), cam.get('camera_model')) if v) or None, size=list(size) if len(size) == 2 else None, url=((f.get('assets') or {}).get('sd') or {}).get('href'), hd=((f.get('assets') or {}).get('hd') or {}).get('href')))
    return out


def _groups(frames, lat, lon, n):
    """The capture runs (sequences) among `frames`, nearest first: [{frames: [...], nearest: frame, count, spacing_m}], each frame with its distance in metres from the point; at most n."""
    by = collections.defaultdict(list)
    for f in frames: f['distance_m'] = round(_metres((lat, lon), (f['lat'], f['lon'])), 1); by[f['seq']].append(f)
    out = []
    for seq, fs in by.items():
        pts = np.array([[f['lat'], f['lon']] for f in fs]); gaps = []
        if len(fs) > 1:
            for i in range(len(fs)): gaps.append(min(_metres((pts[i][0], pts[i][1]), (pts[j][0], pts[j][1])) for j in range(len(fs)) if j != i))
        out.append(dict(seq=seq, nearest=min(fs, key=lambda f: f['distance_m']), count=len(fs), spacing_m=round(float(np.median(gaps)), 1) if gaps else None))
    return sorted(out, key=lambda g: g['nearest']['distance_m'])[:n]


GOOGLE_LINK_M, GOOGLE_STEP_M, GOOGLE_STEPS = 40.0, 15.0, 12      # panoramas this close (metres) belong to one run; the run is followed along the road in steps of this length, this many each way


def _pano(m, f_lat, f_lon):
    try: t = dt.datetime.strptime(m.get('date', ''), '%Y-%m').replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError: t = None
    return dict(seq='g', id=m['pano_id'], lat=m['location']['lat'], lon=m['location']['lng'], compass=None, pano=True, t=t, camera='Google Street View car', size=None, url=None)


def _google_ask(la, lo, key, get, radius=30):
    m = get(GOOGLE_META, dict(location=f'{la:.6f},{lo:.6f}', radius=radius, source='outdoor', key=key))
    if m.get('status') not in ('OK', 'ZERO_RESULTS'): raise RuntimeError(f'Google refused the Street View lookup: {m.get("status")} {m.get("error_message", "")[:120]}')
    return _pano(m, la, lo) if m.get('status') == 'OK' else None


def _google_near(lat, lon, n, key, get):
    """The nearest runs of Google panoramas. Google only answers with the single nearest panorama to a spot, so ask at the point and on rings round it; panoramas within GOOGLE_LINK_M of each other are one run (the frames of one drive along a road), and each run is followed
    along the road in both directions (GOOGLE_STEPS steps of GOOGLE_STEP_M, trying a little to either side to follow a bend) to find its other panoramas. Each run is {seq, nearest, count, spacing_m, frames}."""
    spots = [(lat, lon)] + [(lat + r * math.cos(math.radians(a)) / 111320.0, lon + r * math.sin(math.radians(a)) / (111320.0 * math.cos(math.radians(lat)))) for r in GOOGLE_RING_M for a in range(0, 360, 45)]
    with ThreadPoolExecutor(8) as ex: found = {p['id']: p for p in ex.map(lambda sp: _google_ask(sp[0], sp[1], key, get), spots) if p}
    pts = list(found.values()); parent = list(range(len(pts)))
    def root(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(pts)):
        for j in range(i):
            if _metres((pts[i]['lat'], pts[i]['lon']), (pts[j]['lat'], pts[j]['lon'])) <= GOOGLE_LINK_M: parent[root(i)] = root(j)
    runs = collections.defaultdict(list)
    for i, p in enumerate(pts): runs[root(i)].append(p)
    seen = dict(found); lock = __import__('threading').Lock()
    def follow(end, ahead):
        """Walk on from the panorama `end` heading `ahead` degrees: at each step look a step further, a little to either side too, and take the new panorama nearest the straight way on."""
        cur, head, out = end, ahead, []
        for _ in range(GOOGLE_STEPS):
            best = None
            for off in (0, -25, 25):
                h = math.radians(head + off); la = cur['lat'] + GOOGLE_STEP_M * math.cos(h) / 111320.0; lo = cur['lon'] + GOOGLE_STEP_M * math.sin(h) / (111320.0 * math.cos(math.radians(cur['lat'])))
                p = _google_ask(la, lo, key, get, 8)
                with lock: new = p is not None and p['id'] not in seen
                if new and 4.0 <= _metres((cur['lat'], cur['lon']), (p['lat'], p['lon'])) <= 2.5 * GOOGLE_STEP_M and (best is None or abs(off) < abs(best[0])): best = (off, p)
            if best is None: break
            with lock:
                if best[1]['id'] in seen: break
                seen[best[1]['id']] = best[1]
            out.append(best[1]); head = _bearing((cur['lat'], cur['lon']), (best[1]['lat'], best[1]['lon'])); cur = best[1]
        return out
    def fill(fs):
        """Panoramas the rings stepped over: between two found ones more than 1.2 steps apart, look at the middle (a few passes)."""
        for _ in range(3):
            if len(fs) < 2: return
            k = math.cos(math.radians(lat)); xy = np.array([[(f['lon'] - lon) * 111320.0 * k, (f['lat'] - lat) * 111320.0] for f in fs]); c = xy - xy.mean(axis=0); proj = c @ np.linalg.svd(c, full_matrices=False)[2][0]; order = list(np.argsort(proj)); added = 0
            for a, b in zip(order, order[1:]):
                pa, pb = fs[a], fs[b]
                if _metres((pa['lat'], pa['lon']), (pb['lat'], pb['lon'])) <= 1.2 * GOOGLE_STEP_M: continue
                p = _google_ask((pa['lat'] + pb['lat']) / 2, (pa['lon'] + pb['lon']) / 2, key, get, 8)
                with lock:
                    if p is not None and p['id'] not in seen: seen[p['id']] = p; fs.append(p); added += 1
            if not added: return
    with ThreadPoolExecutor(8) as ex: list(ex.map(fill, runs.values()))
    jobs = []
    for fs in runs.values():
        if len(fs) == 1: jobs += [(fs, fs[0], a) for a in (0, 180)]; continue                                                    # (one panorama alone: the road could run either way; try along and across the compass)
        k = math.cos(math.radians(lat)); xy = np.array([[(f['lon'] - lon) * 111320.0 * k, (f['lat'] - lat) * 111320.0] for f in fs]); c = xy - xy.mean(axis=0); axis = np.linalg.svd(c, full_matrices=False)[2][0]; proj = c @ axis
        lo_i, hi_i = int(np.argmin(proj)), int(np.argmax(proj)); bearing = math.degrees(math.atan2(axis[0], axis[1])) % 360
        jobs += [(fs, fs[hi_i], bearing), (fs, fs[lo_i], (bearing + 180) % 360)]
    with ThreadPoolExecutor(8) as ex: extra = list(ex.map(lambda j: follow(j[1], j[2]), jobs))
    for (fs, _, _), more in zip(jobs, extra): fs.extend(more)
    out = []
    for fs in runs.values():
        fs = list({f['id']: f for f in fs}.values()); pts_ = [(f['lat'], f['lon']) for f in fs]; gaps = [min(_metres(pts_[i], pts_[j]) for j in range(len(fs)) if j != i) for i in range(len(fs))] if len(fs) > 1 else []
        near = min(fs, key=lambda f: _metres((lat, lon), (f['lat'], f['lon']))); out.append(dict(seq='g:' + near['id'][:8], nearest=dict(near, distance_m=round(_metres((lat, lon), (near['lat'], near['lon'])), 1)), count=len(fs), spacing_m=round(float(np.median(gaps)), 1) if gaps else None, frames=fs))
    return sorted(out, key=lambda g: g['nearest']['distance_m'])[:n]


def _rule(key, ok, text): return dict(key=key, ok=ok, text=text)


def _road_rule(ctx, run_pos):
    """Whether the run was within ON_ROAD_M of a drivable road at the nearest point of the run (street-level pictures are on roads, and count when they are that close to the run): from the road data of the area (OpenStreetMap, through the cached mirror pool)."""
    ways = ctx.get('ways')
    if run_pos is None: return _rule('on_road', None, 'there is no race track yet')
    if ways is None: return _rule('on_road', None, 'the roads here could not be looked up')
    d, who = roads.distances(np.array([run_pos[0]]), np.array([run_pos[1]]), ways)[0]; name = ways[who].get('name') or ways[who].get('highway') if who >= 0 else None
    if who >= 0 and d <= ON_ROAD_M: return _rule('on_road', True, f"the run was {d:.0f} m from a road there ({name})")
    return _rule('on_road', False, 'no road within ' + f"{ON_ROAD_M:g} m of the run there" + ('' if who < 0 else f" (the nearest, {name}, is {d:.0f} m away)") + ': a trail, a path or off the roads')


def _roads_near(rd, lat, lon, r, svc=None):
    """The drivable roads within r metres of a point ([{id, highway, name, geometry}]) from the cached OpenStreetMap lookup; None when it cannot be had."""
    a = (svc or osm.pool(os.path.join(rd, 'cache', 'osm'))).query(osm.ways_ql(_box_sn(lat, lon, r), osm.DRIVABLE))
    return None if a is None else osm.ways(a)


def _box_sn(lat, lon, r):
    w, s, e, n = _box(lat, lon, r); return s, w, n, e


def describe_near(prov, g, radius, secs, ctx):
    """One capture run near the point as the page shows it, with the rules that would rule it out (as for the sections found along the run): each {key, ok (True / False / None unknown), text}. `ctx`: tr (the race track or None), roads (the roads doc or None), clips, gaps."""
    f = g['nearest']; tr = ctx.get('tr'); rules = []; run_d = run_km = run_t = bearing = run_pos = None
    if tr is not None:
        d, t = track_dist(tr); ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon']) & np.isfinite(tr['t']); la, lo = np.asarray(tr['lat'])[ok], np.asarray(tr['lon'])[ok]
        k = math.cos(math.radians(f['lat'])); dd = np.hypot((la - f['lat']) * 111320.0, (lo - f['lon']) * 111320.0 * k); i = int(np.argmin(dd)); run_d, run_km, run_t = float(dd[i]), float(d[i]) / 1000.0, float(t[i])
        run_pos = (float(la[i]), float(lo[i])); j0, j1 = max(0, i - 25), min(len(la) - 1, i + 25); bearing = _bearing((la[j0], lo[j0]), (la[j1], lo[j1])) if j1 > j0 else None
    kind = '360' if f['pano'] else '2d'; sec = next((s for s in secs if s['provider'] == prov and (s['seq'] == g['seq'] or prov == 'google') and run_km is not None and s['km0'] - 0.03 <= run_km <= s['km1'] + 0.03), None)
    rules.append(_rule('near_run', None if run_d is None else run_d <= ON_ROAD_M, 'there is no race track yet' if run_d is None else f"{run_d:.0f} m from the run's track (pictures count within {ON_ROAD_M:g} m)"))
    rules.append(_road_rule(ctx, run_pos))
    if f['pano']: rules.append(_rule('direction', True, 'a 360 camera sees every way'))
    elif f.get('compass') is None or bearing is None: rules.append(_rule('direction', None, 'the way the camera faced or the way the runner went is not known'))
    else:
        rel = _rel(f['compass'], bearing); rules.append(_rule('direction', abs(rel) <= 45, f"the flat camera faced {direction(rel)} of the way the runner went ({abs(rel):.0f}° off)" ))
    if sec is not None: rules.append(_rule('pictures', sec['plausible'], f"part of section {sec['id']}: " + (sec['why_not'] if not sec['plausible'] else f"{sec['frames']} pictures, {sec['spacing_m']} m apart, enough for a clip")))
    else:
        enough = g['count'] >= MIN_FRAMES and g['spacing_m'] is not None and g['spacing_m'] <= MAX_SPACING_M
        rules.append(_rule('pictures', enough, f"{g['count']} picture{'s' if g['count'] != 1 else ''} of this capture run within {radius:.0f} m" + (f", {g['spacing_m']:.0f} m apart" if g['spacing_m'] is not None else '') + f" (a clip needs {MIN_FRAMES} or more, {MAX_SPACING_M:g} m apart or less, along {MIN_LENGTH_M} m of the run)"))
    if run_t is not None and f.get('t') and prov != 'google': lt = light_between(f['lat'], f['lon'], f['t'], run_t); rules.append(_rule('light', lt['warning'] is None, lt['warning'] or f"the light fits: {sun_phrase(lt['captured_sun'])} when filmed, {sun_phrase(lt['race_sun'])} when you passed"))
    else: rules.append(_rule('light', None, 'Google gives only the month it was taken' if prov == 'google' else 'the time it was filmed or the time you passed is not known'))
    if run_t is not None and ctx.get('clips') is not None:
        nc = nearest_clips(dict(passed=[run_t - 5, run_t + 5]), ctx['clips'], tr, ctx.get('gaps')); rules.append(_rule('footage', not nc['overlaps'], f"overlaps camera clip {', '.join(nc['overlaps'])}" if nc['overlaps'] else (f"fills gap {nc['in_gap']}" if nc['in_gap'] else 'between camera clips')))
    if sec is not None and sec.get('quality') and sec['quality'].get('grade'): rules.append(_rule('quality', sec['quality']['grade'] != 'poor', f"clip quality {sec['quality']['grade']} ({sec['quality']['score']})"))
    return dict(provider=prov, id=f['id'], sequence=g['seq'], lat=round(f['lat'], 6), lon=round(f['lon'], 6), distance_m=f['distance_m'], kind=kind, camera=f.get('camera'), size=f.get('size'), captured=f.get('t'), compass=f.get('compass'), pictures=g['count'], spacing_m=g['spacing_m'],
                section=sec['id'] if sec else None, section_key=sec['key'] if sec else None, run_distance_m=None if run_d is None else round(run_d, 1), run_km=None if run_km is None else round(run_km, 3), passed=run_t, url=f.get('url'), rules=rules, usable=all(r['ok'] is not False for r in rules), ruled_out=[r['text'] for r in rules if r['ok'] is False])


def near_point(rd, lat, lon, n=5, tr=None, clips=None, gaps=None, get=_get, token=None, gkey=None, osm_svc=None, log=None):
    """The street view nearest (as the crow flies) to a point, from each provider, whatever the run did there: the `n` nearest capture runs of Mapillary and Panoramax (the search widens from NEAR_RADII until there are enough) and the nearest panoramas of Google,
    each with the rules that would rule it out. No filters. {lat, lon, n, providers: {name: {items, radius_m, error?}}}."""
    log = log or (lambda m: None); log('looking up the roads round the point…')
    docs = {p: load(rd, p) for p in PROVIDERS}; secs = annotate(rd, docs, tr, clips, gaps); ctx = dict(tr=tr, ways=_roads_near(rd, lat, lon, NEAR_RADII[-1] + 150.0, osm_svc) if tr is not None else None, clips=clips, gaps=gaps); out = {}
    for prov, fetch, key in (('mapillary', _frames_mapillary, token), ('panoramax', _frames_panoramax, True), ('google', None, gkey)):
        if not key: out[prov] = dict(items=[], radius_m=None, error=('no MAPILLARY_TOKEN in secrets.env' if prov == 'mapillary' else 'no GOOGLE_MAPS_API_KEY in secrets.env')); continue
        log(f'asking {prov}…')
        try:
            if prov == 'google': groups, radius = _google_near(lat, lon, n, gkey, get), GOOGLE_RING_M[-1] + 30
            else:
                for radius in NEAR_RADII:
                    log(f'{prov}: pictures within {radius:g} m…'); groups = _groups(fetch(lat, lon, radius, token, get), lat, lon, n)
                    if len(groups) >= n: break
        except RuntimeError as e: out[prov] = dict(items=[], radius_m=None, error=str(e)); continue
        out[prov] = dict(items=[describe_near(prov, g, radius, secs, ctx) for g in groups], radius_m=radius); log(f'{prov}: {len(groups)} capture run{"" if len(groups) == 1 else "s"} found')
    return dict(lat=lat, lon=lon, n=n, providers=out)


NEAR_CACHE_M = 100.0              # a click this near an earlier search shows that search again (nothing is fetched)
NEAR_CACHE_KEEP = 60


def near_cached(rd, lat, lon):
    """The result of the nearest earlier search within NEAR_CACHE_M of this point (its own `lat`/`lon` say where it was made), or None."""
    try: entries = json.load(open(os.path.join(adir(rd), 'near_cache.json')))['entries']
    except (OSError, ValueError, KeyError): return None
    best = min(((_metres((lat, lon), (e['lat'], e['lon'])), e) for e in entries), key=lambda x: x[0], default=None)
    return best[1]['result'] if best and best[0] <= NEAR_CACHE_M else None


def near_store(rd, result):
    """Keep a search result for later clicks near it (the newest NEAR_CACHE_KEEP are kept)."""
    p = os.path.join(adir(rd), 'near_cache.json')
    try: entries = json.load(open(p))['entries']
    except (OSError, ValueError, KeyError): entries = []
    entries = [e for e in entries if (e['lat'], e['lon']) != (result['lat'], result['lon'])] + [dict(lat=result['lat'], lon=result['lon'], result=result)]
    os.makedirs(adir(rd), exist_ok=True); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(dict(entries=entries[-NEAR_CACHE_KEEP:]), open(tmp, 'w'), separators=(',', ':')); os.replace(tmp, p)


def image_near(rd, provider, item, w=256, fetch=_bytes, get=_get):
    """JPEG bytes of a picture found by `near_point` (`item` has id, url for Panoramax, compass for Google): kept in streetview/img/."""
    w = 256 if w <= 256 else 1024 if w <= 1024 else 2048; f = os.path.join(adir(rd), 'img', f"{provider[0]}-{item['id']}-{w}.jpg")
    if os.path.exists(f): return open(f, 'rb').read()
    if provider == 'mapillary':
        tok = _key('MAPILLARY_TOKEN')
        if not tok: raise RuntimeError('mapillary: no MAPILLARY_TOKEN in secrets.env')
        url = get(f"https://graph.mapillary.com/{item['id']}", dict(access_token=tok, fields=f'thumb_{w}_url')).get(f'thumb_{w}_url')
        if not url: raise RuntimeError('mapillary has no picture for this frame')
    elif provider == 'panoramax':
        url = item.get('url')
        if not url: raise RuntimeError('panoramax gave no picture address for this frame')
    else:
        key = _key('GOOGLE_MAPS_API_KEY')
        if not key: raise RuntimeError('google: no GOOGLE_MAPS_API_KEY in secrets.env')
        data = fetch('https://maps.googleapis.com/maps/api/streetview', dict(size='640x400', pano=item['id'], heading=item.get('compass') or 0, fov=90, pitch=0, key=key)); url = None
    if url: data = fetch(url)
    os.makedirs(os.path.dirname(f), exist_ok=True); tmp = f'{f}.{os.getpid()}.tmp'; open(tmp, 'wb').write(data); os.replace(tmp, f); return data


# --- sections promoted from the click-the-map search --------------------------------------------------------------------------------------------------------------------------------------
PROMOTE_M = 30.0                  # a promoted capture run counts the pictures within this far of the run (the stages use ON_ROAD_M): you chose it, so it is looser
PROMOTE_REACH_M = 500.0           # and the stretch of the run it is placed on reaches this far each way from the place


def manual_sections(rd):
    """The sections promoted by hand ([] when there are none), each with `manual` and the `road` (line, km0) it was placed on."""
    try: return json.load(open(os.path.join(adir(rd), 'manual.json')))['sections']
    except (OSError, ValueError, KeyError): return []


def _save_manual(rd, sections):
    os.makedirs(adir(rd), exist_ok=True); p = os.path.join(adir(rd), 'manual.json'); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(dict(schema=SCHEMA, sections=sections), open(tmp, 'w'), separators=(',', ':')); os.replace(tmp, p)


def road_of(rd, s):
    """{line, km0} of the road a section was found on: its stretch in the roads doc, else the stretch a promoted section was placed on (None when neither)."""
    st = next((x for x in (load(rd, 'roads') or {'stretches': []})['stretches'] if x['id'] == s.get('stretch')), None)
    return dict(line=st['line'], km0=st['km0']) if st else s.get('road')


def _run_frames(provider, item_id, seq, lat, lon, token, gkey, get):
    """The pictures of one capture run round a place, as the stages make them (without their km): [{seq, lat, lon, a?, c, t, id, pano, camera, size, u, h}]."""
    if provider == 'google':
        run = next((g for g in _google_near(lat, lon, 6, gkey, get) if any(f['id'] == item_id for f in g['frames'])), None)
        return [] if run is None else [dict(seq='g', id=f['id'], lat=f['lat'], lon=f['lon'], compass=None, pano=True, t=f['t'], camera=f['camera'], size=None, u=None, h=None) for f in run['frames']]
    frames = (_frames_mapillary if provider == 'mapillary' else _frames_panoramax)(lat, lon, 450.0, token, get)
    return [dict(f, u=f.get('url'), h=f.get('hd')) for f in frames if f['seq'] == seq]


def promote(rd, provider, item_id, seq, lat, lon, tr, token=None, gkey=None, get=_get):
    """Make a section of the capture run found near a clicked place, so it can be chosen for the film like the others: the run's pictures within PROMOTE_M of the race track, placed along the stretch of the run PROMOTE_REACH_M each way from the place. Saved in manual.json
    (kept when the stages are run again). Returns the section; ValueError (with the reason) when nothing of the run lies along the run track. A section already there with the same key is returned as it is."""
    if tr is None: raise ValueError('there is no race track to place it on')
    frames = _run_frames(provider, item_id, seq, lat, lon, token, gkey, get)
    if not frames: raise ValueError('the picture was not found again: click the map again')
    d, t = track_dist(tr); ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon']) & np.isfinite(tr['t']); la, lo = np.asarray(tr['lat'])[ok], np.asarray(tr['lon'])[ok]; k = math.cos(math.radians(lat))
    i = int(np.argmin(np.hypot((la - lat) * 111320.0, (lo - lon) * 111320.0 * k))); lo_m, hi_m = max(0.0, d[i] - PROMOTE_REACH_M), d[i] + PROMOTE_REACH_M
    marks = np.arange(lo_m, min(hi_m, d[-1]) + 1e-6, 20.0); idx = np.searchsorted(d, marks).clip(0, len(d) - 1); st = dict(id='manual', km0=round(float(d[idx[0]]) / 1000.0, 3), line=[[round(float(la[j]), 5), round(float(lo[j]), 5)] for j in idx])
    line = Line(st); kept = []
    for f in frames:
        km, dist, b = line.locate((f['lat'], f['lon']))
        if dist <= PROMOTE_M: kept.append(dict(f, seq=f['seq'], km=km, b=b, c=f.get('compass'), a=None if f['pano'] or f.get('compass') is None else _rel(f['compass'], b), t=f.get('t')))
    secs = sections_of(provider, st, kept)
    if not secs: raise ValueError(f'none of its {len(frames)} pictures lies within {PROMOTE_M:g} m of the run track')
    sec = next((x for x in secs if any(i_['id'] == item_id for i_ in x['items'])), max(secs, key=lambda x: x['frames']))
    for x in sec['items']: x.pop('u', None) if x.get('u') is None else None
    key = section_key(sec); existing = [x for x in manual_sections(rd) if section_key(x) == key]
    if existing: return existing[0]
    n = sum(1 for x in manual_sections(rd) if x['provider'] == provider) + 1; sec.update(id=f"{provider[0].upper()}+{n}", manual=True, stretch='manual', road=dict(line=st['line'], km0=st['km0']))
    _save_manual(rd, manual_sections(rd) + [sec]); return sec


def unpromote(rd, key):
    """Take a promoted section out again (and its choice). Returns whether there was one."""
    keep = [x for x in manual_sections(rd) if section_key(x) != key]; had = len(keep) != len(manual_sections(rd))
    if had: _save_manual(rd, keep); set_choice(rd, key, 'none')
    return had
