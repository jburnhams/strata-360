"""The cold open: a few seconds of the race's best moment, played with its own sound before the opening title, so the film starts on a hook and then tells the race in order (overview 12, open question 6: "intro teasers").

What counts as the best moment is read from the analysis that is already there, per second of every clip, each signal fitted to the project's own range (a rank among all the project's seconds, so a quiet race still has a loudest moment) and to its level:
  excite    cheering, shouting, laughter or a crowd in the clip's sound (`audio_events.json`)
  energy    how hard the wearer is moving and how lively the scene looks (the candidates stage's energy: motion plus the scene labels)
  scenery   the scenery and clarity rating of the front view (scenes stage)
  you       a close view of you is possible (identity)
  steady    the camera's steadiness
Each of the first three counts half by its rank and half by its own level, so the loudest cheer of a race wins over one that is merely louder than most seconds. Added to them: the words you marked MUST USE in the transcript (a bonus) and where the clip lies in the race (later scores a little higher: the climb, the finish). Words marked NEVER USE keep a window out, a window is never cut through the
middle of something said (it grows to take the whole line, up to MAX_S), and it lies in usable footage only (the candidates stage's spans). Clips in the first EARLY share of the race are left out while later ones exist, since the story
starts there anyway.

  signals(folder) -> [per-clip dict]                 what the choice is made from (reads the clip folders)
  candidates(sigs, per=PER) -> [candidate dict]      the best windows, best first (pure: what the tests use)
  run(folder, per=PER, render=False) -> doc           both, written to <project>/strata360/cold_open/cold_open.json with the best one chosen; `render` adds a preview (mp4 and a 2 x 2 contact picture) of each
  choose(folder, cid) -> doc                          another candidate, or 'none' for no cold open
  for_film(folder) -> candidate | None                what the final film opens with (None without the file, when 'none' is chosen, or with STRATA_COLD_OPEN=0)
  segment_of(c)                                       the plan-segment dict of a candidate (what edit/framing.resolve_segment and the renderer read)

The final film (render/final.py) renders the chosen window from the original footage with the film's own framing for its technique, no race overlay, the clip's own sound (audio/mix.clip_sound) and its speech as subtitles, then cuts to the
opening title (edit/bookends.py) and the story."""
import json, os, time
import numpy as np

COLD_S = 6.0                 # the length of a window, before it grows to take whole lines
MAX_S = 10.0                 # the longest a cold open may grow to
LINE_PAD_S = 0.25            # kept before the first and after the last word of a line in the window
STEP_S = 0.5                 # windows are tried this far apart
EARLY = 0.25                 # clips in the first quarter of the race are not used while later ones exist
MIN_STEADY = 0.15            # no second of the window may be shakier than this (steadiness, 0 shaking .. 1 still)
GAP_S = 30.0                 # two candidates from one clip are at least this far apart
PER = 5                      # candidates kept
PER_CLIP = 2                 # of them from any one clip
MUST_BONUS = 0.3             # added to a second inside words you marked MUST USE
WEIGHTS = dict(excite=0.35, energy=0.2, scenery=0.2, you=0.15, steady=0.1)
CROWD = ('cheering', 'shouting', 'laughter', 'crowd')


def fit_range(arrays):
    """Each array's values as their rank among all the values of all the arrays, 0 (lowest) to 1 (highest); tied values take the lowest of their ranks (a level most seconds share, such as no cheering at all, is not lifted by being common), NaN becomes 0.
    The project's own range, whatever its absolute levels; all alike is 0.5."""
    flat = np.concatenate([np.asarray(a, float) for a in arrays]) if arrays else np.zeros(0); ok = np.isfinite(flat)
    if ok.sum() < 2 or np.ptp(flat[ok]) == 0: return [np.where(np.isfinite(np.asarray(a, float)), 0.5, 0.0) for a in arrays]
    vals = np.sort(flat[ok]); out = []
    for a in arrays:
        a = np.asarray(a, float); r = np.searchsorted(vals, a, 'left') / (len(vals) - 1)
        out.append(np.where(np.isfinite(a), np.clip(r, 0.0, 1.0), 0.0))
    return out


def whole_lines(a, b, lines, dur, max_s=MAX_S, pad=LINE_PAD_S):
    """The window [a, b) grown so that no line ([(t0, t1, mark)]) is cut: a line across an edge is taken whole, with `pad` either side. None when that makes it longer than `max_s` or runs it off the clip (0 to `dur`)."""
    for _ in range(len(lines) + 1):
        na, nb = a, b
        for t0, t1, _m in lines:
            if t0 < na < t1: na = t0 - pad
            if t0 < nb < t1: nb = t1 + pad
        if (na, nb) == (a, b): break
        a, b = na, nb
    if a < -1e-6 or b > dur + 1e-6 or b - a > max_s + 1e-6: return None
    return max(a, 0.0), min(b, dur)


def _technique(you, excite, people):
    """The camera move: your face when you are close in view, a pan across the crowd when it is loud and busy, else a push in."""
    if you >= 0.5: return 'selfie_close', 'you'
    if excite >= 0.6 and people >= 2: return 'pan_reveal', 'ahead'
    return 'push_in', 'ahead'


def _why(parts, pos):
    bits = [f"{n} {parts[n]:.2f}" for n in ('excite', 'energy', 'scenery', 'you') if parts.get(n, 0) >= 0.6]
    if parts.get('must'): bits.append('words you marked must use')
    return ', '.join(bits + [f'{round(pos * 100)}% of the way through the race'])


def candidates(sigs, per=PER, T=COLD_S, step=STEP_S, per_clip=PER_CLIP, gap=GAP_S):
    """The best cold-open windows of a project, best first: [dict(id, clip, clip_start_s, dur_s, technique, view, speech, score, parts, why, pos, variant_seed)]. `sigs`: per clip dict(clip, pos 0..1 in the race, dur, t (second centres),
    excite, energy, scenery, you, steady, people (arrays over t), usable (bool array), lines [(t0, t1, mark)])."""
    sigs = [s for s in sigs if len(s['t'])]
    if not sigs: return []
    late = [s for s in sigs if s['pos'] >= EARLY]; sigs = late or sigs
    scaled = {k: [0.5 * r + 0.5 * np.clip(np.nan_to_num(np.asarray(s[k], float)), 0, 1) for r, s in zip(fit_range([s[k] for s in sigs]), sigs)] for k in ('excite', 'energy', 'scenery')}; found = []          # half its rank in the project, half its own level (0..1): a loud race's quieter cheer is not the same as its loudest
    for i, s in enumerate(sigs):
        t = np.asarray(s['t'], float); usable = np.asarray(s['usable'], bool); steady = np.asarray(s['steady'], float); you = np.asarray(s['you'], float); people = np.asarray(s.get('people', np.zeros(len(t))), float)
        must = np.zeros(len(t))
        for t0, t1, m in s['lines']:
            if m == 'must': must[(t >= t0) & (t <= t1)] = 1.0
        per_s = (WEIGHTS['excite'] * scaled['excite'][i] + WEIGHTS['energy'] * scaled['energy'][i] + WEIGHTS['scenery'] * scaled['scenery'][i] + WEIGHTS['you'] * np.clip(you, 0, 1) + WEIGHTS['steady'] * np.clip(steady, 0, 1)) + MUST_BONUS * must
        for a0 in np.arange(0.0, s['dur'] - T + 1e-9, step):
            w = whole_lines(float(a0), float(a0) + T, s['lines'], s['dur'])
            if w is None: continue
            a, b = w; m = (t >= a) & (t < b)
            if m.sum() < 2 or not usable[m].all() or steady[m].min() < MIN_STEADY: continue
            if any(mk == 'never' and t1 > a and t0 < b for t0, t1, mk in s['lines']): continue
            ex = scaled['excite'][i][m]; sc = (0.8 * per_s[m].mean() + 0.2 * ex.max()) * (0.8 + 0.2 * s['pos'])
            parts = dict(excite=round(float(ex.mean()), 2), energy=round(float(scaled['energy'][i][m].mean()), 2), scenery=round(float(scaled['scenery'][i][m].mean()), 2), you=round(float(you[m].mean()), 2), steady=round(float(steady[m].mean()), 2), must=bool(must[m].any()))
            tech, view = _technique(parts['you'], parts['excite'], float(people[m].mean()))
            speech = any(t1 > a and t0 < b for t0, t1, _ in s['lines'])
            found.append(dict(clip=s['clip'], clip_start_s=round(a, 2), dur_s=round(b - a, 2), technique=tech, view=view, speech=speech, score=round(float(sc), 3), parts=parts, pos=round(float(s['pos']), 3), why=_why(parts, s['pos'])))
    out = []
    for c in sorted(found, key=lambda c: -c['score']):
        mine = [o for o in out if o['clip'] == c['clip']]
        if len(mine) >= per_clip or any(abs(o['clip_start_s'] - c['clip_start_s']) < gap for o in mine): continue
        out.append(c)
        if len(out) >= per: break
    for k, c in enumerate(out): c.update(id=f'cold-{k}', variant_seed=2000 + k)
    return out


def segment_of(c):
    """The plan-segment dict (what edit/framing.resolve_segment and the film renderer read) of a candidate: a window of footage at film time 0 with its own speech."""
    return dict(id=f"{c['clip']}@cold.{c['id']}", clip=c['clip'], clip_start_s=c['clip_start_s'], dur_s=c['dur_s'], technique=c['technique'], variant_seed=c.get('variant_seed', 1), kind='you' if c.get('view') == 'you' else 'best', view=c.get('view', 'ahead'),
                speech=bool(c.get('speech')), role='cold_open', transition=dict(type='cut', beats=0, dur_s=0.0), utc_start=None, film_start_s=0.0, index=0)


def _load(d, name):
    try: return json.load(open(os.path.join(d, name)))
    except (OSError, ValueError): return None


def clip_signals(d, clip, pos):
    """The per-second signals of one clip folder (see `candidates`), or None when the clip cannot be read."""
    from strata360.analysis import candidates as CA, sound_events as SE
    from strata360.edit import script_pack as SP
    try: T = CA.timeline(d)
    except (OSError, KeyError, TypeError, ValueError, ZeroDivisionError): return None
    t = T['t']; ev = _load(d, 'audio_events.json'); excite = np.zeros(len(t))
    if ev and ev.get('windows'):
        for k, x in enumerate(t):
            c = SE.scores_between(ev, x - 0.5, x + 0.5); excite[k] = max([c.get(n, 0.0) for n in CROWD] or [0.0])
    cj = _load(d, 'candidates.json'); usable = np.zeros(len(t), bool)
    if cj and cj.get('spans') is not None:
        for sp in cj['spans']: usable[(t >= sp['start_s']) & (t < sp['end_s'])] = True
    else: usable = (T['steady'] >= 0.1) & (T['expo'] >= 0.4) & (T['blocked'] <= 0.5)
    lines = [(float(l['t0']), float(l['t1']), l.get('mark')) for l in SP.transcript_lines(d, SP.label_of(clip))]
    return dict(clip=clip, pos=pos, dur=float(T['dur']), t=t, excite=excite, energy=T['energy'], scenery=T['scenic'], you=T['you_close'], steady=T['steady'], people=T['people'], usable=usable, lines=lines)


def signals(folder):
    """The signals of every clip of a project, in race order."""
    from strata360.pipeline import config
    from strata360.edit import bookends as BK
    rd = os.path.join(config.race_dir(folder), 'clips'); clips = BK._race_clips(folder) if os.path.isdir(rd) else []; n = len(clips); out = []
    for i, (c, _) in enumerate(clips):
        s = clip_signals(os.path.join(rd, c), c, i / max(n - 1, 1))
        if s is not None: out.append(s)
    return out


def out_dir(folder):
    from strata360.pipeline import config
    return os.path.join(config.race_dir(folder), 'cold_open')


def render_preview(folder, c, d, lib=None):
    """A preview of a candidate from the clip's proxy (960x540, the bookends' preview): (mp4, jpg) in `d`."""
    from strata360.edit import bookends as BK, framing as FR, techniques as TQ
    lib = lib or TQ.with_cams(TQ.load(), folder); data = FR.clip_data(folder, c['clip'], head=False); path = FR.resolve_segment(segment_of(c), lib, data)
    return BK.render_preview(folder, dict(c, kind='cold_open'), d, lib=lib, data=data, path=path)


def run(folder, per=PER, render=False, log=print):
    """Find the candidates, choose the best, write cold_open.json (returned). A choice made before (`choose`) is kept while that candidate is still found."""
    d = out_dir(folder); os.makedirs(d, exist_ok=True); t0 = time.time(); cs = candidates(signals(folder), per=per); old = _load(d, 'cold_open.json') or {}
    key = lambda c: (c['clip'], c['clip_start_s']); chosen, by = (cs[0]['id'] if cs else None), 'score'
    if old.get('by') == 'you':                                                                        # your own choice stands while it is still there
        if old.get('chosen') == 'none': chosen, by = 'none', 'you'
        else:
            prev = next((c for c in (old.get('candidates') or []) if c['id'] == old.get('chosen')), None); same = next((c['id'] for c in cs if prev is not None and key(c) == key(prev)), None)
            if same is not None: chosen, by = same, 'you'
    if render:
        for c in cs:
            try: c['video'], c['picture'] = (os.path.relpath(p, d) for p in render_preview(folder, c, d))
            except Exception as e: c['error'] = f'{type(e).__name__}: {e}'; log(f"  {c['id']}: {c['error']}")
    doc = dict(schema=1, generated=time.strftime('%Y-%m-%dT%H:%M:%S'), seconds=round(time.time() - t0, 1), candidates=cs, chosen=chosen, by=by)
    json.dump(doc, open(os.path.join(d, 'cold_open.json'), 'w'), indent=1); return doc


def choose(folder, cid):
    """Make candidate `cid` the cold open ('none': the film has none). Returns the document; raises ValueError for an id that is not a candidate."""
    p = os.path.join(out_dir(folder), 'cold_open.json'); doc = _load(out_dir(folder), 'cold_open.json')
    if doc is None: raise ValueError('no cold open candidates yet: run `strata360 coldopen FOLDER` first')
    if cid != 'none' and not any(c['id'] == cid for c in doc['candidates']): raise ValueError(f"no candidate {cid}: the candidates are {', '.join(c['id'] for c in doc['candidates']) or 'none'}")
    doc.update(chosen=cid, by='you'); json.dump(doc, open(p, 'w'), indent=1); return doc


def for_film(folder):
    """The candidate the film opens with, or None (no cold_open.json, 'none' chosen, or STRATA_COLD_OPEN=0)."""
    if os.environ.get('STRATA_COLD_OPEN') == '0': return None
    doc = _load(out_dir(folder), 'cold_open.json')
    if not doc or doc.get('chosen') in (None, 'none'): return None
    return next((c for c in doc.get('candidates') or [] if c['id'] == doc['chosen']), None)
