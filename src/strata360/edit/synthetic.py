"""Synthetic clips (implementation plan N1): clips the project makes itself for the gaps in the footage, such as an animated map of the route for a stretch with no camera footage.

`<race dir>/synthetic.json` = {"clips": [{id, kind, t0, t1, duration_s, seconds, speedup, fps, style, key, status, file?}]}. A synthetic clip covers [t0, t1] of the race (UTC, ISO) and is shown in
`seconds` of film: its speed-up is duration_s / seconds. `key` identifies what would be rendered (the span, the length, the kind, the style, the frame rate), so a render is reused while it is unchanged."""
import datetime as dt, hashlib, json, math, os

FILE = 'synthetic.json'
KINDS = ('map',)
MIN_SECONDS = 2.0


def _iso(t): return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def default_seconds(duration_s):
    """How long a gap of this length is shown by default: 12 s for an hour, 20 s for four, 27 s for ten (a little more for a longer gap, never less than 6 s or more than 45 s)."""
    return round(min(max(6.0 + 6.0 * math.log2(1.0 + duration_s / 3600.0), 6.0), 45.0), 1)


def key_of(c):
    blob = json.dumps([c['kind'], c['t0'], c['t1'], round(c['seconds'], 2), c['fps'], c.get('style') or {}], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def make(gap, seconds=None, speedup=None, kind='map', style=None, fps=30.0, t0=None, t1=None, id=None):
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
    if old and old.get('key') == clip['key']: clip = dict(clip, status=old.get('status', clip['status']), **({'file': old['file']} if old.get('file') else {}))
    doc['clips'] = sorted([c for c in doc['clips'] if c['id'] != clip['id']] + [clip], key=lambda c: c['t0']); save(folder, doc); return clip


def remove(folder, clip_id):
    doc = load(folder); n = len(doc['clips']); doc['clips'] = [c for c in doc['clips'] if c['id'] != clip_id]; save(folder, doc); return len(doc['clips']) < n
