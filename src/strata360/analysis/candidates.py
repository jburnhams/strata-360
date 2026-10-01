"""`candidates` stage: turn all per-clip data into the usable moments the optimiser and the GUI work with (`candidates.json`).

A candidate is a stretch of one clip that can be cut anywhere inside: it has a start and end (clip-relative and UTC), a feature vector in the names the technique library
uses (`edit/techniques.json` needs: steady, clear_nadir, open_ground, canopy, subject, speech, protagonist, low_obstruction, resolution), a quality (0..1), an energy (0..1),
the shortest/longest sensible cut, and for speech the transcript with safe cut points. Everything is computed from a 1 Hz score timeline built from motion, exposure, audio,
transcript, and (when present) people/identity/scenes, so the stage never decodes video. Missing optional data falls back to neutral values and is listed in `missing`.

Splitting rules: a stretch ends where the picture becomes unusable (very shaky, lens blocked, exposure blown/crushed), where speech starts or ends (speech gets its own stretch so
dialogue is framed steadily and cut on pauses), and where the scene changes (setting or crowd level). Stretches shorter than 1.5 s are dropped."""
import json, os
import numpy as np
from scipy.ndimage import uniform_filter1d

SCHEMA_VERSION = 2
MIN_LEN = 1.5
MAX_STRETCH = 45.0


def _load(d, name):
    p = os.path.join(d, name)
    return json.load(open(p)) if os.path.exists(p) else None


def _iso_add(start_utc, s):
    import datetime as dt
    t0 = dt.datetime.fromisoformat(start_utc.replace('Z', '+00:00')); return (t0 + dt.timedelta(seconds=float(s))).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


GRID_LOW_DETAIL = 0.004; GRID_LOW_CONTRAST = 0.03; GRID_BAD_FRAC = 0.5      # view-quality grid: a cell is "empty" below both; the whole frame is bad when more than this share of it is empty


def low_fraction(vq):
    """Per quality map (once a second) the share of the covered sphere (solid-angle weighted) in cells with both low detail and low contrast: a frame that is mist, a blocked lens or darkness all over has
    most of its cells empty; a frame with a clear sky or a plain field only some. `vq` is `exposure.load_quality`."""
    det, con = vq['detail'].astype(np.float32), vq['contrast'].astype(np.float32); ok = np.isfinite(det) & np.isfinite(con); gh = det.shape[1]
    wlat = np.cos(np.radians(90.0 - (np.arange(gh) + 0.5) * 180.0 / gh))[None, :, None]; w = ok * wlat; low = ((det < GRID_LOW_DETAIL) & (con < GRID_LOW_CONTRAST)) * w
    return low.sum((1, 2)) / np.maximum(w.sum((1, 2)), 1e-9)


def timeline(d):
    """Per-second arrays for a clip folder: dict(n, steady, expo, speech, me, people, energy, scenic, blocked, setting, ...) plus the raw docs and a `missing` list."""
    sp_doc = _load(d, 'speakers.json'); clip = _load(d, 'clip.json'); mo = _load(d, 'motion.json'); ex = _load(d, 'exposure.json'); au = _load(d, 'audio.json'); tr = _load(d, 'transcript.json'); al = _load(d, 'alignment.json')
    idn = _load(d, 'identity.json'); sc = _load(d, 'scenes.json'); dur = float(clip['video']['source_frames'] / clip['video']['nominal_fps']); n = max(int(np.floor(dur)), 1); t = np.arange(n) + 0.5
    missing = [k for k, v in (('motion', mo), ('speakers', sp_doc), ('exposure', ex), ('audio', au), ('transcript', tr), ('identity', idn), ('scenes', sc)) if v is None]
    def at(ts, vs, default): return np.interp(t, ts, vs) if len(ts) else np.full(n, default)
    steady = at(mo['series']['t'], np.exp(-np.array(mo['series']['shake_dps']) / 25.0), 0.5) if mo else np.full(n, 0.5)
    shake = at(mo['series']['t'], np.array(mo['series']['shake_dps']), 0.0) if mo else np.zeros(n)
    energy = at(mo['series']['t'], np.clip(np.array(mo['series']['ang_speed_dps']) / 90.0 + np.array(mo['series']['acc_energy']) / 1.2, 0, 1), 0.4) if mo else np.full(n, 0.4)
    expo = np.ones(n)
    if ex:
        ts = [f['t_s'] for f in ex['frames']]; bad = [f['sphere']['clipped_frac'] + f['sphere']['crushed_frac'] for f in ex['frames']]; expo = 1.0 - np.clip(at(ts, bad, 0.0) * 2.5, 0, 1)
    speech = np.zeros(n); chatter = np.zeros(n)                                                       # speech = the wearer talking (dialogue); chatter = other people's voices around them
    labels = {}
    if sp_doc:
        for s in sp_doc['segments']:
            if s.get('label'): labels[(round(s['t0'], 2), round(s['t1'], 2))] = s['label']
    for s in (tr['segments'] if tr else []):
        if s.get('text', '').strip() and not s.get('flags') and not s.get('suspect') and (s.get('no_speech') or 0) < 0.6:
            who = labels.get((round(s['t0'], 2), round(s['t1'], 2)), 'wearer' if not labels else 'other')     # without voice labels every voice counts as dialogue (old behaviour)
            (speech if who == 'wearer' else chatter)[(t >= s['t0']) & (t <= s['t1'])] = 1.0
    me = np.zeros(n); people = np.zeros(n)
    if idn and idn['samples']:
        ts = [r['t_s'] for r in idn['samples']]; me = at(ts, [1.0 if r['me'] else 0.0 for r in idn['samples']], 0.0); people = at(ts, [r['n_people'] for r in idn['samples']], 0.0)
    scenic = np.full(n, 0.5); sen = np.full(n, 0.5); blocked = np.zeros(n); setting = [None] * n; canopy = np.zeros(n); open_ground = np.full(n, 0.5)
    if sc:
        fr = [i for i in sc['items'] if i['ok'] and i['view'] == 'front']; ts = [i['t_s'] for i in fr]
        if fr:
            scenic = at(ts, [float(i['scenic']) if isinstance(i.get('scenic'), (int, float)) else 0.5 for i in fr], 0.5); sen = at(ts, [float(i['energy']) if isinstance(i.get('energy'), (int, float)) else 0.5 for i in fr], 0.5)
            blocked = at(ts, [1.0 if i.get('lens_problems') in ('blocked', 'fog') else 0.4 if i.get('lens_problems') in ('droplets', 'glare') else 0.0 for i in fr], 0.0)
            canopy = at(ts, [1.0 if i.get('setting') in ('forest',) else 0.3 if i.get('setting') == 'trail' else 0.0 for i in fr], 0.0)
            open_ground = at(ts, [1.0 if i.get('setting') in ('field', 'road', 'mountain', 'town') else 0.3 for i in fr], 0.5)
            near = [int(np.argmin(np.abs(np.array(ts) - x))) for x in t]; setting = [fr[j].get('setting') for j in near]
    grid_low = np.zeros(n); vq = None
    try:
        from strata360.analysis.exposure import load_quality
        vq = load_quality(d)
    except ImportError: pass
    if vq is not None and len(vq['t']):                                                               # a double check on "the lens is blocked or fogged": the vision model says so AND most of the sphere has no detail or contrast; if the picture as a whole still has something in it, the stretch stays usable
        grid_low = at(vq['t'], low_fraction(vq), 0.0); hard = blocked > 0.5; blocked = np.where(hard & (grid_low > GRID_BAD_FRAC), blocked, np.where(hard, 0.4, blocked))
    return dict(n=n, t=t, dur=dur, grid_low=grid_low, has_quality=vq is not None, shake=shake, chatter=chatter, steady=steady, energy=0.6 * energy + 0.4 * sen, expo=expo, speech=speech, me=me, people=people, scenic=scenic, blocked=blocked, canopy=canopy, open_ground=open_ground,
                setting=setting, missing=missing, clip=clip, tr=tr, al=al, sc=sc, mo=mo)


KIND_TEXT = {'span': ('the footage becomes usable', 'the footage stops being usable'), 'best': ('the best-looking part of the stretch begins', 'the best-looking part ends'),
             'speech': ('you start speaking', 'you stop speaking'), 'person': ('another person comes into view', 'the person leaves the view'), 'you': ('you come into view', 'you leave the view'),
             'scene': ('the scene changes', 'the scene changes again')}
KIND_VIEW = {'span': 'ahead', 'best': 'ahead', 'speech': 'speaker', 'person': 'person', 'you': 'you', 'scene': 'ahead'}


def _runs(mask, gap=0):
    """(start, end) second ranges where the boolean mask is true; holes of at most `gap` seconds are bridged."""
    idx = np.flatnonzero(mask); out = []
    for k in idx:
        if out and k - out[-1][1] <= gap: out[-1][1] = int(k) + 1
        else: out.append([int(k), int(k) + 1])
    return [(a, b) for a, b in out]


def _inside(runs, spans, min_len):
    """The parts of `runs` that lie inside a usable span (a run crossing two spans is cut), at least min_len seconds: [(a, b, span index)]."""
    out = []
    for a, b in runs:
        for k, (s0, s1) in enumerate(spans):
            x, y = max(a, s0), min(b, s1)
            if y - x >= min_len: out.append((x, y, k))
    return out


def build(d, thr=None):
    """Usable footage and the ways to see it.

    Unusable means a real problem and nothing else: camera shake too violent, the lens blocked or fogged, or the picture badly exposed. Everything else is usable, and what to use of it is the
    optimiser's choice. So a clip has a few usable SPANS (the stretches between problems), and on top of each span overlapping candidates that are different ways to see the same footage:
      span    the whole usable stretch (framed ahead)             best    its steadiest, best-looking parts
      speech  you talking (dialogue: steady framing, cut on pauses)   person  others in view (framed on them)     you   you in view    scene   one setting of a stretch with several
    Candidates overlap freely; the planner never uses two overlapping stretches of one clip at once. `priority` ranks a clip's candidates by quality (1 = best)."""
    T = timeline(d); n = T['n']; clip = T['clip']
    q = np.clip(0.5 * T['steady'] + 0.2 * T['expo'] + 0.2 * T['scenic'] + 0.1 * (1 - T['blocked']), 0, 1) * (1 - 0.7 * T['blocked'])                           # per-second usefulness (a ranking, never a reason to drop footage)
    shaky = T['steady'] < 0.1; blocked = T['blocked'] > 0.5; badexp = T['expo'] < 0.4; bad = shaky | blocked | badexp
    why_bad = ['too shaky' if shaky[i] else 'lens blocked or fogged' if blocked[i] else 'badly exposed' if badexp[i] else None for i in range(n)]
    detail = lambda i: f"too shaky ({T['shake'][i]:.0f} deg/s of camera shake; the limit is about 57)" if shaky[i] else 'lens blocked or fogged' if blocked[i] else 'badly exposed (blown out or crushed)'
    stats = lambda sl: dict(steadiness=round(float(T['steady'][sl].mean()), 2), shake_dps=round(float(T['shake'][sl].mean()), 1), exposure_ok=round(float(T['expo'][sl].mean()), 2), scenic=round(float(T['scenic'][sl].mean()), 2),
                            lens_blocked=round(float(T['blocked'][sl].mean()), 2), people=round(float(T['people'][sl].mean()), 1), setting=next((x for x in T['setting'][sl] if x), None), score=round(float(q[sl].mean()), 2))
    good_runs = _runs(~bad); spans = [(a, b) for a, b in good_runs if b - a >= MIN_LEN]; moments = []
    for a, b in _runs(bad):                                                                                        # problems: runs of bad seconds, with the reasons that apply
        rs = [why_bad[i] for i in range(a, b)]; top = sorted(set(rs), key=lambda x: -rs.count(x))
        moments.append(dict(start_s=float(a), end_s=float(b), usable=False, reasons=top, detail=detail(a + rs.index(top[0])), stats=stats(slice(a, b)), starts_because=('start of the clip' if a == 0 else f'{top[0]} begins'), ends_because=('end of the clip' if b >= n else 'the problem ends')))
    for a, b in good_runs:                                                                                         # good footage squeezed between problems, too short to cut
        if b - a < MIN_LEN: moments.append(dict(start_s=float(a), end_s=float(b), usable=False, reasons=[f'too short ({b - a} s) between problems; the minimum is {MIN_LEN} s'], detail=None, stats=stats(slice(a, b)), starts_because='the problem before it ends', ends_because='the next problem begins'))
    moments.sort(key=lambda m: m['start_s'])
    speech = T['speech'] > 0.5; me = T['me'] >= 0.5; found = []                                                   # (a, b, kind, span index)
    for k, (a, b) in enumerate(spans): found.append((a, b, 'span', k))
    for a, b, k in _inside(_runs(uniform_filter1d(q, 3, mode='nearest') >= 0.7, gap=1), spans, 2.5):
        if (b - a) < 0.85 * (spans[k][1] - spans[k][0]): found.append((a, b, 'best', k))
    for a, b, k in _inside(_runs(speech, gap=1), spans, MIN_LEN): found.append((a, b, 'speech', k))
    for a, b, k in _inside(_runs(me, gap=1), spans, 2.0): found.append((a, b, 'you', k))
    try:
        from strata360.analysis import views
        ps = views.person_samples(str(d), (clip.get('source_files') or {}).get('osv')) if os.path.exists(os.path.join(d, 'identity.json')) else []
    except Exception: ps = []
    if ps:
        pm = np.zeros(n, bool)
        for s in ps: pm[max(int(s['t'] - 0.5), 0):min(int(s['t'] + 1.5), n)] = True
        for a, b, k in _inside(_runs(pm, gap=1), spans, 2.0): found.append((a, b, 'person', k))
    st = T['setting']
    for k, (s0, s1) in enumerate(spans):
        if len({x for x in st[s0:s1] if x}) >= 2:
            cur = s0
            for j in range(s0 + 1, s1 + 1):
                if j == s1 or st[j] != st[cur]:
                    if st[cur] and j - cur >= 2.5 and (j - cur) < 0.85 * (s1 - s0): found.append((cur, j, 'scene', k))
                    cur = j
    order = {'span': 0, 'best': 1, 'speech': 2, 'you': 3, 'person': 4, 'scene': 5}; found.sort(key=lambda x: (x[0], order[x[2]], x[1])); cands = []
    for c, (i0, i1, kind, k) in enumerate(found):
        sl = slice(i0, i1); qq = float(q[sl].mean()); s_ = float(T['steady'][sl].mean()); nad = float(np.clip(1.0 - T['blocked'][sl].max() * 0.8, 0, 1)); sp = kind == 'speech'
        feats = dict(steady=round(s_, 3), clear_nadir=round(nad, 3), open_ground=round(float(T['open_ground'][sl].mean()), 3), canopy=round(float(T['canopy'][sl].mean()), 3),
                     subject=round(float(np.clip(T['me'][sl].mean() * 0.7 + min(T['people'][sl].mean(), 3) / 3 * 0.5, 0, 1)), 3), speech=1.0 if sp else 0.0, protagonist=round(float(T['me'][sl].mean()), 3),
                     low_obstruction=round(float(1 - T['blocked'][sl].mean()), 3), chatter=round(float(T['chatter'][sl].mean()), 3), resolution=round(float(np.clip(0.55 + 0.45 * T['expo'][sl].mean(), 0, 1)), 3))
        s0, s1 = spans[k]; before = why_bad[s0 - 1] if s0 > 0 else None; after = why_bad[s1] if s1 < n else None
        if kind == 'span': sb = f'usable again after a problem ({before})' if before else 'start of the clip'; eb = f'a problem begins ({after})' if after else 'end of the clip'
        else: sb, eb = KIND_TEXT[kind]
        cand = dict(id=f"{clip['clip_id']}#{c:02d}", clip=clip['clip_id'], kind=kind, view=KIND_VIEW[kind], span=k, start_s=float(i0), end_s=float(i1), start_utc=_iso_add(clip['time']['start_utc'], i0), end_utc=_iso_add(clip['time']['start_utc'], i1),
                    quality=round(qq, 3), energy=round(float(T['energy'][sl].mean()), 3), min_dur=3.0 if sp else 1.0, max_dur=float(i1 - i0), features=feats, settings=sorted({x for x in T['setting'][i0:i1] if x}), people=round(float(T['people'][sl].mean()), 1))
        cand['why'] = dict(starts_because=sb, ends_because=eb, steadiness=round(s_, 2), shake_dps=round(float(T['shake'][sl].mean()), 1), exposure_ok=round(float(T['expo'][sl].mean()), 2), scenic=round(float(T['scenic'][sl].mean()), 2),
                           lens_blocked=round(float(T['blocked'][sl].mean()), 2), score=round(qq, 2), speech=sp, chatter=round(float(T['chatter'][sl].mean()), 2))
        if sp and T['tr']:
            segs = [s for s in T['tr']['segments'] if s['t1'] > i0 and s['t0'] < i1 and s.get('text', '').strip() and not s.get('flags')]
            cand['transcript'] = [dict(t0=s['t0'], t1=s['t1'], lang=s['lang'], text=s['text'], text_en=s.get('text_en')) for s in segs]
            cand['cuts'] = [dict(t=c_['t'], pause_s=c_['pause_s']) for a in ((T['al'] or {}).get('segments') or []) if a for c_ in (a.get('cuts') or []) if c_ and c_.get('safe') and i0 <= c_['t'] <= i1]
        cands.append(cand)
    for r, c in enumerate(sorted(cands, key=lambda c: (-c['quality'], -(c['end_s'] - c['start_s']))), 1): c['priority'] = r
    return dict(schema=SCHEMA_VERSION, thresholds=dict(usable_score=0.0, min_len_s=MIN_LEN, max_stretch_s=MAX_STRETCH), missing=T['missing'], candidates=cands, unusable=moments,
                spans=[dict(start_s=float(a), end_s=float(b)) for a, b in spans],
                summary=dict(unusable_s=round(sum(m['end_s'] - m['start_s'] for m in moments), 1), usable_s=round(sum(b - a for a, b in spans), 1), n=len(cands), spans=len(spans), total_s=round(sum(b - a for a, b in spans), 1),
                             speech=sum(1 for c in cands if c['kind'] == 'speech'), clip_s=round(T['dur'], 1)))
