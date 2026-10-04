"""`scenes` stage: what is in each part of a clip, from a local VLM (analysis/scenes_vlm.py in `.venv-vision`) on two body-frame views every few seconds: the front lens (what the
runner sees ahead) and the rear lens (the wearer and what follows). Output `scenes.json`: per sample the answers, plus clip-level summaries (settings, tags, scenic and energy averages,
lens problems) the candidate builder and the optimiser use."""
import json, os, shutil, subprocess, tempfile
from collections import Counter
import numpy as np
from strata360.analysis import views as V
from strata360.osv.telemetry import video_pts

SCHEMA_VERSION = 3                # 2: each item also has `scenery` (1 to 10, people ignored), `clarity` (1 to 5) and `scenery_why`; the general description is as in 1
                                  # 3: `summary.front` and `summary.rear` hold the labels of each direction on their own (the rear answers of schema 2 files were lost when earlier answers were reused)
YAW = {'front': 0, 'rear': 180}   # a view's number in the image file names (its yaw from the runner's heading), which the VLM script reports as `view`
NAME = {0: 'front', 180: 'rear'}


LOG_KEYS = ('setting', 'description', 'people', 'crowd', 'lighting', 'weather', 'water', 'ground_snow', 'scenic', 'energy', 'lens_problems', 'tags')      # (schema 3 dropped `activity` and `mood`, which nothing read, and added `water` and `ground_snow`)


def item(log, scenery):
    """One picture's answers as the fields of a scenes.json item (`ok`, the general answers, `scenery`, `clarity`, `scenery_why`): the clips' stage and the photo analysis both build their records here, so they cannot drift apart."""
    a = dict(log or {}); sc = scenery or {}; score, clar = sc.get('score'), sc.get('clarity')
    if a.get('lens_problems') == 'fog' and a.get('weather') in ('fog', 'rain', 'cloud', 'snow'): a['lens_problems'] = 'none'                   # the scenery is foggy, not the lens (the candidates treat a fogged lens as a blocked one)
    return dict(ok=bool(log), **{k: a.get(k) for k in LOG_KEYS}, scenery=float(score) if isinstance(score, (int, float)) else None, clarity=float(clar) if isinstance(clar, (int, float)) else None, scenery_why=sc.get('reason'))


def patch_sun(clip_dir):
    """Apply the clip's stored sun field (the `sun` stage) to the clip's existing scenes.json without asking the model again: True when the file was changed. Safe to repeat."""
    from strata360.gps import sun as SUN
    p = os.path.join(clip_dir, 'scenes.json'); sun = SUN.load(clip_dir)
    if not sun or not sun.get('covered') or not os.path.exists(p): return False
    doc = json.load(open(p)); before = json.dumps(doc, sort_keys=True); apply_sun(doc, sun)
    if json.dumps(doc, sort_keys=True) == before: return False
    tmp = f'{p}.{os.getpid()}.tmp'; json.dump(doc, open(tmp, 'w'), indent=1); os.replace(tmp, p); return True


def reusable(previous, every_s, sampling='fixed', px=None, fov=None, model=None):
    """The general-description answers of an earlier scenes.json when they were made for the same sampling (same spacing), as {(frame, view): answer}; {} when there are none to reuse: that pass is the slow one and its answers do not
    change when only the scenery prompt does."""
    if not previous or previous.get('sample_every_s') != every_s or previous.get('sampling', 'fixed') != sampling or (px is not None and previous.get('px', 768) != px) or (fov is not None and previous.get('fov', 100.0) != fov) or (model is not None and previous.get('model') != model) or not previous.get('items'): return {}
    return {(i['frame'], YAW[i['view']]): {k: i.get(k) for k in LOG_KEYS} for i in previous['items'] if i.get('ok') and i.get('view') in YAW}


def _vlm(py, src, tmp, out, models, prompt):
    subprocess.run([py, '-m', 'strata360.analysis.scenes_vlm', tmp, out, '--prompt', prompt] + (['--model', models] if models else []), check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
    return json.load(open(out))


def summarise(items):
    """The clip-level summary of a list of scenes.json items: the overall settings, tags and scores, and the `front` and `rear` blocks with the labels of each direction on their own."""
    def num(k, view=None):
        v = [float(i[k]) for i in items if (i['ok'] or k in ('scenery', 'clarity')) and (view is None or i['view'] == view) and isinstance(i.get(k), (int, float))]; return round(float(np.mean(v)), 3) if v else None
    tags = Counter(t for i in items for t in (i.get('tags') or []) if isinstance(t, str)); settings = Counter(i['setting'] for i in items if i.get('setting'))
    summary = dict(settings=dict(settings.most_common(4)), tags=[t for t, _ in tags.most_common(10)], scenic_front=num('scenic', 'front'), scenery_front=num('scenery', 'front'), scenery_rear=num('scenery', 'rear'), clarity_front=num('clarity', 'front'), clarity_rear=num('clarity', 'rear'), energy_front=num('energy', 'front'), people_front=num('people', 'front'),
                   lens_problems=dict(Counter(i['lens_problems'] for i in items if i.get('lens_problems') not in (None, 'none'))), lighting=dict(Counter(i['lighting'] for i in items if i.get('lighting')).most_common(3)),
                   answered=sum(1 for i in items if i['ok']), images=len(items))
    def block(view):                                                                               # the labels of one direction on their own: what is ahead, what is behind
        its = [i for i in items if i['view'] == view and i['ok']]; tg = Counter(t for i in its for t in (i.get('tags') or []) if isinstance(t, str))
        top = lambda k, n=3: dict(Counter(i[k] for i in its if i.get(k) and i[k] != 'unknown').most_common(n))
        return dict(answered=len(its), settings=top('setting', 4), weather=top('weather'), lighting=top('lighting'), crowd=top('crowd'), water={k: n for k, n in top('water', 4).items() if k != 'none'}, ground_snow=round(sum(1 for i in its if i.get('ground_snow') is True) / len(its), 2) if its else None, lens_problems={k: v for k, v in top('lens_problems', 4).items() if k != 'none'}, tags=[t for t, _ in tg.most_common(10)],
                    people=num('people', view), scenic=num('scenic', view), energy=num('energy', view), scenery=num('scenery', view), clarity=num('clarity', view))
    summary['front'], summary['rear'] = block('front'), block('rear')
    return summary


def apply_sun(doc, sun):
    """Bring the clip's stored sun field (gps/sun.py) into a scenes document: each item gets the sun's elevation at its moment, the summary gets `sun`, and a picture the model called overcast or bright while the sun was in
    twilight (below the horizon, above -12 degrees) is set to dusk (the model keeps its own answer in `lighting_model`): the model under-calls dusk, the sun does not. A picture the model placed indoors keeps its own answer (the room has its own lights). Safe to repeat. Returns the document."""
    from strata360.gps import sun as SUN
    if not sun or not sun.get('covered'): return doc
    for it in doc['items']:
        e = SUN.elevation_in_clip(sun, it['t_s'])
        if e is None: continue
        it['sun_elevation_deg'] = round(e, 1)
        if SUN.daylight(e) == 'twilight' and it.get('lighting') in ('overcast', 'bright') and it.get('setting') != 'indoor' and 'lighting_model' not in it: it['lighting_model'] = it['lighting']; it['lighting'] = 'dusk'
    doc['summary'] = dict(summarise(doc['items']), sun=dict(elevation_deg=sun['elevation_deg'], daylight=sun['daylight']))
    return doc


def analyse(osv, work_dir, every_s=5.0, models=None, px=512, previous=None, times=None, fov=120.0, sun=None):
    """`times` (clip seconds, from analysis/sampling.py) replaces the fixed spacing `every_s` when the clip has a proxy; `every_s` stays the fallback and part of what an earlier run must match to be reused. `sun` is the clip's stored sun field (gps/sun.py) when the sun stage has run: see apply_sun."""
    pts = video_pts(osv, 0); fps = (len(pts) - 1) / max(pts[-1] - pts[0], 1e-6); every = max(int(round(every_s * fps)), 1); tmp = tempfile.mkdtemp(prefix='s360scn_', dir=work_dir)
    try:
        proxy = os.path.join(work_dir, 'proxy.mp4')
        adaptive = times is not None and V.proxy_available(proxy); sampling = 'adaptive' if adaptive else 'fixed'
        if V.proxy_available(proxy): V.write_stab_views_proxy(proxy, osv, tmp, every=every, yaws=(0, 180), px=px, fov=fov, **(dict(times=times) if adaptive else {}))
        else: V.write_stab_views(osv, tmp, every=every, yaws=(0, 180), px=px, fov=fov)
        py = os.environ.get('STRATA_VISION_PYTHON') or os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(os.path.dirname(__file__), '..', '..'); out = os.path.join(tmp, 'vlm.json')
        scen = _vlm(py, src, tmp, os.path.join(tmp, 'scenery.json'), models, 'scenery'); old = reusable(previous, every_s, sampling, px, fov, scen['model'])                 # the scenery prompt is always run (it is the new part)
        want = [(i['frame'], i['view']) for i in scen['items']]; todo = [k for k in want if k not in old]; got = {}; secs = scen['seconds']
        if todo:                                                                                   # only the general answers that are missing (all of them on a first run; the rear ones an earlier run lost)
            sub = os.path.join(tmp, 'log'); os.makedirs(sub)
            for f, v in todo:
                name = f's{f:05d}_v{v:03d}.jpg'
                if os.path.exists(os.path.join(tmp, name)): shutil.copy(os.path.join(tmp, name), os.path.join(sub, name))
            r = _vlm(py, src, sub, out, models, 'log'); secs += r['seconds']; got = {(i['frame'], i['view']): i['answer'] for i in r['items']}
        raw = dict(model=scen['model'], seconds=secs, items=[dict(frame=f, view=v, answer=old.get((f, v)) or got.get((f, v))) for f, v in want])
        by = {(i['frame'], i['view']): i['answer'] or {} for i in scen['items']}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    items = []
    for it in raw['items']:
        items.append(dict(frame=it['frame'], t_s=round(float(pts[min(it['frame'], len(pts) - 1)] - pts[0]), 2), view=NAME[it['view']], **item(it['answer'], by.get((it['frame'], it['view'])))))
    doc = dict(schema=SCHEMA_VERSION, model=raw['model'], sample_every_s=every_s, sampling=sampling, px=px, fov=fov, seconds_model=raw['seconds'], items=items, summary=summarise(items))
    return apply_sun(doc, sun)
