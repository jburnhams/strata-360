"""Synthetic clips (implementation plan N1): clips the project makes itself for the gaps in the footage, such as an animated map of the route for a stretch with no camera footage.

`<race dir>/synthetic.json` = {"clips": [{id, kind, t0, t1, duration_s, seconds, speedup, fps, style, key, status, file?}]}. A synthetic clip covers [t0, t1] of the race (UTC, ISO) and is shown in
`seconds` of film: its speed-up is duration_s / seconds. `key` identifies what would be rendered (the span, the length, the kind, the style, the frame rate and, when set, the size), so a render is reused while it is unchanged."""
import datetime as dt, hashlib, json, math, os

FILE = 'synthetic.json'
KINDS = ('map', 'flyover')          # the animated 2D map (overlay/mapclip.py) and the 3D terrain flyover (overlay/flyover.py)
SIZES = {'flyover': '3840x2160'}    # the picture size a kind is made at when none is asked for (the 2D map: the renderer's 1920x1080); 4K for the flyover
MIN_SECONDS = 2.0


def _iso(t): return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def default_seconds(duration_s):
    """How long a gap of this length is shown by default: 12 s for an hour, 20 s for four, 27 s for ten (a little more for a longer gap, never less than 6 s or more than 45 s)."""
    return round(min(max(6.0 + 6.0 * math.log2(1.0 + duration_s / 3600.0), 6.0), 45.0), 1)


SHORT_S = 5.0                 # a clip shorter than this is a 2D map: a flyover has no time to show the land
DRAMATIC_RELIEF_M, FLAT_RELIEF_M, SHORT_KM = 900.0, 300.0, 10.0


def choose_kind(gap, seconds, last=None):
    """How the planner draws a gap, so that the script only says that there is one and for how long: a 3D flyover where the land is the story (a big climb or descent: ascent plus descent of 900 m or more), a 2D map for a short clip (under 5 s), a short hop (under 10 km) or flat ground (under 300 m of relief); in between
    it alternates with the kind chosen just before (`last`), so the film has both. 2D maps are the cheap, quick change of picture; flyovers cost minutes of machine time each."""
    relief = float(gap.get('ascent_m') or 0) + float(gap.get('descent_m') or 0); km = float(gap.get('distance_km') or 0)
    if seconds < SHORT_S or km < SHORT_KM or relief < FLAT_RELIEF_M: return 'map'
    if relief >= DRAMATIC_RELIEF_M: return 'flyover'
    return 'map' if last == 'flyover' else 'flyover'


def key_of(c):
    blob = json.dumps([c['kind'], c['t0'], c['t1'], round(c['seconds'], 2), c['fps'], c.get('style') or {}] + ([c['size']] if c.get('size') else []), sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def make(gap, seconds=None, speedup=None, kind='map', style=None, fps=30.0, t0=None, t1=None, id=None, size=None, approved=True, by='planner'):
    """The clip for a gap (or for a stretch of it: `t0` and `t1` in epoch seconds), by length in the film or by speed-up (not both; neither gives the default)."""
    if kind not in KINDS: raise ValueError(f'kind: one of {KINDS}')
    if seconds is not None and speedup is not None: raise ValueError('give the length in the film or the speed-up, not both')
    a, b = float(gap['t0'] if t0 is None else t0), float(gap['t1'] if t1 is None else t1)
    if not gap['t0'] - 1e-6 <= a < b <= gap['t1'] + 1e-6: raise ValueError('the stretch must lie inside the gap')
    dur = b - a
    if speedup is not None:
        if speedup < 1: raise ValueError('speed-up: 1 or more'); 
        seconds = dur / speedup
    elif seconds is None: seconds = default_seconds(dur)
    if seconds < MIN_SECONDS: raise ValueError(f'a clip shorter than {MIN_SECONDS:g} s is not useful')
    c = dict(id=id or gap['id'], kind=kind, gap=gap['id'], t0=_iso(a), t1=_iso(b), duration_s=round(dur, 1), seconds=round(float(seconds), 2), speedup=round(dur / float(seconds), 1), fps=float(fps), style=style or {}, status='planned')
    size = size or SIZES.get(kind)
    if size:
        try: w, h = (int(x) for x in str(size).lower().split('x'))
        except ValueError: raise ValueError('size: WIDTHxHEIGHT, such as 3840x2160')
        if w < 320 or h < 180: raise ValueError('size: at least 320x180')
        c['size'] = f'{w}x{h}'
    c['approved'] = bool(approved)                                                              # kept for older plans: no clip waits for approval any more
    c['by'] = by                                                                                  # who chose its kind: the planner (it may change it) or the user (it stays)
    c['key'] = key_of(dict(c, t0=round(a), t1=round(b))); return c


def load(folder):
    from strata360.pipeline import config
    try: d = json.load(open(os.path.join(config.race_dir(folder), FILE)))
    except (OSError, ValueError): d = {}
    d.setdefault('clips', []); return d


def save(folder, doc):
    from strata360.pipeline import config
    rd = config.race_dir(folder); os.makedirs(rd, exist_ok=True); p = os.path.join(rd, FILE); tmp = p + '.tmp'; json.dump(doc, open(tmp, 'w'), indent=1); os.replace(tmp, p); return doc


def upsert(folder, clip):
    """Add the clip, or replace the one with its id. A changed key means the old render no longer matches: the status goes back to planned and the file is forgotten."""
    doc = load(folder); old = next((c for c in doc['clips'] if c['id'] == clip['id']), None)
    if old and old.get('key') == clip['key']: clip = dict(clip, status=old.get('status', clip['status']), approved=bool(old.get('approved', True)) or bool(clip.get('approved', True)), **({'file': old['file']} if old.get('file') else {}))
    doc['clips'] = sorted([c for c in doc['clips'] if c['id'] != clip['id']] + [clip], key=lambda c: c['t0']); save(folder, doc); return clip


def remove(folder, clip_id):
    doc = load(folder); n = len(doc['clips']); doc['clips'] = [c for c in doc['clips'] if c['id'] != clip_id]; save(folder, doc); return len(doc['clips']) < n
