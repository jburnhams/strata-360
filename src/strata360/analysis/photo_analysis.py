"""The clip stages that make sense for a still photo, run on the photos uploaded to a project (photos.py).

  exposure       how light the photo is: mean luma, the share of blown highlights and crushed shadows, the spread in stops          (the clip `exposure` stage)
  quality        plain image measurements: detail, blur, haze, contrast, saturation                                                (the clip `quality` stage: no ranking of beauty)
  places         where it was taken: the address and named places nearby (OpenStreetMap), and the race facts at that moment        (the clip `places` stage)
  people         the persons (YOLO pose) and faces (InsightFace, with the head pose and an embedding) in it                         (the clip `people` stage; `.venv-vision`)
  identity       which face is the wearer (the face profile from `who`), and how many people are in shot                           (the clip `identity` stage)
  face_view      whether the wearer's face is seen clearly (found, not tilted far forward, not turned far away)                   (the clip `face_view` stage)
  objects        the everyday objects in it (YOLO11, 80 classes: bicycle, car, dog, bottle, backpack, bench, boat, sign ...) with boxes; people are left to `people`   (photos only: not run for clips)
  scenes         the scene described by the local vision model: setting, light, weather, tags, a scenery score 1 to 10 and clarity (the clip `scenes` stage; `.venv-vision`)
  thumb_overlay  the picture with the race overlay as it was at the time the photo was taken                                       (the clip `thumb_overlay` stage)

The other clip stages have nothing to work on in a still: ingest (a video file), audio_extract / audio_clean / audio_background / audio_events / audio / transcribe / align / transcript_check / speakers (no sound), motion / proxy / quality_grid by direction (a
single flat view), thumb / thumb_best (the photo is its own thumbnail: photos.thumb) and candidates (no moments to choose between).

Each result is kept in `<project>/photos/analysis/<id>.json` with the version and key it was made for, so a stage is only redone when the code (its version), the photo or what it reads (the wearer profile, the race track, the overlay settings) changes, or with `force`. Faces' embeddings are in
`<id>.npy`. A stage that cannot run says why and the run stops there for that photo (loudly: nothing is skipped silently); the others go on."""
import datetime as dt, hashlib, json, os, shutil, subprocess, tempfile

import numpy as np

SCHEMA = 1
VERSIONS = dict(exposure=1, quality=1, places=1, people=1, objects=1, identity=1, face_view=1, scenes=1, thumb_overlay=1)
ORDER = tuple(VERSIONS)
MODEL_STAGES = ('people', 'objects', 'scenes')                      # need `.venv-vision` and the models
NOT_APPLICABLE = ('ingest', 'audio_extract', 'audio_clean', 'audio_background', 'audio_events', 'audio', 'transcribe', 'align', 'transcript_check', 'speakers', 'motion', 'proxy', 'thumb', 'thumb_best', 'candidates')
ME_MIN_DET = 0.5
WORK_PX = 1600                                            # photos are looked at this wide (longest side) by the measurements and the detectors
VLM_PX = 1024


def adir(rd): return os.path.join(rd, 'photos', 'analysis')
def _doc_path(rd, pid): return os.path.join(adir(rd), f'{pid}.json')


def load_doc(rd, pid):
    try: return json.load(open(_doc_path(rd, pid)))
    except (OSError, ValueError): return dict(schema=SCHEMA, id=pid, stages={})


def save_doc(rd, doc):
    os.makedirs(adir(rd), exist_ok=True); p = _doc_path(rd, doc['id']); tmp = p + '.tmp'
    with open(tmp, 'w') as f: json.dump(doc, f, indent=1)
    os.replace(tmp, p)


def read_bgr(path, px=WORK_PX):
    """The photo as a BGR uint8 array, turned the right way up and at most `px` on its longest side."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)); im.thumbnail((px, px))
    if im.mode in ('RGBA', 'LA', 'P'): bg = Image.new('RGB', im.size, (255, 255, 255)); rgba = im.convert('RGBA'); bg.paste(rgba, mask=rgba.split()[3]); im = bg
    elif im.mode in ('I;16', 'I', 'F'): im = im.point(lambda v: v / 256).convert('L')
    return np.asarray(im.convert('RGB'))[:, :, ::-1].copy()


# ---- stages that need no model ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _lin(c): c = c / 255.0; return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def exposure(img):
    """{luma (0-1, sRGB), mean_lin (linear), range_stops (5th to 95th percentile of linear luma, in stops), clip_hi, clip_lo (shares), verdict: 'dark' | 'bright' | 'ok'}."""
    b, g, r = (_lin(img[..., i].astype(np.float32)) for i in range(3)); lin = 0.2126 * r + 0.7152 * g + 0.0722 * b; luma = float(np.mean(0.2126 * img[..., 2] + 0.7152 * img[..., 1] + 0.0722 * img[..., 0]) / 255.0)
    lo, hi = np.percentile(lin, [5, 95]); stops = float(np.log2(max(hi, 1e-4) / max(lo, 1e-4))); gray = 0.2126 * img[..., 2] + 0.7152 * img[..., 1] + 0.0722 * img[..., 0]
    out = dict(luma=round(luma, 3), mean_lin=round(float(lin.mean()), 4), range_stops=round(stops, 2), clip_hi=round(float((gray > 250).mean()), 4), clip_lo=round(float((gray < 8).mean()), 4))
    out['verdict'] = 'dark' if luma < 0.2 or out['clip_lo'] > 0.4 else 'bright' if luma > 0.8 or out['clip_hi'] > 0.3 else 'ok'; return out


def quality(img):
    """The channels of the clip `quality` stage (analysis/quality_grid.py) for the whole photo: fine detail, mid detail, blur (fine over mid: low = blurry), tex (mid detail: low = featureless), dark (haze: min channel), contrast, sat, clip_hi, clip_lo, luma."""
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32); b1 = cv2.GaussianBlur(g, (0, 0), 1.0); b4 = cv2.GaussianBlur(g, (0, 0), 4.0); fine, mid = float(np.abs(g - b1).mean()), float(np.abs(b1 - b4).mean())
    out = dict(fine=fine, mid=mid, blur=fine / (mid + 1.0), tex=mid, dark=float(img.min(2).mean()), contrast=float(g.std()), sat=float(cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1].mean()), clip_hi=float((g > 250).mean()), clip_lo=float((g < 8).mean()), luma=float(g.mean()))
    out = {k: round(v, 3) for k, v in out.items()}; out['verdict'] = 'featureless' if out['tex'] < 1.0 else 'blurry' if out['blur'] < 0.45 else 'hazy' if out['dark'] > 150 and out['contrast'] < 35 else 'ok'; return out


def places(entry, cache_dir, race_text=None, reverse=None, nearby=None):
    """Where the photo was taken: the address and the named places within a kilometre of its position (OpenStreetMap), with `race_text`, the race facts at that moment. `reverse` and `nearby` are the lookups (analysis/places.py)."""
    from strata360.analysis import places as P
    reverse = reverse or P.reverse; nearby = nearby or P.nearby; loc = entry.get('loc')
    if not loc: return dict(covered=False, note='no position for this photo (no GPS in it and the time is outside the run)', race=race_text)
    a = reverse(loc['lat'], loc['lon'], cache_dir) or {}; near = nearby(loc['lat'], loc['lon'], cache_dir) or []
    names = [n for n in (a.get('hamlet'), a.get('village'), a.get('suburb'), a.get('town'), a.get('city'), a.get('municipality')) if n]
    return dict(covered=True, source='OpenStreetMap (Nominatim, Overpass)', position=loc, address=a, nearby=near, race=race_text,
                summary=dict(places=names[:2], road=a.get('road'), county=a.get('county'), country=a.get('country'), text=(', '.join(names[:2]) or a.get('display_name') or 'unknown') + (f" ({a['county']})" if a.get('county') else '')))


# ---- stages that read the detections ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def identity(det, emb, prof):
    """Which face is the wearer: the best face whose similarity to the wearer profile is at the profile's threshold, and how many people are in shot (persons over 0.5 and faces not inside one of them). {me: None | {face, sim, box}, n_people, others, threshold}."""
    from strata360.analysis import identity as I
    faces = det.get('faces') or []; people = det.get('people') or []; idx = [f for f in faces if f.get('emb') is not None]
    sims = I.score_faces(emb[[f['emb'] for f in idx]], prof) if idx else np.zeros(0); thr = prof['threshold']; me = None
    for f, s in zip(idx, sims):
        if s >= thr and (me is None or s > me['sim']): me = dict(face=faces.index(f), sim=round(float(s), 3), box=f['box'])
    inside = lambda f, p: p['box'][0] <= (f['box'][0] + f['box'][2]) / 2 <= p['box'][2] and p['box'][1] <= (f['box'][1] + f['box'][3]) / 2 <= p['box'][3]
    persons = [p for p in people if p['conf'] > 0.5]; extra_faces = [f for f in faces if f['score'] >= ME_MIN_DET and not any(inside(f, p) for p in persons)]; n = len(persons) + len(extra_faces)
    return dict(threshold=round(float(thr), 3), me=me, n_people=n, others=max(n - (1 if me else 0), 0))


def face_view(det, ident):
    """Whether the wearer's face is seen clearly in the photo (analysis/face_view.py `verdict`): {found, clear, score, pitch, yaw}; found False when the wearer's face is not in it."""
    from strata360.analysis import face_view as FV
    me = (ident or {}).get('me')
    if not me: return dict(found=False, clear=False, score=0.0, pitch=None, yaw=None)
    f = det['faces'][me['face']]
    if f.get('pose') is None: return dict(found=True, clear=False, score=0.0, pitch=None, yaw=None, note='no head pose for this face')
    score, pitch, yaw = FV.verdict(f); return dict(found=True, clear=score >= FV.CLEAR, score=round(score, 2), pitch=pitch, yaw=yaw)


def scenes_summary(log, scenery):
    """A photo's scene answers (the `log` and `scenery` prompts of analysis/scenes_vlm.py) as one record, like a clip's scenes.json item."""
    from strata360.analysis.scenes import LOG_KEYS
    a = log or {}; sc = scenery or {}; score, clar = sc.get('score'), sc.get('clarity')
    return dict(ok=bool(log), **{k: a.get(k) for k in LOG_KEYS}, scenery=float(score) if isinstance(score, (int, float)) else None, clarity=float(clar) if isinstance(clar, (int, float)) else None, scenery_why=sc.get('reason'))


# ---- the model runs (subprocesses in .venv-vision) ---------------------------------------------------------------------------------------------------------------------------------------------------------

def _py_src():
    here = os.path.dirname(__file__); return os.path.join(here, '..', '..', '..', '.venv-vision', 'bin', 'python'), os.path.join(here, '..', '..')


def run_detect(images, tmp):
    """{index: {w, h, people, faces}} and the embeddings (n, 512) for the BGR images {index: array}, by analysis/photo_detect.py in `.venv-vision`."""
    import cv2
    py, src = _py_src()
    for k, im in images.items(): cv2.imwrite(os.path.join(tmp, f'p{k:05d}.jpg'), im, [cv2.IMWRITE_JPEG_QUALITY, 92])
    out_json, out_npy = os.path.join(tmp, 'det.json'), os.path.join(tmp, 'det.npy')
    subprocess.run([py, '-m', 'strata360.analysis.photo_detect', tmp, out_json, out_npy], check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
    return {int(k): v for k, v in json.load(open(out_json))['images'].items()}, np.load(out_npy)


def run_objects(images, tmp):
    """{index: {w, h, objects: [{label, conf, box}]}} for the BGR images {index: array}, by analysis/photo_objects.py in `.venv-vision`."""
    import cv2
    py, src = _py_src()
    for k, im in images.items(): cv2.imwrite(os.path.join(tmp, f'p{k:05d}.jpg'), im, [cv2.IMWRITE_JPEG_QUALITY, 92])
    out_json = os.path.join(tmp, 'objects.json')
    subprocess.run([py, '-m', 'strata360.analysis.photo_objects', tmp, out_json], check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
    return {int(k): v for k, v in json.load(open(out_json))['images'].items()}


def run_vlm(images, tmp, models=None):
    """{index: (log answer, scenery answer)} for the BGR images, by the local vision model (analysis/scenes_vlm.py) run twice: the general description and the scenery rating."""
    import cv2
    py, src = _py_src(); out = {}
    for k, im in images.items():
        h, w = im.shape[:2]; s = VLM_PX / max(h, w)
        if s < 1: im = cv2.resize(im, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(tmp, f's{k}_v0.jpg'), im, [cv2.IMWRITE_JPEG_QUALITY, 92])
    for prompt in ('log', 'scenery'):
        o = os.path.join(tmp, f'{prompt}.json')
        subprocess.run([py, '-m', 'strata360.analysis.scenes_vlm', tmp, o, '--prompt', prompt] + (['--model', models] if models else []), check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
        for it in json.load(open(o))['items']: out.setdefault(it['frame'], {})[prompt] = it['answer']
    return {k: (v.get('log'), v.get('scenery')) for k, v in out.items()}


# ---- the run -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _key(*parts): return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def run(folder, stages=None, only=None, force=False, log=print, detect=run_detect, vlm=run_vlm, reverse=None, nearby=None, objects=run_objects):
    """Run the stages (all of ORDER, or `stages`) over the photos (all, or the ids in `only`), redoing only what is out of date unless `force`. Returns {stage: [photo ids it was run for]}; a stage that failed for lack of something (a profile, the models) raises after the others have been tried."""
    from strata360 import photos as PH
    from strata360.gps import context as X, track
    from strata360.pipeline import config
    cfg = config.load(folder) if os.path.exists(os.path.join(config.race_dir(folder), 'race.json')) else {}; rd = config.race_dir(folder); tz = cfg.get('timezone') or 'Europe/Brussels'
    tp = config.track_path(folder, cfg); tr = track.load(tp) if tp else None
    want = [s for s in ORDER if stages is None or s in stages]; bad = [s for s in (stages or []) if s not in VERSIONS]
    if bad: raise ValueError(f'unknown photo stage(s) {", ".join(bad)}: one of {", ".join(ORDER)}')
    rows = [PH.located(e, tr) for e in PH.load(rd)['photos'] if only is None or e['id'] in only]; done = {s: [] for s in want}; problems = []
    if not rows: log('no photos'); return done
    docs = {r['id']: load_doc(rd, r['id']) for r in rows}; imgs = {}
    def img(r):
        if r['id'] not in imgs: imgs[r['id']] = read_bgr(os.path.join(rd, r['file']))
        return imgs[r['id']]
    prof_path = os.path.join('profiles', cfg.get('profile', 'me') + '.npz')
    def keys(stage, r):
        src = os.path.join(rd, r['file']); base = [os.path.getmtime(src), os.path.getsize(src)]
        if stage in ('places', 'thumb_overlay'): base += [r.get('loc'), r['taken_utc'], tp and os.path.getmtime(tp)]
        if stage == 'identity': base += [os.path.exists(prof_path) and os.path.getmtime(prof_path), cfg.get('profile', 'me')]
        if stage == 'thumb_overlay': base += [cfg.get('overlay'), tz]
        return _key(stage, VERSIONS[stage], base)
    def todo(stage): return [r for r in rows if force or (docs[r['id']]['stages'].get(stage) or {}).get('key') != keys(stage, r)]
    def stamp(stage, r, result):
        docs[r['id']][stage] = result; docs[r['id']]['stages'][stage] = dict(version=VERSIONS[stage], key=keys(stage, r), at=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')); save_doc(rd, docs[r['id']]); done[stage].append(r['id'])
    for stage in want:
        rs = todo(stage)
        if not rs: log(f'{stage}: up to date'); continue
        try:
            if stage in ('exposure', 'quality'):
                for r in rs: stamp(stage, r, (exposure if stage == 'exposure' else quality)(img(r)))
            elif stage == 'places':
                for r in rs:
                    text = None
                    if tr is not None and r.get('track'): text = X.describe(X.context_at(tr, r['taken_utc'], r['taken_utc'], tz))
                    stamp(stage, r, places(r, os.path.join(rd, 'cache', 'places'), text, reverse, nearby))
            elif stage == 'people':
                tmp = tempfile.mkdtemp(prefix='s360photo_', dir=os.path.join(rd, 'photos') if os.path.isdir(os.path.join(rd, 'photos')) else None)
                try:
                    order = {i: r for i, r in enumerate(rs)}; dets, embs = detect({i: img(r) for i, r in order.items()}, tmp)
                    for i, r in order.items():
                        d = dets[i]; mine = [f['emb'] for f in d['faces'] if f.get('emb') is not None]; remap = {e: j for j, e in enumerate(mine)}
                        d = dict(d, faces=[dict(f, emb=remap.get(f['emb'])) for f in d['faces']]); os.makedirs(adir(rd), exist_ok=True); npy = os.path.join(adir(rd), f"{r['id']}.npy")
                        if mine: np.save(npy, embs[mine].astype(np.float16))
                        elif os.path.exists(npy): os.replace(npy, npy + '.old')                                                                                   # (no faces now: the old embeddings no longer belong to it)
                        stamp(stage, r, d)
                finally: shutil.rmtree(tmp, ignore_errors=True)
            elif stage == 'objects':
                tmp = tempfile.mkdtemp(prefix='s360photo_', dir=os.path.join(rd, 'photos') if os.path.isdir(os.path.join(rd, 'photos')) else None)
                try:
                    order = {i: r for i, r in enumerate(rs)}; found = objects({i: img(r) for i, r in order.items()}, tmp)
                    for i, r in order.items(): stamp(stage, r, found.get(i) or dict(w=0, h=0, objects=[]))
                finally: shutil.rmtree(tmp, ignore_errors=True)
            elif stage == 'identity':
                from strata360.analysis import identity as I
                if not os.path.exists(prof_path): raise RuntimeError(f'no wearer profile {prof_path}: run ./strata360 who RACE --me N (or --auto) first')
                prof = I.load_profile(prof_path)
                for r in rs:
                    det = docs[r['id']].get('people')
                    if det is None: raise RuntimeError(f"{r['id']}: the people stage has not run for this photo yet")
                    p = os.path.join(adir(rd), f"{r['id']}.npy"); emb = np.load(p).astype(np.float32) if os.path.exists(p) else np.zeros((0, 512), np.float32)
                    stamp(stage, r, identity(det, emb, prof))
            elif stage == 'face_view':
                for r in rs:
                    if docs[r['id']].get('identity') is None: raise RuntimeError(f"{r['id']}: the identity stage has not run for this photo yet")
                    stamp(stage, r, face_view(docs[r['id']]['people'], docs[r['id']]['identity']))
            elif stage == 'scenes':
                tmp = tempfile.mkdtemp(prefix='s360photo_', dir=os.path.join(rd, 'photos') if os.path.isdir(os.path.join(rd, 'photos')) else None)
                try:
                    order = {i: r for i, r in enumerate(rs)}; ans = vlm({i: img(r) for i, r in order.items()}, tmp)
                    for i, r in order.items(): stamp(stage, r, scenes_summary(*ans.get(i, (None, None))))
                finally: shutil.rmtree(tmp, ignore_errors=True)
            elif stage == 'thumb_overlay':
                from strata360 import overlay as O
                import cv2
                for r in rs:
                    if not r.get('track'): stamp(stage, r, dict(made=False, note='taken outside the time of the run: the overlay has nothing to show')); continue
                    im = img(r); ov = O.for_project(folder, (im.shape[1], im.shape[0]))
                    if ov is None: stamp(stage, r, dict(made=False, note='the overlay is off or there is no race track')); continue
                    rgb = np.ascontiguousarray(im[:, :, ::-1]); ov.apply(rgb, r['taken_utc']); out = os.path.join(adir(rd), f"{r['id']}-overlay.jpg"); os.makedirs(adir(rd), exist_ok=True)
                    cv2.imwrite(out, rgb[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90]); stamp(stage, r, dict(made=True, file=os.path.relpath(out, rd)))
            log(f'{stage}: {len(rs)} photo(s)')
        except Exception as e:
            problems.append(f'{stage}: {type(e).__name__}: {e}'); log(f'{stage}: FAILED: {type(e).__name__}: {e}')
    if problems: raise RuntimeError('; '.join(problems))
    return done


def summary(doc):
    """The short facts the pages show for a photo from its analysis document: {tags, setting, description, scenery, clarity, people, me, face_clear, place, exposure, quality, overlay} (only those the stages have made)."""
    s = doc.get('scenes') or {}; out = {}
    if s.get('ok'): out.update(setting=s.get('setting'), description=s.get('description'), tags=(s.get('tags') or [])[:5], lighting=s.get('lighting'), weather=s.get('weather'))
    if s.get('scenery') is not None: out['scenery'] = s['scenery']
    if s.get('clarity') is not None: out['clarity'] = s['clarity']
    if doc.get('objects'):
        counts = {}
        for o in doc['objects'].get('objects') or []: counts[o['label']] = counts.get(o['label'], 0) + 1
        out['objects'] = [dict(label=k, n=v) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:8]]
    if doc.get('identity'): out.update(people=doc['identity']['n_people'], me=bool(doc['identity']['me']))
    if doc.get('face_view') and doc['face_view'].get('found'): out['face_clear'] = doc['face_view']['clear']
    if (doc.get('places') or {}).get('covered'): out['place'] = doc['places']['summary']['text']
    if doc.get('exposure'): out['exposure'] = doc['exposure']['verdict']
    if doc.get('quality'): out['quality'] = doc['quality']['verdict']
    if (doc.get('thumb_overlay') or {}).get('made'): out['overlay'] = True
    out['stages'] = sorted(doc.get('stages') or {}); return out
