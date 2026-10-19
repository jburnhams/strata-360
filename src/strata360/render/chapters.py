"""YouTube chapter markers for the final film, from its time map (render/timemap.py) and the race's stages (gps/tracks.py `stage_schedule`): written beside the film as `chapters.txt` (ready to paste into the video's description) and `chapters.json`.

A chapter starts wherever the stage of the race on screen changes: "Stage 3, km 42", "Checkpoint 2, km 38" (km is the distance run from the start, at the chapter's first frame), "Start", "Finish", "Before the start", "After the finish"; without routes, "km 12". A window's race time runs
from its UTC in to its UTC out (a generated clip as the renderer plays it: its gap's whole span over its own seconds), so a stage that changes inside a window starts a chapter at that frame. Windows without a race time (a photo with none, an untimed clip) stay in the chapter before them.
YouTube's rules: the first chapter at 0:00 (it takes in the opening), each at least 10 s (a shorter one is merged into a neighbour), and at least three of them, else YouTube shows none (`youtube` is False then; the files are written anyway)."""
import bisect, datetime as dt, glob, json, os, subprocess

MIN_S = 10.0
NAMES = {'Before Race': 'Before the start', 'At Start': 'Start', 'At Finish': 'Finish', 'After Race': 'After the finish'}


def _secs(u):
    """UTC seconds of an ISO time (or a number), None for none."""
    if u is None or u == '': return None
    if isinstance(u, (int, float)): return float(u)
    return dt.datetime.fromisoformat(str(u).replace('Z', '+00:00')).timestamp()


def title(label, km=None):
    """The chapter's title for a stage label of `stage_schedule` and the km run by then."""
    k = f'km {int(round(km))}' if km is not None else None
    if label in NAMES: return NAMES[label]
    if label == 'On Course': return k or 'On course'
    return f'{label}, {k}' if k else label


def stamp(s):
    """0:00, 4:05, 1:02:03 (YouTube's form)."""
    s = int(s); h, m, x = s // 3600, s % 3600 // 60, s % 60; return f'{h}:{m:02d}:{x:02d}' if h else f'{m}:{x:02d}'


def build(tm, schedule, km_at=None, lead_s=0.0, end_s=None, min_s=MIN_S):
    """The chapters of the film whose time map is `tm`: [{t (film seconds), title, label, km}]. `schedule`: [(UTC seconds from which it holds, label)] (`stage_schedule`); `km_at(utc seconds)`: the km run by then, or None; `lead_s`: the opening before the first window;
    `end_s`: the length of the whole film (default: the windows plus the opening)."""
    if not schedule or not tm.get('windows'): return []
    fps = float(tm['fps']); times = [a for a, _ in schedule]; at = lambda t: schedule[max(0, bisect.bisect_right(times, t) - 1)][1]; pts = []
    for w in tm['windows']:
        u0, u1 = _secs(w.get('utc_in')), _secs(w.get('utc_out'))
        if u0 is None: continue
        u1 = u0 if u1 is None or u1 < u0 else u1; f0, f1 = lead_s + w['film_in'] / fps, lead_s + w['film_out'] / fps; secs = w.get('synthetic_seconds')
        if secs and u1 > u0:                                                                                                 # a generated clip shows its race span over its own seconds, from where the window starts in it, and holds its last frame after (render/synthetic.py `race_time`)
            s0 = float(w.get('source_in_s') or 0.0); s1 = min(s0 + f1 - f0, secs); pts.append((f0, u0 + min(max(s0, 0.0), secs) / secs * (u1 - u0)))
            pts += [(f0 + x - s0, b) for b in times[1:] for x in [(b - u0) / (u1 - u0) * secs] if s0 < x < s1]
            continue
        if w.get('ramp') and u1 > u0:                                                                                        # a speed ramp races through its clip: the race time follows the ramp (edit/hyperlapse.py `offsets`, as the time map's `utc_at`)
            import numpy as np
            from strata360.edit import hyperlapse as HL
            t = np.linspace(0.0, f1 - f0, max(2, int(round((f1 - f0) * fps)) + 1)); off = np.asarray(HL.offsets(w['ramp'], t), float); pts.append((f0, u0))
            pts += [(f0 + float(np.interp(b - u0, off, t)), b) for b in times[1:] if u0 < b < u0 + off[-1]]
            continue
        pts.append((f0, u0))
        if u1 > u0: pts += [(f0 + (b - u0) / (u1 - u0) * (f1 - f0), b) for b in times[1:] if u0 < b < u1]                    # the stage changes inside the window
    out = []
    for f, u in pts:
        lab = at(u)
        if not out or out[-1]['label'] != lab: out.append(dict(t=f, label=lab, km=km_at(u) if km_at else None))
    if not out: return []
    out[0]['t'] = 0.0; end = end_s if end_s is not None else lead_s + tm['frames'] / fps
    while len(out) > 1:                                                                                                      # the shortest chapter under the minimum joins a neighbour, until none is left
        lens = [(b['t'] if b else end) - a['t'] for a, b in zip(out, out[1:] + [None])]; k = min(range(len(out)), key=lambda i: lens[i])
        if lens[k] >= min_s: break
        if k == 0: out[1]['t'] = 0.0                                                                                         # a short first chapter: the next one starts the film
        del out[k]
        out = [c for i, c in enumerate(out) if i == 0 or c['label'] != out[i - 1]['label']]                                     # two of the same stage now side by side are one
    return [dict(t=round(c['t'], 3), title=title(c['label'], c['km']), label=c['label'], km=None if c['km'] is None else round(c['km'], 1)) for c in out]


def text(chapters):
    """The chapters as YouTube reads them in a description: one '0:00 Title' line each."""
    return ''.join(f"{stamp(c['t'])} {c['title']}\n" for c in chapters)


def race(folder):
    """The race's stage schedule and the km run at a UTC time, from the project's run: (schedule, km_at); ([], None) without a run."""
    import numpy as np
    from strata360.gps import tracks as TKS
    from strata360.pipeline import config
    rd = config.race_dir(folder); cur = TKS.current_path(rd)
    if not cur: return [], None
    sched = TKS.stage_schedule(rd); run = TKS.read(cur); ok = np.isfinite(run['t']) & np.isfinite(run['lat']) & np.isfinite(run['lon']); t = run['t'][ok]; cum = TKS._dist(run['lat'][ok], run['lon'][ok]) / 1000.0
    return sched, (lambda u: float(np.interp(u, t, cum))) if len(t) >= 2 else None


def write(folder, tm, directory, lead_s=0.0, end_s=None, min_s=MIN_S):
    """Write chapters.txt and chapters.json into `directory` for the film of time map `tm`; returns dict(chapters, youtube, lead_s). Without a run the files say there are no chapters."""
    sched, km_at = race(folder); ch = build(tm, sched, km_at, lead_s, end_s, min_s); res = dict(chapters=ch, youtube=len(ch) >= 3, lead_s=round(lead_s, 3))
    json.dump(res, open(os.path.join(directory, 'chapters.json'), 'w'), indent=1); open(os.path.join(directory, 'chapters.txt'), 'w').write(text(ch)); return res


def _duration(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True)
    return float(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def for_film(folder, directory=None, min_s=MIN_S):
    """Write the chapters of a film already rendered (its folder under final/, the newest by default) from its timemap.json; what comes before the first window (the cold open and the opening title) is the render's own `lead_s` in chapters.json, else the newest cold-open and bookend-intro pieces' lengths. Returns (directory, the result of `write`)."""
    from strata360.pipeline import config
    if directory is None:
        maps = sorted(glob.glob(os.path.join(config.race_dir(folder), 'final', '*', 'timemap.json')), key=os.path.getmtime)
        if not maps: raise FileNotFoundError('no final film with a time map yet (render one with `strata360 final`)')
        directory = os.path.dirname(maps[-1])
    tm = json.load(open(os.path.join(directory, 'timemap.json'))); film = os.path.join(directory, 'film.mp4'); old = os.path.join(directory, 'chapters.json')
    try: lead = float(json.load(open(old))['lead_s'])                                                                   # the render's own (the cold open and the opening title)
    except (OSError, ValueError, KeyError, TypeError):
        newest = lambda pat: (sorted(glob.glob(os.path.join(directory, pat)), key=os.path.getmtime) or [None])[-1]
        lead = sum((_duration(f) or 0.0) for f in (newest('cold-open-*.mov'), newest('bookend-intro-*.mov')) if f)
    return directory, write(folder, tm, directory, lead, _duration(film) if os.path.exists(film) else None, min_s)
