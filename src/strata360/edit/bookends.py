"""Openings and endings for the film: a short, spectacular first shot and last shot, found in the footage and chosen with a local vision model.

Two kinds of shot, both a few seconds of the original footage with a camera move, so animated text can go over them later:

  globe_face   the whole sphere as a little planet that opens (opening) or closes (ending) onto a close view of your face: the camera starts looking down at the globe and zooms into you
  crowd        the crowd at the start line (opening) or at the finish (ending): a push in or a pan across a busy place, from the moments where the scene stage saw many people

`candidates(folder)` lists the windows that suit each kind from the analysis that is already there (the face view of the wearer, the shake, the scene labels and scenery scores, where in the race the clip lies), best first.
`segment_of(c)` turns one into a plan-segment dict and `framing_of` into its camera path (the same functions the film uses, edit/framing.py), `render_preview` makes a short video and a 2 x 2 contact picture, and `rank` shows the
contact pictures to a local vision model and asks which is the most striking opening (or ending): the answer, with its reasons, is stored with the candidates in `<project>/strata360/bookends/bookends.json`."""
import json, os, re, time
import numpy as np

GLOBE_S = 2.2                    # the zoom between the globe and the face
FACE_S = 3.2                     # the hold on the face
CROWD_S = 5.0
SPIN_DEG = 90.0                  # how far the globe turns while it opens
MIN_FACE = 0.8                   # mean face score (face_view.json, 1 = a clear face) over a face window
MIN_EACH = 0.5                   # and the lowest second in it
CROWD_PEOPLE = 6                 # people in the front view (scenes stage) for a crowd
SETTINGS = ('start_finish', 'town', 'aid_station', 'building')
SEQ_G, SEQ_P, SEQ_FACE = 2.0, 3.2, 2.4      # the sequence: the globe opens (2.0 s), the camera pans round the crowd (3.2 s), and settles on your face (2.4 s)
SEQ_SWEEP = 270.0                         # how far round it pans
KINDS = ('globe_face', 'crowd', 'sequence')


def pick_windows(t, score, T, min_mean, min_each, step=1.0, extra=None):
    """Start times of windows of `T` seconds over the per-second `score` series (times `t`) whose mean is at least `min_mean` and whose worst second is at least `min_each`: [(t0, mean)]. `extra(t0, t1)` may veto a window by
    returning None, else a weight that multiplies the mean."""
    t = np.asarray(t, float); score = np.asarray(score, float); out = []
    if len(t) < 2: return out
    for t0 in np.arange(t[0], t[-1] - T + 1e-9, step):
        m = (t >= t0) & (t <= t0 + T)
        if m.sum() < 2: continue
        s = score[m]
        if not np.isfinite(s).all() or s.mean() < min_mean or s.min() < min_each: continue
        w = 1.0 if extra is None else extra(float(t0), float(t0 + T))
        if w is not None: out.append((float(t0), float(s.mean() * w)))
    return out


def spread(found, gap):
    """The best of `found` [(score, item_with_t0)] keeping candidates at least `gap` seconds apart."""
    out = []
    for sc, it in sorted(found, key=lambda x: -x[0]):
        if all(abs(it['clip_start_s'] - o['clip_start_s']) >= gap or it['clip'] != o['clip'] for _, o in out): out.append((sc, it))
    return out


def globe_path(face, G=GLOBE_S, outro=False, spin=SPIN_DEG, sign=1.0):
    """The camera path of a globe shot made from the keyframes of a close view of the face (`face`: a camera path dict, `keyframes` from 0 to the hold's length): an opening starts as the little planet (looking straight down at the
    sphere, 260 degrees, stereographic) and opens onto the face over `G` seconds, with the face view playing on after it; an ending is the face view followed by the planet closing over `G` seconds. The face keyframes are moved to
    start `G` seconds in (opening) or kept at 0 (ending), so the clip window is `G` longer than the hold."""
    kf = [dict(k) for k in face['keyframes']]; T = kf[-1]['t']
    if not outro:
        for k in kf: k['t'] = round(k['t'] + G, 3)
        a = kf[0]; start = dict(t=0.0, yaw=round(a['yaw'] - sign * spin, 2), pitch=-90.0, fov=260.0, dist=1.0, ease='smooth')
        a['ease'] = 'smooth'; keys = [start] + kf
    else:
        b = kf[-1]; end = dict(t=round(T + G, 3), yaw=round(b['yaw'] + sign * spin, 2), pitch=-90.0, fov=260.0, dist=1.0)
        b['ease'] = 'smooth'; keys = kf + [end]
    for k in keys: k.setdefault('dist', 0.0)
    return dict(ref=face.get('ref', 'world'), keyframes=keys, subject=face.get('subject'), why=('opens from the globe onto your face' if not outro else 'your face, then the globe closes over it'))


def sequence_path(face, G=SEQ_G, P=SEQ_P, sweep=SEQ_SWEEP, outro=False, sign=1.0, spin=SPIN_DEG, wide_fov=95.0):
    """One camera path for the whole sequence, from the keyframes of a close view of the face (`face`, from 0 to the hold): an opening starts as the little planet, opens to a wide flat view over `G` seconds, pans `sweep` degrees round the horizon
    over `P` seconds (keys every 90 degrees, so it goes the long way round) and closes in onto the face, which then holds; an ending is the same run backwards: the face, the pan round, the wide view closing to the planet. The window is `G + P` longer
    than the hold. Yaw is the face's world yaw at the join; the pan ends (opening) or starts (ending) on it."""
    kf = [dict(k) for k in face['keyframes']]; T = kf[-1]['t']; a = kf[0] if not outro else kf[-1]; fy, fp, ff = a['yaw'], a['pitch'], a['fov']; n = max(int(round(sweep / 90.0)), 2)
    pan = []                                                    # the pan, from its far end (yaw fy - sign * sweep) to the face (yaw fy), over P seconds; the last quarter closes in from the wide view to the face's own fov and pitch
    for i in range(n + 1):
        u = i / n; c = max(0.0, (u - 0.75) / 0.25) ** 2
        pan.append(dict(t=round(u * P, 3), yaw=round(fy - sign * sweep * (1 - u), 2), pitch=round(-4.0 + (fp + 4.0) * c, 2), fov=round(wide_fov + (ff - wide_fov) * c, 1), dist=0.0, ease='smooth'))
    if not outro:
        start = dict(t=0.0, yaw=round(pan[0]['yaw'] - sign * spin, 2), pitch=-90.0, fov=260.0, dist=1.0, ease='smooth'); keys = [start, dict(pan[0], t=round(G, 3))]
        keys += [dict(k, t=round(G + k['t'], 3)) for k in pan[1:]]
        for k in kf: k['t'] = round(k['t'] + G + P, 3)
        keys += kf[1:]
    else:
        back = [dict(k, t=round(T + (P - k['t']), 3)) for k in reversed(pan)]                  # the pan run backwards: from the face out to the far end
        keys = kf[:-1] + back + [dict(t=round(T + P + G, 3), yaw=round(back[-1]['yaw'] + sign * spin, 2), pitch=-90.0, fov=260.0, dist=1.0)]
    for k in keys: k.setdefault('dist', 0.0)
    return dict(ref=face.get('ref', 'world'), keyframes=keys, subject=face.get('subject'), why=('the globe opens, the camera pans round the crowd and settles on your face' if not outro else 'your face, a pan round the crowd, then the globe closes'))


def _race_clips(folder):
    """[(clip id, start epoch s)] in time order."""
    from strata360.pipeline import config
    rd = os.path.join(config.race_dir(folder), 'clips'); out = []
    for c in sorted(os.listdir(rd)):
        try: cj = json.load(open(os.path.join(rd, c, 'clip.json'))); import datetime as dt; out.append((c, dt.datetime.fromisoformat(cj['time']['start_utc'].replace('Z', '+00:00')).timestamp()))
        except (OSError, ValueError, KeyError): pass
    return sorted(out, key=lambda x: x[1])


def _load(d, name):
    try: return json.load(open(os.path.join(d, name)))
    except (OSError, ValueError): return None


def _series(motion, key):
    s = (motion or {}).get('series') or {}
    return np.asarray(s.get('t', []), float), np.asarray(s.get(key, []), float)


def _steadiness(tm, shake, t0, t1):
    """0 (very shaky) to 1 (still) over the window t0 to t1 of the per-second shake series; 0.5 when the series has no reading in the window (a window past its end is not a shaky one)."""
    w = shake[(tm >= t0) & (tm <= t1)]; w = w[np.isfinite(w)]
    return float(np.clip(1.0 - w.mean() / 45.0, 0.0, 1.0)) if len(w) else 0.5


def candidates(folder, per=6, gap=12.0):
    """{'intro': [...], 'outro': [...]}: candidate dicts (id, kind, where, clip, clip_start_s, dur_s, technique, score, why, features), best first, at most `per` of each kind. Openings come from the first fifth of the race's clips, endings from the last fifth
    (and the globe shots from anywhere in the first or last half), so a crowd is the start line's or the finish's."""
    from strata360.pipeline import config
    clips = _race_clips(folder); n = len(clips); rd = os.path.join(config.race_dir(folder), 'clips'); found = {(w, k): [] for w in ('intro', 'outro') for k in KINDS}
    for i, (c, _) in enumerate(clips):
        d = os.path.join(rd, c); pos = i / max(n - 1, 1); fv = _load(d, 'face_view.json'); mo = _load(d, 'motion.json'); sc = _load(d, 'scenes.json'); dur = float((mo or {}).get('duration_s') or 0.0)
        tm, shake = _series(mo, 'shake_dps'); steady = lambda t0, t1: _steadiness(tm, shake, t0, t1)
        items = [it for it in (sc or {}).get('items', []) if it.get('ok')]
        scenery = lambda t0, t1: float(np.mean([it['scenery'] for it in items if t0 - 3 <= it['t_s'] <= t1 + 3 and isinstance(it.get('scenery'), (int, float))] or [4.0])) / 10.0
        if fv and fv.get('samples'):
            s = fv['samples']; t = [x['t'] for x in s]; score = [x['score'] for x in s]; total = GLOBE_S + FACE_S
            for where, ok, late in (('intro', pos <= 0.5, pos), ('outro', pos >= 0.5, 1 - pos)):
                if not ok: continue
                for t0, m in pick_windows(t, score, FACE_S, MIN_FACE, MIN_EACH, extra=lambda a, b: (0.6 + 0.4 * steady(a, b)) * (0.7 + 0.3 * scenery(a, b))):
                    # an opening starts the globe `GLOBE_S` before the face hold, an ending runs the globe after it
                    start = max(t0 - GLOBE_S, 0.0) if where == 'intro' else t0; hold = start + GLOBE_S if where == 'intro' else t0; pro = 0.8 + 0.2 * (1 - late)
                    if start + total > dur and dur: continue
                    found[(where, 'globe_face')].append((m * pro, dict(clip=c, clip_start_s=round(start, 2), dur_s=round(total, 2), technique='selfie_close', hold_t0=round(hold, 2), face=round(m, 2), steady=round(steady(t0, t0 + FACE_S), 2))))
        if fv and fv.get('samples'):
            s = fv['samples']; t = [x['t'] for x in s]; score = [x['score'] for x in s]; total = SEQ_G + SEQ_P + SEQ_FACE

            def crowd_near(a, b): return float(np.mean([it.get('people') or 0 for it in items if a - 2 <= it['t_s'] <= b + 2] or [0.0]))

            def weight(a, b, where):
                ppl = crowd_near(a - SEQ_P, a) if where == 'intro' else crowd_near(b, b + SEQ_P)
                return None if ppl < CROWD_PEOPLE / 2 else (0.5 + 0.5 * min(ppl / 15.0, 1.0)) * (0.6 + 0.4 * steady(a, b))
            for where, ok in (('intro', pos <= 0.25), ('outro', pos >= 0.75)):
                if not ok: continue
                for t0, m in pick_windows(t, score, SEQ_FACE, MIN_FACE, MIN_EACH, extra=lambda a, b, where=where: weight(a, b, where)):
                    start = t0 - SEQ_G - SEQ_P if where == 'intro' else t0
                    if start < 0 or (dur and start + total > dur): continue
                    ppl = crowd_near(t0 - SEQ_P, t0) if where == 'intro' else crowd_near(t0 + SEQ_FACE, t0 + SEQ_FACE + SEQ_P)
                    found[(where, 'sequence')].append((m, dict(clip=c, clip_start_s=round(start, 2), dur_s=round(total, 2), technique='selfie_close', hold_t0=round(t0, 2), face=round(m, 2), steady=round(steady(t0, t0 + SEQ_FACE), 2), people=round(ppl, 1))))
        if items:
            front = [it for it in items if it.get('view') == 'front']
            t = [it['t_s'] for it in front]; pe = [min(float(it.get('people') or 0) / 12.0, 1.0) + (0.3 if it.get('crowd') == 'many' else 0.0) for it in front]
            for where, pre in (('intro', pos <= 0.2), ('outro', pos >= 0.8)):
                if not pre: continue
                for j, it in enumerate(front):
                    if (it.get('people') or 0) < CROWD_PEOPLE and it.get('crowd') != 'many': continue
                    t0 = max(it['t_s'] - CROWD_S / 2, 0.0)
                    if dur and t0 + CROWD_S > dur: t0 = max(dur - CROWD_S, 0.0)
                    w = (min((it.get('people') or 0) / 15.0, 1.0) * 0.4 + (it.get('scenery') or 4) / 10.0 * 0.25 + (it.get('clarity') or 3) / 5.0 * 0.15 + steady(t0, t0 + CROWD_S) * 0.2) * (1.15 if it.get('setting') in SETTINGS else 1.0)
                    found[(where, 'crowd')].append((w, dict(clip=c, clip_start_s=round(t0, 2), dur_s=CROWD_S, technique='push_in', people=it.get('people'), setting=it.get('setting'), steady=round(steady(t0, t0 + CROWD_S), 2))))
    out = {'intro': [], 'outro': []}
    for (where, kind), lst in found.items():
        for rank, (sc, it) in enumerate(spread(lst, gap)[:per]):
            if kind == 'crowd' and rank % 2: it['technique'] = 'pan_reveal'                                          # the push in and the pan across, alternately: the model picks between them
            it.update(id=f"{where}-{kind}-{rank}", kind=kind, where=where, score=round(float(sc), 3), view='you' if kind in ('globe_face', 'sequence') else 'ahead', variant_seed=1000 + rank)
            out[where].append(it)
    for w in out: out[w].sort(key=lambda c: -c['score'])
    return out


def segment_of(c):
    """The plan-segment dict (what edit/framing.resolve_segment and the film renderer read) of a candidate."""
    tech = c['technique']; return dict(id=f"{c['clip']}@bookend.{c['id']}", clip=c['clip'], clip_start_s=c['clip_start_s'], dur_s=c['dur_s'], technique=tech, variant_seed=c.get('variant_seed', 1), kind='you' if c['kind'] in ('globe_face', 'sequence') else 'best',
                                       view=c.get('view', 'ahead'), speech=False, role='bookend', transition=dict(type='cut', beats=0, dur_s=0.0), utc_start=None, film_start_s=0.0, index=0)


def framing_of(folder, c, lib=None, data=None):
    """The camera path of a candidate: the film's own framing for a crowd shot; for a globe shot the framing of the close view of the face over the hold, wrapped in the globe's opening or closing."""
    from strata360.edit import framing as FR, techniques as TQ
    lib = lib or TQ.with_cams(TQ.load(), folder); data = data or FR.clip_data(folder, c['clip'], head=False); g = segment_of(c)
    if c['kind'] == 'crowd': return FR.resolve_segment(g, lib, data)
    outro = c['where'] == 'outro'; seq = c['kind'] == 'sequence'; hold = dict(g, clip_start_s=round(c['hold_t0'], 3), dur_s=SEQ_FACE if seq else FACE_S); face = FR.resolve_segment(hold, lib, data)
    if seq: return sequence_path(face, outro=outro, sign=1.0 if c.get('variant_seed', 1) % 2 else -1.0)
    # the face path is timed from the start of the hold; the window starts GLOBE_S earlier (opening) or at the hold (ending)
    return globe_path(face, GLOBE_S, outro=outro, sign=1.0 if c.get('variant_seed', 1) % 2 else -1.0)


def render_preview(folder, c, out_dir, size=(960, 540), fps=25.0, lib=None, data=None, path=None, title=None, suffix=''):
    """Render a candidate from the clip's proxy: out_dir/<id><suffix>.mp4 and .jpg (a 2 x 2 contact picture of four frames). Returns the two paths. `title`: a title spec (render/titles.py) laid over the shot."""
    import cv2, subprocess
    from strata360.pipeline import guard
    from strata360.render import final as FN, camera as cam
    g = segment_of(c); path = path or framing_of(folder, c, lib, data); os.makedirs(out_dir, exist_ok=True); W, H = size
    src = FN.FinalSource(folder, [g], {g['id']: path}, W, H, fps, source='proxy', decode_w=1920); n = int(round(c['dur_s'] * fps)); mp4 = os.path.join(out_dir, c['id'] + suffix + '.mp4')
    from strata360.render import titles as TT
    tt = TT.Title(title, W, H, c['dur_s']) if title else None
    enc = guard.popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-crf', '20', '-pix_fmt', 'yuv420p', mp4], stdin=subprocess.PIPE)
    shots = {int(round(f * (n - 1))): None for f in (0.0, 0.34, 0.67, 1.0)}
    for i, img in enumerate(src.frames(0, 0, n)):
        rgb = (img // 257).astype(np.uint8)
        if tt is not None: rgb = tt.apply(rgb, i / fps)
        bgr = np.ascontiguousarray(rgb[..., ::-1]); enc.stdin.write(bgr.tobytes())
        if i in shots: shots[i] = bgr
    enc.stdin.close(); enc.wait()
    got = [v for v in shots.values() if v is not None]
    while len(got) < 4: got.append(got[-1])
    half = [cv2.resize(x, (W // 2, H // 2), interpolation=cv2.INTER_AREA) for x in got[:4]]; jpg = os.path.join(out_dir, c['id'] + suffix + '.jpg')
    cv2.imwrite(jpg, np.vstack([np.hstack(half[:2]), np.hstack(half[2:])]), [cv2.IMWRITE_JPEG_QUALITY, 90]); return mp4, jpg


PROMPT = ("You are choosing the {where} shot of a film about an ultramarathon, shot on a 360 camera worn by the runner, for a viewer who has never seen it. Animated title text will be put over the shot later. "
          "Each picture below is one candidate: four frames of a {secs}-second shot in order (top left, top right, bottom left, bottom right). {what} "
          "Judge which candidates would make the most spectacular, striking {where}: composition, light, a clear subject (a face that is sharp and well framed, or a crowd with energy), a clean camera move, nothing blocked, blurred or ugly. "
          "Candidates: {n} (numbered from 0 in the order of the pictures). Answer with ONE JSON object and nothing else: "
          "{{\"scores\": [{{\"i\": 0, \"score\": number 1 to 10, \"why\": \"short reason\"}}, ...], \"best\": index of the best candidate}}.")
WHAT = dict(sequence="The shot starts as the whole world seen as a little planet, opens out and pans all the way round the crowd, then closes in on the runner's face. (Frames: the planet, the pan round the crowd, the move onto the face.)", globe_face="The shot starts as the whole world seen as a little planet and zooms in onto the runner's face." , crowd="The shot is a crowd at the race, with the camera moving slowly.")


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    try: return json.loads(m.group(0)) if m else None
    except ValueError:
        try: return json.loads(re.sub(r',\s*([}\]])', r'\1', m.group(0)))
        except (ValueError, AttributeError): return None


def rank(cands, jpgs, where, kind, server):
    """Ask the vision model (`server`, a vlm.Server with a projector) which of `cands` (with contact pictures `jpgs`, same order) is the best. Returns {id: dict(score, why)} and the id of the best."""
    p = PROMPT.format(where='opening' if where == 'intro' else 'ending', secs=int(round(cands[0]['dur_s'])), what=WHAT[kind], n=len(cands)); ans = parse(server.ask(p, jpgs, 700)) or {}
    out = {cands[int(s['i'])]['id']: dict(vlm_score=float(s.get('score', 0)), vlm_why=str(s.get('why', ''))) for s in ans.get('scores', []) if isinstance(s.get('i'), int) and 0 <= s['i'] < len(cands)}
    best = ans.get('best'); return out, (cands[best]['id'] if isinstance(best, int) and 0 <= best < len(cands) else None)


def run(folder, per=6, out_dir=None, render=True, choose=True, log=print):
    """The whole thing for a project: candidates, previews and the vision model's choice, written to <project>/strata360/bookends/bookends.json (returned)."""
    from strata360.pipeline import config
    from strata360.edit import framing as FR, techniques as TQ
    from strata360.analysis import vlm
    out_dir = out_dir or os.path.join(config.race_dir(folder), 'bookends'); os.makedirs(out_dir, exist_ok=True); t0 = time.time(); cs = candidates(folder, per=per); lib = TQ.with_cams(TQ.load(), folder); cache = {}
    log(f"{sum(len(v) for v in cs.values())} candidates: " + ', '.join(f"{w} {k} {sum(1 for c in cs[w] if c['kind'] == k)}" for w in cs for k in KINDS))
    for where in cs:
        for c in cs[where]:
            if render:
                data = cache.setdefault(c['clip'], FR.clip_data(folder, c['clip'], head=False))
                try: c['video'], c['picture'] = (os.path.relpath(p, out_dir) for p in render_preview(folder, c, out_dir, lib=lib, data=data))
                except Exception as e: c['error'] = f'{type(e).__name__}: {e}'; log(f"  {c['id']}: {c['error']}")
    chosen = {}
    if render and choose:
        w, p = vlm.llm_files()[0], vlm.model_files()[1]; moe = os.path.join(vlm.ROOT, 'models', 'qwen36-35b-a3b'); proj = (glob_first(moe, 'mmproj*.gguf') or p)
        with vlm.Server(w, proj) as srv:
            for where in cs:
                for kind in KINDS:
                    group = [c for c in cs[where] if c['kind'] == kind and c.get('picture')]
                    if len(group) < 2: chosen[f'{where}-{kind}'] = group[0]['id'] if group else None; continue
                    scores, best = rank(group, [os.path.join(out_dir, c['picture']) for c in group], where, kind, srv)
                    for c in group: c.update(scores.get(c['id'], {}))
                    chosen[f'{where}-{kind}'] = best; log(f"{where} {kind}: best {best}")
    doc = dict(schema=1, generated=time.strftime('%Y-%m-%dT%H:%M:%S'), seconds=round(time.time() - t0, 1), candidates=cs, chosen=chosen)
    json.dump(doc, open(os.path.join(out_dir, 'bookends.json'), 'w'), indent=1); return doc


def glob_first(folder, pat):
    import glob
    g = sorted(glob.glob(os.path.join(folder, pat))); return g[0] if g else None


def default_lines(folder):
    """The title words a project has by itself: its name and the dates of its clips (the user's own words go in `--title`, `--subtitle` and `--meta`)."""
    import datetime as dt
    from strata360.pipeline import config
    cfg = config.load(folder); name = re.sub(r'[-_]+', ' ', str(cfg.get('name') or os.path.basename(os.path.abspath(folder)))).strip().title(); clips = _race_clips(folder); lines = [dict(role='title', text=name)]
    if clips:
        a, z = (dt.datetime.fromtimestamp(clips[0][1], dt.timezone.utc), dt.datetime.fromtimestamp(clips[-1][1], dt.timezone.utc))
        lines.append(dict(role='meta', text=f"{a.day} to {z.day} {z.strftime('%B %Y')}" if (a.month, a.year) == (z.month, z.year) else f"{a.day} {a.strftime('%B')} to {z.day} {z.strftime('%B %Y')}"))
    return lines


def title_candidate(folder, cid, lines=None, out_dir=None, server=None, log=print):
    """Design and render the title of candidate `cid` of bookends.json: frames of its preview, the local model's design, the checks (edit/title_design.py). Writes <id>.title.json and <id>.titled.mp4 / .jpg beside the preview; returns (spec, report)."""
    import cv2
    from strata360.pipeline import config
    from strata360.edit import title_design as TD, framing as FR, techniques as TQ
    from strata360.analysis import vlm, palette as PAL
    out_dir = out_dir or os.path.join(config.race_dir(folder), 'bookends'); doc = json.load(open(os.path.join(out_dir, 'bookends.json'))); c = next((x for w in doc['candidates'] for x in doc['candidates'][w] if x['id'] == cid), None)
    if c is None: raise SystemExit(f'no candidate {cid}: see {out_dir}/bookends.json')
    cap = cv2.VideoCapture(os.path.join(out_dir, c['video'])); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); frames = []
    for f in TD.SAMPLES:
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(int(f * n), n - 1)); ok, fr = cap.read(); frames.append(fr[..., ::-1].copy())
    sc = _load(os.path.join(config.race_dir(folder), 'clips', c['clip']), 'scenes.json'); items = [it for it in (sc or {}).get('items', []) if it.get('ok') and abs(it['t_s'] - c['clip_start_s']) < 12]
    scene = '; '.join(f"{it.get('view')}: {it.get('setting')}, {it.get('lighting')}, {it.get('weather')}, {it.get('description')}" for it in items[:3]) or 'not known'
    lines = lines or default_lines(folder); own = server is None
    hold = c.get('hold_t0'); clear = None
    if hold is not None: a_ = hold - c['clip_start_s']; clear = (round(a_, 2), round(a_ + (SEQ_FACE if c['kind'] == 'sequence' else FACE_S), 2))      # the stretch about your face: no words on it
    if own:
        moe = os.path.join(vlm.ROOT, 'models', 'qwen36-35b-a3b'); server = vlm.Server(vlm.llm_files()[0], glob_first(moe, 'mmproj*.gguf') or vlm.model_files()[1]).__enter__()
    try: spec, report = TD.design(frames, lines, {'sequence': 'opening (a globe that opens, a pan round the crowd, a close view of the runner\'s face)', 'globe_face': 'opening (a globe that zooms onto the runner\'s face)', 'crowd': 'opening (a crowd)'}.get(c['kind'], 'opening') if c['where'] == 'intro' else 'ending', c['dur_s'], server, scene=scene, tmp_dir=out_dir, log=log, clear=clear, palette=PAL.load(os.path.join(config.race_dir(folder), 'clips', c['clip'])))
    finally:
        if own: server.__exit__()
    json.dump(dict(spec=spec, report=report), open(os.path.join(out_dir, cid + '.title.json'), 'w'), indent=1)
    lib = TQ.with_cams(TQ.load(), folder); data = FR.clip_data(folder, c['clip'], head=False); render_preview(folder, c, out_dir, lib=lib, data=data, title=spec, suffix='.titled'); return spec, report


def for_film(folder, where=('intro', 'outro')):
    """The openings and endings the film gets: [dict(where, c, spec)] from <project>/strata360/bookends/bookends.json, the best of the kinds in the order sequence, globe_face, crowd (the vision model's choice of each kind) with the title designed for it (<id>.title.json: `strata360 titles`), none when the project has no such file or `STRATA_BOOKENDS=0`."""
    from strata360.pipeline import config
    if os.environ.get('STRATA_BOOKENDS') == '0': return []
    d = os.path.join(config.race_dir(folder), 'bookends'); doc = _load(d, 'bookends.json'); out = []
    if not doc: return out
    for w in where:
        cid = next((doc['chosen'].get(f'{w}-{k}') for k in ('sequence', 'globe_face', 'crowd') if doc['chosen'].get(f'{w}-{k}')), None); c = next((x for x in doc['candidates'].get(w, []) if x['id'] == cid), None)
        if c is None: continue
        t = _load(d, cid + '.title.json'); out.append(dict(where=w, c=c, spec=(t or {}).get('spec')))
    return out
