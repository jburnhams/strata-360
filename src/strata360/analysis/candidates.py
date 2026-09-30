"""`candidates` stage: turn all per-clip data into the usable moments the optimiser and the GUI work with (`candidates.json`).

A candidate is a stretch of one clip that can be cut anywhere inside: it has a start and end (clip-relative and UTC), a feature vector in the names the technique library
uses (`edit/techniques.json` needs: steady, clear_nadir, open_ground, canopy, subject, speech, protagonist, low_obstruction, resolution), a quality (0..1), an energy (0..1),
the shortest/longest sensible cut, and for speech the transcript with safe cut points. Everything is computed from a 1 Hz score timeline built from motion, exposure, audio,
transcript, and (when present) people/identity/scenes, so the stage never decodes video. Missing optional data falls back to neutral values and is listed in `missing`.

Splitting rules: a stretch ends where the picture becomes unusable (very shaky, lens blocked, exposure blown/crushed), where speech starts or ends (speech gets its own stretch so
dialogue is framed steadily and cut on pauses), and where the scene changes (setting or crowd level). Stretches shorter than 1.5 s are dropped."""
import json, os
import numpy as np

SCHEMA_VERSION = 1
MIN_LEN = 1.5
MAX_STRETCH = 45.0


def _load(d, name):
    p = os.path.join(d, name)
    return json.load(open(p)) if os.path.exists(p) else None


def _iso_add(start_utc, s):
    import datetime as dt
    t0 = dt.datetime.fromisoformat(start_utc.replace('Z', '+00:00')); return (t0 + dt.timedelta(seconds=float(s))).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def timeline(d):
    """Per-second arrays for a clip folder: dict(n, steady, expo, speech, me, people, energy, scenic, blocked, setting, ...) plus the raw docs and a `missing` list."""
    sp_doc = _load(d, 'speakers.json'); clip = _load(d, 'clip.json'); mo = _load(d, 'motion.json'); ex = _load(d, 'exposure.json'); au = _load(d, 'audio.json'); tr = _load(d, 'transcript.json'); al = _load(d, 'alignment.json')
    idn = _load(d, 'identity.json'); sc = _load(d, 'scenes.json'); dur = float(clip['video']['source_frames'] / clip['video']['nominal_fps']); n = max(int(np.floor(dur)), 1); t = np.arange(n) + 0.5
    missing = [k for k, v in (('motion', mo), ('speakers', sp_doc), ('exposure', ex), ('audio', au), ('transcript', tr), ('identity', idn), ('scenes', sc)) if v is None]
    def at(ts, vs, default): return np.interp(t, ts, vs) if len(ts) else np.full(n, default)
    steady = at(mo['series']['t'], np.exp(-np.array(mo['series']['shake_dps']) / 25.0), 0.5) if mo else np.full(n, 0.5)
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
    return dict(n=n, t=t, dur=dur, chatter=chatter, steady=steady, energy=0.6 * energy + 0.4 * sen, expo=expo, speech=speech, me=me, people=people, scenic=scenic, blocked=blocked, canopy=canopy, open_ground=open_ground,
                setting=setting, missing=missing, clip=clip, tr=tr, al=al, sc=sc, mo=mo)


def build(d, thr=0.32):
    T = timeline(d); n = T['n']; clip = T['clip']
    q = np.clip(0.5 * T['steady'] + 0.2 * T['expo'] + 0.2 * T['scenic'] + 0.1 * (1 - T['blocked']), 0, 1) * (1 - 0.7 * T['blocked'])                           # per-second usefulness
    good = (q >= thr) & (T['steady'] >= 0.1); speech = T['speech'] > 0.5; chat = T['chatter'] > 0.5
    key = np.zeros(n, int); k = 0                                                                                                                       # a new stretch starts when any of the reasons changes
    for i in range(1, n):
        if good[i] != good[i - 1] or speech[i] != speech[i - 1] or chat[i] != chat[i - 1] or (T['setting'][i] != T['setting'][i - 1] and T['setting'][i] and T['setting'][i - 1]) or abs(T['people'][i] - T['people'][i - 1]) > 6: k += 1
        key[i] = k
    out = []
    for kk in np.unique(key):
        idx = np.flatnonzero(key == kk); i0, i1 = int(idx[0]), int(idx[-1]) + 1
        if not good[i0] or (i1 - i0) < MIN_LEN: continue
        while i1 - i0 > MAX_STRETCH:                                                                                                                  # very long stretches are split so alternatives exist
            j = i0 + int(MAX_STRETCH); out.append((i0, j, bool(speech[i0]))); i0 = j
        out.append((i0, i1, bool(speech[i0])))
    cands = []
    for c, (i0, i1, sp) in enumerate(out):
        sl = slice(i0, i1); qq = float(q[sl].mean()); s_ = float(T['steady'][sl].mean()); nad = float(np.clip(1.0 - T['blocked'][sl].max() * 0.8, 0, 1))
        feats = dict(steady=round(s_, 3), clear_nadir=round(nad, 3), open_ground=round(float(T['open_ground'][sl].mean()), 3), canopy=round(float(T['canopy'][sl].mean()), 3),
                     subject=round(float(np.clip(T['me'][sl].mean() * 0.7 + min(T['people'][sl].mean(), 3) / 3 * 0.5, 0, 1)), 3), speech=1.0 if sp else 0.0, protagonist=round(float(T['me'][sl].mean()), 3),
                     low_obstruction=round(float(1 - T['blocked'][sl].mean()), 3), chatter=round(float(T['chatter'][sl].mean()), 3), resolution=round(float(np.clip(0.55 + 0.45 * T['expo'][sl].mean(), 0, 1)), 3))
        cand = dict(id=f"{clip['clip_id']}#{c:02d}", clip=clip['clip_id'], start_s=float(i0), end_s=float(i1), start_utc=_iso_add(clip['time']['start_utc'], i0), end_utc=_iso_add(clip['time']['start_utc'], i1),
                    quality=round(qq, 3), energy=round(float(T['energy'][sl].mean()), 3), min_dur=3.0 if sp else 1.0, max_dur=float(i1 - i0), features=feats,
                    settings=sorted({x for x in T['setting'][i0:i1] if x}), people=round(float(T['people'][sl].mean()), 1))
        if sp and T['tr']:
            segs = [s for s in T['tr']['segments'] if s['t1'] > i0 and s['t0'] < i1 and s.get('text', '').strip() and not s.get('flags')]
            cand['transcript'] = [dict(t0=s['t0'], t1=s['t1'], lang=s['lang'], text=s['text'], text_en=s.get('text_en')) for s in segs]
            cand['cuts'] = [dict(t=c_['t'], pause_s=c_['pause_s']) for a in ((T['al'] or {}).get('segments') or []) if a for c_ in (a.get('cuts') or []) if c_ and c_.get('safe') and i0 <= c_['t'] <= i1]
        cands.append(cand)
    return dict(schema=SCHEMA_VERSION, thresholds=dict(usable_score=thr, min_len_s=MIN_LEN, max_stretch_s=MAX_STRETCH), missing=T['missing'], candidates=cands,
                summary=dict(n=len(cands), total_s=round(sum(c['end_s'] - c['start_s'] for c in cands), 1), speech=sum(1 for c in cands if c['features']['speech']), clip_s=round(T['dur'], 1)))
