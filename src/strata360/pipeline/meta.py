"""Project details the user sets: the film/race title, the date, and the race results.

Stored in `<project>/project.json`: {"title", "date" (YYYY-MM-DD, null = use the earliest capture), "results": {"starters", "finishers", "finished" (true/false/null), "position"}}.
Defaults come from the footage: the title from the folder name (without a leading date), the date from the earliest clip start (local date)."""
import datetime as dt, glob, json, os, re
from strata360.pipeline import config

DEFAULTS = dict(title=None, date=None, results=dict(starters=None, finishers=None, finished=None, position=None))


def _path(folder): return os.path.join(config.race_dir(folder), 'project.json')


def earliest_capture(folder, tz='Europe/Brussels'):
    """(date, iso start) of the earliest clip, local date in the race timezone."""
    from zoneinfo import ZoneInfo
    best = None
    for f in glob.glob(os.path.join(config.race_dir(folder), 'clips', '*', 'clip.json')):
        try: t = json.load(open(f))['time']['start_utc']
        except (OSError, ValueError, KeyError): continue
        if best is None or t < best: best = t
    if not best: return None, None
    d = dt.datetime.fromisoformat(best.replace('Z', '+00:00')).astimezone(ZoneInfo(tz)); return d.date().isoformat(), best


def default_title(folder):
    n = os.path.basename(os.path.abspath(str(folder)).rstrip(os.sep)); n = re.sub(r'^\d{4}-\d{2}-\d{2}\s*[-–]?\s*', '', n).strip(); return n or None


def load(folder):
    p = _path(folder); d = json.load(open(p)) if os.path.exists(p) else {}
    out = json.loads(json.dumps(DEFAULTS)); out.update({k: v for k, v in d.items() if k not in ('results', 'edit')}); out['results'].update(d.get('results') or {})
    cap, iso = earliest_capture(folder); out['defaults'] = dict(title=default_title(folder), date=cap, earliest_capture_utc=iso)
    out['effective'] = dict(title=out['title'] or out['defaults']['title'], date=out['date'] or cap); return out


def save(folder, patch):
    """Merge `patch` (title, date, results{...}) into project.json; empty strings become null; numbers are validated."""
    p = _path(folder); d = json.load(open(p)) if os.path.exists(p) else {}
    for k in ('title', 'date'):
        if k in patch: v = (patch[k] or '').strip() or None; d[k] = v
    if 'date' in d and d['date'] is not None:
        try: dt.date.fromisoformat(d['date'])
        except ValueError: raise ValueError('date must be YYYY-MM-DD')
    if 'results' in patch:
        r = d.setdefault('results', {})
        for k in ('starters', 'finishers', 'position'):
            if k in patch['results']:
                v = patch['results'][k]; r[k] = None if v in (None, '') else int(v)
                if r[k] is not None and r[k] < 1: raise ValueError(f'{k} must be 1 or more')
        if 'finished' in patch['results']: r['finished'] = patch['results']['finished']
        if r.get('finished') is False: r['position'] = None                                        # a DNF has no finishing position
        s, f, pos = r.get('starters'), r.get('finishers'), r.get('position')
        if s is not None and f is not None and f > s: raise ValueError('finishers cannot exceed starters')
        if pos is not None and f is not None and pos > f: raise ValueError('finishing position cannot be worse than the number of finishers')
    os.makedirs(config.race_dir(folder), exist_ok=True); tmp = _path(folder) + '.tmp'; json.dump(d, open(tmp, 'w'), indent=1); os.replace(tmp, _path(folder)); return load(folder)


def describe(folder):
    """The facts as one paragraph for the script writer."""
    m = load(folder); e = m['effective']; r = m['results']; bits = []
    if e['title']: bits.append(f"Title: {e['title']}.")
    if e['date']: bits.append(f"Date: {e['date']}.")
    if r.get('starters') is not None: bits.append(f"{r['starters']} runners started" + (f" and {r['finishers']} finished." if r.get('finishers') is not None else '.'))
    if r.get('finished') is True: bits.append('The runner finished' + (f", in position {r['position']}." if r.get('position') else '.'))
    elif r.get('finished') is False: bits.append('The runner did not finish (DNF).')
    return ' '.join(bits)
